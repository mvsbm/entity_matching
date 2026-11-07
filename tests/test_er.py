"""Self-checks for the er engine. Run from the project root: python -m pytest tests/
Self-contained: small hand-made frames, the tracked config and reference data; no generated files needed."""
import json
import logging
import math
import re
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from splink import Linker

from er.candidates import Records, candidates, estimate, estimate_touching, found_by, generate
from er.config import (Budget, Comparator, Comparison, DeletionKeys, FSModel, FSSpec, InputError, Key, KeyBlocker, Level, OverBudget,
                       Resolver, Rule, RulesSpec, SortedNeighbourhood, Stage, TfidfNeighbours, ThresholdRule, keys_sql)
from er.evaluate import adopt, cluster_metrics, fp_upper, paired_test, predicted_pairs, true_pairs, wilson
from er.io import load
from er.match import exact_u, parameters, pattern_coverage, rule_edges, sample_u, score_fs, stale_u, train_fs, u_values, waterfall, scored_u
from er.pipeline import (accept_curve, check_budget, clustered, entity_folds, grown_pairs, preflight, select_threshold,
                         window_only)
from er.config import dump_pipeline, fields_read, legal_pattern, load_pipeline
from er.settings import fit_to_file, load_settings
from er.standardize import normalize, prepare
from er.strings import connect
from er.tune import pick_within_noise

UID = "uid"
PAIR = pd.DataFrame({"uid_l": ["001a"], "uid_r": ["001b"]}, dtype="string")  # same name, in 4 of the 120 records


@pytest.fixture(scope="module")
def con_db():
    return connect()


@pytest.fixture(scope="module")
def records() -> pd.DataFrame:
    """60 entities, two records each: same phone, the second name sometimes with one kana changed."""
    rng = np.random.default_rng(0)
    names = ["サトウヒロシ", "スズキケイコ", "タカハシアキラ", "タナカユウコ", "イトウタロウ", "ワタナベミホ"]
    rows = []
    for e in range(60):
        name, phone = names[e % len(names)] + "アイウエオ"[e // 12], f"{rng.integers(10_000):04d}"
        rows.append(dict(uid=f"{e:03d}a", name=name, phone=phone, entity=f"E{e}"))
        rows.append(dict(uid=f"{e:03d}b", name=name[:-1] + "カ" if e % 3 == 0 else name, phone=phone, entity=f"E{e}"))
    return pd.DataFrame(rows).astype("string")


def model(m_method: str = "em", tf: bool = False, extra_name_levels: tuple[Level, ...] = ()) -> FSModel:
    return FSModel(
        name="test",
        comparisons=(
            Comparison(name="name", null_if_missing=("name",), tf=Key("name") if tf else None, levels=(
                Level(label="exact", any_of=(("name", Comparator("exact")),), tf=tf),
                Level(label="close", any_of=(("name", Comparator("jaro_winkler", 0.9)),)), *extra_name_levels)),
            Comparison(name="phone", null_if_missing=("phone",), levels=(
                Level(label="exact", any_of=(("phone", Comparator("exact")),)),)),
        ),
        prior_rules=((Key("name"), Key("phone")),), prior_recall=0.9, u_max_pairs=1e4, m_method=m_method,
        em_rules=((Key("phone"),),), seed=0)


def test_string_functions_are_character_level_and_null_safe(con_db):
    con, _ = con_db  # DuckDB's own jaro_winkler_similarity compares bytes and gives 0.897 here
    assert con.sql("select round(cl_jaro_winkler('サトウヒロシ', 'サトウタカシ'), 3), cl_levenshtein('サトウ', 'サトオ'), "
                   "cl_levenshtein('サトウ', NULL) is null").fetchall() == [(0.844, 1.0, True)]


def test_typed_addresses_normalize_to_one_key():
    typed = pd.Series(["東京都千代田区丸の内1丁目3番17号", "千代田区丸の内１－３－１７", "東京都千代田区丸の内1-3-17　サクラハイツ101"],
                      dtype="string")
    assert normalize(typed, ("address",), load_settings().standardize).nunique() == 1


def test_a_u_sample_is_drawn_once_per_set_of_records(con_db, records, monkeypatch):
    import er.match as M
    con, db = con_db
    labels = records.set_index(UID)["entity"]
    M.SCORED_U.clear()
    fresh = train_fs(model("labels"), records, db, UID, labels)
    sampled, real = [], M.sample_u
    monkeypatch.setattr(M, "sample_u", lambda m, comps, *a: sampled.extend(c.name for c in comps) or real(m, comps, *a))
    assert model("em").u_keys() == model("labels").u_keys()
    other = train_fs(model("em"), records, db, UID, labels)  # another m method, the same comparisons and records
    con.register("er_shuffled", records.sample(frac=1, random_state=0))  # the same records as a table, in another order
    table = M.scored_sample(model(), "er_shuffled", db, UID)
    assert sampled == []
    assert table == M.scored_sample(model(), records, db, UID) == u_values(other) == u_values(fresh)
    M.SCORED_U.clear()
    again = train_fs(model("labels"), records, db, UID, labels)
    assert sampled == ["name", "phone"] and parameters(fresh).fillna(0).round(12).equals(parameters(again).fillna(0).round(12))


def test_a_one_edit_level_is_counted_exactly_through_deletion_keys(con_db):
    from rapidfuzz.distance import DamerauLevenshtein, Hamming
    from er.match import counted
    _, db = con_db
    rng = np.random.default_rng(1)  # repeated values, an insertion, an adjacent swap, unequal lengths for Hamming, a blank
    vals = [f"{rng.integers(300):03d}" for _ in range(300)] + ["12", "123", "1234", "2134", None]
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(len(vals))], "cif": vals, "phone": vals[::-1]}, dtype="string")
    one_off = lambda col, f: Comparison(name=col, null_if_missing=(col,), levels=(
        Level(label="exact", any_of=((col, Comparator("exact")),)), Level(label="one off", any_of=((col, Comparator(f, 1)),))))
    m = FSModel(name="t", comparisons=(one_off("cif", "damerau_levenshtein"), one_off("phone", "hamming")), prior_rules=(),
                prior_recall=0.5, u_max_pairs=1e4, m_method="em", em_rules=(), seed=0, u_exact_by_counts=True, u_near_by_keys=True)
    u = exact_u(m, df, db)
    filled = [v for v in vals if v is not None]
    pairs = [(a, b) for i, a in enumerate(filled) for b in filled[i + 1:]]
    for name, dist in (("cif", DamerauLevenshtein.distance), ("phone", Hamming.distance)):
        assert u[name]["exact"] == pytest.approx(sum(a == b for a, b in pairs) / len(pairs))
        assert u[name]["one off"] == pytest.approx(sum(a != b and dist(a, b) <= 1 for a, b in pairs) / len(pairs))
        assert u[name]["else"] == pytest.approx(1 - u[name]["exact"] - u[name]["one off"])
    assert counted(m, u) == {"cif", "phone"} and counted(replace(m, u_near_by_keys=False), u) == set()  # nothing left to sample


def test_u_sampled_per_comparison_equals_sampling_them_together(con_db, records):
    _, db = con_db
    m = replace(model(), u_max_pairs=2_000)  # fewer than the 7,140 pairs, so a real sample
    name, phone = m.comparisons
    assert sample_u(m, [name, phone], records, db, UID) == {**sample_u(m, [name], records, db, UID), **sample_u(m, [phone], records, db, UID)}


def test_levels_without_an_estimate_get_bounds_not_splink_defaults(con_db, records):
    _, db = con_db  # JW ≥ 0.95 after JW ≥ 0.9: no pair can reach it
    m = model(extra_name_levels=(Level(label="shadowed", any_of=(("name", Comparator("jaro_winkler", 0.95)),)),))
    model_json = train_fs(m, records, db, UID)
    filled = model_json["er"]["filled"]  # m also lists phone: EM blocks on phone, so it can never estimate phone's m
    assert filled["u"] == [["name", "shadowed"]] and ["name", "shadowed"] in filled["m"]
    assert all("m_probability" in lv and "u_probability" in lv for c in model_json["comparisons"]
               for lv in c["comparison_levels"] if not lv.get("is_null_level"))
    assert parameters(model_json).set_index(["comparison", "level"]).at[("name", "shadowed"), "weight"] == 0


def test_registered_pairs_score_like_splink_blocking(con_db, records):
    _, db = con_db
    model_json = train_fs(model(), records, db, UID)
    splink_json = {k: v for k, v in model_json.items() if k != "er"}
    native = Linker(db.register(records), {**splink_json, "blocking_rules_to_generate_predictions": [keys_sql((Key("phone"),))]},
                    log_level=logging.ERROR).inference.predict().as_pandas_dataframe().astype({"uid_l": "string", "uid_r": "string"})
    ours = score_fs(model_json, records, native[["uid_l", "uid_r"]], db, UID)
    both = native.merge(ours, on=["uid_l", "uid_r"], suffixes=("_native", "_registered"))
    assert len(both) == len(native) > 0
    assert np.allclose(both["match_weight_native"], both["match_weight_registered"], atol=1e-9)


def test_waterfall_bits_sum_to_the_match_weight(con_db, records):
    _, db = con_db
    model_json = train_fs(model(), records, db, UID)
    pairs = pd.DataFrame({"uid_l": ["001a", "000a", "000a"], "uid_r": ["001b", "000b", "059b"]}, dtype="string")
    scored = score_fs(model_json, records, pairs, db, UID)  # exact name, close name, different entity
    for _, row in scored.iterrows():
        bits = waterfall(model_json, {c: row[f"gamma_{c}"] for c in ("name", "phone")}, len(records))
        assert bits["bits"].sum() == pytest.approx(row["match_weight"])


def test_term_frequencies_come_from_the_fitting_records(con_db, records):
    _, db = con_db
    model_json, plain = train_fs(model(tf=True), records, db, UID), train_fs(model(), records, db, UID)
    other = records.assign(name=records["name"].where(records["uid"].isin(["001a", "001b"]), "ヨソ"))  # the pair's name: 2 of 120

    def weight(m: dict, df: pd.DataFrame, d) -> float:
        return score_fs(m, df, PAIR, d, UID)["match_weight"].item()
    with_tf = weight(model_json, records, db)
    assert with_tf != pytest.approx(weight(plain, records, db))  # the adjustment applies
    assert with_tf == pytest.approx(weight(model_json, other, db)) == pytest.approx(weight(model_json, other, connect()[1]))


def test_prior_is_rescaled_to_the_scored_set_size(con_db, records):
    _, db = con_db
    model_json = train_fs(model(), records, db, UID)
    padded = pd.concat([records, pd.DataFrame({"uid": [f"p{i:03d}" for i in range(120)], "name": "ヨソ", "phone": "9999",
                                               "entity": "pad"}, dtype="string")], ignore_index=True)
    lam = model_json["probability_two_random_records_match"]
    scaled = lam * (len(records) - 1) / (len(padded) - 1)
    expected = math.log2(scaled / (1 - scaled)) - math.log2(lam / (1 - lam))
    assert score_fs(model_json, padded, PAIR, db, UID)["match_weight"].item() - \
        score_fs(model_json, records, PAIR, db, UID)["match_weight"].item() == pytest.approx(expected)


def test_shared_connection_gives_the_same_rules_and_clusters_as_a_fresh_one(con_db):
    _, db = con_db
    spec = RulesSpec(standardize=load_settings().standardize, resolver=Resolver(method="connected_components"),
                     budget=Budget(max_pairs_per_record=10**4, max_block_size=10**4, target_rows=10**4, benchmark_pairs=100),
                     stages=(Stage(name="fuzzy", rules=(Rule(name="R", exact=("phone",), fuzzy=("name",)),),
                                   comparators={"name": Comparator("jaro_winkler", 0.8)}),))
    a = pd.DataFrame({"uid": ["1", "2", "3"], "phone": ["11", "11", "22"], "name": ["サトウ", "サトオ", "スズキ"]}, dtype="string")
    b = pd.DataFrame({"uid": ["7", "8", "9"], "phone": ["33", "33", "33"], "name": ["タナカ", "タナカ", "イトウ"]}, dtype="string")
    base = lambda d: pd.DataFrame({UID: d[UID], "cluster_id": d[UID]})
    first = rule_edges(spec, a, db, UID)[0]
    clustered(db.duckdb_con, db, base(a), first, a[UID], UID)  # leaves whatever it caches on the shared db
    shared, fresh = rule_edges(spec, b, db, UID)[0], rule_edges(spec, b, connect()[1], UID)[0]
    assert shared.reset_index(drop=True).equals(fresh.reset_index(drop=True)) and len(shared) == 1
    assert clustered(db.duckdb_con, db, base(b), shared, b[UID], UID).equals(clustered(*connect(), base(b), fresh, b[UID], UID))


def test_uncertainty():
    lo, hi = wilson(329, 420)
    assert (round(lo, 4), round(hi, 4)) == (0.7415, 0.8201)
    assert abs(fp_upper(0, 57) - 3 / 57) < 0.003       # zero FP among n bounds the rate at ≈ 3/n
    assert round(fp_upper(0, 3000), 4) == 0.001
    t = paired_test(base={("a", "b")}, variant={("a", "b"), ("c", "d"), ("x", "y")}, truth={("a", "b"), ("c", "d")})
    assert (t["TP_gains"], t["TP_losses"], t["FP_added"]) == (1, 0, 1)


def test_threshold_rule_takes_the_first_safe_weight_plus_margin():
    curve = pd.DataFrame(dict(min_match_weight=[0, 2, 4, 6, 8], pairs_FP=[3, 1, 0, 0, 0],
                              stage_fp_rate_hi=[0.03, 0.02, 0.016, 0.019, 0.02]))
    weight, _ = select_threshold(curve, ThresholdRule(grid=(0, 2, 4, 6, 8), max_fp=0, max_fp_rate_hi=0.05, margin_steps=1))
    assert weight == 6


def test_accept_curve_counts_pairs_over_folds():
    class Fold:  # accept_curve reads only the scored pairs
        def __init__(self, weights: list[float], fp: list[bool]):
            self.scored = pd.DataFrame(dict(match_weight=weights, fp=fp, named=True))
    curve = accept_curve([Fold([1, 5, 9], [True, False, False]), Fold([3, 7], [True, False])], [0, 4, 8])
    assert curve[["accepted", "pairs_FP"]].to_numpy().tolist() == [[5, 2], [3, 0], [1, 0]]
    assert curve["stage_fp_rate_hi"].iloc[1] == pytest.approx(fp_upper(0, 3))


def test_adopt_by_rule():
    sel = dict(TP_gains=10, TP_losses=0, p=0.002, FP_added=0, FP_removed=0)
    val = dict(TP_gains=1, TP_losses=0, FP_added=0, FP_removed=0)
    assert adopt("better", sel, val, 0.05)
    assert not adopt("better", sel | dict(FP_added=1), val, 0.05)       # adds a false pair on the selection set
    assert not adopt("better", sel | dict(p=0.2), val, 0.05)            # gain within noise
    assert not adopt("better", sel, val | dict(TP_losses=2), 0.05)       # loses on val
    assert adopt("cheaper", dict(sel, TP_gains=0, p=1.0), val, 0.05)
    assert not adopt("cheaper", sel | dict(TP_losses=1), val, 0.05)


def test_pick_within_noise_prefers_the_cheaper_tie():
    front = pd.DataFrame(dict(recall=[0.90, 0.91], lo=[0.87, 0.88], hi=[0.93, 0.94], ok=[True, True], cost=[100, 900]))
    assert pick_within_noise(front, "recall", "lo", "hi", "ok", "cost") == 0
    assert pick_within_noise(front.assign(ok=False), "recall", "lo", "hi", "ok", "cost") is None  # no fallback to failing rows


def test_settings_resolve_paths_from_any_working_folder(monkeypatch):
    root = load_settings().root
    monkeypatch.chdir(root / "notebooks")
    assert load_settings().data.bronze_dir == root / "data" / "medallion" / "bronze"


# ---------- the core every reported number rests on ----------

def brute_pairs(groups: pd.Series) -> set[tuple[str, str]]:  # every pair inside each group, by enumeration
    out = set()
    for _, members in groups.groupby(groups.to_numpy()):
        ids = sorted(members.index)
        out.update((a, b) for i, a in enumerate(ids) for b in ids[i + 1:])
    return out


