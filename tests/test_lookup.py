"""Look up: one record against the run's index, as an increment of that record alone would list and score its pairs."""
import numpy as np
import pandas as pd
import pytest

from er.config import InputError


def test_a_sorted_window_places_the_record_as_the_run_s_window_does_at_either_end_and_among_equal_keys():
    import duckdb
    from er import index
    from er.config import Key, SortedNeighbourhood
    rng = np.random.default_rng(0)
    x = SortedNeighbourhood(name="w", key=Key("k"), window=4)
    for n in (1, 5, 1024, 1025, 1500, 2049):
        stored = [(f"k{rng.integers(0, n // 3 + 2):05d}", f"r{i:05d}") for i in range(n)]  # many equal keys: the ID orders them
        con = duckdb.connect()
        con.execute("ATTACH ':memory:' AS ix")
        con.execute("CREATE TABLE src AS SELECT * FROM (VALUES " + ", ".join(f"('{k}', '{u}')" for k, u in stored) + ") t(k, uid)")
        con.execute("CREATE TABLE ix.g0 AS SELECT row_number() OVER (ORDER BY k, uid) AS pos, k AS key, uid FROM src ORDER BY pos")
        con.execute(f"CREATE TABLE ix.g0_sparse AS SELECT pos, key, uid FROM ix.g0 WHERE (pos - 1) % {index.SPARSE} = 0 ORDER BY pos")
        order = sorted(stored)
        for key, me in [("a", "q"), ("zzz", "q"), (order[0][0], "q"), (order[-1][0], "q"), (order[n // 2][0], "r99999"), *order[:3], order[-1]]:
            rest = [r for r in order if r[1] != me]  # a stored record looked up as new: the window as if it weren't there
            at = sum(r < (key, me) for r in rest)
            want = [u for _, u in rest[max(0, at - 3):at] + rest[at:at + 3]]
            assert index._window(con, "g0", x, me, key) == want, (n, key, me)


def test_a_lookup_lists_and_scores_the_pairs_an_increment_of_the_record_would_and_says_when_its_index_is_out_of_date(tmp_path, population, monkeypatch):
    from er import cli, index
    from er.candidates import candidates
    from er.match import review_floor, score_fs
    from er.report import run_model
    from er.strings import connect
    s, p, g = population
    uid, rng = s.data.unique_id, np.random.default_rng(0)
    df = g.df.copy()
    crowd = rng.random(len(df)) < 0.2  # a phone and a prefecture shared by a fifth of the records: blocks too big, gated
    df.loc[crowd, "PHONE_NUM_4"], df.loc[crowd, "ADDRESS_ONE"] = "0000", "東京都"
    held = rng.random(len(df)) < 0.1
    df[~held].to_parquet(tmp_path / "first.parquet", index=False)
    df[held].to_parquet(tmp_path / "new.parquet", index=False)
    ws = tmp_path / "ws"
    assert cli.main(["resolve", "records", str(tmp_path / "first.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    with pytest.raises(InputError, match="no index yet"):
        cli.match_record({"workspace": str(ws), "values": ["PHONE_NUM_4=1234"], "record": None, "from": None, "count": None}, None)
    s2, p2, _ = cli.setup({"workspace": str(ws)})
    built = index.build(ws, s2, p2)
    assert built["records"] == (~held).sum() and built["tables"]["big"]["rows"] > 0  # the crowd's blocks, counted

    m = index.manifest(ws)
    fitted, model = index._pipeline(ws, s2, p2, m["columns"]), run_model(ws)
    stored = pd.concat([pd.read_parquet(f) for f in sorted((ws / "state" / "records").glob("part-*.parquet"))], ignore_index=True)
    sources = sorted({c for d in fitted.fs.standardize.derived for alt in d.sources for c in alt})
    gated = 0
    for _, rec in df[held].head(12).iterrows():
        values = {c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}
        con, db = connect(s2.compute)
        con.execute(f"ATTACH '{ws / 'index' / 'index.duckdb'}' AS ix (READ_ONLY)")
        query = index._query(con, ws, s2, fitted, values, None).assign(**{uid: rec[uid]})  # prepared as the lookup prepares it, under its own ID
        con.register("er_q", query)
        con.execute("CREATE TEMP TABLE qry AS SELECT * FROM er_q")
        found, checked = index._candidates(con, fitted, uid, rec[uid])
        found = {**found, **index._gate(con, fitted, model, uid, rec[uid], found, checked, m["records"])}
        mine = index._scored(con, model, uid, rec[uid], sorted(found), m["records"] + 1)
        gated += sum(len(c.get("big", ())) for c in checked)
        both = pd.concat([stored, query], ignore_index=True).astype({uid: "string"})  # the batch path: the record against all, as an increment of it alone
        con.register("er_all", both)
        con.execute("CREATE TABLE records AS SELECT * FROM er_all")
        con.execute(f"CREATE TABLE new_ids AS SELECT '{rec[uid]}' AS \"{uid}\"")
        gate = lambda pairs: score_fs(model, "records", pairs, db, uid, into="er_gate", n_records=len(both))
        candidates(fitted.fs.blockers, "records", uid, "new_ids", fitted.fs.budget, con=con, into="cands", touching=True, gate=gate, floor=review_floor(fitted))
        score_fs(model, "records", "cands", db, uid, into="scores", n_records=len(both))
        ref = dict(con.execute(f"""SELECT CASE WHEN "{uid}_l" = '{rec[uid]}' THEN "{uid}_r" ELSE "{uid}_l" END, match_weight FROM scores""").fetchall())
        con.close()
        got = dict(zip(mine["uid"], mine["weight"]))
        assert set(got) == set(ref), rec[uid]  # no pair missed, none added
        assert all(abs(got[k] - ref[k]) < 1e-9 for k in ref), rec[uid]  # each scored alike
    assert gated  # some records fell in a block too big: gated as the run gates it

    assert "PERSON_ORG_CODE" not in {c["column"] for c in index.status(ws, s2)["columns"]}  # a column the run's file lacks: never offered

    con, db = connect(s2.compute)  # stored records looked up as new: the batch path with each already among the records, once
    con.execute(f"ATTACH '{ws / 'index' / 'index.duckdb'}' AS ix (READ_ONLY)")
    con.register("er_stored", stored.astype({uid: "string"}))
    con.execute("CREATE TABLE records AS SELECT * FROM er_stored")
    for rid in [*stored.loc[crowd[~held], uid].head(3), *stored[uid].head(2)]:
        query = con.execute(f"SELECT * EXCLUDE (h, entity, resolved) FROM ix.records WHERE \"{uid}\" = ?", [rid]).df().astype("string")
        con.register("er_q", query)
        con.execute("CREATE OR REPLACE TEMP TABLE qry AS SELECT * FROM er_q")
        found, checked = index._candidates(con, fitted, uid, rid, 0)
        found = {**found, **index._gate(con, fitted, model, uid, rid, found, checked, m["records"])}
        mine = index._scored(con, model, uid, rid, sorted(found), m["records"])
        con.execute(f"CREATE OR REPLACE TABLE new_ids AS SELECT '{rid}' AS \"{uid}\"")
        gate = lambda pairs: score_fs(model, "records", pairs, db, uid, into="er_gate", n_records=m["records"])
        candidates(fitted.fs.blockers, "records", uid, "new_ids", fitted.fs.budget, con=con, into="cands", touching=True, gate=gate, floor=review_floor(fitted))
        score_fs(model, "records", "cands", db, uid, into="scores", n_records=m["records"])
        ref = dict(con.execute(f"""SELECT CASE WHEN "{uid}_l" = '{rid}' THEN "{uid}_r" ELSE "{uid}_l" END, match_weight FROM scores""").fetchall())
        got = dict(zip(mine["uid"], mine["weight"]))
        assert set(got) == set(ref) and all(abs(got[k] - ref[k]) < 1e-9 for k in ref), rid
    con.close()
    monkeypatch.setattr(index, "run_model", lambda out: {**run_model(out), "er": {**run_model(out)["er"], "tf": {"name": {"x": 0.1}}}})
    with pytest.raises(InputError, match="term frequency"):  # a model a lookup can't score as a run does: refused when built, said in words
        index.build(ws, s2, p2)
    monkeypatch.undo()

    rec = df[held].iloc[0]
    said = cli.match_record({"workspace": str(ws), "values": [f"{c}={rec[c]}" for c in ("FULL_NAME_KANA", "PHONE_NUM_4") if pd.notna(rec[c])],
                             "record": None, "from": "-1000", "count": "5"}, None)
    assert said["found"] >= len(said["entities"]) and len(said["entities"]) <= 5 and said["seconds"] and said["record"]["full_name"]
    gold = pd.read_parquet(ws / "gold.parquet")
    pairs = gold[gold.duplicated("cluster_id", keep=False)].sort_values(uid)
    if len(pairs):  # a stored record, as if new: its entity's other records, itself left out
        one = pairs.iloc[0]
        got = cli.match_record({"workspace": str(ws), "values": None, "record": one[uid], "from": "-1000", "count": "50"}, None)
        assert one["cluster_id"] in {e["entity"] for e in got["entities"]} and one[uid] not in {e["record"] for e in got["entities"]}
    with pytest.raises(InputError, match="one of them"):
        cli.match_record({"workspace": str(ws), "values": ["PHONE_NUM_4=1"], "record": "x", "from": None, "count": None}, None)

    before = (ws / "index" / "manifest.json").read_text(encoding="utf-8")
    monkeypatch.setattr(index, "classifier", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):  # a build cut short: the index before it stands, and nothing of the new one is left
        index.build(ws, s2, p2)
    monkeypatch.undo()
    assert (ws / "index" / "manifest.json").read_text(encoding="utf-8") == before and not list((ws / "index").glob(".build-*"))
    assert cli.main(["add", "records", str(tmp_path / "new.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    assert index.stale(ws)  # the run changed: the index says so, and a lookup refuses until it is built again
    with pytest.raises(InputError, match="changed since it was built"):
        cli.match_record({"workspace": str(ws), "values": ["PHONE_NUM_4=1234"], "record": None, "from": None, "count": None}, None)
    index.build(ws, s2, p2)
    assert index.stale(ws) is None and index.manifest(ws)["records"] == len(df)
