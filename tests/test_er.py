"""Self-checks for the er engine, kept out of the notebooks. Run from the project root: python -m pytest tests/
Self-contained: a small hand-made frame plus the tracked settings; no generated data needed."""
import logging
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from splink import Linker

from er.candidates import candidates, estimate, found_by, generate
from er.config import (Budget, Comparator, Comparison, DeletionKeys, FSModel, Key, KeyBlocker, Level, OverBudget, ProbSpec,
                       Resolver, Rule, RulesSpec, SortedNeighbourhood, Stage, TfidfNeighbours, ThresholdRule, keys_sql)
from er.evaluate import adopt, cluster_metrics, fp_upper, paired_test, predicted_pairs, true_pairs, wilson
from er.io import load, read_stage, write_stage
from er.match import parameters, rule_edges, sample_u, score_fs, train_fs, u_values, waterfall, with_scored_u
from er.pipeline import accept_curve, cascade, check_budget, entity_folds, grown_pairs, preflight, select_threshold, window_only
from er.resolve import connected_components, constrained
from er.settings import load_settings
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
                     budget=Budget(max_candidate_pairs=10**6, max_block_size=10**4, target_rows=10**4, benchmark_pairs=100),
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
    assert load_settings().data.silver_dir == root / "data" / "medallion" / "silver"


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
    spec = ProbSpec(standardize=replace(load_settings().standardize, derived=()), previous_stage="rules", stage="fs", model=model(),
                    blockers=(KeyBlocker(name="phone", keys=(Key("phone"),)),), min_match_weight=-10.0,  # toy weights: −6 to −3
                    resolver=Resolver(method="connected_components"),
                    budget=Budget(max_candidate_pairs=10**6, max_block_size=10**4, target_rows=10**6, benchmark_pairs=10))
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
    budget = Budget(max_candidate_pairs=100, max_block_size=100, target_rows=10, benchmark_pairs=10)
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
                     budget=Budget(max_candidate_pairs=3, max_block_size=10, target_rows=10, benchmark_pairs=10),
                     stages=(Stage(name="exact", rules=(Rule(name="R", exact=("phone",)),)),))
    plan = preflight(spec, df)
    assert plan["P"].tolist() == [3 + 1]  # C(3,2) + C(2,2)
    with pytest.raises(OverBudget):
        check_budget(plan, spec.budget)


def test_load_validates_input_and_stage_files_refuse_a_changed_input(tmp_path):
    data = replace(load_settings().data, silver_dir=tmp_path / "silver", labels_dir=tmp_path / "labels", artifacts_dir=tmp_path / "artifacts")
    data.silver_dir.mkdir(); data.labels_dir.mkdir()
    uid, ent = data.unique_id, data.entity_id
    write = lambda ids, entities: (pd.DataFrame({uid: ids, "x": "a"}).to_csv(data.silver_dir / "d.csv", index=False),
                                   pd.DataFrame({uid: ids[:len(entities)], ent: entities}).to_csv(data.labels_dir / "d.csv", index=False))
    write(["1", "1"], ["E", "E"])
    with pytest.raises(ValueError, match="more than once"):
        load(data, "d")
    write(["1", "2"], ["E"])
    with pytest.raises(ValueError, match="different"):
        load(data, "d")
    write(["1", "2"], ["E", "E"])
    records, _ = load(data, "d")
    pairs = pd.DataFrame({f"{uid}_l": ["1"], f"{uid}_r": ["2"]})
    write_stage(data, "d", "rules", pairs, records[[uid]], records.iloc[:0], config="v1")
    read_stage(data, "d", "rules")  # fine while the input is unchanged
    write(["1", "3"], ["E", "E"])
    with pytest.raises(ValueError, match="stale"):
        read_stage(data, "d", "rules")


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
    few, _ = grown_pairs(df, entity, "uid", KeyBlocker(name="few", keys=(Key("few"),)), 10**6)
    own, _ = grown_pairs(df, entity, "uid", KeyBlocker(name="own", keys=(Key("own"),)), 10**6)
    assert few == pytest.approx(2, abs=0.1) and own == pytest.approx(1, abs=0.1)


def test_a_blocking_key_limits_a_rule_join(con_db):
    _, db = con_db
    std = replace(load_settings().standardize, derived=())  # a hand-made frame without the real input columns
    df = pd.DataFrame({"uid": list("ABC"), "phone": ["1", "1", "1"], "name": ["サトウ", "サトオ", "カトウ"]}, dtype="string")
    budget = Budget(max_candidate_pairs=10, max_block_size=10, target_rows=10, benchmark_pairs=10)
    def spec(blocking):
        return RulesSpec(standardize=std, resolver=Resolver(method="connected_components"), budget=budget,
                         stages=(Stage(name="fuzzy", rules=(Rule(name="R", exact=("phone",), fuzzy=("name",), blocking=blocking),),
                                       comparators={"name": Comparator("levenshtein", 1)}),))
    plain = set(map(tuple, rule_edges(spec(()), df, db, UID)[0][["uid_l", "uid_r"]].to_numpy()))
    s = spec((Key("name", ("initial",)),))
    blocked = set(map(tuple, rule_edges(s, prepare(std, df, s.normalized()), db, UID)[0][["uid_l", "uid_r"]].to_numpy()))
    assert plain == {("A", "B"), ("A", "C")} and blocked == {("A", "B")}  # カトウ starts differently: not joined