def test_pair_and_cluster_metrics_match_a_brute_force_recount():
    rng = np.random.default_rng(1)
    ids = [f"r{i:03d}" for i in range(80)]
    entity = pd.Series(rng.integers(0, 30, 80).astype(str), index=ids)
    cluster = pd.Series(np.where(rng.random(80) < 0.7, entity.to_numpy(), rng.integers(30, 60, 80).astype(str)), index=ids)
    truth, pred = brute_pairs(entity), brute_pairs(cluster)
    assert predicted_pairs(cluster) == pred
    assert set(map(tuple, true_pairs(entity.rename_axis("uid"), "uid").to_numpy())) == truth
    m = cluster_metrics(cluster, entity)
    assert (m["TP"], m["FP"], m["FN"]) == (len(truth & pred), len(pred - truth), len(truth - pred))
    assert m["overmerged"] == sum(entity[cluster == c].nunique() > 1 for c in cluster.unique())
    assert m["split"] == sum(cluster[entity == e].nunique() > 1 for e in entity.unique())
    bcubed = np.mean([((cluster == cluster[i]) & (entity == entity[i])).sum() / (cluster == cluster[i]).sum() for i in ids])
    assert m["bcubed_precision"] == pytest.approx(bcubed)


def test_entity_folds_keep_every_entity_in_one_fold():
    data = load_settings().data
    truth = pd.DataFrame({data.unique_id: [f"r{i}" for i in range(300)], data.entity_id: [f"E{i // 3}" for i in range(300)]})
    folds = entity_folds(truth, data, 3, 0)
    by_entity = truth.assign(fold=folds.to_numpy()).groupby(data.entity_id)["fold"].nunique()
    assert by_entity.max() == 1 and folds.nunique() == 3 and folds.equals(entity_folds(truth, data, 3, 0))


def test_the_run_s_clustering_merges_whole_clusters_and_names_each_after_its_smallest_id(con_db):
    con, db = con_db
    ids = pd.Series(list("ABCDEF"), dtype="string")
    base = pd.DataFrame({UID: list("ABCDEF"), "cluster_id": ["A", "A", "C", "C", "E", "F"]})  # the rules' clusters: AB, CD
    pair = lambda rows: pd.DataFrame(rows, columns=["uid_l", "uid_r"], dtype="string")
    out = clustered(con, db, base, pair([("D", "B"), ("E", "F")]), ids, UID)
    assert out.tolist() == ["A", "A", "A", "A", "E", "E"]  # D–B joins both whole clusters; E–F a new one
    assert clustered(con, db, base, pair([]), ids, UID).tolist() == base["cluster_id"].tolist()  # no pair: as they were


def test_deletion_keys_find_every_pair_one_edit_apart():
    names = {"0": "サトウヒロシ", "1": "サトウヒロミ", "2": "サトヒロシ", "3": "サトウヒロシイ", "4": "サウトヒロシ",  # swap ウ/ト
             "5": "サトウタカシ", "6": "サトウヒロシ"}
    df = pd.DataFrame({"uid": list(names), "name": list(names.values()), "area": ["1", "1", "1", "1", "1", "1", "2"]}, dtype="string")
    pairs = set(map(tuple, generate(DeletionKeys(name="d", key=Key("name")), df, UID, {"0"}).to_numpy()))
    assert pairs == {("0", "1"), ("0", "2"), ("0", "3"), ("0", "4"), ("0", "6")}  # 5: two substitutions away
    within = set(map(tuple, generate(DeletionKeys(name="d", key=Key("name"), within=(Key("area"),)), df, UID, {"0"}).to_numpy()))
    assert within == pairs - {("0", "6")}  # another area
    every = generate(DeletionKeys(name="d", key=Key("name")), df, UID, set(names))
    assert estimate(DeletionKeys(name="d", key=Key("name")), df, len(df))["est_pairs"] >= len(every)  # an upper bound


def test_u_from_the_scored_file(con_db, records):
    _, db = con_db
    fitted = train_fs(model(), records, db, UID)
    same = scored_u(model(), fitted, records, db, UID)[0]  # the fitting records, the same sample: the same model
    assert score_fs(same, records, PAIR, db, UID)["match_weight"].item() == pytest.approx(score_fs(fitted, records, PAIR, db, UID)["match_weight"].item())
    padded = pd.concat([records, pd.DataFrame({"uid": [f"p{i:03d}" for i in range(240)], "name": [f"ヨソ{i}" for i in range(240)],
                                               "phone": [f"{i:04d}" for i in range(240)], "entity": "pad"}, dtype="string")], ignore_index=True)
    other = scored_u(model(), fitted, padded, db, UID)[0]
    u = lambda m: {lv["label_for_charts"]: lv["u_probability"] for c in m["comparisons"] if c["output_column_name"] == "phone" for lv in c["comparison_levels"] if not lv.get("is_null_level")}
    assert u(other)["exact"] < u(fitted)["exact"]  # more distinct phones: random pairs agree less often
    unseen = {tuple(x) for x in fitted["er"]["filled"]["m"]}  # never seen in training: m follows u, 0 bits
    m = lambda j: {(c["output_column_name"], lv["label_for_charts"]): (lv["m_probability"], lv["u_probability"]) for c in j["comparisons"]
                   for lv in c["comparison_levels"] if not lv.get("is_null_level")}
    assert all(mu[0] == m(fitted)[k][0] if k not in unseen else mu[0] == mu[1] for k, mu in m(other).items())  # m stays as fitted


def test_window_only_counts_potential_matches_no_key_reaches(con_db, records):
    _, db = con_db
    data = replace(load_settings().data, unique_id=UID, entity_id="entity")
    spec = FSSpec(standardize=replace(load_settings().standardize, derived=()), previous_stage="rules", stage="fs", model=model(),
                    blockers=(KeyBlocker(name="phone", keys=(Key("phone"),)),), min_match_weight=-10.0,  # toy weights: −6 to −3
                    resolver=Resolver(method="connected_components"),
                    budget=Budget(max_pairs_per_record=10**4, max_block_size=10**4, target_rows=10**6, benchmark_pairs=10))
    model_json, truth = train_fs(model(), records, db, UID), records[[UID, "entity"]]
    keyed = window_only(spec, model_json, records, truth, db, data, [len(records), 10**6])
    windowed = window_only(replace(spec, blockers=(SortedNeighbourhood(name="s", key=Key("name"), window=2),)), model_json,
                           records, truth, db, data, [len(records)])
    assert keyed["window_only"].eq(0).all() and keyed["potential"].iloc[1] < keyed["potential"].iloc[0]  # λ falls with N
    assert windowed["window_only"].iloc[0] == windowed["potential"].iloc[0] > 0  # every true pair shares the phone, none a key here
    moving = window_only(replace(spec, model=replace(spec.model, u_from_scored=True)), model_json, records, truth, db, data, [len(records)])
    assert moving["potential"].iloc[0] == keyed["potential"].iloc[0]  # at its own size, u from the records is the fitted u


def test_candidate_generators_respect_query_window_and_cosine():
    df = pd.DataFrame({"uid": [f"{i}" for i in range(8)], "phone": ["1", "1", "1", "2", "2", "3", "3", "3"],
                       "name": ["サトウ", "サトオ", "サトウ", "タナカ", "タナカ", "スズキ", "スズキイチ", "イトウ"]}, dtype="string")
    query = {"0", "5"}
    keys = generate(KeyBlocker(name="k", keys=(Key("phone"),)), df, UID, query)
    assert set(map(tuple, keys.to_numpy())) == {("0", "1"), ("0", "2"), ("5", "6"), ("5", "7")}  # only pairs touching a query
    sn = generate(SortedNeighbourhood(name="s", key=Key("name"), window=2), df, UID, query)
    order = df.sort_values(["name", "uid"])["uid"].tolist()
    assert all(abs(order.index(a) - order.index(b)) == 1 and query & {a, b} for a, b in sn.to_numpy())
    tf = generate(TfidfNeighbours(name="t", key=Key("name"), ngram=(2, 3), k=3, min_cosine=0.5), df, UID, query)
    assert ("5", "7") not in set(map(tuple, tf.to_numpy()))  # スズキ vs イトウ share no 2-3-gram: below the cosine cutoff
    assert len(tf) and all(query & {a, b} for a, b in tf.to_numpy())
    assert len(generate(KeyBlocker(name="k", keys=(Key("phone"),)), df, UID, None)) == 3 + 1 + 3  # None: every record a query
    clusters = pd.Series(["c0", "c0", "c2", "c3", "c4", "c5", "c6", "c7"], index=df["uid"].to_numpy())
    budget = Budget(max_pairs_per_record=100, max_block_size=100, target_rows=10, benchmark_pairs=10)
    union, _ = candidates((KeyBlocker(name="k", keys=(Key("phone"),)), SortedNeighbourhood(name="s", key=Key("name"), window=2)),
                          df, UID, None, budget, clusters)
    sources = dict(zip(zip(union["uid_l"], union["uid_r"]), union["sources"]))
    assert ("0", "1") not in sources and sources[("0", "2")] == sources[("3", "4")] == "k+s"  # one cluster already; found by both
    named = pd.DataFrame({"sources": ["person_name", "sn_person_name", "sn_person_name+person_name"]}, dtype="string")
    assert found_by(named, ["person_name"]).tolist() == [True, False, True]  # whole names only


def test_preflight_counts_block_pairs_and_the_budget_stops_a_run():
    df = pd.DataFrame({"uid": list("ABCDE"), "phone": ["1", "1", "1", "2", "2"]}, dtype="string")
    spec = RulesSpec(standardize=load_settings().standardize, resolver=Resolver(method="connected_components"),
                     budget=Budget(max_pairs_per_record=0.6, max_block_size=10, target_rows=10, benchmark_pairs=10),
                     stages=(Stage(name="exact", rules=(Rule(name="R", exact=("phone",)),)),))
    plan = preflight(spec, df)
    assert plan["P"].tolist() == [3 + 1]  # C(3,2) + C(2,2)
    with pytest.raises(OverBudget):
        check_budget(plan, spec.budget, len(df))


def test_load_validates_input(tmp_path):
    data = replace(load_settings().data, bronze_dir=tmp_path / "bronze", labels_dir=tmp_path / "labels")
    data.bronze_dir.mkdir(); data.labels_dir.mkdir()
    uid, ent = data.unique_id, data.entity_id
    write = lambda ids, entities: (pd.DataFrame({uid: ids, "x": "a"}).to_parquet(data.bronze_dir / "d.parquet", index=False),
                                   pd.DataFrame({uid: ids[:len(entities)], ent: entities}).to_parquet(data.labels_dir / "d.parquet", index=False))
    write(["1", "1"], ["E", "E"])
    with pytest.raises(ValueError, match="more than once"):
        load(data, "d")
    write(["1", "2"], ["E"])
    with pytest.raises(ValueError, match="different"):
        load(data, "d")
    write(["1", "2"], ["E", "E"])
    records, truth = load(data, "d")
    assert records[uid].tolist() == ["1", "2"] and str(truth[ent].dtype) == "string"


def test_prepare_names_missing_input_columns():
    with pytest.raises(ValueError, match="lacks columns"):
        prepare(load_settings().standardize, pd.DataFrame({"uid": ["1"]}, dtype="string"), [], used=["person_name"])


def test_blocking_normalizers():
    std = load_settings().standardize
    s = pd.Series(["マツモト", "", pd.NA], dtype="string")
    assert normalize(s, ("initial",), std).tolist()[:1] == ["マ"] and normalize(s, ("initial",), std).isna().tolist()[1:] == [True, True]
    assert normalize(pd.Series(["1000033"], dtype="string"), ("first3",), std).tolist() == ["100"]
    assert normalize(pd.Series(["サトウ"], dtype="string"), ("reverse",), std).tolist() == ["ウトサ"]


def test_legal_forms_go_wherever_banks_write_them_and_the_generator_s_names_lose_exactly_its_forms():
    import re
    import unicodedata
    from er.generate import generate, load_reference, load_spec
    s = load_settings()
    std = s.standardize
    strip = lambda xs: normalize(pd.Series(xs, dtype="string"), ("nfkc", "strip_legal_form"), std).tolist()
    assert strip(["カ)ヤマダ", "ヤマダ(カ", "ヤマダ(カ)ショウジ", "ｲ)ﾔﾏﾀﾞｸﾘﾆﾂｸ", "カブシキガイシヤヤマダ", "トクヒ)ヤマダ", "イリョウホウジンシャダンヤマダ"]) \
        == ["ヤマダ", "ヤマダ", "ヤマダショウジ", "ヤマダクリニツク", "ヤマダ", "ヤマダ", "ヤマダ"]
    assert strip(["ヤマダ(ザイ", "ザイ)ヤマダ", "シヤ)ヤマダ"]) == ["ヤマダ(ザイ", "ヤマダ", "ヤマダ"]  # ザイ stands first only
    spec = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=3_000)
    names = generate(spec, *load_reference(s.paths["reference"])).df["NYS_CNV_P_NAME_KANA"].dropna().astype("string").str.normalize("NFKC")
    written = sorted({unicodedata.normalize("NFKC", f) for f, _ in spec.legal_forms_written if f}, key=len, reverse=True)
    assert strip(names) == names.str.replace("|".join(map(re.escape, written)), "", regex=True).tolist()


def test_grown_pairs_tells_a_square_law_key_from_a_linear_one():
    rng = np.random.default_rng(0)
    entities = np.repeat(np.arange(4000), 2)  # two records per entity
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(8000)], "few": rng.integers(0, 50, 8000).astype(str),  # 50 values
                       "own": entities.astype(str)}).astype("string")
    entity = pd.Series(entities.astype(str), index=df["uid"].to_numpy())
    few, at_few = grown_pairs(df, entity, "uid", KeyBlocker(name="few", keys=(Key("few"),)), 10**6)
    own, at_own = grown_pairs(df, entity, "uid", KeyBlocker(name="own", keys=(Key("own"),)), 10**6)
    assert few == pytest.approx(2, abs=0.01) and own == 1.0
    assert at_own == 10**6 // 2 and at_few == pytest.approx(10**6 * (10**6 - 1) / 2 / 50, rel=0.05)  # C(n, 2) / 50 values


def test_a_blocking_key_limits_a_rule_join(con_db):
    _, db = con_db
    std = replace(load_settings().standardize, derived=())  # a hand-made frame without the real input columns
    df = pd.DataFrame({"uid": list("ABC"), "phone": ["1", "1", "1"], "name": ["サトウ", "サトオ", "カトウ"]}, dtype="string")
    budget = Budget(max_pairs_per_record=10, max_block_size=10, target_rows=10, benchmark_pairs=10)
    def spec(blocking):
        return RulesSpec(standardize=std, resolver=Resolver(method="connected_components"), budget=budget,
                         stages=(Stage(name="fuzzy", rules=(Rule(name="R", exact=("phone",), fuzzy=("name",), blocking=blocking),),
                                       comparators={"name": Comparator("levenshtein", 1)}),))
    plain = set(map(tuple, rule_edges(spec(()), df, db, UID)[0][["uid_l", "uid_r"]].to_numpy()))
    s = spec((Key("name", ("initial",)),))
    blocked = set(map(tuple, rule_edges(s, prepare(std, df, s.normalized()), db, UID)[0][["uid_l", "uid_r"]].to_numpy()))
    assert plain == {("A", "B"), ("A", "C")} and blocked == {("A", "B")}  # カトウ starts differently: not joined


def pipeline_and_columns():
    s = load_settings()
    p = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    return s, p, {c for sources in s.columns.values() for alt in sources for c in alt} - {"ENTITY_ID"}  # every mapped record column


def test_the_pipeline_file_writes_and_loads_back_unchanged(tmp_path):
    s, p, _ = pipeline_and_columns()
    dump_pipeline(p, s.chains, tmp_path / "p.toml")
    assert load_pipeline(tmp_path / "p.toml", s.standardize, s.chains, s.columns) == p


def test_a_mandatory_field_or_an_empty_one_of_group_stops_the_run():
    s, p, cols = pipeline_and_columns()
    with pytest.raises(InputError, match=r"id \(expected in CONT_ID\)"):
        fit_to_file(p, s, cols - {"CONT_ID"})
    names = {"FULL_NAME_KANA", "O_PERSON_NAME_KANA", "LAST_NAME_KANA", "GIVEN_NAME_KANA", "NYS_CNV_P_NAME_KANA"}
    with pytest.raises(ValueError, match="person_name .* / company_name"):
        fit_to_file(p, s, cols - names)
    with pytest.raises(ValueError, match="entity"):
        fit_to_file(p, s, cols, labelled=True)  # a labelled run needs the truth
    with pytest.raises(InputError, match="can run: every .* reads a field this file lacks"):
        fit_to_file(p, s, {"CONT_ID", "NYS_CNV_P_NAME_KANA"})  # a mistake to fix, not a traceback
    fit_to_file(p, s, cols | {"ENTITY_ID"}, labelled=True)


