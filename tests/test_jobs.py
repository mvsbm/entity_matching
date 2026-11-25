"""The jobs (python -m nayose, nayose/__main__.py) as a machine runs them, each in a process of its own: a run built,
updated, matched, decided and looked up in its folder, each job's JSON and exit code (0; 2, a mistake people fix; 75,
another job is writing); a rebuild keeping people's decisions; report.txt; and people's decisions read and refused."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

import nayose
from nayose.engines import DuckDB


def job(*words) -> tuple[int, dict]:  # python -m nayose WORDS: its exit code and what it printed
    done = subprocess.run([sys.executable, "-m", "nayose", *map(str, words)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    return done.returncode, json.loads(done.stdout.strip().splitlines()[-1])


def test_a_run_is_built_updated_matched_decided_and_looked_up_in_its_folder(tmp_path, population):
    g = population
    half = len(g.df) // 2
    g.df.iloc[:half].to_parquet(tmp_path / "first.parquet", index=False)
    g.df.iloc[half:].to_parquet(tmp_path / "batch.parquet", index=False)
    run = tmp_path / "run"
    code, said = job("build", tmp_path / "first.parquet", "--out", run)
    assert code == 0 and said["records"] == half and (run / "run.duckdb").is_file() and "· build ·" in (run / "report.txt").read_text(encoding="utf-8")
    assert job("build", tmp_path / "first.parquet", "--out", run)[0] == 2  # a folder that holds a run: refused without --overwrite
    code, said = job("update", tmp_path / "batch.parquet", "--out", run)
    told = (run / "report.txt").read_text(encoding="utf-8")
    assert code == 0 and said["added"] == len(g.df) - half and "· update of " in told
    assert "fit" not in said["steps"] and "build again" in told  # the build's model, and the run has grown past it
    assert job("update", tmp_path / "batch.parquet", "--out", run)[1]["added"] == 0  # given twice: nothing new, nothing written
    code, said = job("match", "--out", run, "--threshold", 6)
    table = pd.read_parquet(said["into"])
    assert code == 0 and said["pairs"] == len(table) > 0 and table["decision"].isna().all()
    assert job("match", "--out", run, "--threshold", -5)[0] == 2  # below keep_from: the run keeps no pair there
    table.head(3).assign(decision="match")[["id_l", "id_r", "decision"]].to_parquet(tmp_path / "decided.parquet", index=False)
    code, said = job("decide", tmp_path / "decided.parquet", "--out", run)
    assert code == 0 and said["decisions"] == 3 and said["entities"] < len(g.df)
    older = DuckDB(run / "run.duckdb")  # as a run built before decisions named their round holds them: as batch
    older.con.execute("ALTER TABLE decisions RENAME COLUMN round TO batch")
    older.close()
    code, said = job("build", tmp_path / "first.parquet", "--out", run, "--overwrite")
    assert code == 0 and DuckDB(run / "run.duckdb").value("SELECT COUNT(round) FROM decisions") == 3  # people's decisions stay
    code, said = job("lookup", "--out", run, "--record", g.df["CONT_ID"].iloc[0])
    assert code == 0 and said["record"]["id"] == g.df["CONT_ID"].iloc[0] and "entities" in said
    assert job("lookup", "--out", run, "NOPE=1")[0] == 2 and job("lookup", "--out", tmp_path / "none", "--record", "1")[0] == 2
    other = DuckDB(run / "run.duckdb")  # a run another method built: every job after a build refuses it
    other.run("UPDATE method SET fingerprint = 'another'")
    other.close()
    for words in (["decide", tmp_path / "decided.parquet"], ["match", "--threshold", 6]):
        code, said = job(*words, "--out", run)
        assert code == 2 and "changed since the run was built" in said["error"] and "--overwrite" in said["fix"], words
    g.df.head(30).to_parquet(tmp_path / "few.parquet", index=False)
    code, said = job("build", tmp_path / "few.parquet", "--out", tmp_path / "few")
    assert code == 2 and "near-certain rule" in said["error"] and not (tmp_path / "few" / "run.duckdb").exists()  # a fit refused: no run made


def test_a_second_writer_is_told_to_try_again_later(tmp_path, population):
    population.df.to_parquet(tmp_path / "in.parquet", index=False)
    run = tmp_path / "run"
    assert job("build", tmp_path / "in.parquet", "--out", run)[0] == 0
    from nayose.__main__ import locked
    with open(run / ".lock", "w") as held:
        assert locked(held)
        code, said = job("update", tmp_path / "in.parquet", "--out", run)
    assert code == 75 and said["severity"] == "WARNING" and "another job" in said["error"]


def test_people_s_decisions_are_read_in_either_order_and_any_width_of_space_once_each_and_refused_where_they_name_nothing(tmp_path):
    engine = DuckDB()
    engine.run("CREATE TABLE records AS SELECT * FROM UNNEST(['a', 'b', 'c', 'd']) AS id")
    for c in ("kind", "kind_p", "kind_by", "kind_flagged"):
        engine.run(f"ALTER TABLE records ADD COLUMN {c} {'BOOLEAN' if c == 'kind_flagged' else 'DOUBLE' if c == 'kind_p' else 'VARCHAR' if c == 'kind_by' else 'INTEGER'}")
    nayose.decide(engine, [])

    def given(rows: list[tuple], columns: tuple = ("id_l", "id_r", "decision")) -> int:  # the decisions stored after
        pd.DataFrame(rows, columns=list(columns)).to_parquet(tmp_path / "given.parquet", index=False)
        nayose.decide(engine, [tmp_path / "given.parquet"])
        return engine.value("SELECT COUNT(*) FROM decisions")

    assert given([("b", "a", "　Match "), ("c", "d", None), ("c", "d", "　")]) == 1  # a blank decision skips its row
    assert engine.rows("SELECT id, entity, resolved_by FROM gold ORDER BY id") == [("a", "a", "review"), ("b", "a", "review"), ("c", "c", None), ("d", "d", None)]
    assert given([("a", "b", "match")]) == 1  # given again: nothing new
    assert given([("a", "b", "no_match")]) == 2 and engine.value("SELECT COUNT(DISTINCT entity) FROM gold") == 4  # the latest stands
    for rows, columns, refused in [([("a", "b", "same")], None, "match or no_match, not same"),
                                   ([("a", "b", "match"), ("b", "a", "no_match")], None, "decided both ways"),
                                   ([("a", "151", "match")], None, "name no record"),
                                   ([("a", None, "match")], None, "lack an ID"),
                                   ([("a", "b", None)], None, "no row has a decision"),
                                   ([("a", "b")], ("id_l", "id_r"), "lack the columns")]:
        with pytest.raises(Exception, match=refused):
            given(rows, columns or ("id_l", "id_r", "decision"))
    assert engine.value("SELECT COUNT(*) FROM decisions") == 2  # a refused table stores nothing


def test_an_update_is_refused_once_the_method_its_values_or_the_mapping_changed_since_the_build(tmp_path, population, monkeypatch):
    population.df.to_parquet(tmp_path / "in.parquet", index=False)
    engine = DuckDB()
    nayose.build(engine, [tmp_path / "in.parquet"])
    monkeypatch.setattr(nayose, "fingerprint", lambda *a, **k: "another")
    with pytest.raises(nayose.InputError, match="changed since the run was built"):
        nayose.update(engine, [tmp_path / "in.parquet"])


def test_each_generator_s_candidates_and_matches_are_counted_and_the_generators_that_can_go_lose_none(tmp_path, population):
    import importlib.util
    import duckdb
    import nayose
    from nayose.engines import DuckDB
    spec = importlib.util.spec_from_file_location("key_quality", Path(__file__).resolve().parents[1] / "scripts" / "key_quality.py")
    kq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kq)
    population.df.to_parquet(tmp_path / "in.parquet", index=False)
    population.truth.to_parquet(tmp_path / "truth.parquet", index=False)
    engine = DuckDB(tmp_path / "run.duckdb")
    nayose.build(engine, [tmp_path / "in.parquet"])
    engine.close()
    got = kq.measure(tmp_path, tmp_path / "truth.parquet", 6.0)
    used = set(nayose.config()["score"]["generators"])
    assert {r["generator"] for r in got["generators"]} == used and got["matches"] >= got["true"] > 0
    assert all(r["only"] == 0 for r in got["generators"] if r["generator"] in got["drop"])
    con = duckdb.connect(str(tmp_path / "run.duckdb"), read_only=True)
    lost = con.execute("SELECT COUNT(*) FROM scored WHERE rule IS NULL AND points >= 6 AND named AND generators IS NOT NULL "
                       "AND list_has_all(?, string_split(generators, '+'))", [got["drop"]]).fetchone()[0]
    text = kq.report(got, truth=True)
    values = {str(v) for v in population.df.stack().unique() if len(str(v)) > 3}
    assert got["drop"] and lost == 0 and not [v for v in values if v in text]  # some go, none lost; no record's value shown
    listed = con.execute("SELECT COUNT(*) FROM (SELECT unnest(string_split(generators, '+')) FROM cands)").fetchone()[0]
    alone = con.execute("SELECT COUNT(*) FROM scored WHERE rule IS NULL AND points >= 6 AND named AND generators NOT LIKE '%+%'").fetchone()[0]
    assert sum(r["candidates"] for r in got["generators"]) == listed and sum(r["only"] for r in got["generators"]) == alone


def test_a_build_runs_on_a_file_where_a_compared_field_is_never_filled(tmp_path, population):
    df = population.df.copy()
    df[["BIRTH_DATE", "CIF_ID"]] = None  # no record has them: their comparisons have nothing to count, so are sampled
    df.to_parquet(tmp_path / "in.parquet", index=False)
    engine = DuckDB()
    nayose.build(engine, [tmp_path / "in.parquet"])
    assert engine.value("SELECT COUNT(*) FROM gold") == len(df)
    bits = dict(engine.rows("SELECT comparison, MAX(ABS(bits)) FROM model WHERE comparison IN ('birth', 'cif') GROUP BY 1"))
    assert bits == {"birth": 0.0, "cif": 0.0}  # learned nothing about them: every level weighs nothing


def test_an_update_leaves_the_key_index_a_build_of_the_same_records_makes(tmp_path, population):
    df = population.df
    first, rest = df.iloc[: len(df) // 2].copy(), df.iloc[len(df) // 2:].copy()
    first.loc[first.index[:2], "PHONE_NUM_4"] = "4321"  # the batch makes this phone a placeholder: both made again
    many = df.head(70).assign(CONT_ID=[f"9{i:09d}" for i in range(70)], PHONE_NUM_4="4321", CIF_ID=None)
    first.to_parquet(tmp_path / "first.parquet", index=False)
    pd.concat([rest, many]).to_parquet(tmp_path / "batch.parquet", index=False)
    pd.concat([first, rest, many]).to_parquet(tmp_path / "all.parquet", index=False)
    updated, built = DuckDB(), DuckDB()
    nayose.build(updated, [tmp_path / "first.parquet"])
    nayose.update(updated, [tmp_path / "batch.parquet"])
    nayose.build(built, [tmp_path / "all.parquet"])
    remade = updated.value("SELECT COUNT(*) FROM records WHERE id IN UNNEST(@ids) AND phone IS NULL",
                           {"ids": list(first["CONT_ID"].head(2))})
    index = lambda engine: {t: engine.con.execute(f"SELECT * FROM {t} ORDER BY ALL").fetchall()
                            for t in ("every_key", "rule_keys")}
    assert remade == 2 and index(updated) == index(built)
