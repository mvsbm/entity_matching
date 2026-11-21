"""The keys a run lists pairs by: as the method names them (an edit-distance key: er.candidates.EditKeys), the gap
they leave (design.gap, at design time), and the values read as missing."""
import itertools
import json
import random

import pandas as pd
import pytest
from rapidfuzz.distance import Levenshtein

from er.engine.duckdb import DuckDB
from er.candidates import Records
from er.config import EditKeys, InputError, Key


@pytest.mark.parametrize("k, grouped", [(1, False), (2, False), (2, True), (3, False)])
def test_values_within_k_edits_are_every_pair_brute_force_finds_and_no_other(k, grouped):
    rnd = random.Random(k)
    vals = ["".join(rnd.choice("アイウカキ") for _ in range(rnd.randint(1, 11))) for _ in range(900)] + \
           ["".join(rnd.choice("abc") for _ in range(rnd.randint(1, 9))) for _ in range(300)]  # repeats, short values, two scripts
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(len(vals))], "name": vals, "g": [str(i % 3) for i in range(len(vals))]}, dtype="string")
    within = (Key("g"),) if grouped else ()
    r = Records(df, "uid")
    try:
        got = {tuple(x) for x in r.engine.rows(f"SELECT {'g, ' if grouped else ''}v, x FROM {r.near_values(EditKeys(name='e', key=Key('name'), within=within, edits=k), 10**9)}")}
    finally:
        r.close()
    u = sorted({(g if grouped else None, v) for v, g in zip(vals, df["g"]) if len(v) >= 2 * (k + 1)})
    want = {((g,) if grouped else ()) + (min(a, b), max(a, b)) for (g, a), (h, b) in itertools.combinations(u, 2)
            if g == h and a != b and Levenshtein.distance(a, b) <= k}
    assert got == want and len(want) > 100  # PassJoin's windows lose none, and cpdist keeps only those within k


def test_a_value_a_crowd_holds_pairs_by_no_edit_key():
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(80)], "name": ["フメイフメイ"] * 70 + ["フメイフメイ1", "フメイフメ", "サトウハナコ", "サトーハナコ", "サトウハナコ", "カトウハナコ", "x", "y", "z", "w"]},
                      dtype="string")
    r = Records(df, "uid")
    try:
        pairs = {tuple(x) for x in r.engine.rows(f"SELECT v, x FROM {r.near_values(EditKeys(name='e', key=Key('name'), edits=1), 64)}")}
    finally:
        r.close()
    assert ("カトウハナコ", "サトウハナコ") in pairs and not any("フメイフメイ" in p for p in pairs)  # a placeholder's 70 records would pair with each neighbour


def test_atoms_follow_the_method_and_the_records(population):
    from design.sample import atoms
    s, p, g = population
    have = {"person_name__kana_fold", "phone", "customer_id", "postal_code", "company_name__nfkc_strip_legal_form_kana_fold", "birth_date"}
    found = atoms(p, have)
    assert {a.column for a in found} <= have  # only what the records hold
    assert any(a.column == "person_name__kana_fold" and a.edits == 2 for a in found)  # compared by a similarity: within two edits
    assert any(a.column == "customer_id" and a.edits == 1 for a in found) and not any(a.column == "customer_id" and a.edits == 2 for a in found)



def _placeholders(population, rows: dict) -> tuple:  # steps.load.placeholders on a table of these columns, as load leaves records
    from types import SimpleNamespace
    from er.steps.job import start
    from er.steps.load import placeholders
    s, p, g = population
    job = start(s, p)
    df = pd.DataFrame(rows, dtype="string")
    job.engine.register("er_rows", df)
    job.engine.run("CREATE TABLE records AS SELECT * FROM er_rows")
    run = SimpleNamespace(job=job, engine=job.engine, notes=job.log.notes, placeholders=placeholders(job, p, "records", {}))
    return run, job.engine.frame("SELECT * FROM records ORDER BY 1")


def test_a_placeholder_is_found_on_records_without_an_id_beside_another_and_read_as_missing_in_every_field_of_its_columns(population):
    s, p, g = population
    uid, n = s.data.unique_id, 1000
    rows = {uid: [f"r{i:04d}" for i in range(n)], "customer_id": [None] * n,  # no record with a customer ID: each a customer of its own
            "person_name": ["テスト"] * 200 + [f"ナマエ{i}" for i in range(n - 200)], "full_name": ["テスト"] * 200 + [f"ナマエ{i}" for i in range(n - 200)],
            "birth_date": ["19000101"] * 200 + ["11111111"] * 200 + [f"19{50 + i % 50:02d}{1 + i % 12:02d}{1 + i % 28:02d}" for i in range(n - 400)]}
    run, out = _placeholders(population, rows)
    assert set(run.placeholders) == {"person_name", "birth_date"} and set(run.placeholders["birth_date"]) == {"19000101", "11111111"}  # neither hides the other
    assert out["person_name"].iloc[:200].isna().all() and out["full_name"].iloc[:200].isna().all()  # the name read into full_name too: no rule reads it
    assert out["full_name"].iloc[200:].notna().all()