def test_an_absent_optional_field_disables_exactly_what_reads_it():
    s, p, cols = pipeline_and_columns()
    q, gone = fit_to_file(p, s, cols - {"CIF_ID"})
    assert "customer_id" not in fields_read(replace(q, generators={b.name: b for b in q.fs.blockers}))
    rules = {r.name for st in q.rules.stages for r in st.rules}
    assert rules == {r.name for st in p.rules.stages for r in st.rules} - {"X1_CIF_PERSON_NAME", "X2_CIF_COMPANY_NAME", "X3_CIF_PHONE", "F3_NAME~_CIF"}
    assert [b.name for b in q.fs.blockers] == [b.name for b in p.fs.blockers if b.name != "cif"]
    assert [c.name for c in q.fs.model.comparisons] == ["name", "company", "address", "phone"]
    assert [[k.column for k in r] for r in q.fs.model.prior_rules] == [["full_name", "address_code", "phone"]]
    assert {g.split(" (")[0] for g in gone} == {"rule X1_CIF_PERSON_NAME", "rule X2_CIF_COMPANY_NAME", "rule X3_CIF_PHONE", "rule F3_NAME~_CIF",
                                                "generator cif", "level cif: exact", "comparison cif",
                                                "prior rule ['customer_id', 'full_name']", "prior rule ['customer_id', 'company_name']"}
    q, gone = fit_to_file(p, s, cols - {"FULL_NAME_KANA", "O_PERSON_NAME_KANA"})  # a field built from the sources the file has
    person = next(d for d in q.rules.standardize.derived if d.name == "person_name")
    assert person.sources == (("LAST_NAME_KANA", "GIVEN_NAME_KANA"),) and any("X1_CIF_PERSON_NAME" in g for g in gone)


def test_pattern_coverage_finds_the_patterns_no_key_guarantees(con_db, records):
    _, db = con_db
    spec = FSSpec(standardize=replace(load_settings().standardize, derived=()), previous_stage="rules", stage="fs", model=model(),
                    blockers=(KeyBlocker(name="phone", keys=(Key("phone"),)),), min_match_weight=-10.0,  # toy weights
                    resolver=Resolver(method="connected_components"),
                    budget=Budget(max_pairs_per_record=10**4, max_block_size=10**4, target_rows=10**6, benchmark_pairs=10))
    model_json = train_fs(model(), records, db, UID)
    open_ = pattern_coverage(spec, model_json, len(records))
    assert len(open_) and not (open_["phone"] == "exact").any()  # the phone key guarantees every pattern with phone exact
    named = pattern_coverage(replace(spec, blockers=spec.blockers + (KeyBlocker(name="name", keys=(Key("name"),)),)), model_json, len(records))
    assert len(named) < len(open_) and not (named["name"] == "exact").any()  # a name key adds the name-exact patterns
    assert len(pattern_coverage(spec, model_json, 10**9)) <= len(open_)  # fewer patterns reach the threshold at scale


def test_exact_u_counts_every_pair(con_db, records):
    _, db = con_db
    holes = records.assign(name=records["name"].mask(records.index % 7 == 0))  # some names missing: the null level
    u = exact_u(model(), holes, db)
    pairs = [(a, b) for i, a in enumerate(holes.itertuples()) for b in list(holes.itertuples())[i + 1:]]
    filled = [(a, b) for a, b in pairs if pd.notna(a.name) and pd.notna(b.name)]
    assert u["name"]["exact"] == pytest.approx(sum(a.name == b.name for a, b in filled) / len(filled))
    assert u["phone"]["exact"] == pytest.approx(sum(a.phone == b.phone for a, b in pairs) / len(pairs))
    assert "close" not in u["name"]  # a fuzzy level stays sampled


def test_blank_values_are_missing_and_full_width_spaces_are_stripped():
    s = load_settings()
    p = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns)
    sources = {c for alts in s.columns.values() for alt in alts for c in alt}
    raw = pd.DataFrame({c: [pd.NA] * 3 for c in sources}, dtype="string")
    raw["CONT_ID"] = ["1", "2", "3"]
    raw["FULL_NAME_KANA"] = ["\u3000", " ", pd.NA]  # blank: the next source must win
    raw["O_PERSON_NAME_KANA"] = ["ヤマダ\u3000タロウ", pd.NA, pd.NA]
    raw["NYS_CNV_P_NAME_KANA"] = [pd.NA, "カブシキガイシャ", "\u3000"]  # a legal form alone is no company name
    df = prepare(p.fs.standardize, raw, p.fs.normalized() + p.rules.normalized())
    assert df["person_name"].tolist()[:1] == ["ヤマダタロウ"] and df["full_name"].isna().all()
    assert df["person_name"].isna().tolist()[1:] == [True, True]
    assert df["company_name__nfkc_strip_legal_form_kana_fold"].isna().all()


@pytest.fixture(scope="module")
def population():
    """A small generated population and the final pipeline, for whole runs."""
    from er.generate import generate as make, load_reference, load_spec
    s = load_settings()
    p = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns)
    g = make(replace(load_spec(s.root / "config" / "generator.toml")[0], entities=400), *load_reference(s.paths["reference"]))
    return s, p, g


def test_a_run_refuses_a_resolver_it_cannot_apply(population):
    from er.run import Run
    s, p, _ = population  # choose.py could adopt the constrained resolver; the run would then cluster otherwise
    constrained = Resolver(method="constrained", cannot_link=("given_name",))
    for q in (replace(p, fs=replace(p.fs, resolver=constrained)), replace(p, rules=replace(p.rules, resolver=constrained))):
        with pytest.raises(InputError, match="connected components only"):
            Run(q, s)


def test_a_run_ignores_record_order_refuses_a_used_folder_and_an_increment_keeps_every_cluster(tmp_path, population):
    from er.match import scaled_prior
    from er.report import qa
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    g.df.sample(frac=1, random_state=1).to_parquet(tmp_path / "shuffled.parquet", index=False)
    first = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    sheet = qa(first, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    assert len(sheet) and {"person_name_l", "person_name_r", "address_l", "address_r", "phone_l", "name", "name_bits"} <= set(sheet.columns)
    lam = scaled_prior(first.scoring, first.n)  # the prior and each field's bits add up to the score a reviewer sees
    bits = sheet[[f"{c.name}_bits" for c in p.fs.model.comparisons]].sum(axis=1) + math.log2(lam / (1 - lam))
    assert np.allclose(bits, sheet["match_weight"], atol=0.05)
    Run(p, s, model=first.model).full(tmp_path / "shuffled.parquet", tmp_path / "b")
    gold = [pd.read_parquet(tmp_path / d / "gold.parquet") for d in ("a", "b")]
    pd.testing.assert_frame_equal(*gold)  # clusters, and the stage and rule that resolved each record
    assert gold[0]["cluster_id"].nunique() < len(gold[0])

    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    Run(p, s, model=first.model).full(tmp_path / "old.parquet", tmp_path / "c")
    before = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c")
    after = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    assert sorted(after.index) == sorted(g.df[uid]) and after.index.is_unique
    assert after.reindex(before.index).groupby(before.to_numpy()).nunique().eq(1).all()  # no stored cluster is split
    assert Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c").added == 0  # a retry adds nothing twice
    pd.testing.assert_series_equal(pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"], after)

    with pytest.raises(InputError, match="already holds a run"):  # a full run never mixes with an earlier one
        Run(p, s, model=first.model).full(tmp_path / "all.parquet", tmp_path / "c")
    Run(p, s, model=first.model).full(tmp_path / "all.parquet", tmp_path / "c", overwrite=True)
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "c" / "gold.parquet"), gold[0])
    assert [f.name for f in (tmp_path / "c" / "state" / "records").iterdir()] == ["part-00000.parquet"]

    g.df.drop(columns="PHONE_NUM_4").to_parquet(tmp_path / "no_phone.parquet", index=False)
    with pytest.raises(InputError, match="fitted on other comparison levels") as e:  # the model compares the phone; this file has none
        Run(p, s, model=first.model).full(tmp_path / "no_phone.parquet", tmp_path / "d")
    assert "without --model" in e.value.fix


def test_an_interrupted_increment_completes_when_run_again(tmp_path, population, monkeypatch):
    import os
    import shutil
    from er.run import Run
    s, p, g = population
    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    Run(p, s).full(tmp_path / "old.parquet", tmp_path / "clean")
    shutil.copytree(tmp_path / "clean", tmp_path / "cut")
    Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "clean")

    renames, replace_ = [], os.replace
    def cut_short(a, b):  # dies halfway through the renames: gold and the clusters replaced, the batch's records not
        renames.append(b)
        if len(renames) == 5:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(os, "replace", cut_short)
    with pytest.raises(KeyboardInterrupt):
        Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "cut")
    monkeypatch.undo()
    again = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "cut")  # first finishes the interrupted write
    assert again.added == 0  # so the batch is in the run already: nothing to add
    pd.testing.assert_frame_equal(*(pd.read_parquet(tmp_path / d / "gold.parquet") for d in ("clean", "cut")))
    assert not list((tmp_path / "cut").rglob("*.tmp"))


def test_an_overwrite_cut_short_keeps_the_old_run_and_people_s_answers(tmp_path, population, monkeypatch):
    import os
    import er.folder
    from er.folder import finish_writes
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    pd.DataFrame({uid: g.df[uid].astype("string")[:5], "kind": [1] * 5}).to_parquet(tmp_path / "answers.parquet")
    Run(p, s, kind_labels=tmp_path / "answers.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    before = pd.read_parquet(tmp_path / "run" / "gold.parquet")
    lit = er.folder.lit
    def full_disk(path):  # the new gold can't be written
        if "gold" in str(path):
            raise OSError("No space left on device")
        return lit(path)
    monkeypatch.setattr(er.folder, "lit", full_disk)
    with pytest.raises(OSError):
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    monkeypatch.undo()
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "run" / "gold.parquet"), before)  # the old run stands
    assert len(pd.read_parquet(tmp_path / "run" / "kind_answers")) == 5  # and people's answers with it

    moves, replace_ = [], os.replace
    def cut_short(a, b):  # dies after the first of the moves that replace the old run
        moves.append(b)
        if len(moves) == 3:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(os, "replace", cut_short)
    with pytest.raises(KeyboardInterrupt):
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    monkeypatch.undo()
    finish_writes(tmp_path / "run")  # what the next run, increment or decisions do first
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "run" / "gold.parquet"), before)
    assert len(pd.read_parquet(tmp_path / "run" / "kind_answers")) == 5
    assert len(pd.read_parquet(tmp_path / "run" / "state" / "records")) == len(g.df) and not (tmp_path / "run" / ".full.tmp").exists()


def test_an_increment_refuses_a_changed_pipeline_and_steps_json_says_what_went_in(tmp_path, population):
    import hashlib
    import json
    from er.run import Run
    s, p, g = population
    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    Run(p, s).full(tmp_path / "old.parquet", tmp_path / "run")
    entry = json.loads((tmp_path / "run" / "steps.json").read_text())["runs"][-1]
    assert entry["inputs"][0]["sha256"] == hashlib.sha256((tmp_path / "old.parquet").read_bytes()).hexdigest() and entry["code"] and entry["config"]
    changed = replace(p, fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 1))
    with pytest.raises(InputError, match="changed since the full run"):
        Run(changed, s).increment(tmp_path / "new.parquet", tmp_path / "run")  # the batch would be resolved otherwise
    Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "run")  # the run's own pipeline: it goes on


