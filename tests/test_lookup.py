"""Look up: one record against the run's index, as an increment of that record alone would list and score its pairs;
search, by any values' starts; and the index kept up to date by what changed, answering as one built again would."""
import json
import shutil
from dataclasses import replace

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
        later = rng.random(n) < 0.1  # added since the index was built: the window of both
        con = duckdb.connect()
        for db, part in (("ix", [r for r, x in zip(stored, later) if not x]), ("dx", [r for r, x in zip(stored, later) if x])):
            con.execute(f"ATTACH ':memory:' AS {db}")
            con.register("src", pd.DataFrame(part, columns=["k", "uid"], dtype="string"))
            con.execute(f"CREATE TABLE {db}.g0 AS SELECT row_number() OVER (ORDER BY k, uid) AS pos, k AS key, uid FROM src ORDER BY pos")
            con.execute(f"CREATE TABLE {db}.g0_sparse AS SELECT pos, key, uid FROM {db}.g0 WHERE (pos - 1) % {index.SPARSE} = 0 ORDER BY pos")
            con.unregister("src")
        order = sorted(stored)
        for key, me in [("a", "q"), ("zzz", "q"), (order[0][0], "q"), (order[-1][0], "q"), (order[n // 2][0], "r99999"), *order[:3], order[-1]]:
            rest = [r for r in order if r[1] != me]  # a stored record looked up as new: the window as if it weren't there
            at = sum(r < (key, me) for r in rest)
            want = [u for _, u in rest[max(0, at - 3):at] + rest[at:at + 3]]
            assert index._window(con, "g0", x, me, key) == want, (n, key, me)


def answers(ws, s, p, asks: list[tuple[dict | None, str | None]]) -> list[dict]:  # what each lookup and search answers, all of it but its time
    from er import index
    out = []
    for values, record in asks:
        r = index.look_up(ws, s, p, values=values, record=record, at_least=-1e9, most=10**6)
        out.append({**{k: r[k] for k in ("record", "entities", "found", "candidates", "likely", "checked")}, "records": r["index"]["records"]})
        if values:
            r = index.search(ws, s, p, values, most=10**6)
            out.append({**{k: r[k] for k in ("entities", "found", "listed", "candidates", "typed", "over")}, "records": r["index"]["records"]})
    return out


def test_a_lookup_lists_and_scores_the_pairs_an_increment_of_the_record_would_and_the_index_kept_up_to_date_answers_as_one_built_again(tmp_path, population, monkeypatch):
    from er import brief, cli, index
    from er.candidates import candidates
    from er.match import review_floor, score_fs
    from er.explain import run_model
    from er.strings import connect
    s, p, g = population
    uid, rng = s.data.unique_id, np.random.default_rng(0)
    df = g.df.copy()
    crowd = rng.random(len(df)) < 0.2  # a given name and a postal code shared by a fifth of the records: blocks too big, gated
    df.loc[crowd, "GIVEN_NAME_KANA"], df.loc[crowd, "POST_CD"] = "タロウ", "1500042"
    held = rng.random(len(df)) < 0.1
    df[~held].to_parquet(tmp_path / "first.parquet", index=False)
    df[held].to_parquet(tmp_path / "new.parquet", index=False)
    ws = tmp_path / "ws"
    assert cli.main(["resolve", "records", str(tmp_path / "first.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    with pytest.raises(InputError, match="no index yet"):
        cli.match_record({"workspace": str(ws), "values": ["PHONE_NUM_4=1234"], "record": None, "from": None, "count": None}, None)
    s2, p2, _ = cli.setup({"workspace": str(ws)})
    built = index.build(ws, s2, p2)
    assert built["records"] == (~held).sum()

    m = index.manifest(ws)
    fitted, model = index._pipeline(ws, s2, p2, m["columns"]), run_model(ws)
    stored = pd.concat([pd.read_parquet(f) for f in sorted((ws / "state" / "records").glob("part-*.parquet"))], ignore_index=True)
    sources = sorted({c for d in fitted.fs.standardize.derived for alt in d.sources for c in alt})
    gated = 0
    for _, rec in df[held].head(12).iterrows():
        values = {c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}
        con = connect(s2.compute)
        index._attach(con, ws, m)
        query = index._query(con, s2, fitted, values, None, index._classifier(ws, s2, fitted, m)).assign(**{uid: rec[uid]})  # prepared as the lookup prepares it, under its own ID
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
        gate = lambda pairs: score_fs(model, "records", pairs, con, uid, into="er_gate", n_records=len(both))
        candidates(fitted.fs.blockers, "records", uid, "new_ids", fitted.fs.budget, con=con, into="cands", touching=True, gate=gate, floor=review_floor(fitted))
        score_fs(model, "records", "cands", con, uid, into="scores", n_records=len(both))
        ref = dict(con.execute(f"""SELECT CASE WHEN "{uid}_l" = '{rec[uid]}' THEN "{uid}_r" ELSE "{uid}_l" END, match_weight FROM scores""").fetchall())
        con.close()
        got = dict(zip(mine["uid"], mine["weight"]))
        assert set(got) == set(ref), rec[uid]  # no pair missed, none added
        assert all(abs(got[k] - ref[k]) < 1e-9 for k in ref), rec[uid]  # each scored alike
    assert gated  # some records fell in a block too big: gated as the run gates it

    con = connect(s2.compute)  # stored records looked up as new: the batch path with each already among the records, once
    index._attach(con, ws, m)
    con.register("er_stored", stored.astype({uid: "string"}))
    con.execute("CREATE TABLE records AS SELECT * FROM er_stored")
    for rid in [*stored.loc[crowd[~held], uid].head(3), *stored[uid].head(2)]:
        query = con.execute(f"SELECT * EXCLUDE (h, entity, resolved) FROM ixr.records WHERE \"{uid}\" = ?", [rid]).df().astype("string")
        con.register("er_q", query)
        con.execute("CREATE OR REPLACE TEMP TABLE qry AS SELECT * FROM er_q")
        found, checked = index._candidates(con, fitted, uid, rid, 0)
        found = {**found, **index._gate(con, fitted, model, uid, rid, found, checked, m["records"])}
        mine = index._scored(con, model, uid, rid, sorted(found), m["records"])
        con.execute(f"CREATE OR REPLACE TABLE new_ids AS SELECT '{rid}' AS \"{uid}\"")
        gate = lambda pairs: score_fs(model, "records", pairs, con, uid, into="er_gate", n_records=m["records"])
        candidates(fitted.fs.blockers, "records", uid, "new_ids", fitted.fs.budget, con=con, into="cands", touching=True, gate=gate, floor=review_floor(fitted))
        score_fs(model, "records", "cands", con, uid, into="scores", n_records=m["records"])
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
    monkeypatch.setattr(index, "_publish", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))  # its files all written, none yet in place
    with pytest.raises(KeyboardInterrupt):  # a build cut short: the index before it stands, and nothing of the new one is left
        index.build(ws, s2, p2)
    monkeypatch.undo()
    assert (ws / "index" / "manifest.json").read_text(encoding="utf-8") == before and not list((ws / "index").glob(".build-*"))

    new = df[held]
    first, later = new.iloc[: len(new) // 3], new.iloc[len(new) // 3:]  # a batch under REBUILD of the index, then the rest
    first.to_parquet(tmp_path / "first_new.parquet", index=False)
    later.to_parquet(tmp_path / "later_new.parquet", index=False)
    pick = lambda d, k: [(dict(FULL_NAME_KANA=r["FULL_NAME_KANA"][:3]) if pd.notna(r["FULL_NAME_KANA"]) else dict(PHONE_NUM_4=r["PHONE_NUM_4"]), None) for _, r in d.head(k).iterrows()]
    asks = [*((None, r) for r in first[uid].head(4)), *((None, r) for r in stored[uid].head(3)), *pick(first, 3), *pick(later, 3),
            *(({c: r[c] for c in sources if c in r and pd.notna(r[c])}, None) for _, r in later.head(3).iterrows())]

    def kept(*words: str) -> dict:  # a command that changes the run, then what its index answers, against an index of all of it built again
        assert cli.main([*words, "--workspace", str(ws), "--format", "json"]) == 0
        m = index.manifest(ws)
        assert index.stale(ws) is None  # brought up to date by the command
        again = tmp_path / f"again-{m['updates']}"
        shutil.copytree(ws, again, ignore=shutil.ignore_patterns(index.INDEX))
        index.build(again, s2, p2)
        assert answers(ws, s2, p2, asks) == answers(again, s2, p2, asks), words  # what changed, written beside it, answers as one built again
        return m

    monkeypatch.setattr(index, "REBUILD", 1.0)  # each change written beside the same index, one after another
    m = kept("add", "records", str(tmp_path / "first_new.parquet"))
    assert m["added"] == len(first) and m["updates"] == 1 and m["records"] == (~held).sum()  # written beside the index, not built again
    entity = pd.read_parquet(ws / "gold.parquet").set_index(uid)["cluster_id"]
    pairs = pd.read_parquet(ws / "scored")  # a pair of stored records in two entities: a "same" joins them
    stored_pair = pairs[~pairs[f"{uid}_l"].isin(first[uid]) & ~pairs[f"{uid}_r"].isin(first[uid])
                        & (pairs[f"{uid}_l"].map(entity) != pairs[f"{uid}_r"].map(entity))].iloc[0]
    pd.DataFrame({f"{uid}_l": [stored_pair[f"{uid}_l"]], f"{uid}_r": [stored_pair[f"{uid}_r"]], "decision": ["match"]}).to_parquet(tmp_path / "same.parquet", index=False)
    m = kept("apply", "decisions", "--file", str(tmp_path / "same.parquet"))
    assert m["moved"] >= 1 and m["added"] == len(first) and m["updates"] == 2  # the entity the decision joined, moved; the records added, still beside it
    monkeypatch.setattr(index, "REBUILD", 0.01)
    assert cli.main(["add", "records", str(tmp_path / "later_new.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    assert index.manifest(ws)["records"] == len(df) and index.manifest(ws)["added"] == 0 and index.stale(ws) is None  # past REBUILD of it: built again
    monkeypatch.undo()
    assert {f.name for f in (ws / "index").iterdir()} == {"manifest.json", *(f for f in index.manifest(ws)["files"].values() if f)}  # the files it names, no other

    old, real = index.manifest(ws), index.manifest
    index.build(ws, s2, p2)  # a reader read the manifest just before this write, whose files it removes
    reads = iter([old])
    monkeypatch.setattr(index, "manifest", lambda w: next(reads, None) or real(w))
    assert index.look_up(ws, s2, p2, record=stored[uid].iloc[0], at_least=-1e9)["index"]["records"] == len(df)  # it reads the new one
    monkeypatch.undo()
    monkeypatch.setattr(index, "update", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert cli.indexed({"workspace": str(ws)}) == dict(error="OSError: disk full", fix=f"build it: {brief.nayose('build', 'index', '--workspace', ws)}")  # the run stands: why its index waits


def _records(ws, uid: str, entity: str) -> set[str]:  # an entity's records, as the run holds them
    gold = pd.read_parquet(ws / "gold.parquet")
    return set(gold.loc[gold["cluster_id"] == entity, uid])


def test_a_look_up_that_reaches_nothing_says_how_near_it_came_and_reads_values_typed_otherwise_as_records_hold_them(tmp_path, population, monkeypatch):
    from er import cli, index
    s, p, g = population
    df = g.df.dropna(subset=["FULL_NAME_KANA"])
    uid, dummy = s.data.unique_id, df.head(80).copy()  # a placeholder name on 80 customers: read as missing in every field built from its columns
    dummy[uid], dummy["CIF_ID"], dummy["FULL_NAME_KANA"] = [f"D{i}" for i in range(80)], [f"9{i:07d}" for i in range(80)], "テストタロウ"
    pd.concat([g.df, dummy], ignore_index=True).to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "ws"
    assert cli.main(["resolve", "records", str(tmp_path / "all.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    assert cli.main(["build", "index", "--workspace", str(ws), "--format", "json"]) == 0
    s2, p2, _ = cli.setup({"workspace": str(ws)})
    assert json.loads((ws / "state" / "placeholders.json").read_text(encoding="utf-8")).get("person_name")
    stored = pd.read_parquet(ws / "state" / "records").set_index(uid)
    looked = index.look_up(ws, s2, p2, values={"FULL_NAME_KANA": "テストタロウ"}, at_least=-1e9)["record"]
    assert stored.loc["D0", ["full_name", "person_name"]].isna().all() and looked["full_name"] is None and looked["person_name"] is None  # as the run read it
    name = df["FULL_NAME_KANA"].iloc[0]
    r = index.look_up(ws, s2, p2, values={"FULL_NAME_KANA": name}, at_least=1e9)
    assert r["found"] == 0 and r["at_least"] == 1e9 and r["closest"]["points"] == max(x["points"] for x in index.look_up(ws, s2, p2, values={"FULL_NAME_KANA": name}, at_least=-1e9, most=10**6)["entities"])
    assert r["closest"]["shown"].get("full_name", "").startswith(name[:2])  # of those tied, one named as typed
    typed = {"FULL_NAME_KANA": "まつもと", "PHONE_NUM_4": "１２-３４", "BIRTH_DATE": "93-05-25"}
    assert index._folded(s2, typed) == typed  # its mapping prepares them so already: one reading
    old = cli.setup({"workspace": str(ws)})[0]
    old = replace(old, standardize=replace(old.standardize, derived=tuple(replace(d, normalize=tuple(x for x in d.normalize if x not in ("katakana", "strip_separators")))
                                                                           for d in old.standardize.derived)))
    assert index._folded(old, typed) == {"FULL_NAME_KANA": "マツモト", "PHONE_NUM_4": "1234", "BIRTH_DATE": "93-05-25"} and index._typed("〒", "digits") == "〒"  # a mapping without them
    real = index._look_up
    answer = lambda found, points: dict(found=found, closest=None if found else dict(points=points), entities=[])
    monkeypatch.setattr(index, "_look_up", lambda ws, s, p, values, record, at_least, most: answer(0, -20) if values["FULL_NAME_KANA"] == "まつもと" else answer(1, None))
    monkeypatch.setattr(index, "_folded", lambda s, values: {c: "マツモト" for c in values})  # as a workspace mapped before the steps
    assert index.look_up(ws, s2, p2, values={"FULL_NAME_KANA": "まつもと"})["read_as"] == {"FULL_NAME_KANA": "マツモト"}  # as given nothing; as records hold it, found: said
    monkeypatch.setattr(index, "_look_up", lambda ws, s, p, values, record, at_least, most: answer(0, -10 if values["FULL_NAME_KANA"] == "まつもと" else -30))
    assert "read_as" not in index.look_up(ws, s2, p2, values={"FULL_NAME_KANA": "まつもと"})  # read otherwise, no nearer: as given
    monkeypatch.setattr(index, "_look_up", real)
