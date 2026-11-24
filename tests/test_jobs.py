"""The jobs (python -m nayose, nayose/__main__.py) as a machine runs them, each in a process of its own: a run built,
updated, matched, decided and looked up in its folder, each job's JSON and exit code (0; 2, a mistake people fix; 75,
another job is writing); a rebuild keeping people's decisions; report.txt; and people's decisions read and refused."""
import json
import subprocess
import sys

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
    assert code == 0 and said["records"] == half and (run / "run.duckdb").is_file() and "full run" in (run / "report.txt").read_text(encoding="utf-8")
    assert job("build", tmp_path / "first.parquet", "--out", run)[0] == 2  # a folder that holds a run: refused without --overwrite
    code, said = job("update", tmp_path / "batch.parquet", "--out", run)
    assert code == 0 and said["added"] == len(g.df) - half and "increment of" in (run / "report.txt").read_text(encoding="utf-8")
    assert job("update", tmp_path / "batch.parquet", "--out", run)[1]["added"] == 0  # given twice: nothing new, nothing written
    code, said = job("match", "--out", run, "--threshold", 6)
    table = pd.read_parquet(said["into"])
    assert code == 0 and said["pairs"] == len(table) > 0 and table["decision"].isna().all()
    assert job("match", "--out", run, "--threshold", -5)[0] == 2  # below keep_from: the run keeps no pair there
    table.head(3).assign(decision="match")[["id_l", "id_r", "decision"]].to_parquet(tmp_path / "decided.parquet", index=False)
    code, said = job("decide", tmp_path / "decided.parquet", "--out", run)
    assert code == 0 and said["decisions"] == 3 and said["entities"] < len(g.df)
    code, said = job("build", tmp_path / "first.parquet", "--out", run, "--overwrite")
    assert code == 0 and DuckDB(run / "run.duckdb").value("SELECT COUNT(*) FROM decisions") == 3  # people's decisions stay
    code, said = job("lookup", "--out", run, "--record", g.df["CONT_ID"].iloc[0])
    assert code == 0 and said["record"]["id"] == g.df["CONT_ID"].iloc[0] and "entities" in said
    assert job("lookup", "--out", run, "NOPE=1")[0] == 2 and job("lookup", "--out", tmp_path / "none", "--record", "1")[0] == 2
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
    assert engine.rows("SELECT id, cluster_id, resolved_by FROM gold ORDER BY id") == [("a", "a", "review"), ("b", "a", "review"), ("c", "c", None), ("d", "d", None)]
    assert given([("a", "b", "match")]) == 1  # given again: nothing new
    assert given([("a", "b", "no_match")]) == 2 and engine.value("SELECT COUNT(DISTINCT cluster_id) FROM gold") == 4  # the latest stands
    for rows, columns, refused in [([("a", "b", "same")], None, "match or no_match, not same"),
                                   ([("a", "b", "match"), ("b", "a", "no_match")], None, "decided both ways"),
                                   ([("a", "151", "match")], None, "name no record"),
                                   ([("a", None, "match")], None, "lack an ID"),
                                   ([("a", "b", None)], None, "no row has a decision"),
                                   ([("a", "b")], ("id_l", "id_r"), "lack the columns")]:
        with pytest.raises(Exception, match=refused):
            given(rows, columns or ("id_l", "id_r", "decision"))
    assert engine.value("SELECT COUNT(*) FROM decisions") == 2  # a refused table stores nothing