def test_answers_given_wrong_stop_the_run(tmp_path, population):
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    with pytest.raises(InputError, match="no file matches"):
        Run(p, s, kind_labels=tmp_path / "answres.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    pd.DataFrame({"kind": [1]}).to_parquet(tmp_path / "no_ids.parquet")
    with pytest.raises(InputError, match="needs the columns"):
        Run(p, s, kind_labels=tmp_path / "no_ids.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    (tmp_path / "sheet.parquet").write_text(f"{s.data.unique_id},kind\n0000000001,1\n")  # a sheet saved as CSV: the same door as records
    with pytest.raises(InputError, match="not a Parquet file"):
        Run(p, s, kind_labels=tmp_path / "sheet.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    with pytest.raises(InputError, match="no run in"):
        Run(p, s).increment(tmp_path / "all.parquet", tmp_path / "empty")


def test_describe_records_says_what_a_file_holds_without_preparing_it(tmp_path, population):
    import duckdb
    from er.source import describe
    s, p, g = population
    uid, phone = s.data.unique_id, s.columns["phone"][0][0]
    df = g.df.rename(columns={uid: "customer_no", phone: "TEL"}).astype({"TEL": "string"})
    df.loc[df.index[:5], "TEL"] = ["", " ", "\u3000", None, "12"]  # blank is missing, as a run reads it
    df["Postal Code"] = df.pop(s.columns["postal_code"][0][0])  # the field's own name, not the column the mapping names
    df = df.drop(columns=[c for alt in s.columns["postal_code"][1:] for c in alt if c in df])
    df["n"] = range(len(df))  # a number column: read as text
    df.to_parquet(tmp_path / "theirs.parquet", index=False)
    d = describe(tmp_path / "theirs.parquet", duckdb.connect(), s.columns, s.detect)
    blank = lambda x: x.isna() | x.astype("string").str.fullmatch("[ \t\n\r\u3000]*").fillna(True)
    assert d["records"] == len(df) and {c["column"]: round(c["filled"], 9) for c in d["columns"]} == {c: round(1 - blank(df[c]).mean(), 9) for c in df}
    person = next(f for f in d["fields"] if f["field"] == "person_name")
    alts = [df[a[0]].mask(blank(df[a[0]])) if len(a) == 1 else (df[a[0]].mask(blank(df[a[0]])) + df[a[1]].mask(blank(df[a[1]]))) for a in person["sources"]]
    whole = alts[0]
    for x in alts[1:]:
        whole = whole.fillna(x)
    assert math.isclose(person["filled"], whole.notna().mean()) and [x["found"] for x in person["alternatives"]] == [True] * len(alts)
    assert {x["field"]: x["column"] for x in d["suggested"]} == {"id": "customer_no", "phone": "TEL", "postal_code": "Postal Code"}  # values, values, name
    assert d["fit"]["phone"]["TEL"] > 0.9 and not next(f for f in d["fields"] if f["field"] == "phone")["sources"][0] == ["TEL"]  # suggested, not applied


def test_a_joined_alternative_whose_parts_never_fill_together_is_filled_nowhere(tmp_path):
    import duckdb
    from er.source import describe
    pd.DataFrame({"a": ["x", None, "z"], "b": [None, "y", ""]}).to_parquet(tmp_path / "f.parquet", index=False)
    d = describe(tmp_path / "f.parquet", duckdb.connect(), {"both": (("a", "b"),), "either": (("a", "b"), ("a",), ("b",))}, {})
    shares = {f["field"]: f["filled"] for f in d["fields"]}
    assert shares["both"] == 0 and shares["either"] == 1  # each row holds one of them


def test_the_file_s_contents_say_which_feature_each_column_fills(tmp_path, capsys, monkeypatch):
    import random
    from er.cli import main
    from er.settings import compiled, features_from, load_settings
    s = load_settings()
    assert compiled(features_from(s.columns)) == {k: v for k, v in s.columns.items() if k != "entity"}  # the structure is the mapping, read back
    people = json.loads((s.paths["reference"] / "individual.json").read_text(encoding="utf-8"))
    places = json.loads((s.paths["reference"] / "addresses.json").read_text(encoding="utf-8"))
    rnd, n = random.Random(0), 400
    who, where = rnd.sample(people, n), rnd.sample(places, n)
    pd.DataFrame({  # columns named nothing a mapping knows: only their contents say what they hold
        "c1": [f"R{i:06d}" for i in range(n)], "c2": [p["surname_kana"] for p in who], "c3": [p["given_kana"] for p in who],
        "c4": [p["surname_kana"] + " " + p["given_kana"] for p in who], "c5": [p["surname"] + p["given"] for p in who],
        "c6": [f"株式会社{p['surname']}商事" for p in who], "c7": [f"{a['pref']}{a['city']}{a['town']}{rnd.randint(1, 9)}-{rnd.randint(1, 30)}" for a in where],
        "c8": ["".join(rnd.choice("abcdefgh") for _ in range(6)) for _ in range(n)],
        "c9": [a["postal"] for a in where], "c10": [a["postal"] for a in where],  # a postal code, and a copy of it
        "c11": [f"{rnd.randint(0, n // 2):010d}" for _ in range(n)],  # an address code: ten digits, shared
        "c12": [f"{rnd.randrange(10 ** 12, 10 ** 13)}" for _ in range(n)]}).to_parquet(tmp_path / "theirs.parquet", index=False)  # a customer number
    monkeypatch.chdir(tmp_path)

    def say(*words: object) -> tuple[int, dict]:
        code = main([*map(str, words), "--format", "json"])
        return code, json.loads(capsys.readouterr().out.splitlines()[-1])

    say("create", "workspace", "w")
    code, d = say("load", "records", "theirs.parquet", "--workspace", "workspaces/w")
    assert code == 0 and {c: x["script"] for c, x in d["profile"].items()} == {"c1": "romaji", "c2": "kana", "c3": "kana", "c4": "kana", "c5": "kanji",
                                                                               "c6": "kanji", "c7": "kanji", "c8": "romaji", "c9": None, "c10": None,
                                                                               "c11": None, "c12": None}  # digits: no script
    assert {x["feature"]: x["column"] for x in d["placements"]} == {
        "ID/Record ID": "c1", "Name/Full name": "c4", "Name/Full name/Family name": "c2", "Name/Full name/Given name": "c3",
        "Name/Company name": "c6", "Address/Address": "c7", "Address/Postal code": "c9", "Address/Address code": "c11", "ID/Customer number": "c12"}
    # the narrow pattern (a postal code) placed before the broad one (five digits or more), and its copy (c10) nowhere; an ID
    # mostly unique; the kanji full name (c5) waits for a kanji feature; the random text, nowhere
    code, _ = say("set", "feature", *(f"{x['feature']}={x['column']}" for x in d["placements"]), "--workspace", "workspaces/w")
    m = load_settings(columns=tmp_path / "workspaces" / "w" / "columns.toml").columns
    assert code == 0 and m["id"] == (("c1",),) and m["person_name"] == (("c4",), ("c2", "c3")) and m["given_name"] == (("c3",),)
    assert m["full_name"] == (("c4",),) and m["any_name"] == (("c4",), ("c2", "c3"), ("c6",)) and m["company_name"] == (("c6",),)
    code, e = say("set", "feature", "Name/Nickname=c8", "--workspace", "workspaces/w")
    assert code == 2 and "Name/Full name/Family name" in e["fix"]  # no such feature: the ones there are
    say("set", "feature", "Address/Address=", "--workspace", "workspaces/w")
    assert load_settings(columns=tmp_path / "workspaces" / "w" / "columns.toml").columns["address"] == ()  # no column, still declared
    assert say("describe", "records", "theirs.parquet", "--workspace", "workspaces/w")[1]["placements"][0]["feature"] == "Address/Address"  # offered again


def test_a_workspace_keeps_its_own_mapping_and_a_copy_of_its_files(tmp_path, population, capsys, monkeypatch):
    import threading
    from er import folder
    from er.cli import main
    from er.settings import settings_path
    from er.source import sha256
    s, p, g = population
    g.df.rename(columns={s.data.unique_id: "customer_no"}).to_parquet(tmp_path / "theirs.parquet", index=False)  # their own ID column
    monkeypatch.chdir(tmp_path)  # workspaces/, in the folder nayose starts from
    project = settings_path().read_text(encoding="utf-8")

    def say(*words: object) -> tuple[int, dict]:  # the exit code, and the last event
        code = main([*map(str, words), "--format", "json"])
        return code, json.loads(capsys.readouterr().out.splitlines()[-1])

    assert say("create", "workspace", "a")[0] == 0 and say("create", "workspace", "b")[0] == 0
    assert say("create", "workspace", "a")[0] == 2 and say("create", "workspace", "../x")[0] == 2  # taken; not a name
    (tmp_path / "workspaces" / "notes").mkdir()  # a folder that is no workspace
    assert {w["name"] for w in say("list", "workspaces")[1]["workspaces"]} == {"a", "b"}
    a, b = Path("workspaces/a"), Path("workspaces/b")

    code, e = say("load", "records", "theirs.parquet", "--workspace", a)  # copied, then described: the ID is not where the mapping looks
    assert code == 0 and [(x["field"], x["column"]) for x in e["suggested"]] == [("id", "customer_no")] and "turned_off" not in e  # nothing prepared
    code, e = say("check", "records", a / "inputs" / "0001-theirs", "--workspace", a)  # the full check stops, and says the line to run
    assert code == 2 and e["hints"] == {"id": "customer_no"} and "set columns id=customer_no --workspace" in e["fix"]
    assert folder.sums(a / "inputs" / "0001-theirs") == {"theirs.parquet": sha256(tmp_path / "theirs.parquet")}
    say("load", "records", "theirs.parquet", "--workspace", a)
    assert [x.name for x in folder.parts(a)] == ["0001-theirs"]  # the same content again: not copied again
    assert say("set", "columns", "id=customer_no", "--workspace", a)[0] == 0
    assert settings_path().read_text(encoding="utf-8") == project and 'id = "CONT_ID"' in (b / "columns.toml").read_text()  # a's alone
    code, e = say("resolve", "records", "--workspace", b)
    assert code == 2 and e["error"].startswith("no records file")
    assert say("resolve", "records", "--workspace", a)[1]["summary"][0][1].startswith(f"{len(g.df):,}")  # the file loaded last
    (tmp_path / "theirs.parquet").unlink()
    assert say("rerun", "records", "--workspace", a)[0] == 0  # its own copy: the original may go
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")  # another folder: the paths steps.json holds lead nowhere, its inputs/ still holds them
    assert say("rerun", "records", "--workspace", tmp_path / a)[0] == 0
    monkeypatch.chdir(tmp_path)
    d = say("describe", "workspace", a)[1]
    assert d["columns"] == "own" and [(x["name"], x["read"]) for x in d["inputs"]] == [("0001-theirs", True)]
    assert say("describe", "workspace", b)[1]["records"] == 0  # nothing run yet: no error
    assert say("describe", "workspace", "workspaces/none")[0] == 2

    for n, rows in (("one", g.df.iloc[:10]), ("two", g.df.iloc[10:20])):
        rows.to_parquet(tmp_path / f"{n}.parquet", index=False)
    said = []

    def take(n: str) -> None:
        try:
            said.append(folder.take_in(b, tmp_path / f"{n}.parquet")[0].name)
        except folder.Busy:  # one writer at a time: the others are told to try again
            said.append("busy")
    given = [threading.Thread(target=take, args=(n,)) for n in ("one", "two", "one")]  # at once
    [t.start() for t in given]
    [t.join() for t in given]
    for n in ("one", "two"):  # tried again, one at a time
        take(n)
    names = [x.name for x in folder.parts(b)]
    assert "busy" in said or len(set(said)) < 3  # they met
    assert sorted(x.split("-", 1)[1] for x in names) == ["one", "two"] and len({x[:4] for x in names}) == 2  # each once, numbered apart
    assert not list((b / "inputs").glob(".*"))  # no copy left half done


def test_design_time_measures_the_run_s_own_gold_pairs_and_rule_clusters(tmp_path, population):
    """scripts/choose.py measures through er.pipeline, which reads the tables of an er.run.Run: it must report the gold,
    the accepted pairs and their weights, and the rules' clusters that the run writes."""
    from er.pipeline import automatic, run_fs, run_rules
    from er.run import Run
    s, p, g = population
    p = replace(p, fs=replace(p.fs, needs=("name", "company")))  # a pair with no name compared is held back
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")
    res = run_fs(p, s, tmp_path / "all.parquet", g.truth, run.model)
    labelled = (res.records.set_index(uid)[["CLUSTER_ID", "MATCH_STAGE", "MATCH_RULE"]]
                .set_axis(["cluster_id", "resolved_stage", "resolved_by"], axis=1).astype("string"))
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)[list(labelled.columns)].astype("string")
    pd.testing.assert_frame_equal(gold, labelled.loc[gold.index], check_index_type=False)
    key = lambda d: d[[l, r, "match_weight"]].astype({l: "string", r: "string"}).sort_values([l, r], ignore_index=True)
    design, ran = key(res.scored[automatic(res.scored, p.fs.min_match_weight) & res.scored["keep"]]), key(pd.read_parquet(tmp_path / "run" / "matches"))
    assert len(design) > 0
    pd.testing.assert_frame_equal(design, ran, check_exact=False, atol=1e-9)
    rules = run_rules(p, s, tmp_path / "all.parquet", g.truth).records.set_index(uid)["CLUSTER_ID"]
    stored = pd.read_parquet(tmp_path / "run" / "state" / "rule_clusters.parquet").set_index(uid)["cluster_id"].astype("string")
    assert rules.loc[stored.index].tolist() == stored.tolist()


def test_a_pair_with_no_name_compared_is_left_to_people(tmp_path, population):
    """A company at a person's address with the person's phone: each record lacks the other's name field, so no name
    is compared, and address and phone alone reach the threshold. With needs, people decide it instead."""
    from er.report import qa
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    home = g.df[g.df[["FULL_NAME_KANA", "PHONE_NUM_4", "SOURCE_ADDR_CD", "STD_ADDRESS"]].notna().all(axis=1)].iloc[0]
    firm = home.copy()
    firm[["FULL_NAME_KANA", "O_PERSON_NAME_KANA", "LAST_NAME_KANA", "GIVEN_NAME_KANA", "CIF_ID", "BIRTH_DATE"]] = pd.NA
    firm[[uid, "NYS_CNV_P_NAME_KANA"]] = ["9" * len(home[uid]), "カブシキガイシャテスト"]
    pd.concat([g.df, firm.to_frame().T.astype(g.df.dtypes)], ignore_index=True).to_parquet(tmp_path / "all.parquet", index=False)
    pair = (home[uid], firm[uid])
    p = replace(p, fs=replace(p.fs, min_match_weight=4.0))
    for needs, out in (((), "a"), (("name", "company"), "b")):
        run = Run(replace(p, fs=replace(p.fs, needs=needs)), s).full(tmp_path / "all.parquet", tmp_path / out)
        weight = run.con.execute(f'SELECT match_weight FROM scores WHERE "{l}" = ? AND "{r}" = ?', list(pair)).fetchall()[0][0]
        merged = run.con.execute(f'SELECT count(*) FROM matches WHERE "{l}" = ? AND "{r}" = ?', list(pair)).fetchall()[0][0]
        assert weight >= 4.0 and merged == (not needs)
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    row = sheet[(sheet[l] == pair[0]) & (sheet[r] == pair[1])]
    assert row["why"].tolist() == ["decide"] and not row["accepted"].any()


def test_the_batch_budget_counts_the_pairs_touching_the_batch():
    df = pd.DataFrame({"id": [f"{i:02d}" for i in range(9)], "k": list("aaabbbccc"), "n": ["サトウ", "サト", "サウ", "スズキ", "スズ", "ヤマダ",
                                                                                         "ヤマダ", "ヤマ", "タナカ"]})
    batch = ["00", "03", "04"]
    for b in (KeyBlocker(name="k", keys=(Key("k"),)), DeletionKeys(name="d", key=Key("n"))):
        r = Records(df, "id", query=batch)
        est, pairs = estimate_touching(b, r), generate(b, df, "id", batch)
        r.close()
        assert est["est_pairs"] >= len(pairs) > 0  # an upper bound, exact for equal keys
        assert est["est_pairs"] == len(pairs) or isinstance(b, DeletionKeys)


@pytest.fixture(scope="module")
def wide_band(population):
    """The final pipeline with a wide safety margin (four grid steps) and its threshold three steps up, so the margin holds
    pairs to decide on a small population."""
    s, p, g = population
    return s, replace(p, threshold=replace(p.threshold, margin_steps=4), fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 6)), g


def test_the_review_sheet_asks_about_each_cluster_pair_in_the_safety_margin_once(tmp_path, wide_band):
    from er.match import review_floor
    from er.report import qa
    from er.run import Run
    s, p, g = wide_band
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    t, lo = p.fs.min_match_weight, review_floor(p)
    assert lo == t - 8  # margin_steps (4) grid steps of 2 bits below the threshold
    decide, audit = sheet[sheet["why"] == "decide"], sheet[sheet["why"] == "audit"]
    assert len(decide) and sheet["decision"].isna().all()
    assert decide["match_weight"].between(lo, t, inclusive="left").all() and audit["accepted"].all()
    gold = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)["cluster_id"]
    a, b = decide[f"{uid}_l"].map(gold).to_numpy(), decide[f"{uid}_r"].map(gold).to_numpy()
    assert (a != b).all() and not pd.DataFrame({"x": np.minimum(a, b), "y": np.maximum(a, b)}).duplicated().any()


def test_decisions_join_clusters_without_scoring_and_a_full_run_applies_them_again(tmp_path, wide_band):
    from er.report import qa
    from er.run import Run
    s, p, g = wide_band
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    yes = sheet[sheet["why"] == "decide"].index[0]
    sheet.loc[yes, "decision"] = "match"
    sheet.to_parquet(tmp_path / "reviewed.parquet")  # the sheet as people return it; undecided rows are skipped
    rejected = run.con.execute(f'SELECT "{l}", "{r}" FROM matches ORDER BY match_weight DESC LIMIT 1').fetchall()[0]
    pd.DataFrame({l: [rejected[0]], r: [rejected[1]], "decision": [" No_Match "]}).to_parquet(tmp_path / "rejected.parquet")
    before = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    Run(p, s).decide(tmp_path / "reviewed.parquet", tmp_path / "a")
    Run(p, s).decide(tmp_path / "rejected.parquet", tmp_path / "a")  # an accepted pair people reject: it splits nothing now
    after = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    pair = sheet.loc[yes, [l, r]].tolist()
    assert after.loc[pair[0], "cluster_id"] == after.loc[pair[1], "cluster_id"] != before.loc[pair[1], "cluster_id"] or \
        before.loc[pair[0], "cluster_id"] != before.loc[pair[1], "cluster_id"]
    joined = before["resolved_stage"].isna() & after["resolved_stage"].notna()
    assert joined.any() and after.loc[joined, "resolved_by"].eq("review").all()
    assert len(pd.read_parquet(tmp_path / "a" / "decisions")) == 2

    rerun = Run(p, s, model=run.model).full(tmp_path / "all.parquet", tmp_path / "a", overwrite=True)  # people's work survives
    again = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    assert again.loc[pair[0], "cluster_id"] == again.loc[pair[1], "cluster_id"]
    matches = pd.read_parquet(tmp_path / "a" / "matches")
    assert not ((matches[l] == rejected[0]) & (matches[r] == rejected[1])).any()
    sheet = qa(rerun, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]  # what people see: what the run did
    accepted = sheet.set_index([l, r]).index.isin(matches.set_index([l, r]).index)
    assert (sheet["accepted"] == accepted).all() and sheet.loc[sheet["why"] == "audit", "accepted"].all()
    assert not ((sheet[l] == rejected[0]) & (sheet[r] == rejected[1])).any()  # a pair people rejected is no audit row

    sheet.loc[yes, "decision"] = "maybe"
    sheet.to_parquet(tmp_path / "bad.parquet")
    with pytest.raises(ValueError, match="match or no_match"):
        Run(p, s).decide(tmp_path / "bad.parquet", tmp_path / "a")
    pd.DataFrame({l: ["nobody"], r: [pair[0]], "decision": ["match"]}).to_parquet(tmp_path / "unknown.parquet")
    with pytest.raises(ValueError, match="IDs that name no record of the run"):
        Run(p, s).decide(tmp_path / "unknown.parquet", tmp_path / "a")
    pd.DataFrame({l: [None], r: [pair[0]], "decision": ["match"]}).to_parquet(tmp_path / "blank.parquet")
    with pytest.raises(ValueError, match="decided rows lack an ID"):  # it would decide a pair of one record with itself
        Run(p, s).decide(tmp_path / "blank.parquet", tmp_path / "a")