def test_copies_of_one_customer_s_record_are_no_crowd_and_a_known_placeholder_is_not_new_again(population):
    s, p, g = population
    uid = s.data.unique_id
    rows = {uid: [f"c{i:03d}" for i in range(70)], "customer_id": ["C1"] * 70, "person_name": ["サトウハナコ"] * 70, "phone": ["1234"] * 70}
    run, out = _placeholders(population, rows)
    assert "person_name" not in run.placeholders and "phone" not in run.placeholders and out["person_name"].notna().all()  # one customer's 70 copies
    from er.steps.load import placeholders
    run.job.log.notes.clear()
    run.engine.run("UPDATE records SET phone = '1234'")
    placeholders(run.job, p, "records", {"phone": ["1234"]})
    assert out is not None and not any(x.startswith("phone:") for x in run.job.log.notes)  # read as missing as before, and not said again
    assert run.engine.value("SELECT count(*) FROM records WHERE phone IS NOT NULL") == 0


def test_a_short_phone_held_by_many_records_each_is_kept_and_a_dummy_far_past_them_is_still_read_as_missing(population):
    s, p, g = population
    uid = s.data.unique_id
    phones = [f"{i % 100:04d}" for i in range(20_000)] + ["9999"] * 3_000  # 100 values, 200 customers each, as 4 digits on a large file; one dummy
    rows = {uid: [f"r{i:05d}" for i in range(len(phones))], "customer_id": [None] * len(phones), "phone": phones}
    run, out = _placeholders(population, rows)
    assert run.placeholders == {"phone": ["9999"]} and out["phone"].notna().sum() == 20_000


def test_the_gap_counts_a_pair_as_the_rules_only_where_they_kept_it():
    import duckdb
    from types import SimpleNamespace
    from design.sample import listed_by
    engine = DuckDB(duckdb.connect())
    engine.run("CREATE TABLE rule_edges AS SELECT 'a' AS id_l, 'b' AS id_r UNION ALL SELECT 'c', 'd'")  # both found by a rule
    engine.run("CREATE TABLE rule_kept AS SELECT 'c' AS id_l, 'd' AS id_r")  # one kept: the other's records were resolved already
    got = listed_by(SimpleNamespace(engine=engine, l="id_l", r="id_r"), pd.DataFrame({"id_l": ["a", "c"], "id_r": ["b", "d"]}))
    assert got["ruled"].tolist() == [False, True] and got["listed"].tolist() == [False, True]


@pytest.fixture(scope="module")
def ran(population, tmp_path_factory):
    from er.jobs.build import build
    s, p, g = population
    d = tmp_path_factory.mktemp("keys")
    g.df.to_parquet(d / "in.parquet", index=False)
    return s, p, g, d, build(d / "in.parquet", d / "ws", s, p)


def test_a_run_lists_by_every_key_the_method_names_and_keeps_none_of_its_own(ran):
    s, p, g, d, run = ran
    listed = [x["name"] for x in next(x for x in run.steps if x["step"] == "candidates")["generators"]]
    assert sorted(listed) == sorted(b.name for b in run.pipeline.fs.blockers) == sorted(b.name for b in p.fs.blockers)
    assert not (d / "ws" / "state" / "keys.json").exists() and not {"keys", "probe", "gap"} & {x["step"] for x in run.steps}


def test_the_gap_counts_from_the_search_floor(ran):
    from design.gap import gap, thresholds
    from er.match import review_floor, search_floor
    s, p, g, d, run = ran
    assert search_floor(p) < review_floor(p) and thresholds(p) == sorted({search_floor(p), review_floor(p), p.fs.min_match_weight, 20.0})
    rows = gap(run)["thresholds"]
    assert [x["bits"] for x in rows] == thresholds(p) and rows[0]["bits"] == search_floor(p)
    assert all(x["missed_lo"] <= x["missed"] <= x["missed_hi"] for x in rows) and [x["pairs"] for x in rows] == sorted((x["pairs"] for x in rows), reverse=True)


def test_a_pipeline_with_keys_to_learn_and_a_workspace_holding_keys_a_run_learned_are_refused(ran, population):
    from er import folder
    from er.config import pipeline_from
    import tomllib
    s, p, g, d, run = ran
    cfg = tomllib.loads((s.root / "config" / "final.toml").read_text(encoding="utf-8"))
    with pytest.raises(InputError, match=r"\[keys\] sets nothing") as e:
        pipeline_from({**cfg, "keys": {"records": 50_000}}, s.standardize, s.chains)
    assert e.value.fix == "delete [keys]"
    name = {**cfg["model"]["comparisons"][0], "tf": {"field": "person_name"}}
    with pytest.raises(InputError, match="tf sets nothing") as e:  # term frequencies: a level weighs the same whichever value agrees
        pipeline_from({**cfg, "model": {**cfg["model"], "comparisons": [name, *cfg["model"]["comparisons"][1:]]}}, s.standardize, s.chains)
    assert e.value.fix == "delete tf from those comparisons and their levels"
    (d / "ws" / "state" / "keys.json").write_text(json.dumps({}), encoding="utf-8")
    try:
        with pytest.raises(InputError, match="keys learned on its file or left out"):
            folder.current(d / "ws")
        folder.current(d / "ws", replacing=True)  # a full run --overwrite replaces state/ whole
    finally:
        (d / "ws" / "state" / "keys.json").unlink()
