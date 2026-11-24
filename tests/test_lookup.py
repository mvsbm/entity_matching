"""Look up: one record against the run's index, as an increment of that record alone would list and score its pairs;
and the index kept up to date by what changed, answering as one built again would."""
import json
import shutil
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest



def answers(ws, s, p, asks: list[tuple[dict | None, str | None]]) -> list[dict]:  # what each lookup answers, all of it but its time
    from er.jobs import index
    out = []
    for values, record in asks:
        r = index.look_up(ws, s, p, values=values, record=record, at_least=-1e9, most=10**6)
        out.append({**{k: r[k] for k in ("record", "entities", "found", "candidates", "likely", "checked")}, "records": r["index"]["records"]})
    return out


def test_a_lookup_lists_and_scores_the_pairs_an_increment_of_the_record_would_and_the_index_kept_up_to_date_answers_as_one_built_again(tmp_path, population, monkeypatch):
    from er.__main__ import main
    from er.config import load_pipeline
    from er.jobs import index
    from er.jobs.build import build, indexed
    from er.jobs.decide import decide
    from er.jobs.update import update
    from er.jobs.index import run_model
    from er.candidates import candidates
    from er.match import review_floor, score_fs
    from er.engine.duckdb import connect
    s, p, g = population
    uid, rng = s.data.unique_id, np.random.default_rng(0)
    df = g.df.copy()
    crowd = rng.random(len(df)) < 0.2  # a given name and a postal code shared by a fifth of the records: blocks too big, gated
    df.loc[crowd, "GIVEN_NAME_KANA"], df.loc[crowd, "POST_CD"] = "タロウ", "1500042"
    held = rng.random(len(df)) < 0.1
    df[~held].to_parquet(tmp_path / "first.parquet", index=False)
    df[held].to_parquet(tmp_path / "new.parquet", index=False)
    ws = tmp_path / "ws"
    s2, p2 = s, load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)  # as python -m er runs it
    assert build(tmp_path / "first.parquet", ws, s2, p2).index["records"] == (~held).sum() and index.stale(ws) is None  # the run, then its index
    built = index.build(ws, s2, p2)
    assert built["records"] == (~held).sum()

    m = index.manifest(ws)
    fitted, model = index._pipeline(ws, s2, p2, m["columns"]), run_model(ws)
    stored = pd.concat([pd.read_parquet(f) for f in sorted((ws / "state" / "records").glob("part-*.parquet"))], ignore_index=True)
    sources = sorted({c for d in fitted.fs.standardize.derived for alt in d.sources for c in alt})
    gated = 0
    for _, rec in df[held].head(12).iterrows():
        values = {c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}
        engine = connect(s2.compute)
        index._attach(engine, ws, m)
        query = index._query(engine, s2, fitted, values, None, index._classifier(ws, s2, fitted, m)).assign(**{uid: rec[uid]})  # prepared as the lookup prepares it, under its own ID
        engine.register("er_q", query)
        engine.run("CREATE TEMP TABLE qry AS SELECT * FROM er_q")
        found, checked = index._candidates(engine, fitted, uid, rec[uid])
        found = {**found, **index._gate(engine, fitted, model, uid, rec[uid], found, checked, m["records"])}
        mine = index._scored(engine, model, uid, rec[uid], sorted(found), m["records"] + 1)
        gated += sum(len(c.get("big", ())) for c in checked)
        both = pd.concat([stored, query], ignore_index=True).astype({uid: "string"})  # the batch path: the record against all, as an increment of it alone
        engine.register("er_all", both)
        engine.run("CREATE TABLE records AS SELECT * FROM er_all")
        engine.run(f"CREATE TABLE new_ids AS SELECT '{rec[uid]}' AS \"{uid}\"")
        gate = lambda pairs: score_fs(model, "records", pairs, engine, uid, into="er_gate", n_records=len(both))
        candidates(fitted.fs.blockers, "records", uid, "new_ids", fitted.fs.budget, engine=engine, into="cands", touching=True, gate=gate, floor=review_floor(fitted))
        score_fs(model, "records", "cands", engine, uid, into="scores", n_records=len(both))
        ref = dict(engine.rows(f"""SELECT CASE WHEN "{uid}_l" = '{rec[uid]}' THEN "{uid}_r" ELSE "{uid}_l" END, match_weight FROM scores"""))
        engine.close()
        got = dict(zip(mine["uid"], mine["weight"]))
        assert set(got) == set(ref), rec[uid]  # no pair missed, none added
        assert all(abs(got[k] - ref[k]) < 1e-9 for k in ref), rec[uid]  # each scored alike
    assert gated  # some records fell in a block too big: gated as the run gates it

    engine = connect(s2.compute)  # stored records looked up as new: the batch path with each already among the records, once
    index._attach(engine, ws, m)
    engine.register("er_stored", stored.astype({uid: "string"}))
    engine.run("CREATE TABLE records AS SELECT * FROM er_stored")
    for rid in [*stored.loc[crowd[~held], uid].head(3), *stored[uid].head(2)]:
        query = engine.frame(f"SELECT * EXCLUDE (h, entity) FROM ixr.records WHERE \"{uid}\" = ?", [rid]).astype("string")
        engine.register("er_q", query)
        engine.run("CREATE OR REPLACE TEMP TABLE qry AS SELECT * FROM er_q")
        found, checked = index._candidates(engine, fitted, uid, rid, 0)
        found = {**found, **index._gate(engine, fitted, model, uid, rid, found, checked, m["records"])}
        mine = index._scored(engine, model, uid, rid, sorted(found), m["records"])
        engine.run(f"CREATE OR REPLACE TABLE new_ids AS SELECT '{rid}' AS \"{uid}\"")
        gate = lambda pairs: score_fs(model, "records", pairs, engine, uid, into="er_gate", n_records=m["records"])
        candidates(fitted.fs.blockers, "records", uid, "new_ids", fitted.fs.budget, engine=engine, into="cands", touching=True, gate=gate, floor=review_floor(fitted))
        score_fs(model, "records", "cands", engine, uid, into="scores", n_records=m["records"])
        ref = dict(engine.rows(f"""SELECT CASE WHEN "{uid}_l" = '{rid}' THEN "{uid}_r" ELSE "{uid}_l" END, match_weight FROM scores"""))
        got = dict(zip(mine["uid"], mine["weight"]))
        assert set(got) == set(ref) and all(abs(got[k] - ref[k]) < 1e-9 for k in ref), rid
    engine.close()

    rec = df[held].iloc[0]
    said = index.look_up(ws, s2, p2, values={c: rec[c] for c in ("FULL_NAME_KANA", "PHONE_NUM_4") if pd.notna(rec[c])}, at_least=-1000, most=5)
    assert said["found"] >= len(said["entities"]) and len(said["entities"]) <= 5 and said["seconds"] and said["record"]["full_name"]
    gold = pd.read_parquet(ws / "gold.parquet")
    pairs = gold[gold.duplicated("cluster_id", keep=False)].sort_values(uid)
    if len(pairs):  # a stored record, as if new: its entity's other records, itself left out
        one = pairs.iloc[0]
        got = index.look_up(ws, s2, p2, record=one[uid], at_least=-1000, most=50)
        assert one["cluster_id"] in {e["entity"] for e in got["entities"]} and one[uid] not in {e["record"] for e in got["entities"]}
    assert main(["lookup", "--out", str(ws), "PHONE_NUM_4=1", "--record", "x"]) == 2  # one of them, never both

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

    def kept(job, path) -> dict:  # a job that changes the run, then what its index answers, against an index of all of it built again
        job(path, ws, s2, p2)
        m = index.manifest(ws)
        assert index.stale(ws) is None  # brought up to date by the job
        again = tmp_path / f"again-{m['updates']}"
        shutil.copytree(ws, again, ignore=shutil.ignore_patterns(index.INDEX))
        index.build(again, s2, p2)
        assert answers(ws, s2, p2, asks) == answers(again, s2, p2, asks), path  # what changed, written beside it, answers as one built again
        return m

    monkeypatch.setattr(index, "REBUILD", 1.0)  # each change written beside the same index, one after another
    m = kept(update, tmp_path / "first_new.parquet")
    assert m["added"] == len(first) and m["updates"] == 1 and m["records"] == (~held).sum()  # written beside the index, not built again
    entity = pd.read_parquet(ws / "gold.parquet").set_index(uid)["cluster_id"]
    pairs = pd.read_parquet(ws / "scored")  # a pair of stored records in two entities: a "same" joins them
    stored_pair = pairs[~pairs[f"{uid}_l"].isin(first[uid]) & ~pairs[f"{uid}_r"].isin(first[uid])
                        & (pairs[f"{uid}_l"].map(entity) != pairs[f"{uid}_r"].map(entity))].iloc[0]
    pd.DataFrame({f"{uid}_l": [stored_pair[f"{uid}_l"]], f"{uid}_r": [stored_pair[f"{uid}_r"]], "decision": ["match"]}).to_parquet(tmp_path / "same.parquet", index=False)
    m = kept(decide, tmp_path / "same.parquet")
    assert m["moved"] >= 1 and m["added"] == len(first) and m["updates"] == 2  # the entity the decision joined, moved; the records added, still beside it
    monkeypatch.setattr(index, "REBUILD", 0.01)
    update(tmp_path / "later_new.parquet", ws, s2, p2)
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
    assert indexed(ws, s2, p2, index.update) == dict(error="OSError: disk full", fix="run the job again")  # the run stands: why its index waits


def _records(ws, uid: str, entity: str) -> set[str]:  # an entity's records, as the run holds them
    gold = pd.read_parquet(ws / "gold.parquet")
    return set(gold.loc[gold["cluster_id"] == entity, uid])


def test_a_look_up_that_reaches_nothing_says_how_near_it_came_and_reads_values_typed_otherwise_as_records_hold_them(tmp_path, population, monkeypatch):
    from er.config import load_pipeline
    from er.jobs import index
    from er.jobs.build import build
    s, p, g = population
    df = g.df.dropna(subset=["FULL_NAME_KANA"])
    uid, dummy = s.data.unique_id, df.head(80).copy()  # a placeholder name on 80 customers: read as missing in every field built from its columns
    dummy[uid], dummy["CIF_ID"], dummy["FULL_NAME_KANA"] = [f"D{i}" for i in range(80)], [f"9{i:07d}" for i in range(80)], "テストタロウ"
    pd.concat([g.df, dummy], ignore_index=True).to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "ws"
    s2, p2 = s, load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)  # as python -m er runs it
    build(tmp_path / "all.parquet", ws, s2, p2)  # its index with it
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
    old = s2
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