def test_an_increment_counts_exact_u_again_and_samples_only_a_drifted_comparison(tmp_path, population, monkeypatch):
    import json
    import er.match as M
    from er.run import Run
    s, p, g = population
    new = np.random.default_rng(1).random(len(g.df)) < 0.1
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    full = Run(p, s).full(tmp_path / "old.parquet", tmp_path / "c")
    basis = json.loads((tmp_path / "c" / "state" / "scoring.json").read_text())["basis"]
    model = p.fs.model
    same = stale_u(model, basis, {name: b["exact"] for name, b in basis.items()}, full.n)
    assert all(x["drift_bits"] == 0 for x in same.values())  # nothing moved: nothing is stale
    halved = {name: {k: v / (2 if name == "name" else 1) for k, v in b["exact"].items()} for name, b in basis.items()}
    moved = stale_u(model, basis, halved, full.n)
    assert moved["name"]["drift_bits"] == pytest.approx(1) and all(x["drift_bits"] == 0 for k, x in moved.items() if k != "name")
    assert stale_u(model, {}, {}, full.n)["name"]["drift_bits"] == math.inf  # never sampled: sample it

    sampled, real = [], M.sample_u
    monkeypatch.setattr(M, "sample_u", lambda m, comps, *a: sampled.extend(c.name for c in comps) or real(m, comps, *a))
    inc = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c")
    after = json.loads((tmp_path / "c" / "state" / "scoring.json").read_text())["basis"]
    stale = [k for k, b in after.items() if b["last_check"]["drift_bits"] > (b["last_check"]["se_bits"] or math.inf)]
    assert sampled == stale  # sampled again exactly where drift outgrew the sampling error
    exact = exact_u(model, "records", inc.db)  # the exact levels are always counted on every record
    for c in inc.scoring["comparisons"]:
        for lv in c["comparison_levels"]:
            if lv.get("label_for_charts") in exact.get(c["output_column_name"], {}):
                assert lv["u_probability"] == pytest.approx(exact[c["output_column_name"]][lv["label_for_charts"]])


def test_the_loader_reads_parquet_by_column_name_and_says_what_is_wrong(tmp_path, con_db):
    from er.source import open_source
    con, _ = con_db
    pd.DataFrame({"cont_id": ["1", "2"], "Phone-Num 4": [599, 1234], "x": ["a", "b"]}).to_parquet(tmp_path / "a.parquet", index=False)
    pd.DataFrame({"CONT_ID": ["3"], "y": ["c"]}).to_parquet(tmp_path / "b.parquet", index=False)
    src = open_source(tmp_path / "a.parquet", con, ["CONT_ID", "PHONE_NUM_4"])  # case, width and separators aside
    assert src.columns == ["CONT_ID", "PHONE_NUM_4", "x"]
    assert con.execute(f"SELECT PHONE_NUM_4 FROM {src.sql}").fetchall() == [("599",), ("1234",)]  # text, zeros lost upstream
    assert any("read as CONT_ID" in x for x in src.notes) and any("stored as a number" in x for x in src.notes)
    both = open_source(tmp_path / "*.parquet", con, ["CONT_ID"])  # a glob: read together by column name
    assert con.execute(f"SELECT count(*) FROM {both.sql}").fetchall()[0][0] == 3 and any("lacks" in x for x in both.notes)

    with pytest.raises(InputError, match="no file matches") as e:
        open_source(tmp_path / "aa.parquet", con, [])
    assert "a.parquet" in e.value.fix  # did you mean
    (tmp_path / "c.parquet").write_text("CONT_ID,name\n1,x\n")
    with pytest.raises(InputError, match="looks like text"):
        open_source(tmp_path / "c.parquet", con, [])
    (tmp_path / "d.parquet").write_bytes((tmp_path / "a.parquet").read_bytes()[:-10])
    with pytest.raises(InputError, match="cut short"):
        open_source(tmp_path / "d.parquet", con, [])
    pd.DataFrame({"cont_id": ["1"], "CONT-ID": ["2"]}).to_parquet(tmp_path / "e.parquet", index=False)
    with pytest.raises(InputError, match="could each be CONT_ID"):
        open_source(tmp_path / "e.parquet", con, ["CONT_ID"])


def test_a_run_sets_aside_what_it_cannot_resolve_and_suggests_a_mapping(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    df = pd.concat([df, df.iloc[[0]], df.iloc[[1]].assign(PHONE_NUM_4="9999")], ignore_index=True)  # an exact copy; a clash
    df.loc[2, uid] = " "  # no ID
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    aside = pd.read_parquet(tmp_path / "run" / "set_aside")
    assert sorted(aside["reason"]) == ["no ID", "the same ID with different content", "the same ID with different content"]
    assert run.n == len(g.df) - 2 and any("kept once" in x for x in run.notes)

    g.df.rename(columns={uid: "customer_no"}).to_parquet(tmp_path / "renamed.parquet", index=False)
    with pytest.raises(InputError, match="lacks a field every run needs") as e:
        Run(p, s).load(tmp_path / "renamed.parquet")
    assert 'id = "customer_no"' in e.value.fix  # suggested from its values: filled and unique



def nayose(*words: object, check: bool = False):  # the command line, as a user runs it, in a process of its own
    import subprocess
    import sys
    return subprocess.run([sys.executable, "-m", "er.cli", *map(str, words)], capture_output=True, text=True, check=check)


def test_nayose_prints_a_mistake_as_two_lines_and_exits_with_2(tmp_path):
    done = nayose("check", "records", tmp_path / "none.parquet")
    assert done.returncode == 2 and done.stderr.splitlines()[0].startswith("error: no file matches")
    assert done.stderr.splitlines()[1].startswith("fix: ") and "Traceback" not in done.stderr
    done = nayose("check", "records", tmp_path / "none.parquet", "--format", "json")
    error = json.loads(done.stdout.splitlines()[-1])
    assert done.returncode == 2 and error["event"] == "error" and error["exit"] == 2 and error["fix"]
    assert nayose("resolve", "records", tmp_path / "x.parquet").returncode == 2  # --workspace missing: the parser says so


def test_every_command_has_its_help(capsys):
    from er.cli import COMMANDS, parser
    for c in COMMANDS:
        with pytest.raises(SystemExit) as done:
            parser().parse_args([c.verb, c.noun, "--help"])
        shown = capsys.readouterr().out
        assert done.value.code == 0 and c.help in shown and c.example in shown


def test_nayose_takes_a_file_from_the_check_to_people_s_answers(tmp_path, population, capsys):
    from er.cli import COMMANDS, main
    s, p, g = population
    uid, half = s.data.unique_id, len(g.df) // 2
    g.df.iloc[:half].to_parquet(tmp_path / "first.parquet", index=False)
    g.df.iloc[half:].to_parquet(tmp_path / "new.parquet", index=False)
    run, declared = tmp_path / "run", {c.name: set(c.result) for c in COMMANDS}

    def say(*words: object) -> dict:  # one command, as JSON; its result checked against its declaration
        code = main([*map(str, words), "--format", "json"])
        said = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
        assert code == 0 and said[-1]["event"] == "result", said[-1]
        r = said[-1]
        assert set(r) - {"event", "command"} <= declared[r["command"]] and "next" in r
        return r

    assert say("check", "records", tmp_path / "first.parquet")["records"] == half
    assert say("resolve", "records", tmp_path / "first.parquet", "--workspace", run)["summary"][0][0] == "records"
    pair = say("list", "pairs", "--workspace", run, "--open")["pairs"][0]
    say("decide", "pair", pair["id_r"], pair["id_l"], "match", "--workspace", run)  # either order
    assert say("apply", "decisions", "--workspace", run)["matches"] == 1
    assert say("apply", "decisions", "--workspace", run)["decisions"] == 0  # given twice: nothing new
    gold = pd.read_parquet(run / "gold.parquet").set_index(uid)
    assert gold.loc[pair["id_l"], "cluster_id"] == gold.loc[pair["id_r"], "cluster_id"]
    record = say("list", "kinds", "--workspace", run, "--open")["kinds"][0]["id"]
    say("answer", "kind", record, "company", "--workspace", run)
    say("apply", "answers", "--workspace", run)
    assert pd.read_parquet(run / "gold.parquet").set_index(uid).loc[record, ["kind", "kind_by"]].tolist() == [2, "people"]
    entity = say("describe", "entity", pair["id_l"], "--workspace", run)
    assert {pair["id_l"], pair["id_r"]} <= {x["id"] for x in entity["records"]} and any(x["by"] == "people: match" for x in entity["links"])
    matched = say("match", "records", tmp_path / "new.parquet", "--workspace", run)
    assert len(matched["records"]) == len(g.df) - half and set(matched["counts"]) <= {"joins an entity", "a new entity"}
    added = say("add", "records", tmp_path / "new.parquet", "--workspace", run)
    assert added["summary"][0][1].startswith(f"{len(g.df):,}")
    assert say("describe", "workspace", run)["records"] == len(g.df)
    graph = say("describe", "matching", "--workspace", run)
    assert {n["id"] for n in graph["nodes"]} >= {"rules", "candidates", "score", "group"} and graph["edges"]


def test_a_nearly_empty_field_is_kept_and_the_fit_skips_what_it_cannot_learn_from(tmp_path, population):
    from er.run import Run
    s, p, g = population
    sparse = g.df.copy()
    sparse.loc[sparse.index[10:], ["STD_ADDRESS", "ORIGINAL_ADDRESS"]] = None  # no two records share an address
    sparse.to_parquet(tmp_path / "sparse.parquet", index=False)
    seen = []
    run = Run(p, s, echo=seen.append).full(tmp_path / "sparse.parquet", tmp_path / "run")
    assert [x["step"] for x in seen] == ["load", "budget", "fit", "rules", "candidates", "score", "cluster", "write"]  # step by step
    assert "address" in run.model["er"]["skipped"] and any("sharing address" in x for x in run.notes)
    sparse.assign(PHONE_NUM_4=None).to_parquet(tmp_path / "bare.parquet", index=False)  # nothing left to learn from
    with pytest.raises(InputError, match="can't be estimated|share phone or address"):  # whichever check finds nothing first
        Run(p, s).full(tmp_path / "bare.parquet", tmp_path / "bare")


def test_an_increment_keeps_the_open_review_queue(tmp_path, population):
    from er.report import qa
    from er.run import Run
    s, p, g = population
    p = replace(p, threshold=replace(p.threshold, margin_steps=4), fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 6))  # a wide band
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    new = np.random.default_rng(2).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    fields = [f for f in s.columns if f not in ("id", "entity")]
    run = Run(p, s).full(tmp_path / "old.parquet", tmp_path / "c")
    first = qa(run, fields)["review_sheet"]
    first.to_parquet(tmp_path / "c" / "review.parquet")
    open_ = first[first["why"] == "decide"]
    assert len(open_) >= 2
    first.loc[open_.index[:1], "decision"] = "no_match"  # one decided and given back; the rest still open
    first.loc[open_.index[:1]].to_parquet(tmp_path / "given.parquet")
    Run(p, s).decide(tmp_path / "given.parquet", tmp_path / "c")
    inc = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c")
    sheet = qa(inc, fields, previous=tmp_path / "c" / "review.parquet")["review_sheet"]
    pairs = set(map(tuple, sheet.loc[sheet["why"] == "decide", [l, r]].to_numpy()))
    gold = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    still = {(a, b) for a, b in open_.iloc[1:][[l, r]].to_numpy() if gold[a] != gold[b]}
    assert still and still <= pairs  # still open after the increment
    assert tuple(open_.iloc[0][[l, r]]) not in pairs  # decided: gone


def test_a_run_folder_takes_one_writer_at_a_time(tmp_path, population):
    import threading
    from er.folder import run_lock
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    held, done = threading.Event(), threading.Event()

    def other_job():  # another job holds the folder, in a thread of its own
        with run_lock(tmp_path / "run"):
            held.set()
            done.wait()
    job = threading.Thread(target=other_job)
    job.start()
    held.wait()
    with pytest.raises(InputError, match="another job is writing"):
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")
    done.set()
    job.join()
    with run_lock(tmp_path / "run"), run_lock(tmp_path / "run"):  # the thread holding it may take it again (a rerun's full run)
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")  # released by the other: free again


def test_matching_a_batch_names_the_entities_adding_it_would_give_and_writes_nothing(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid, half = s.data.unique_id, len(g.df) // 2
    g.df.iloc[:half].to_parquet(tmp_path / "first.parquet", index=False)
    pd.concat([g.df.iloc[half:], g.df.iloc[:1]]).to_parquet(tmp_path / "batch.parquet", index=False)  # one already in the run
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "first.parquet", out)
    files = lambda: {f: f.read_bytes() for f in out.rglob("*") if f.is_file() and f.name != ".lock"}
    before = files()
    m = Run(p, s).match(tmp_path / "batch.parquet", out)
    assert files() == before
    assert m.loc[m[uid] == g.df.iloc[0][uid], "status"].item() == "already in the run"
    assert set(m["status"]) == {"joins an entity", "a new entity", "already in the run"} and len(m) == len(g.df) - half + 1
    Run(p, s).increment(tmp_path / "batch.parquet", out)
    gold = pd.read_parquet(out / "gold.parquet").set_index(uid)["cluster_id"]
    assert (gold.loc[m[uid]].to_numpy() == m["entity"].to_numpy()).all()  # the entities the increment then gave


