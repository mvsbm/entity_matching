"""Self-checks for the er engine. Run from the project root: python -m pytest tests/
Self-contained: small hand-made frames, the tracked config and reference data; no generated files needed."""
import logging
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from splink import Linker

from er.candidates import Records, candidates, estimate, estimate_touching, found_by, generate
from er.config import (Budget, Comparator, Comparison, DeletionKeys, FSModel, FSSpec, Key, KeyBlocker, Level, OverBudget,
                       Resolver, Rule, RulesSpec, SortedNeighbourhood, Stage, TfidfNeighbours, ThresholdRule, keys_sql)
from er.evaluate import adopt, cluster_metrics, fp_upper, paired_test, predicted_pairs, true_pairs, wilson
from er.io import load
from er.match import exact_u, parameters, rule_edges, sample_u, score_fs, stale_u, train_fs, u_values, waterfall, with_scored_u
from er.pipeline import (accept_curve, cascade, check_budget, entity_folds, grown_pairs, pattern_coverage, preflight, select_threshold,
                         window_only)
from er.resolve import connected_components, constrained
from er.config import dump_pipeline, fields_read, load_pipeline
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


def test_reused_u_gives_the_same_model(con_db, records):
    _, db = con_db
    labels = records.set_index(UID)["entity"]
    u = u_values(train_fs(model("em"), records, db, UID, labels))
    assert model("em").u_keys() == model("labels").u_keys()
    fresh = train_fs(model("labels"), records, db, UID, labels)
    reused = train_fs(model("labels"), records, db, UID, labels, u=u)
    assert parameters(fresh).fillna(0).round(12).equals(parameters(reused).fillna(0).round(12))


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
    first = rule_edges(spec, a, db, UID)[0]
    connected_components(a[UID], first, db, UID)  # leaves whatever it caches on the shared db
    shared, fresh = rule_edges(spec, b, db, UID)[0], rule_edges(spec, b, connect()[1], UID)[0]
    assert shared.reset_index(drop=True).equals(fresh.reset_index(drop=True)) and len(shared) == 1
    assert connected_components(b[UID], shared, db, UID).equals(connected_components(b[UID], fresh, connect()[1], UID))


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
            self.scored = pd.DataFrame(dict(match_weight=weights, fp=fp))
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


def test_cascade_skips_pairs_already_resolved_on_both_sides(con_db):
    _, db = con_db
    ids = pd.Series(list("ABCDEF"), dtype="string", name=UID)
    pair = lambda rows: pd.DataFrame(rows, columns=["uid_l", "uid_r"], dtype="string")
    stages = [("rules", pair([("A", "B"), ("C", "D")])), ("model", pair([("B", "C"), ("A", "E"), ("E", "F")]))]
    entity = pd.Series(list("xxyyxx"), index=list("ABCDEF"))
    clusters, stage_of, kept, _ = cascade(ids, stages, lambda e: connected_components(ids, e, db, UID), entity, UID)
    assert ("B", "C") not in set(map(tuple, kept[["uid_l", "uid_r"]].to_numpy()))  # both already resolved by the rules
    assert clusters["A"] == clusters["E"] == clusters["F"] != clusters["C"]
    assert stage_of.to_dict() == dict(A="rules", B="rules", C="rules", D="rules", E="model", F="model")
    clusters, _, kept, _ = cascade(ids, stages, lambda e: connected_components(ids, e, db, UID), entity, UID, bridge=("model",))
    assert ("B", "C") in set(map(tuple, kept[["uid_l", "uid_r"]].to_numpy()))  # a bridging stage may join two clusters
    assert clusters["A"] == clusters["C"] == clusters["F"]


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
    same = with_scored_u(model(), fitted, records, db, UID)  # the fitting records, the same sample: the same model
    assert score_fs(same, records, PAIR, db, UID)["match_weight"].item() == pytest.approx(score_fs(fitted, records, PAIR, db, UID)["match_weight"].item())
    padded = pd.concat([records, pd.DataFrame({"uid": [f"p{i:03d}" for i in range(240)], "name": [f"ヨソ{i}" for i in range(240)],
                                               "phone": [f"{i:04d}" for i in range(240)], "entity": "pad"}, dtype="string")], ignore_index=True)
    other = with_scored_u(model(), fitted, padded, db, UID)
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


def test_constrained_resolver_refuses_a_conflicting_merge():
    records = pd.DataFrame({"uid": list("ABC"), "given": ["ヒロシ", "ヒロシ", "タカシ"]}, dtype="string")
    edges = pd.DataFrame({"uid_l": ["A", "B"], "uid_r": ["B", "C"], "score": [0.9, 0.8]})
    out = constrained(records["uid"], edges, records, ("given",), UID)
    assert out["A"] == out["B"] != out["C"]


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
        prepare(load_settings().standardize, pd.DataFrame({"uid": ["1"]}, dtype="string"), [])


def test_blocking_normalizers():
    std = load_settings().standardize
    s = pd.Series(["マツモト", "", pd.NA], dtype="string")
    assert normalize(s, ("initial",), std).tolist()[:1] == ["マ"] and normalize(s, ("initial",), std).isna().tolist()[1:] == [True, True]
    assert normalize(pd.Series(["1000033"], dtype="string"), ("first3",), std).tolist() == ["100"]
    assert normalize(pd.Series(["サトウ"], dtype="string"), ("reverse",), std).tolist() == ["ウトサ"]


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
    with pytest.raises(ValueError, match=r"id \(expected \(\('CONT_ID',\),\)\)"):
        fit_to_file(p, s, cols - {"CONT_ID"})
    names = {"FULL_NAME_KANA", "O_PERSON_NAME_KANA", "LAST_NAME_KANA", "GIVEN_NAME_KANA", "NYS_CNV_P_NAME_KANA"}
    with pytest.raises(ValueError, match="person_name .* / company_name"):
        fit_to_file(p, s, cols - names)
    with pytest.raises(ValueError, match="entity"):
        fit_to_file(p, s, cols, labelled=True)  # a labelled run needs the truth
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


