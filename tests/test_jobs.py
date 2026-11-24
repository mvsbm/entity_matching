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


def test_an_update_is_refused_once_the_method_its_values_or_the_mapping_changed_since_the_build(tmp_path, population, monkeypatch):
    population.df.to_parquet(tmp_path / "in.parquet", index=False)
    engine = DuckDB()
    nayose.build(engine, [tmp_path / "in.parquet"])
    monkeypatch.setattr(nayose, "fingerprint", lambda *a, **k: "another")
    with pytest.raises(nayose.InputError, match="changed since the run was built"):
        nayose.update(engine, [tmp_path / "in.parquet"])


def test_each_key_s_candidates_and_matches_are_counted_and_the_keys_that_can_go_lose_none(tmp_path, population):
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
    used = set(nayose.config()["score"]["keys"])
    assert {r["key"] for r in got["keys"]} <= used and got["matches"] >= got["true"] > 0
    assert all(r["only"] == 0 for r in got["keys"] if r["key"] in got["drop"])
    con = duckdb.connect(str(tmp_path / "run.duckdb"), read_only=True)
    lost = con.execute("SELECT COUNT(*) FROM scored WHERE rule IS NULL AND match_weight >= 6 AND named AND sources IS NOT NULL "
                       "AND list_has_all(?, string_split(sources, '+'))", [got["drop"]]).fetchone()[0]
    text = kq.report(got, truth=True)
    names = [n for n in population.df["FULL_NAME_KANA"].dropna().unique() if len(n) > 3][:200]
    assert lost == 0 and not [n for n in names if n in text]  # none lost; no record's value shown