def test_a_rerun_reads_the_run_s_files_in_order_and_keeps_what_the_increments_kept(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid, n = s.data.unique_id, len(g.df)
    other = next(c for c in g.df.columns if c != uid)
    resent = g.df.iloc[:1].assign(**{other: "changed"})  # an ID of the run, sent again with other content
    for i, part in enumerate([g.df.iloc[:n // 2], g.df.iloc[n // 2:3 * n // 4], pd.concat([g.df.iloc[3 * n // 4:], resent])]):
        part.to_parquet(tmp_path / f"{i}.parquet", index=False)
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "0.parquet", out)
    for i in (1, 2):
        Run(p, s).increment(tmp_path / f"{i}.parquet", out)
    added = pd.read_parquet(out / "gold.parquet")
    Run(p, s).rerun(out)
    again = pd.read_parquet(out / "gold.parquet")
    Run(p, s).full([tmp_path / f"{i}.parquet" for i in range(3)], tmp_path / "fresh")
    assert again.equals(pd.read_parquet(tmp_path / "fresh" / "gold.parquet"))  # a full run on the same files, in order
    assert sorted(again[uid]) == sorted(added[uid])
    aside = pd.read_parquet(out / "set_aside")
    assert aside.loc[aside[uid] == resent[uid].item(), "reason"].tolist() == ["already in the run"]
    (tmp_path / "1.parquet").unlink()
    with pytest.raises(InputError, match="1.parquet: gone since the run read it"):
        Run(p, s).rerun(out)


def test_one_answer_is_typed_into_the_sheet_and_waits_for_a_busy_folder(tmp_path, population):
    import threading
    from er.folder import Busy, run_lock, type_in
    from er.run import Run
    s, p, g = population
    l, r = f"{s.data.unique_id}_l", f"{s.data.unique_id}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    a, b = pd.read_parquet(out / "review.parquet").iloc[0][[l, r]]
    type_in(out, "review.parquet", "decision", "match", **{l: a, r: b})
    sheet = pd.read_parquet(out / "review.parquet")
    assert sheet.iloc[0]["decision"] == "match" and sheet["decision"].iloc[1:].isna().all()
    type_in(out, "review.parquet", "decision", None, **{l: a, r: b})
    assert pd.read_parquet(out / "review.parquet")["decision"].isna().all()
    with pytest.raises(InputError, match="no row for"):
        type_in(out, "review.parquet", "decision", "match", **{l: b, r: "nobody"})
    held, done = threading.Event(), threading.Event()

    def other_job():  # a run writing to the folder, in a thread of its own
        with run_lock(out):
            held.set()
            done.wait()
    job = threading.Thread(target=other_job)
    job.start()
    held.wait()
    with pytest.raises(Busy):
        type_in(out, "review.parquet", "decision", "match", **{l: a, r: b})
    done.set()
    job.join()


def test_set_columns_rewrites_the_fields_lines_and_keeps_the_rest(tmp_path):
    import shutil
    from er.settings import set_columns
    root = load_settings().root
    (tmp_path / "config").mkdir()
    (tmp_path / "pyproject.toml").touch()
    f = tmp_path / "config" / "settings.toml"
    shutil.copy(root / "config" / "settings.toml", f)
    before = f.read_text(encoding="utf-8")
    set_columns(f, {"phone": (("TEL4",),), "person_name": (("NAME",), ("SEI", "MEI")), "town_code": (("TOWN",),), "birth_date": ()})
    s = load_settings(f)
    assert s.columns["phone"] == (("TEL4",),) and s.columns["person_name"] == (("NAME",), ("SEI", "MEI")) and s.columns["birth_date"] == ()  # no column, still declared
    after = f.read_text(encoding="utf-8")
    line = lambda name: next(x for x in after.split("\n[columns]\n", 1)[1].splitlines() if x.startswith(f"{name} ="))
    assert 'normalize = ["nfkc", "strip_spaces"]' in line("person_name") and "# municipality + town + chome" in line("town_code")  # options, comments stay
    assert len(after.splitlines()) == len(before.splitlines()) and line("birth_date").startswith("birth_date = []") and "#" in line("birth_date")
    with pytest.raises(InputError, match="id must name one column"):
        set_columns(f, {"id": (("A",), ("B",))})
    assert f.read_text(encoding="utf-8") == after and not (tmp_path / "config" / "settings.toml.tmp").exists()


def test_describe_says_what_a_run_folder_holds_and_what_joined_an_entity(tmp_path, population):
    from er.report import describe_entity, describe_workspace
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out = tmp_path / "run"
    run = Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    gold = pd.read_parquet(out / "gold.parquet")
    d = describe_workspace(run.con, out, uid)
    assert (d["records"], d["entities"]) == (len(gold), gold["cluster_id"].nunique()) and d["runs"][0]["what"] == "full run"
    assert d["pairs"]["decide"] + d["pairs"]["audit"] == len(pd.read_parquet(out / "review.parquet")) and not d["write_owed"]
    assert d["summary"][0][0] == "records"
    big = d["largest"][0]
    e = describe_entity(run.con, out, uid, big["entity"], run.fields)
    assert len(e["records"]) == big["records"] and len(e["links"]) >= big["records"] - 1  # a cluster is joined by its links
    assert {x["by"] for x in e["links"]} <= {*(r.name for _, _, r in p.rules.each()), "fs"}
    with pytest.raises(InputError, match="no record of the run"):
        describe_entity(run.con, out, uid, "nobody", run.fields)


def test_a_sheet_given_back_with_no_answer_or_a_kind_in_words_is_refused(tmp_path):
    import duckdb
    from er.source import answers, decisions
    pd.DataFrame({"uid_l": ["1"], "uid_r": ["2"], "decision": [None]}, dtype="string").to_parquet(tmp_path / "untouched.parquet")
    with pytest.raises(InputError, match="no row has a decision"):
        decisions(tmp_path / "untouched.parquet", duckdb.connect(), "uid_l", "uid_r", into="d")
    for kinds, error in ([None, None], "no row is answered"), (["2 company", None], r"a kind is 1, 2 or 0, not \['2 company'\]"):
        pd.DataFrame({"uid": ["1", "2"], "kind": kinds}, dtype="string").to_parquet(tmp_path / "kinds.parquet")
        with pytest.raises(InputError, match=error):
            answers(tmp_path / "kinds.parquet", duckdb.connect(), "uid")
    pd.DataFrame({"uid": ["1", "2"], "kind": ["2.0", None]}, dtype="string").to_parquet(tmp_path / "kinds.parquet")
    assert len(answers(tmp_path / "kinds.parquet", duckdb.connect(), "uid")) == 1  # a spreadsheet's 2.0 is 2



def test_a_run_and_its_reports_land_together_even_when_the_write_is_cut_short(tmp_path, population, monkeypatch):
    import er.folder
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out, real = tmp_path / "run", er.folder.finish_writes

    def killed(folder):  # the process dies once the moves owed are saved, before it does them
        if (folder / "pending.json").exists():
            raise SystemExit("killed")
        real(folder)
    monkeypatch.setattr(er.folder, "finish_writes", killed)
    with pytest.raises(SystemExit):
        Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    monkeypatch.setattr(er.folder, "finish_writes", real)
    again = Run(p, s).increment(tmp_path / "all.parquet", out)  # the retry: the next job finishes the moves, and finds nothing new
    assert again.added == 0 and (out / "gold.parquet").exists()
    assert {"qa.md", "report.txt", "review.parquet", "kind_review.parquet"} <= {f.name for f in out.iterdir()} and not list(out.rglob("*.tmp"))


def test_the_scheduler_serves_the_inbox_in_order_and_parks_what_people_must_fix(tmp_path, population):
    import os
    import shutil
    import sys
    from er import inbox as schedule
    s, p, g = population
    uid = s.data.unique_id
    made = []
    code, _, _, tries = schedule.attempt(lambda: made.append(1) or [sys.executable, "-c", "import sys; sys.exit(1)"], retries=2, wait=0)
    assert (code, tries, len(made)) == (1, 3, 3)  # an unexpected failure is tried again, its command made again: the folder may hold the run now

    inbox, run = tmp_path / "inbox", tmp_path / "run"
    (inbox / "batches").mkdir(parents=True)
    new = np.random.default_rng(3).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(inbox / "batches" / "a_first.parquet", index=False)
    g.df[new].to_parquet(inbox / "batches" / "b_new.parquet", index=False)
    shutil.copy(inbox / "batches" / "b_new.parquet", inbox / "batches" / "c_again.parquet")  # the same content, twice
    (inbox / "batches" / "d_bad.parquet").write_text("CONT_ID\n1\n")  # a CSV, named as Parquet
    for k, f in enumerate(sorted((inbox / "batches").iterdir())):
        os.utime(f, (1_000 + k, 1_000 + k))  # arrival order
    serve = lambda: nayose("serve", "inbox", inbox, "--workspace", run)
    done = serve()
    assert done.returncode == 0, done.stderr
    jobs = [(e["file"], e["outcome"]) for e in schedule.ledger(run)]
    assert jobs == [("a_first.parquet", "done"), ("b_new.parquet", "done"), ("c_again.parquet", "done"), ("d_bad.parquet", "failed")]
    assert len(pd.read_parquet(run / "gold.parquet")) == len(g.df)  # the first batch the full run, the second an increment
    parked = list((inbox / "failed" / "batches").glob("*.error.txt"))
    assert len(parked) == 1 and "not a Parquet file" in parked[0].read_text()
    assert not list((inbox / "batches").glob("*.parquet"))

    sheet = pd.read_parquet(run / "review.parquet")
    (inbox / "decisions").mkdir(exist_ok=True)
    sheet.iloc[:1].assign(decision="match").to_parquet(inbox / "decisions" / "reviewed.parquet")
    assert serve().returncode == 0 and schedule.ledger(run)[-1]["outcome"] == "done"
    assert (run / "decisions").exists()
    from er.folder import inputs
    assert [f.parent.name for f in inputs(run)] == ["0001-a_first", "0002-b_new"]  # copied into the workspace: found there, wherever the batch went
    before = len(schedule.ledger(run))
    assert serve().returncode == 0 and len(schedule.ledger(run)) == before  # nothing waiting: nothing done

    from er.folder import run_lock
    g.df[~new].head(10).to_parquet(inbox / "batches" / "e_busy.parquet", index=False)  # records the run holds: nothing new
    with run_lock(run):  # someone runs nayose on the folder by hand
        busy = nayose("serve", "inbox", inbox, "--workspace", run, "--retries", "0")
    assert busy.returncode != 0 and (schedule.ledger(run)[-1]["outcome"], schedule.ledger(run)[-1]["exit"]) == ("stopped", 75)
    assert (inbox / "batches" / "e_busy.parquet").exists()  # it waits in the inbox, not parked in failed/
    assert serve().returncode == 0 and schedule.ledger(run)[-1]["outcome"] == "done"

    sheet.assign(decision=pd.NA).to_parquet(inbox / "decisions" / "untouched.parquet")  # given back as it was sent
    answers = pd.DataFrame({uid: g.df[uid].head(3), "kind": ["1", "1", "2"]})
    answers.to_parquet(inbox / "answers" / "three.parquet")
    for k, f in enumerate(("untouched", "three")):
        os.utime(next(inbox.rglob(f"{f}.parquet")), (2_000 + k, 2_000 + k))  # arrival order
    assert serve().returncode == 0
    assert [(e["file"], e["outcome"]) for e in schedule.ledger(run)[-2:]] == [("untouched.parquet", "failed"), ("three.parquet", "done")]
    assert "no row has a decision" in next((inbox / "failed" / "decisions").glob("*untouched.parquet.error.txt")).read_text()
    gold = pd.read_parquet(run / "gold.parquet").set_index(uid)
    assert (gold.loc[answers[uid], "kind_by"] == "people").all()  # the answers went in by a rerun


def test_an_oversized_block_is_checked_on_a_sample_and_a_placeholder_is_skipped(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    dummy = df.index[:100]
    df.loc[dummy, ["PHONE_NUM_4", "ADDRESS_ONE"]] = ["0000", "東京都"]  # a dummy phone on 100 records: one block of 100
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")  # no stop
    block = run.gated[run.gated["value"].str.contains("0000") & (run.gated["generator"] == "phone_prefecture")]
    assert len(block) == 1 and block["decision"].iloc[0].startswith("skipped") and block["records"].iloc[0] == 100
    assert any("0000" in x and "skipped" in x for x in run.examples) and not any("0000" in x for x in run.notes)
    check = nayose("check", "records", tmp_path / "in.parquet")
    assert check.returncode == 0 and "checked by sampling" in check.stdout

    same = pd.concat([g.df.iloc[[0]]] * 70, ignore_index=True)  # 70 copies of one record: every key's block oversized
    same[uid] = [f"copy{i:03d}" for i in range(70)]
    pd.concat([g.df, same]).to_parquet(tmp_path / "copies.parquet", index=False)
    run = Run(p, s).full(tmp_path / "copies.parquet", tmp_path / "copies")
    gold = pd.read_parquet(tmp_path / "copies" / "gold.parquet").set_index(uid)
    assert gold.loc[same[uid], "cluster_id"].nunique() == 1  # the sample shows they match: kept and joined
    assert (run.gated["decision"] == "kept").any()


def test_a_rule_never_trusts_a_value_held_by_an_oversized_block(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    many = df.index[:70]
    df.loc[many, ["CIF_ID", "FULL_NAME_KANA"]] = ["9999999999999", "ヤマダタロウ"]  # one customer ID and name on 70 records
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    kept = pd.read_parquet(tmp_path / "run" / "rule_kept")
    ids = set(df.loc[many, uid])
    by_x1 = kept[(kept["rule"] == "X1_CIF_PERSON_NAME") & kept[f"{uid}_l"].isin(ids) & kept[f"{uid}_r"].isin(ids)]
    assert by_x1.empty and any("X1_CIF_PERSON_NAME doesn't trust" in x for x in run.notes)


def test_the_run_report_holds_no_record_value(tmp_path, population):
    import re
    from er.report import qa, report_text
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    df.loc[df.index[:100], ["PHONE_NUM_4", "ADDRESS_ONE"]] = ["0000", "東京都"]  # placeholders: notes that quote a value
    df.loc[df.index[100:170], ["CIF_ID", "FULL_NAME_KANA"]] = ["9999999999999", "ヤマダタロウ"]
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    tables = qa(run, [f for f in s.columns if f not in ("id", "entity")])
    text = report_text(run, tables, s.root / "config" / "final.toml")
    assert any("9999999999999" in x for x in run.examples) and any("0000" in x for x in run.examples)
    assert not re.search(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]", text)  # no kana or kanji: no name, address or town
    assert not any(v in text for c in (uid, "CIF_ID") for v in df[c].dropna())  # no record ID, no customer ID
    expected = (1 - pd.read_parquet(tmp_path / "run" / "matches")["match_probability"]).sum()
    assert run.steps[-2]["step"] == "cluster" and run.steps[-2]["expected_false"] == round(expected, 2)
    assert f"about {expected:,.{1 if expected >= 1 else 2}f} of them false" in text and "MODEL" in text and "birth_date" in text


def test_the_runaway_guard_stops_only_what_would_not_fit(tmp_path, population, monkeypatch):
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    monkeypatch.setattr(Run, "capacity", lambda self: 10)
    with pytest.raises(InputError, match="more than fit in memory"):
        Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")


def test_the_generator_makes_direct_matches_rare_and_reports_how_hard_it_is():
    from er.generate import check, generate, halfwidth, load_reference, load_spec, profile
    import unicodedata
    s = load_settings()
    spec = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=8_000)
    g = generate(spec, *load_reference(s.paths["reference"]))
    check(spec, g)  # CONT_ID unique, digits, fill rates
    hard = profile(g)
    assert 0.004 <= hard["direct (exact rules)"] <= 0.02  # calibrated to about 1% on the full population
    assert hard["same customer ID"] < 0.05 and 0.05 < hard["nothing in common"] < 0.2
    assert halfwidth("ガッコウ") == "ｶﾞｯｺｳ" and unicodedata.normalize("NFKC", halfwidth("ガッコウ")) == "ガッコウ"


def test_test_is_counted_once_per_population(tmp_path):
    from er.io import append_leaderboard, test_evaluations
    data = replace(load_settings().data, labels_dir=tmp_path / "labels", experiments_dir=tmp_path / "experiments")
    data.labels_dir.mkdir()
    uid, ent = data.unique_id, data.entity_id
    labels = lambda ids: pd.DataFrame({uid: ids, ent: ["E"] * len(ids)}).to_parquet(data.labels_dir / "test.parquet", index=False)
    labels(["1", "2"])
    append_leaderboard(data, "fs:FINAL", ("config", 1), "test", {})
    labels(["3", "4"])  # a newly generated population: a test nobody has seen
    append_leaderboard(data, "fs:FINAL", ("config", 2), "test", {})
    assert test_evaluations(data)["configs_on_test"].max() == 1
    append_leaderboard(data, "fs:FINAL", ("config", 3), "test", {})  # the same population, a second configuration
    assert test_evaluations(data)["configs_on_test"].max() == 2
    (data.labels_dir / "test.parquet").unlink()  # a development round of choose.py: train and val only, test never read
    dev = replace(data, datasets=("train", "val"))
    append_leaderboard(dev, "fs:x", ("config", 4), "val", {})
    assert test_evaluations(dev).empty



# ---------- person or company ----------

@pytest.fixture(scope="module")
def kind_population():
    """A small population with one name column for every kind, a person/company flag that is sometimes wrong, companies
    under their representative's name and sole traders; the settings that read it; the final pipeline."""
    from er.generate import KindProblems, generate as make, kind_problems, load_reference, load_registry, load_spec
    from er.settings import shared_name
    base = load_settings()
    spec = replace(load_spec(base.root / "config" / "generator.toml")[0], entities=1_500)
    ref, std = load_reference(base.paths["reference"]), base.standardize
    g = kind_problems(make(spec, *ref), KindProblems(), load_registry(base.paths["reference"]), std.legal_front, std.legal_end,
                      spec.kana_confusions, spec.branches)
    s = shared_name(base, "NAME_KANA")
    return s, load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns), g


def test_the_name_model_saves_and_loads_to_the_same_scores(tmp_path):
    from er.kind import NameModel
    texts = pd.Series(["ヤマダタロウ", "スズキハナコ", "ヤマダシヨウテン", "トヨタシトウシヤ", "サトウイチロウ", "ミツヒシシヨウシ"] * 3, dtype="string")
    m = NameModel.fit(texts, np.array([0, 0, 1, 1, 0, 1] * 3), ngram=3)
    m.save(tmp_path / "m.npz", "k")
    probe = pd.Series(["ヤマダハナコ", pd.NA, "スズキシヨウテン"], dtype="string")
    back = NameModel.load(tmp_path / "m.npz", "k")
    assert np.allclose(m.logit(probe), back.logit(probe), equal_nan=True) and np.isnan(back.logit(probe)[1])
    assert NameModel.load(tmp_path / "m.npz", "another key") is None  # a model trained under other settings isn't loaded


def test_a_run_loads_the_committed_name_model_and_it_is_what_training_builds():
    """config/kind_names.npz is what scripts/train_name_model.py builds from today's reference data, generator settings
    and code; a run refuses one trained under its other settings."""
    from er.generate import train_name_model
    from er.kind import name_model
    s = load_settings()
    spec = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns).kind
    kept, fresh = name_model(s, spec), train_name_model(s, spec)
    assert kept.terms == fresh.terms and np.allclose(kept.coef, fresh.coef, rtol=0, atol=1e-3) and abs(kept.intercept - fresh.intercept) < 1e-3, \
        "the training changed: run scripts/train_name_model.py and commit config/kind_names.npz"
    other = replace(s, standardize=replace(s.standardize, legal_forms=s.standardize.legal_forms[1:]))
    with pytest.raises(InputError, match="trained under other settings") as stop:
        name_model(other, spec)
    assert "train_name_model.py" in stop.value.fix


def test_each_side_s_line_keeps_within_its_labels():
    from er.config import KindSpec
    from er.kind import lines
    p = np.r_[np.full(50, 0.999), [0.97], np.full(300, 0.01), [0.03]]  # 50 companies, a person at 0.97, 300 persons, a company at 0.03
    company = np.r_[np.ones(50, bool), [False], np.zeros(300, bool), [True]]
    line_c, line_p, error = lines(p, company, KindSpec(margin_steps=1, labels_to_draw=len(p)))
    assert line_c == 0.99   # the lowest line with no person above it is 0.98; one step stricter
    assert lines(p, company, KindSpec(margin_steps=1, labels_to_draw=len(p) + 1))[0] == 0.995  # fewer answers than the draw: one more
    assert (line_p, error) == (0.98, 0.0)  # 300 right: the rate's 95% bound is 0.99%; at 0.95, 1 wrong in 301 bounds it at 1.6%
    few = np.r_[np.full(40, 0.01), np.full(10, 0.999)]  # 40 persons, none wrong: the bound is still 7.2%
    assert lines(few, np.r_[np.zeros(40, bool), np.ones(10, bool)], KindSpec())[1] == 1.01


def test_the_kind_problems_change_names_dates_and_the_flag_only(kind_population):
    from er.generate import generate as make, load_reference, load_spec
    s, p, g = kind_population
    made = make(replace(load_spec(s.root / "config" / "generator.toml")[0], entities=1_500), *load_reference(s.paths["reference"])).df
    assert {"NAME_KANA", "PERSON_ORG_CODE"} <= set(g.df.columns) and "FULL_NAME_KANA" not in g.df.columns
    assert g.df[["CONT_ID", "CIF_ID"]].equals(made[["CONT_ID", "CIF_ID"]])  # the records start as generate() made them
    stay = g.truth["KIND"].eq("person").to_numpy()  # only a company moves: to its representative's address and phone
    assert g.df.loc[stay, ["PHONE_NUM_4", "STD_ADDRESS"]].equals(made.loc[stay, ["PHONE_NUM_4", "STD_ADDRESS"]])
    assert set(g.truth["CASE"]) == {"company", "person", "representative", "sole trader"}
    flag_company = g.df["PERSON_ORG_CODE"] == "2"
    assert 0.02 < (flag_company != g.truth["KIND"].eq("company")).mean() < 0.1  # the flag is wrong, now and then


def test_without_labels_only_a_legal_form_makes_a_company_and_a_person_company_pair_goes_to_people(tmp_path, kind_population):
    from er.report import qa
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    home = g.df[g.df[["NAME_KANA", "PHONE_NUM_4", "SOURCE_ADDR_CD", "STD_ADDRESS"]].notna().all(axis=1) & g.truth["CASE"].eq("person").to_numpy()].iloc[0]
    firm = home.copy()
    firm[["CIF_ID", "BIRTH_DATE"]] = pd.NA
    firm[[uid, "NAME_KANA", "PERSON_ORG_CODE"]] = ["9" * len(home[uid]), "カブシキガイシャテスト", "2"]
    pd.concat([g.df, firm.to_frame().T.astype(g.df.dtypes)], ignore_index=True).to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(replace(p, fs=replace(p.fs, min_match_weight=4.0)), s).full(tmp_path / "all.parquet", tmp_path / "run")
    rec = run.con.sql(f'SELECT "{uid}", person_name, company_name, kind FROM records').df().set_index(uid)
    assert rec.loc[firm[uid], "kind"] == 2 and pd.isna(rec.loc[firm[uid], "person_name"]) and rec.loc[firm[uid], "company_name"] == "カブシキガイシャテスト"
    assert pd.notna(rec.loc[home[uid], "person_name"]) and pd.isna(rec.loc[home[uid], "company_name"])
    named = rec[rec.index.isin(g.df[uid])].join(g.df.set_index(uid)["NAME_KANA"])
    written = named["NAME_KANA"].str.normalize("NFKC").str.replace("[ 　]", "", regex=True).str.contains(legal_pattern(s.standardize))
    assert set(named["kind"]) == {2, 0}  # 2 company or 0 not sure: never a sure person without answers
    assert ((named["kind"] == 2) == written.fillna(False)).all()  # a company exactly where a legal form is written
    pair = (home[uid], firm[uid])
    assert run.con.execute(f'SELECT count(*) FROM matches WHERE "{l}" = ? AND "{r}" = ?', list(pair)).fetchall()[0][0] == 0
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    assert sheet[(sheet[l] == pair[0]) & (sheet[r] == pair[1])]["why"].tolist() == ["decide"]


def kind_sheet_for(run, s, p, draw):  # the run's review sheet, as Run.report writes it, with a smaller draw
    from er.kind import kind_review_sheet
    return kind_review_sheet(run.con, "records", s.data.unique_id, replace(p.kind, labels_to_draw=draw, review_max=200), s.flag_company)


def test_the_review_sheet_says_in_words_why_each_record_is_there(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a"), s, p, 300)
    assert set(sheet["why"]) == {"decide", "measure"} and sheet[uid].is_unique and sheet["kind"].isna().all()
    decide = sheet[sheet["why"] == "decide"]
    assert len(decide) <= 200 and (decide["reason"].str.contains("the flag says")).all()
    assert decide["reason"].str.startswith(("the engine is sure it is", "the engine is not sure", "the name looks like")).all()
    assert set(sheet["engine_says"]) <= {"2 company", "1 person", "0 not sure"} and sheet["name_says"].str.match(r"[12] (company|person) \(").all()
    measure = sheet[sheet["why"] == "measure"]
    assert len(measure) == 300 and set(measure["drawn"]) == {"at random"} and measure["reason"].str.startswith("drawn at random").all()
    flags = g.df.set_index(uid).loc[decide[uid], "PERSON_ORG_CODE"].astype(int).to_numpy()
    sure = decide["reason"].str.startswith("the engine is sure").to_numpy()
    assert sure.any() and (decide["engine"].to_numpy()[sure] != flags[sure]).all()  # held: the engine's sure kind against the flag
    assert decide["reason"].str.endswith("held back from matching until you decide").sum() >= sure.sum()


def test_with_answers_the_kinds_are_the_same_every_run_people_s_stand_and_a_customer_takes_its_surest_record(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a"), s, p, 900)
    sheet["kind"] = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)  # people's answers: here, the truth
    sheet.loc[sheet.index[:3], "kind"] = 0  # can't tell: kept out
    sheet.to_parquet(tmp_path / "labels.parquet")
    a = Run(p, s, kind_labels=tmp_path / "labels.parquet").full(tmp_path / "all.parquet", tmp_path / "b")
    Run(p, s, kind_labels=tmp_path / "labels.parquet").full(tmp_path / "all.parquet", tmp_path / "c")
    ga, gb = (pd.read_parquet(tmp_path / x / "gold.parquet") for x in ("b", "c"))
    assert a.classifier.labels == len(sheet) - 3 and a.classifier.measured == (sheet["why"] == "measure").sum() - (sheet["why"][:3] == "measure").sum()
    assert ga[["kind", "kind_p", "kind_by", "customer_kind"]].equals(gb[["kind", "kind_p", "kind_by", "customer_kind"]])
    answered = ga.set_index(uid).loc[sheet[uid][3:]]
    assert (answered["kind_by"] == "people").all() and (answered["kind"].to_numpy() == sheet["kind"][3:].to_numpy()).all()  # people's answers stand
    assert len(pd.read_parquet(tmp_path / "b" / "kind_answers" / "part-00000.parquet")) == len(sheet)  # kept as given, for later runs
    inputs = json.loads((tmp_path / "b" / "steps.json").read_text())["runs"][0]["inputs"]
    assert {Path(i["file"]).name for i in inputs} == {"all.parquet", "kind_names.npz", "labels.parquet"}  # what went in, with its SHA-256
    by = ga.groupby("cluster_id").agg(any_company=("kind", lambda k: (k == 2).any()), leans=("kind_p", "max"),
                                      any_person=("kind", lambda k: (k == 1).any()), customer=("customer_kind", "first"))
    expect = np.where(by.any_company, 2, np.where((by.leans.fillna(0) < 0.5) & by.any_person, 1, 0))
    assert (by.customer.to_numpy() == expect).all()
    wrong = ga.set_index(uid).join(g.truth.set_index("CONT_ID")["KIND"])
    assert not ((wrong["kind"] == 2) & (wrong["KIND"] != "company")).any()  # no sure company that isn't one


def test_answers_without_a_measuring_draw_keep_the_legal_form_rule(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 600)
    decide = (sheet["why"] == "decide").to_numpy()  # the top of the sheet: answered first
    truth = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)
    sheet.assign(kind=pd.array(np.where(decide, truth, pd.NA), dtype="Int8")).to_parquet(tmp_path / "top.parquet")
    run = Run(p, s, kind_labels=tmp_path / "top.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    assert run.classifier.labels == decide.sum() >= 50 and run.classifier.measured == 0 and run.classifier.fitted is None
    before, after = (pd.read_parquet(tmp_path / x / "gold.parquet").set_index(uid) for x in ("free", "run"))
    engine = after.index[after["kind_by"] == "engine"]
    assert (before.loc[engine, "kind"] == 2).any() and after.loc[engine, "kind"].equals(before.loc[engine, "kind"])  # a legal form still decides
    assert (after.loc[sheet[uid][decide], "kind"].to_numpy() == truth[decide]).all()  # and people's answers stand


def test_a_sheet_s_ids_must_name_records_of_the_file(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 100).assign(kind=1)
    sheet.assign(**{uid: sheet[uid].astype("int64")}).to_parquet(tmp_path / "numbers.parquet")  # as a spreadsheet gives 0000000151 back
    with pytest.raises(InputError, match="IDs that name no record of"):  # as for decisions
        Run(p, s, kind_labels=tmp_path / "numbers.parquet").full(tmp_path / "all.parquet", tmp_path / "a")
    sheet.assign(**{uid: [pd.NA, *sheet[uid][1:]]}).astype({uid: "string"}).to_parquet(tmp_path / "blank.parquet")
    with pytest.raises(InputError, match="answered rows have no"):
        Run(p, s, kind_labels=tmp_path / "blank.parquet").full(tmp_path / "all.parquet", tmp_path / "b")


def test_a_new_part_takes_the_number_after_the_highest(tmp_path):
    from er.folder import next_part
    assert next_part(tmp_path) == 0
    (tmp_path / "part-00001.parquet").touch()  # part-00000 deleted by hand: undone
    assert next_part(tmp_path) == 2


def test_the_field_check_and_the_run_read_one_legal_form_table():
    import duckdb
    s = load_settings()
    names = ["イ)ヤマダクリニック", "ヤマダショウジ(カ", "トクヒ)ミライノカイ", "カブシキガイシヤヤマダ", "カ)ヤマダ", "ヤマダ(カ)", "株式会社ヤマダ", "ヤマダ㈱", "（有）ヤマダ商店"]
    folded = normalize(pd.Series(names, dtype="string"), ("nfkc", "strip_spaces"), s.standardize)  # as the field holds them
    pattern = s.detect["company_name"].replace("'", "''")
    assert all(duckdb.sql(f"SELECT regexp_matches('{n}', '{pattern}')").fetchall()[0][0] for n in folded)  # every one looks right
    assert normalize(pd.Series(names[6:], dtype="string"), ("nfkc", "strip_legal_form"), s.standardize).tolist() == ["ヤマダ", "ヤマダ", "ヤマダ商店"]


def test_a_decision_keeps_each_record_s_kind_and_a_merged_customer_takes_its_surest(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")
    before = pd.read_parquet(tmp_path / "run" / "gold.parquet")
    alone = before.groupby("cluster_id").filter(lambda c: len(c) == 1)
    company, other = alone[alone["kind"] == 2].iloc[0], alone[alone["kind"] == 0].iloc[0]  # a sure company, a record not sure
    pair = sorted([company[uid], other[uid]])
    pd.DataFrame({f"{uid}_l": [pair[0]], f"{uid}_r": [pair[1]], "decision": ["match"]}).to_parquet(tmp_path / "decided.parquet")
    Run(p, s).decide(tmp_path / "decided.parquet", tmp_path / "run")
    after = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert list(after.reset_index().columns) == list(before.columns)
    assert after.loc[pair, "cluster_id"].nunique() == 1 and (after.loc[pair, "customer_kind"] == 2).all()
    assert after["kind"].equals(before.set_index(uid)["kind"].reindex(after.index))  # each record's kind stands


def test_answers_add_up_over_sheets_each_kept_as_given_and_a_blank_row_erases_nothing(tmp_path, kind_population):
    import shutil
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 600)
    truth = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)
    half = len(sheet) // 2
    first = sheet.assign(kind=pd.array([*truth[:half], *[pd.NA] * (len(sheet) - half)], dtype="Int8"))  # the second half left blank
    first.to_parquet(tmp_path / "first.parquet")
    run1 = Run(p, s, kind_labels=tmp_path / "first.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    assert set(run1.labels[uid]) == set(sheet[uid][:half])  # a blank row isn't an answer: its record comes back on the next sheet
    second = sheet.assign(kind=pd.array([pd.NA] * half + list(truth[half:]), dtype="Int8"))  # the first half blank this time
    second.to_parquet(tmp_path / "second.parquet")
    run2 = Run(p, s, kind_labels=tmp_path / "second.parquet").full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    answers = tmp_path / "run" / "kind_answers"
    parts = sorted(answers.glob("part-*.parquet"))
    assert [set(pd.read_parquet(f)[uid]) for f in parts] == [set(sheet[uid][:half]), set(sheet[uid][half:])]  # a part per sheet, its filled rows
    assert len(run2.classifier.decided) == len(sheet)  # both sheets' answers stand
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid).loc[sheet[uid]]
    assert (gold["kind_by"] == "people").all() and (gold["kind"].to_numpy() == truth).all()

    parts[1].unlink()  # a sheet answered wrong: deleting its part undoes it
    Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    assert set(pd.read_parquet(answers)[uid]) == set(sheet[uid][:half])
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert not (gold.loc[sheet[uid][half:], "kind_by"] == "people").any()

    os_ = tmp_path / "run" / "state" / "kind_labels.parquet"  # a folder that keeps its answers in state/
    shutil.move(parts[0], os_)
    shutil.rmtree(answers)
    Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    assert set(pd.read_parquet(answers / "part-00000.parquet")[uid]) == set(sheet[uid][:half]) and not os_.exists()  # kept, not lost


def test_a_record_people_can_t_tell_stays_out_of_name_matching_and_off_the_next_sheet(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 600)
    first = sheet[uid].iloc[0]
    sheet.assign(kind=pd.array([0] + [pd.NA] * (len(sheet) - 1), dtype="Int8")).to_parquet(tmp_path / "answers.parquet")
    run = Run(p, s, kind_labels=tmp_path / "answers.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert gold.loc[first, ["kind", "kind_by"]].tolist() == [0, "people"] and gold.loc[first, "kind_held"]
    names = run.con.execute(f'SELECT person_name, company_name FROM records WHERE "{uid}" = ?', [first]).fetchall()[0]
    assert names == (None, None)  # its name goes to neither side: its pairs go to people
    assert first not in set(kind_sheet_for(run, s, p, 600)[uid])


def test_an_increment_classifies_its_batch_on_the_run_s_answers(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    batch = np.random.default_rng(0).random(len(g.df)) < 0.1
    g.df[~batch].to_parquet(tmp_path / "first.parquet", index=False)
    g.df[batch].to_parquet(tmp_path / "new.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "first.parquet", tmp_path / "free"), s, p, 600)
    sheet["kind"] = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)
    sheet.to_parquet(tmp_path / "answers.parquet")
    full = Run(p, s, kind_labels=tmp_path / "answers.parquet").full(tmp_path / "first.parquet", tmp_path / "run")
    inc = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "run")
    assert inc.classifier.labels == full.classifier.labels > 0 and inc.classifier.fitted.line_company == full.classifier.fitted.line_company
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert (gold.loc[sheet[uid], "kind_by"] == "people").all()  # the stored records' answers stand
    new = gold.loc[g.df.loc[batch, uid]]
    assert new["kind"].notna().all() and (new["kind_by"] == "engine").all()  # the batch: kinds from the same engine


def test_the_kind_problems_are_the_same_in_every_process(tmp_path):
    import subprocess
    import sys
    code = """import sys
from dataclasses import replace
from er.generate import KindProblems, generate, kind_problems, load_reference, load_registry, load_spec
from er.settings import load_settings
s = load_settings()
spec = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=400)
g = kind_problems(generate(spec, *load_reference(s.paths["reference"])), KindProblems(representatives=0.5), load_registry(s.paths["reference"]),
                  s.standardize.legal_front, s.standardize.legal_end, spec.kana_confusions, spec.branches)
g.df.to_parquet(sys.argv[1], index=False)"""
    for seed in ("1", "2"):  # Python hashes strings differently in every process: nothing may depend on it
        subprocess.run([sys.executable, "-c", code, str(tmp_path / f"{seed}.parquet")], check=True, env={**__import__("os").environ, "PYTHONHASHSEED": seed})
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "1.parquet"), pd.read_parquet(tmp_path / "2.parquet"))


def test_the_kind_problems_name_no_company_the_name_model_trains_on():
    from er.generate import KindProblems, generate as make, kind_problems, load_reference, load_spec, name_model_split
    s = load_settings()
    spec = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=600)
    registry = pd.DataFrame({"reading": ["ヰヱヰヱ", "アオイ"], "legal": ["カブシキガイシャ"] * 2, "abbreviation": ["カ"] * 2,
                             "front": [True] * 2, "prefecture": ["04", "40"]}).astype(object)  # a training company, a held-out one
    g = kind_problems(make(spec, *load_reference(s.paths["reference"])), KindProblems(), registry, s.standardize.legal_front,
                      s.standardize.legal_end, spec.kana_confusions, spec.branches)
    names = g.df.loc[g.truth["CASE"].eq("company").to_numpy(), "NAME_KANA"].dropna()
    assert len(names) and not names.str.contains("ヰ").any()  # only the held-out company is ever written
    _, _, train, held = name_model_split(load_reference(s.paths["reference"])[0], registry)
    assert set(train["reading"]) == {"ヰヱヰヱ"} and set(held["reading"]) == {"アオイ"}


