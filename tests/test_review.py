"""The match and decide jobs (nayose/sql/match.sql, decide.sql) against er/'s, on the tests' population: the match
table row for row and in its order, gold after people's decisions and after they change some, the match table again
without the pairs said no_match; and people's decisions read and refused as er/ reads and refuses them."""
import pandas as pd
import pytest

import nayose
from nayose.engines import DuckDB


def same(old: pd.DataFrame, new: pd.DataFrame, key: list[str]) -> None:
    assert list(new.columns) == list(old.columns) and len(new) == len(old)
    assert new[key].equals(old[key])  # the order too
    for c in old.columns:  # kind_p: NULL in nayose where er reads NaN; both rounded
        a, b = old[c], new[c]
        a, b = (a.round(9), b.round(9)) if a.dtype.kind == "f" else (a, b)
        assert a.astype("string").fillna("").equals(b.astype("string").fillna("")), c


def test_the_match_table_and_the_entities_people_s_decisions_make_are_er_s(tmp_path, population):
    from er.config import load_pipeline
    from er.jobs.build import build
    from er.jobs.decide import decide
    from er.jobs.match import match
    from er.settings import load_settings
    _, _, g = population
    s = load_settings()
    p, uid = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns), s.data.unique_id
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    run = tmp_path / "run"
    build(tmp_path / "in.parquet", run, s, p)
    engine = DuckDB()
    nayose.records(engine, [tmp_path / "in.parquet"])
    nayose.fit(engine)
    nayose.score(engine)
    nayose.decide(engine, [])
    ids = {f"{uid}_l": "id_l", f"{uid}_r": "id_r"}
    old = pd.read_parquet(match(run, s, p, 6.0)["into"])
    nayose.match(engine, 6.0)
    same(old.rename(columns=ids), engine.frame("SELECT * FROM matched"), ["id_l", "id_r"])
    said = old[[f"{uid}_l", f"{uid}_r"]].assign(decision=(old["rule"].notna() | (old["match_weight"] >= 12)).map({True: "match", False: "no_match"}))
    again = said.assign(decision=said["decision"].where(said.index % 3 > 0, said["decision"].map({"match": "no_match", "no_match": "match"})))
    for i, d in enumerate([said, again]):
        d.to_parquet(tmp_path / f"er_{i}.parquet", index=False)
        d.rename(columns=ids).to_parquet(tmp_path / f"nayose_{i}.parquet", index=False)
        decide(tmp_path / f"er_{i}.parquet", run, s, p)
        nayose.decide(engine, [tmp_path / f"nayose_{i}.parquet"])
        same(pd.read_parquet(run / "gold.parquet").rename(columns={uid: "id"}), engine.frame("SELECT * FROM gold ORDER BY id"), ["id"])
    assert engine.value("SELECT COUNT(DISTINCT cluster_id) FROM gold") < len(g.df)  # people joined some
    old = pd.read_parquet(match(run, s, p, 6.0, into=tmp_path / "again.parquet")["into"])
    nayose.match(engine, 6.0)
    same(old.rename(columns=ids), engine.frame("SELECT * FROM matched"), ["id_l", "id_r"])
    with pytest.raises(nayose.InputError, match="keeps the pairs from"):
        nayose.match(engine, float(nayose.config()["score"]["keep_from"]) - 1)


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
