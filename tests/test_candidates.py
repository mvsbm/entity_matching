"""Pairs: the metrics every reported number rests on, keys and windows, the budget, normalizers."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from er.candidates import candidates, estimate, found_by, generate
from er.config import (Budget, Comparator, DeletionKeys, FSSpec, InputError, Key, KeyBlocker, OverBudget,
                       Resolver, Rule, RulesSpec, SortedNeighbourhood, Stage, TfidfNeighbours)
from er.evaluate import cluster_metrics, edge_metrics, paired_test, predicted_pairs, true_pairs, truth_of
from er.io import load
from er.match import rule_edges, score_fs, train_fs, scored_u
from er.pipeline import (check_budget, clustered, entity_folds, grown_pairs, preflight, window_only)
from er.settings import load_settings
from er.standardize import normalize, prepare

from conftest import PAIR, UID, model


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

    household = entity.astype(int) // 3  # three entities a household: a pair of two of them is neither true nor false
    homes = brute_pairs(household.astype(str)) - truth
    h = cluster_metrics(cluster, entity, household)
    assert (h["TP"], h["FP"], h["FN"], h["household"]) == (len(truth & pred), len(pred - truth - homes), len(truth - pred), len(pred & homes))
    labels = pd.DataFrame({"uid": ids, "entity": entity.to_numpy(), "home": household.to_numpy()})
    t = truth_of(labels, replace(load_settings().data, unique_id="uid", entity_id="entity", household_id="home"))
    assert t == truth and t.household == homes
    test = paired_test(set(), pred, t)  # every pair the clusters join, against none
    assert (test["TP_gains"], test["FP_added"]) == (len(truth & pred), len(pred - truth - homes))
    edges = pd.DataFrame(sorted(pred), columns=["uid_l", "uid_r"])
    e = edge_metrics(edges, entity, "uid", household)
    assert (e["pairs_TP"], e["pairs_FP"], e["pairs_household"]) == (len(truth & pred), len(pred - truth - homes), len(pred & homes))


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
    for asked, pairs in ((["0", "1"], [("0", "1"), ("0", "2"), ("1", "2")]), (["2", None], [("0", "2"), ("1", "2")])):  # two asked in a block; a NULL among them
        assert sorted(map(tuple, generate(KeyBlocker(name="k", keys=(Key("phone"),)), df, UID, asked).to_numpy())) == pairs  # each pair once, none lost
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


def test_candidates_with_no_pair_give_none_and_more_generators_than_bits_are_refused():
    df = pd.DataFrame({"uid": ["1", "2", "3"], "phone": ["1", "2", None]}, dtype="string")
    budget = Budget(max_pairs_per_record=100, max_block_size=100, target_rows=10, benchmark_pairs=10)
    union, _ = candidates((KeyBlocker(name="k", keys=(Key("phone"),)),), df, UID, None, budget)
    assert union.empty and "sources" in union  # no two records share a phone: no pair, no SQL error
    many = tuple(KeyBlocker(name=f"k{i}", keys=(Key("phone"),)) for i in range(64))
    with pytest.raises(InputError, match="at most 63"):  # one bit per generator in a BIGINT
        candidates(many, df, UID, None, budget)


def test_a_deletion_keys_normal_pairs_hold_the_pairs_its_join_lists_and_never_go_below_zero():
    import duckdb
    names = ["JOHNSMITH"] * 200 + [f"N{i:05d}" for i in range(2000)]  # one value on 200 records: each of its keys an oversized block
    df = pd.DataFrame({"uid": [f"{i:05d}" for i in range(len(names))], "name": names}, dtype="string")
    b, budget = DeletionKeys(name="d", key=Key("name")), Budget(max_pairs_per_record=1000, max_block_size=1000, target_rows=10, benchmark_pairs=10)
    est = estimate(b, df, len(df), uid="uid", oversized_from=budget.min_oversized())
    con = duckdb.connect()  # a gate that keeps no oversized block: the join lists the normal blocks' pairs only
    union, _ = candidates((b,), df, "uid", None, budget, con=con, gate=lambda t: con.execute(f"CREATE OR REPLACE TABLE g AS SELECT *, -99.0 AS match_weight FROM {t}") and "g")
    assert est["oversized_blocks"] and est["est_pairs"] - est["oversized_pairs"] < 0 <= len(union) <= est["normal_pairs"] < est["est_pairs"]
    few = pd.DataFrame({"uid": list("0123"), "name": ["ABC", "ABC", "ABX", "ABX"]}, dtype="string")  # block AB oversized; each value's other keys normal
    tight = Budget(max_pairs_per_record=1000, max_block_size=1000, target_rows=10, benchmark_pairs=10, sample_pairs=3)
    union, _ = candidates((b,), few, "uid", None, tight, con=con, gate=lambda t: con.execute(f"CREATE OR REPLACE TABLE g AS SELECT *, -99.0 AS match_weight FROM {t}") and "g")
    assert estimate(b, few, 4, uid="uid", oversized_from=tight.min_oversized())["normal_pairs"] == len(union) == 2  # a value's pair once, in one of its normal blocks


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
    addresses = pd.Series(["東京都千代田区丸の内1丁目1番1号 丸の内ビル3F", "東京都千代田区 丸の内1丁目1番1号", "東京都千代田区\u3000霞が関2丁目3番4号",
                           "　東京都港区六本木6丁目10番1号", "北海道札幌市中央区大通"], dtype="string")
    assert normalize(addresses, ("address",), std).tolist() == ["千代田区丸の内1-1-1", "千代田区丸の内1-1-1", "千代田区霞が関2-3-4", "港区六本木6-10-1",
                                                               "札幌市中央区大通"]  # the building after the street number goes; a space before it, never the address


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