def test_the_ui_serves_only_its_own_link_and_runs_the_commands_as_nayose_does(tmp_path, population):
    import http.client
    import threading
    import time
    from http.server import ThreadingHTTPServer
    from er import cli, ui
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    server = ui.Server(str(tmp_path / "run"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui.handler(server))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(method: str, path: str, body: dict | None = None, token: str = server.token, host: str = f"127.0.0.1:{port}"):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"X-Token": token, "Host": host})
        r = c.getresponse()
        data = r.read()
        return r.status, json.loads(data) if path.startswith("/api") else data.decode()

    def job(command: str, args: dict) -> tuple[str, dict]:
        status, started = call("POST", "/api/run", dict(command=command, args=args))
        assert status == 200, started
        while not (j := call("GET", f"/api/job/{started['job']}")[1])["done"]:
            time.sleep(0.1)
        return started["command"], j

    try:
        assert call("GET", "/api/commands", token="wrong")[0] == 403  # another user of the machine: no link, no page
        assert call("GET", "/api/commands", host="example.com")[0] == 403  # a page elsewhere, through DNS rebinding
        status, d = call("GET", "/api/commands")
        assert status == 200 and [c["name"] for c in d["commands"]] == [c.name for c in cli.COMMANDS] and d["workspace"] == str(tmp_path / "run")
        assert call("GET", "/")[0] == 200
        line, j = job("resolve records", {"input": str(tmp_path / "all.parquet"), "workspace": str(tmp_path / "run")})
        assert line == f"nayose resolve records {tmp_path / 'all.parquet'} --workspace {tmp_path / 'run'}" and j["exit"] == 0
        assert {e["event"] for e in j["events"]} == {"step", "result"}  # each step as it finished, then the result
        _, j = job("list pairs", {"workspace": str(tmp_path / "run"), "open": True})
        assert j["exit"] == 0 and j["events"][-1]["pairs"]
        _, j = job("describe entity", {"id": "nobody", "workspace": str(tmp_path / "run")})
        assert j["exit"] == 2 and j["events"][-1]["event"] == "error" and j["events"][-1]["fix"]
        dry = call("POST", "/api/run", dict(command="list pairs", args={"workspace": "r", "open": True}, dry=True))[1]
        assert dry == {"command": "nayose list pairs --workspace r --open"}  # the equivalent command line, nothing run
        assert call("POST", "/api/run", dict(command="list pairs", args={"nope": 1}))[0] == 400  # only declared parameters
        assert call("POST", "/api/run", dict(command="delete everything", args={}))[0] == 400  # only declared commands
        _, j = job("describe entity", {"workspace": str(tmp_path / "run")})  # no ID: nayose's parser refuses it, as on the command line
        assert j["exit"] == 2 and "required" in j["events"][-1]["error"]
        assert not server.jobs  # a job the page has read to its end is dropped
    finally:
        httpd.shutdown()