def test_a_run_ignores_record_order_refuses_a_used_folder_and_an_increment_keeps_every_cluster(tmp_path, population):
    from er.match import scaled_prior
    from er.run import Run, qa
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
    with pytest.raises(ValueError, match="already in the run"):
        Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c")

    with pytest.raises(FileExistsError, match="already holds a run"):  # a full run never mixes with an earlier one
        Run(p, s, model=first.model).full(tmp_path / "all.parquet", tmp_path / "c")
    Run(p, s, model=first.model).full(tmp_path / "all.parquet", tmp_path / "c", overwrite=True)
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "c" / "gold.parquet"), gold[0])
    assert [f.name for f in (tmp_path / "c" / "state" / "records").iterdir()] == ["part-00000.parquet"]

    g.df.drop(columns="PHONE_NUM_4").to_parquet(tmp_path / "no_phone.parquet", index=False)
    with pytest.raises(ValueError, match="fit on this file instead"):  # the model compares the phone; this file has none
        Run(p, s, model=first.model).full(tmp_path / "no_phone.parquet", tmp_path / "d")


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
    with pytest.raises(ValueError, match="already in the run"):  # the next increment first finishes the interrupted write
        Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "cut")
    pd.testing.assert_frame_equal(*(pd.read_parquet(tmp_path / d / "gold.parquet") for d in ("clean", "cut")))
    assert not list((tmp_path / "cut").rglob("*.tmp"))


def test_the_labelled_engine_and_the_run_give_the_same_gold(tmp_path, population, con_db):
    """scripts/choose.py measures with er.pipeline; scripts/resolve.py runs er.run: the same records and model must
    give the same clusters and the same answer to what resolved each record."""
    from er.pipeline import run_fs, run_rules
    from er.run import Run
    s, p, g = population
    _, db = con_db
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")
    records = g.df.astype("string")
    det = run_rules(p.rules, records, g.truth, db, s.data)
    pairs = det.edges[[f"{uid}_l", f"{uid}_r", "stage", "rule", "score", "kept"]].astype("string")
    clusters = (det.records[[uid, "CLUSTER_ID", "MATCH_STAGE", "MATCH_RULE"]]  # the resolved file, as scripts/choose.py writes it
                .set_axis([uid, "cluster_id", "resolved_stage", "resolved_by"], axis=1).astype("string"))
    res = run_fs(p.fs, run.model, records, g.truth, pairs, clusters, db, s.data)
    labelled = (res.records.set_index(uid)[["CLUSTER_ID", "MATCH_STAGE", "MATCH_RULE"]]
                .set_axis(["cluster_id", "resolved_stage", "resolved_by"], axis=1).astype("string"))
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid).astype("string")
    pd.testing.assert_frame_equal(gold, labelled.loc[gold.index], check_index_type=False)


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
    """The final pipeline with its threshold two steps up, so the safety margin below it holds pairs to decide."""
    s, p, g = population
    return s, replace(p, fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 2)), g


def test_the_review_sheet_asks_about_each_cluster_pair_in_the_safety_margin_once(tmp_path, wide_band):
    from er.run import Run, qa, review_floor
    s, p, g = wide_band
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    t, lo = p.fs.min_match_weight, review_floor(p)
    assert lo == t - 2  # one grid step (margin_steps = 1) below the threshold
    decide, audit = sheet[sheet["why"] == "decide"], sheet[sheet["why"] == "audit"]
    assert len(decide) and sheet["decision"].isna().all()
    assert decide["match_weight"].between(lo, t, inclusive="left").all() and audit["accepted"].all()
    gold = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)["cluster_id"]
    a, b = decide[f"{uid}_l"].map(gold).to_numpy(), decide[f"{uid}_r"].map(gold).to_numpy()
    assert (a != b).all() and not pd.DataFrame({"x": np.minimum(a, b), "y": np.maximum(a, b)}).duplicated().any()


def test_decisions_join_clusters_without_scoring_and_a_full_run_applies_them_again(tmp_path, wide_band):
    from er.run import Run, qa
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

    Run(p, s, model=run.model).full(tmp_path / "all.parquet", tmp_path / "a", overwrite=True)  # people's work survives
    again = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    assert again.loc[pair[0], "cluster_id"] == again.loc[pair[1], "cluster_id"]
    matches = pd.read_parquet(tmp_path / "a" / "matches")
    assert not ((matches[l] == rejected[0]) & (matches[r] == rejected[1])).any()

    sheet.loc[yes, "decision"] = "maybe"
    sheet.to_parquet(tmp_path / "bad.parquet")
    with pytest.raises(ValueError, match="match or no_match"):
        Run(p, s).decide(tmp_path / "bad.parquet", tmp_path / "a")
    pd.DataFrame({l: ["nobody"], r: [pair[0]], "decision": ["match"]}).to_parquet(tmp_path / "unknown.parquet")
    with pytest.raises(ValueError, match="not in the run"):
        Run(p, s).decide(tmp_path / "unknown.parquet", tmp_path / "a")


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