def test_quick_commands_at_once_leave_the_process_s_stderr_alone():
    import sys
    import time
    from er import ui
    real, server = sys.stderr, ui.Server("nowhere")
    for _ in range(10):  # the page starts several at once on every load
        jobs = [server.start("list columns", {})[1] for _ in range(8)] + [server.start("describe entity", {"workspace": "nowhere"})[1]]
        while any(j.code is None for j in jobs):
            time.sleep(0.01)
        assert sys.stderr is real and jobs[-1].code == 2


def test_the_ui_layout_names_only_declared_commands_parameters_and_result_fields():
    import re
    from er import cli
    html = Path(cli.__file__).with_name("ui.html").read_text(encoding="utf-8")
    layout = json.loads(re.search(r'<script type="application/json" id="layout">(.*?)</script>', html, re.S).group(1))
    declared = {c.name: c for c in cli.COMMANDS}
    for screen in layout["screens"]:
        for u in screen["uses"]:
            c = declared[u["command"]]
            params = {p.name for p in c.params}
            assert set(u["args"]) <= params and set(u.get("form", [])) <= params, (screen["id"], u["command"])
            assert set(u["reads"]) <= set(c.result), (screen["id"], u["command"], set(u["reads"]) - set(c.result))
    placed = {(s["id"], u["command"]) for s in layout["screens"] for u in s["uses"]}
    called = {(m.group(1), m.group(2)) for m in re.finditer(r'(?:run|action)\("(\w+)", "(\w+ \w+)"', html)}
    assert called and called <= placed  # every command the page runs, it runs as the layout places it
    block = html.split("const QUEUES = {", 1)[1].split("\n};", 1)[0]
    named = {(q, c) for q, body in re.findall(r"\n  (\w+): \{title(.*?)(?=\n  \w+: \{title|$)", block, re.S)
             for c in re.findall(r'(?:list|one|apply): "(\w+ \w+)"', body)}
    assert len(named) == 6 and named <= placed  # each review queue's commands, placed on its own page
    from er.report import GRAPH_NODES
    screens, flow = {sc["id"]: sc for sc in layout["screens"]}, layout["workflow"]
    assert all(set(sc["strip"]) <= set(GRAPH_NODES) for sc in screens.values())  # each page's flow strip: stages describe matching gives
    assert set(flow["steps"]) <= {*screens, "workspace"} and all(x in flow["steps"] for x in screens if x != "records")  # every page a step
    assert all(l["to"] in flow["steps"] and {(l["screen"], c) for c in l["via"]} <= placed for l in flow["loops"])


def test_the_page_answers_once_per_key_shows_any_row_and_says_when_the_server_is_gone(tmp_path, population):
    import threading
    from http.server import ThreadingHTTPServer
    from er import cli, ui
    sync = pytest.importorskip("playwright.sync_api")
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = tmp_path / "run"
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(run), "--format", "json"]) == 0
    server = ui.Server(str(run), str(tmp_path / "workspaces"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui.handler(server))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except sync.Error:
            httpd.shutdown()
            pytest.skip("no browser: .venv/bin/python -m playwright install chromium")
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/?token={server.token}")
        page.wait_for_selector(".next")
        page.evaluate("setWorkspace('')")  # the first screen of a new user: no workspace
        page.wait_for_selector(".empty .node.static")
        assert page.inner_text("h1").endswith("Choose a workspace") and page.get_attribute(".rail li:first-child .navitem", "aria-current") == "page"
        assert page.get_attribute(".navitem[data-screen=records]", "aria-current") == "false"  # the highlight is where you are
        assert all(b.is_disabled() for b in page.query_selector_all("[data-loop]")) and page.is_disabled("#search")  # off until the first run
        page.click("#picker")  # a new workspace, from the picker: a folder in the server's workspaces/, with its own mapping
        page.fill("#new-name", "fresh")
        page.click("#create")
        page.wait_for_selector("h1:has-text('Prepare your data')")  # a new workspace opens on its next step
        assert (tmp_path / "workspaces" / "fresh" / "columns.toml").is_file() and not page.query_selector("details.fgroup")  # nothing to fill before a file
        company = s.columns["company_name"][0][0]
        g.df.rename(columns={s.data.unique_id: "customer_no"}).to_parquet(tmp_path / "theirs.parquet", index=False)
        page.fill("#cin", str(tmp_path / "theirs.parquet"))
        page.click("#load")  # copied into it, then described
        page.wait_for_selector("details.fgroup[data-g='ID'][open]", timeout=60_000)  # the ID it can't find opens its group
        assert page.inner_text("#files").startswith("0001-theirs") and "Record ID needed" in page.inner_text("details.fgroup[data-g='ID'] summary")
        columns = tmp_path / "workspaces" / "fresh" / "columns.toml"
        page.click("[data-suggest='ID']")  # what the file's contents place there, shown, then kept
        page.click(".drop[data-slot='ID/Record ID'] [data-keep]")
        page.wait_for_function("() => !document.querySelector('.colchip.ghost')")
        assert 'id = "customer_no"' in columns.read_text() and "Record ID needed" not in page.inner_text("details.fgroup[data-g='ID'] summary")
        page.evaluate("document.querySelector(\"details.fgroup[data-g='Name']\").open = true")  # opened: it stays open as the page redraws
        page.click(f".drop[data-slot='Name/Company name'] .colchip[data-col='{company}'] [data-x]")  # taken off
        page.wait_for_function(f"() => !document.querySelector(\".drop[data-slot='Name/Company name'] .colchip[data-col='{company}']\")")
        assert load_settings(columns=columns).columns["company_name"] == () and page.query_selector("details.fgroup[data-g='Name'][open]")
        page.evaluate(f"""() => {{  // dragged back from the file's columns: the drag as the browser fires it
            const dt = new DataTransfer(), from = document.querySelector(".tray .colchip[data-col='{company}']");
            const to = document.querySelector(".drop[data-slot='Name/Company name']");
            from.dispatchEvent(new DragEvent("dragstart", {{dataTransfer: dt, bubbles: true}}));
            to.dispatchEvent(new DragEvent("drop", {{dataTransfer: dt, bubbles: true, cancelable: true}})); }}""")
        page.wait_for_selector(f".drop[data-slot='Name/Company name'] .colchip[data-col='{company}']")
        assert load_settings(columns=columns).columns["company_name"] == ((company,),)
        page.click(".navitem[data-screen=columns]")
        page.wait_for_selector("#files .tag")  # its description starts now
        page.click(".navitem[data-screen=run]")
        page.wait_for_timeout(1500)
        assert not page.query_selector("details.fgroup")  # the page left draws nothing on the page now open
        page.click("[data-act='resolve records']")  # the file loaded last: nothing to type
        page.wait_for_function("() => document.querySelector('#equiv-line').textContent.includes('resolve records')")
        assert page.get_attribute("#f-input", "required") is None and "theirs.parquet" not in page.inner_text("#equiv-line")
        page.keyboard.press("Escape")
        page.click("#picker")
        page.wait_for_selector("tr[data-w]")
        assert [Path(r.get_attribute("data-w")).name for r in page.query_selector_all("tr[data-w]")] == ["fresh"]  # from disk, not the browser
        page.keyboard.press("Escape")
        page.click(".navitem[data-screen=records]")
        page.evaluate(f"setWorkspace({json.dumps(str(run))})")
        page.wait_for_selector(".next")
        assert not any(b.is_disabled() for b in page.query_selector_all("[data-loop]")) and not page.is_disabled("#search")
        page.click(".navitem[data-screen=pairs]")
        page.wait_for_selector("[data-a=match]")
        page.keyboard.press("m")
        page.keyboard.press("m")  # pressed again before the first answer is back
        page.wait_for_function("() => document.querySelector('#written').textContent === '1'")
        page.wait_for_timeout(600)
        assert page.inner_text("#written") == "1" and not page.query_selector("#said .banner")  # one answer, no busy folder
        assert "nayose decide pair" in page.inner_text("#term-body")  # the command line it ran
        states = page.evaluate("""() => {  // each step's state, read from the workspace as describe workspace gives it
            const run = (pairs, kinds) => ({records: 9, entities: 7, pairs: {decide: 0, audit: 0, written_in: 0, ...pairs}, kinds: {decide: 0, measure: 0, written_in: 0, ...kinds}});
            const at = (d) => { const p = progress(d); return [p.next, p.steps.pairs.state, p.steps.kinds.state]; };
            return [at({event: "error", error: "no run"}), at(run({decide: 3}, {measure: 20})), at(run({}, {measure: 20})), at(run({}, {written_in: 2}))]; }""")
        assert states == [["columns", "later", "later"], ["pairs", "attention", "optional"], ["results", "done", "optional"], ["kinds", "done", "attention"]]
        assert page.query_selector(".rail li.attention .sub").inner_text().endswith("to decide")  # the stepper points at the open pairs
        page.click(".navitem[data-screen=run]")
        page.wait_for_selector(".node[data-node=candidates]")
        assert [n.get_attribute("data-node") for n in page.query_selector_all(".flow .node")] == ["records", "rules", "candidates", "score", "accept", "group", "customers"]
        page.click(".node[data-node=candidates]")
        assert page.query_selector_all(".detail .bar")  # each generator drawn as a bar, its pairs as its length
        page.click(".navitem[data-screen=pairs]")
        page.wait_for_selector("[data-a=match]")
        assert page.query_selector(".ruler") and page.query_selector(".ladder i.on")  # the evidence against the line, each comparison's step
        path = page.inner_text("#path")  # how much each part covers: all the records, the pairs listed, the one shown
        assert re.fullmatch(r"All [\d,]+ records\s*›\s*[\d,]+ pairs to review\s*›\s*This pair · \d+ of [\d,]+", path), path
        assert page.query_selector(".zone.all .flow") and page.inner_text(".card.one .question").startswith("Same customer?")
        page.click(".stepfoot a.filled")
        page.wait_for_selector("h1:has-text('Confirm person or company')")
        twice = page.evaluate("""async () => {  // the same command asked twice at once runs once
            const lines = () => [...document.querySelectorAll("#term-body .cmd")].filter((c) => c.textContent.startsWith("nayose list pairs")).length;
            const before = lines();
            await Promise.all([run("pairs", "list pairs"), run("pairs", "list pairs")]);
            return lines() - before; }""")
        assert twice == 1
        assert page.evaluate("""() => {  // a row far past the table's 500 drawn is drawn once picked
            const box = document.body.appendChild(document.createElement("div"));
            const t = grid(box, Array.from({length: 2000}, (_, n) => ({n})), ["n"], {selected: 0});
            t.select(1500);
            return box.querySelector('tr[data-i="1500"]')?.getAttribute("aria-selected") === "true"; }""")
        httpd.shutdown()
        httpd.server_close()
        lost = page.evaluate("() => run('pairs', 'list pairs')")
        assert lost["event"] == "error" and lost["error"].startswith("Lost the server")
        browser.close()


def test_describe_matching_draws_the_pipeline_with_the_run_s_numbers(tmp_path, population):
    import duckdb
    from er.report import GRAPH_NODES, describe_matching
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    nodes = {n["id"]: n for n in describe_matching(duckdb.connect(), out, p, s)["nodes"]}
    assert list(nodes) == list(GRAPH_NODES)
    kept = pd.read_parquet(out / "rule_kept")["rule"].value_counts().to_dict()
    assert {r["name"]: r["pairs"] for r in nodes["rules"]["rules"] if r["pairs"]} == kept
    step = next(x for x in json.loads((out / "steps.json").read_text())["runs"][0]["steps"] if x["step"] == "candidates")
    assert {x["name"]: x["pairs"] for x in nodes["candidates"]["generators"]} == {x["name"]: x["pairs"] for x in step["generators"]}
    gold = pd.read_parquet(out / "gold.parquet")
    assert nodes["accept"]["accepted"] == len(pd.read_parquet(out / "matches")) and nodes["customers"]["count"] == gold["cluster_id"].nunique()
    levels = [lv for c in nodes["score"]["comparisons"] for lv in c["levels"] if lv["m"]]
    assert levels and all(math.isclose(lv["bits"], math.log2(lv["m"] / lv["u"])) for lv in levels)  # each level's worth, as fitted
    assert all(f["example"] for f in nodes["prepare"]["fields"] if f["filled"])  # a real value for every field the file fills
    bare = {n["id"]: n for n in describe_matching(duckdb.connect(), None, p, s)["nodes"]}  # no run yet: the methods only
    assert bare["records"]["count"] is None and bare["rules"]["rules"][0]["pairs"] is None and bare["score"]["comparisons"][0]["levels"][0]["bits"] is None
