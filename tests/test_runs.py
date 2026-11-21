"""Runs: a full run, increments, writes cut short, the probe (design time, on a run), describe matching."""
import json
import shutil
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from er.config import (InputError, Resolver, bits)
from er.match import named_sql
from er.engine.duckdb import connect


def test_a_run_refuses_a_resolver_it_cannot_apply(population):
    from er.steps.job import start
    s, p, _ = population  # choose.py could adopt the constrained resolver; the run would then cluster otherwise
    constrained = Resolver(method="constrained", cannot_link=("given_name",))
    for q in (replace(p, fs=replace(p.fs, resolver=constrained)), replace(p, rules=replace(p.rules, resolver=constrained))):
        with pytest.raises(InputError, match="connected components only"):
            start(s, q)


def test_a_run_ignores_record_order_refuses_a_used_folder_and_an_increment_keeps_every_cluster(tmp_path, population):
    from er.match import scaled_prior
    from er.report import qa
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    g.df.sample(frac=1, random_state=1).to_parquet(tmp_path / "shuffled.parquet", index=False)
    first = build(tmp_path / "all.parquet", tmp_path / "a", s, p)
    sheet = qa(first, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    assert len(sheet) and {"person_name_l", "person_name_r", "address_l", "address_r", "phone_l", "name", "name_bits"} <= set(sheet.columns)
    lam = scaled_prior(first.scoring, first.n)  # the prior and each field's bits add up to the score a reviewer sees
    bits = sheet[[f"{c.name}_bits" for c in p.fs.model.comparisons]].sum(axis=1) + math.log2(lam / (1 - lam))
    assert np.allclose(bits, sheet["match_weight"], atol=0.05)
    build(tmp_path / "shuffled.parquet", tmp_path / "b", s, p, model=first.model)
    gold = [pd.read_parquet(tmp_path / d / "gold.parquet") for d in ("a", "b")]
    pd.testing.assert_frame_equal(*gold)  # clusters, and the stage and rule that resolved each record
    assert gold[0]["cluster_id"].nunique() < len(gold[0])

    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    build(tmp_path / "old.parquet", tmp_path / "c", s, p, model=first.model)
    before = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    update(tmp_path / "new.parquet", tmp_path / "c", s, p)
    after = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    assert sorted(after.index) == sorted(g.df[uid]) and after.index.is_unique
    assert after.reindex(before.index).groupby(before.to_numpy()).nunique().eq(1).all()  # no stored cluster is split
    assert update(tmp_path / "new.parquet", tmp_path / "c", s, p).added == 0  # a retry adds nothing twice
    pd.testing.assert_series_equal(pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"], after)

    with pytest.raises(InputError, match="already holds a run"):  # a full run never mixes with an earlier one
        build(tmp_path / "all.parquet", tmp_path / "c", s, p, model=first.model)
    build(tmp_path / "all.parquet", tmp_path / "c", s, p, model=first.model, overwrite=True)
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "c" / "gold.parquet"), gold[0])
    assert [f.name for f in (tmp_path / "c" / "state" / "records").iterdir()] == ["part-00000.parquet"]

    g.df.drop(columns="PHONE_NUM_4").to_parquet(tmp_path / "no_phone.parquet", index=False)
    with pytest.raises(InputError, match="fitted on other comparison levels") as e:  # the model compares the phone; this file has none
        build(tmp_path / "no_phone.parquet", tmp_path / "d", s, p, model=first.model)
    assert "without --model" in e.value.fix


def test_an_interrupted_increment_completes_when_run_again(tmp_path, population, monkeypatch):
    import os
    import shutil
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    build(tmp_path / "old.parquet", tmp_path / "clean", s, p)
    shutil.copytree(tmp_path / "clean", tmp_path / "cut")
    shutil.copytree(tmp_path / "clean", tmp_path / "unlogged")
    update(tmp_path / "new.parquet", tmp_path / "clean", s, p)

    renames, replace_ = [], os.replace
    def cut_short(a, b):  # dies halfway through the renames: gold and the clusters replaced, the batch's records not
        renames.append(b)
        if len(renames) == 5:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(os, "replace", cut_short)
    with pytest.raises(KeyboardInterrupt):
        update(tmp_path / "new.parquet", tmp_path / "cut", s, p)
    monkeypatch.undo()
    again = update(tmp_path / "new.parquet", tmp_path / "cut", s, p)  # first finishes the interrupted write
    assert again.added == 0  # so the batch is in the run already: nothing to add
    pd.testing.assert_frame_equal(*(pd.read_parquet(tmp_path / d / "gold.parquet") for d in ("clean", "cut")))
    assert not list((tmp_path / "cut").rglob("*.tmp"))

    from er import folder
    before = (tmp_path / "unlogged" / "steps.json").read_text(encoding="utf-8")
    monkeypatch.setattr(folder, "log", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))  # dies as its log is made: nothing lands
    with pytest.raises(KeyboardInterrupt):
        update(tmp_path / "new.parquet", tmp_path / "unlogged", s, p)
    monkeypatch.undo()
    assert (tmp_path / "unlogged" / "steps.json").read_text(encoding="utf-8") == before  # the log and the files it names land together
    assert update(tmp_path / "new.parquet", tmp_path / "unlogged", s, p).added == len(g.df[new])  # so the batch goes in again, whole


def test_without_bridging_an_increment_lists_no_pair_of_two_records_the_rules_joined(tmp_path, population):
    from er.jobs.update import update
    from er.jobs.build import build
    s, p, g = population
    assert not p.fs.bridge
    uid, l, r = s.data.unique_id, f"{s.data.unique_id}_l", f"{s.data.unique_id}_r"
    both = g.df[g.df["CIF_ID"].notna() & g.df["FULL_NAME_KANA"].notna() & g.df["PHONE_NUM_4"].notna()]
    a, b = both.iloc[0], both[both["PHONE_NUM_4"] != both.iloc[0]["PHONE_NUM_4"]].iloc[0]
    x = a.copy()
    x[uid] = "9000000001"
    y = b.copy()
    y[uid], y["PHONE_NUM_4"], y["POST_CD"] = "9000000002", a["PHONE_NUM_4"], a["POST_CD"]  # each joined to its twin by a rule (customer ID and name); the two share a phone and postal area
    g.df.to_parquet(tmp_path / "old.parquet", index=False)
    pd.DataFrame([x, y]).to_parquet(tmp_path / "new.parquet", index=False)
    pd.concat([g.df, pd.DataFrame([x, y])]).to_parquet(tmp_path / "all.parquet", index=False)
    listed = lambda run: run.engine.value(f"SELECT count(*) FROM cands WHERE {l} = '9000000001' AND {r} = '9000000002'")
    full = build(tmp_path / "all.parquet", tmp_path / "full", s, p, reaching_only=False)  # every pair the keys list, whatever it scores
    rc = pd.read_parquet(tmp_path / "full" / "state" / "rule_clusters.parquet").set_index(uid)["cluster_id"]
    assert rc["9000000001"] == rc[a[uid]] != rc["9000000002"] == rc[b[uid]] and not listed(full)  # a full run never lists it
    build(tmp_path / "old.parquet", tmp_path / "inc", s, p, reaching_only=False)
    shutil.copytree(tmp_path / "inc", tmp_path / "reaching")
    every = update(tmp_path / "new.parquet", tmp_path / "inc", s, p, reaching_only=False)
    assert not listed(every)  # nor does an increment
    counted = lambda x: next(z["candidates"] for z in x.steps if z["step"] == "candidates")
    assert counted(update(tmp_path / "new.parquet", tmp_path / "reaching", s, p)) == counted(every)  # nor counts it, storing only what can reach 0


def crowd_batch(g, uid: str, ruled: bool) -> pd.DataFrame:
    """80 copies of one person on one new phone, a placeholder customer ID on all: blocks too big for the batch's keys.
    `ruled`: each two share an address code of their own, so a rule joins them; else every copy is alone."""
    a = g.df[g.df["FULL_NAME_KANA"].notna() & g.df["POST_CD"].notna()].iloc[0]
    rows = []
    for k in range(40):
        for j in range(2):
            x = a.copy()
            x[[uid, "CIF_ID", "PHONE_NUM_4"]] = [f"9{k:04d}{j:05d}", "C00000000", "9999"]
            if ruled:
                x["SOURCE_ADDR_CD"] = f"{k:010d}"
            rows.append(x)
    return pd.DataFrame(rows)


def test_the_gate_keeps_a_block_whose_sampled_pairs_reach_the_search_floor_but_not_the_review_floor(tmp_path, population):
    from er.match import review_floor, search_floor
    from er.jobs.build import build
    s, p, g = population
    grid = tuple(range(0, 32, 2))
    p = replace(p, threshold=replace(p.threshold, grid=grid), fs=replace(p.fs, min_match_weight=30.0))  # a review floor (28) above the crowd's best pair
    assert search_floor(p) == 0 and review_floor(p) == 28 and search_floor(replace(p, threshold=replace(p.threshold, search_floor=99))) == 28
    pd.concat([g.df, crowd_batch(g, s.data.unique_id, False)]).to_parquet(tmp_path / "in.parquet", index=False)
    gated = build(tmp_path / "in.parquet", tmp_path / "run", s, p).gated
    crowd = gated[gated["records"] >= 80]
    assert len(crowd) and (crowd["best"] < review_floor(p)).all() and (crowd["best"] >= search_floor(p)).all()
    assert (crowd["decision"] == "kept").all()  # aimed at the review floor, every one would be skipped


@pytest.mark.parametrize("ruled", [False, True])
def test_an_increment_s_gate_keeps_a_block_on_pairs_the_run_could_list(tmp_path, population, ruled):
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    uid = s.data.unique_id
    p = replace(p, fs=replace(p.fs, model=replace(p.fs.model, u_from_scored=False)))  # the stored u: the copies' pairs score as the run's would
    g.df.to_parquet(tmp_path / "old.parquet", index=False)
    crowd_batch(g, uid, ruled).to_parquet(tmp_path / "new.parquet", index=False)
    build(tmp_path / "old.parquet", tmp_path / "run", s, p)
    run = update(tmp_path / "new.parquet", tmp_path / "run", s, p)
    phone = run.gated[run.gated["generator"] == "phone_prefecture"]
    if ruled:  # every sampled pair joins two records the rules joined: no pair the run could list, without bridging
        assert phone["decision"].str.startswith("skipped").all()
        return
    assert phone.loc[phone["decision"] == "kept", "value"].tolist()  # the block the batch made, listed


def test_a_full_run_cut_short_in_its_moves_lands_with_its_round(tmp_path, population, monkeypatch):
    import os
    from er import folder
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    replace_ = os.replace
    def cut_short(a, b):  # dies at the first move once the moves owed are saved
        if (tmp_path / "run" / folder.PENDING).exists():
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(os, "replace", cut_short)
    with pytest.raises(KeyboardInterrupt):
        build(tmp_path / "all.parquet", tmp_path / "run", s, p)
    monkeypatch.undo()
    folder.finish_writes(tmp_path / "run")  # as the next command on the workspace does
    assert (tmp_path / "run" / "gold.parquet").exists() and len(folder.rounds(tmp_path / "run")) == 1  # the run and its round land together


def test_a_full_run_keeps_the_decisions_people_wrote_in_the_sheet_and_have_not_given_back(tmp_path, population):
    from er.jobs.build import build
    s, p, g = population
    uid, ws = s.data.unique_id, tmp_path / "ws"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    build(tmp_path / "all.parquet", ws, s, p, pipeline_file=s.root / "config" / "final.toml")  # with its reports: the sheet
    sheet = pd.read_parquet(ws / "review.parquet")
    row = sheet.index[sheet["why"] == "decide"][0]
    keys = {f"{uid}_l": sheet.at[row, f"{uid}_l"], f"{uid}_r": sheet.at[row, f"{uid}_r"]}
    sheet.loc[row, "decision"] = "no_match"  # written in the sheet, not applied
    sheet.to_parquet(ws / "review.parquet", index=False)
    build(tmp_path / "all.parquet", ws, s, p, overwrite=True, pipeline_file=s.root / "config" / "final.toml")  # a full run makes the sheet again
    after = pd.read_parquet(ws / "review.parquet")
    assert after[(after[f"{uid}_l"] == keys[f"{uid}_l"]) & (after[f"{uid}_r"] == keys[f"{uid}_r"])]["decision"].tolist() == ["no_match"]


def test_an_overwrite_cut_short_keeps_the_old_run_and_people_s_decisions(tmp_path, population, monkeypatch):
    import os
    import er.folder
    from er.folder import finish_writes
    from er.jobs.build import build
    from er.jobs.decide import decide
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    build(tmp_path / "all.parquet", tmp_path / "run", s, p)
    a, b = sorted(pd.read_parquet(tmp_path / "run" / "gold.parquet").drop_duplicates("cluster_id")[uid].iloc[:2])  # two entities: people say one
    pd.DataFrame({f"{uid}_l": [a], f"{uid}_r": [b], "decision": ["match"]}).to_parquet(tmp_path / "decided.parquet")
    decide(tmp_path / "decided.parquet", tmp_path / "run", s, p)
    before = pd.read_parquet(tmp_path / "run" / "gold.parquet")
    lit = er.folder.lit
    def full_disk(path):  # the new gold can't be written
        if "gold" in str(path):
            raise OSError("No space left on device")
        return lit(path)
    monkeypatch.setattr(er.folder, "lit", full_disk)
    with pytest.raises(OSError):
        build(tmp_path / "all.parquet", tmp_path / "run", s, p, overwrite=True)
    monkeypatch.undo()
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "run" / "gold.parquet"), before)  # the old run stands
    assert len(pd.read_parquet(tmp_path / "run" / "decisions")) == 1  # and people's decisions with it

    moves, replace_ = [], os.replace
    def cut_short(a, b):  # dies after the first of the moves that replace the old run
        moves.append(b)
        if len(moves) == 3:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(os, "replace", cut_short)
    with pytest.raises(KeyboardInterrupt):
        build(tmp_path / "all.parquet", tmp_path / "run", s, p, overwrite=True)
    monkeypatch.undo()
    finish_writes(tmp_path / "run")  # what the next run, increment or decisions do first
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "run" / "gold.parquet"), before)
    assert len(pd.read_parquet(tmp_path / "run" / "decisions")) == 1
    assert len(pd.read_parquet(tmp_path / "run" / "state" / "records")) == len(g.df) and not (tmp_path / "run" / ".full.tmp").exists()


def test_an_increment_refuses_a_changed_pipeline_and_steps_json_says_what_went_in(tmp_path, population):
    import hashlib
    import json
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    build(tmp_path / "old.parquet", tmp_path / "run", s, p)
    entry = json.loads((tmp_path / "run" / "steps.json").read_text(encoding="utf-8"))["runs"][-1]
    assert entry["inputs"][0]["sha256"] == hashlib.sha256((tmp_path / "old.parquet").read_bytes()).hexdigest() and entry["code"] and entry["config"]
    changed = replace(p, fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 1))
    with pytest.raises(InputError, match="changed since the full run"):
        update(tmp_path / "new.parquet", tmp_path / "run", s, changed)  # the batch would be resolved otherwise
    update(tmp_path / "new.parquet", tmp_path / "run", s, p)  # the run's own pipeline: it goes on


def test_an_increment_never_merges_a_pair_people_said_is_different(tmp_path, population):
    from er.jobs.build import build
    from er.jobs.decide import decide
    from er.jobs.update import update
    s, p, g = population
    uid, ws = s.data.unique_id, tmp_path / "run"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    build(tmp_path / "all.parquet", ws, s, p)
    a, b = pd.read_parquet(ws / "matches")[[f"{uid}_l", f"{uid}_r"]].iloc[0]  # the model merged them
    pd.DataFrame({f"{uid}_l": [a], f"{uid}_r": [b], "decision": ["no_match"]}).to_parquet(tmp_path / "said.parquet")
    decide(tmp_path / "said.parquet", ws, s, p)
    g.df[g.df[uid] != b].to_parquet(tmp_path / "without.parquet", index=False)
    g.df[g.df[uid] == b].to_parquet(tmp_path / "back.parquet", index=False)
    build(tmp_path / "without.parquet", ws, s, p, overwrite=True)  # decisions/ stays
    update(tmp_path / "back.parquet", ws, s, p)
    gold = pd.read_parquet(ws / "gold.parquet").set_index(uid)["cluster_id"]
    assert gold[a] != gold[b]  # as a full run applies people's "different"


def test_an_increment_needs_a_workspace_that_holds_a_run(tmp_path, population):
    from er.jobs.update import update
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    with pytest.raises(InputError, match="no workspace at"):  # a folder not there: refused, never made
        update(tmp_path / "all.parquet", tmp_path / "empty", s, p)
    assert not (tmp_path / "empty").exists()
    (tmp_path / "empty").mkdir()
    with pytest.raises(InputError, match="no run in"):
        update(tmp_path / "all.parquet", tmp_path / "empty", s, p)


def test_the_probe_counts_the_matches_no_key_lists_as_the_truth_does(tmp_path, population):
    from er.cluster import merge
    from er.explain import scored_again
    from design.probe import probe as probed
    from er.jobs.build import build
    from er.jobs.decide import decide
    s, p, g = population
    uid, ent = s.data.unique_id, s.data.entity_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    few = replace(p, fs=replace(p.fs, blockers=tuple(b for b in p.fs.blockers if b.name in ("cif", "person_name", "company_name"))))  # a method that misses
    out = tmp_path / "run"
    probe = probed(build(tmp_path / "all.parquet", out, s, few))
    engine = connect(s.compute)  # the truth: every true pair scored as the run scores, at its line, that its likely links don't join
    truth = g.truth[[uid, ent]].merge(g.truth[[uid, ent]], on=ent).query(f"{uid}_x < {uid}_y")
    engine.register("er_t", truth.rename(columns={f"{uid}_x": l, f"{uid}_y": r})[[l, r]])
    scored_again(engine, out, uid, "er_t", "er_ts")
    wide = engine.rows("SELECT * FROM er_ts ORDER BY ALL")
    scored_again(engine, out, uid, "er_t", "er_ts", narrow=True)  # only the columns the model reads: the same scores
    assert engine.rows("SELECT * FROM er_ts ORDER BY ALL") == wide \
        and len(engine.rows("DESCRIBE er_touched")) < len(engine.rows(f"DESCRIBE SELECT * FROM read_parquet('{out}/state/records/*.parquet')"))
    links = " UNION ALL ".join(f"SELECT {l}, {r} FROM read_parquet('{out / x}/*.parquet')" for x in ("matches", "rule_kept") if any((out / x).glob("*.parquet")))
    engine.run(f"CREATE TABLE er_one AS SELECT {uid}, {uid} AS cluster_id FROM read_parquet('{out}/gold.parquet')")
    merge(engine, "er_one", f"({links})", "er_joined", uid)
    missed = engine.rows(f"""SELECT s.{l}, s.{r} FROM er_ts s JOIN er_joined a ON a.{uid} = s.{l} JOIN er_joined b ON b.{uid} = s.{r}
        WHERE s.match_weight >= {few.fs.min_match_weight} AND {named_sql(few.fs)} AND a.cluster_id <> b.cluster_id""")
    phone = g.df.set_index(uid)[s.columns["phone"][0][0]]
    shared = {(a, b) for a, b in missed if pd.notna(phone[a]) and phone[a] == phone[b]}
    by = {x["stratum"]: x for x in probe}
    assert shared and by["phone"]["drawn"] == 1.0 and by["phone"]["hits"] == by["phone"]["missed"] == len(shared)  # every pair drawn: exactly the truth
    assert {tuple(x[:2]) for x in by["phone"]["examples"]} == shared
    apart = sorted(shared)[0]  # people say one of them is different: no match missed, then
    pd.DataFrame({l: [apart[0]], r: [apart[1]], "decision": ["no_match"]}).to_parquet(tmp_path / "apart.parquet")
    decide(tmp_path / "apart.parquet", out, s, few)
    again = probed(build(tmp_path / "all.parquet", out, s, few, overwrite=True))
    phone_again = next(x for x in again if x["stratum"] == "phone")
    assert phone_again["hits"] == len(shared) - 1 and apart not in {tuple(x[:2]) for x in phone_again["examples"]}
    sampled = probed(build(tmp_path / "all.parquet", tmp_path / "run2", s, replace(few, probe=replace(few.probe, pairs=200))))[0]
    assert sampled["drawn"] < 1 and sampled["low"] <= len(shared) <= sampled["high"]  # a share drawn: its interval holds the truth
    full = probed(build(tmp_path / "all.parquet", tmp_path / "run3", s, p))
    assert all(x["hits"] <= by[x["stratum"]]["hits"] for x in full)  # the tuned method's keys miss no more


def test_scoring_in_slices_gives_the_scores_scoring_all_at_once_gives_and_each_long_step_says_how_far_it_is(tmp_path, population, monkeypatch):
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    first = build(tmp_path / "all.parquet", tmp_path / "a", s, p)
    told = []
    whole = build(tmp_path / "all.parquet", tmp_path / "b", s, p, model=first.model)
    monkeypatch.setattr("er.steps.score.SCORE_PAIRS", 20)  # many slices
    monkeypatch.setattr("er.steps.load.CHUNK_ROWS", 100)  # and many chunks
    sliced = build(tmp_path / "all.parquet", tmp_path / "c", s, p, model=first.model, told=lambda *a, **k: told.append((*a, k)))
    monkeypatch.undo()
    scores = [r.engine.frame(f"SELECT * FROM scores ORDER BY {r.l}, {r.r}") for r in (whole, sliced)]
    pd.testing.assert_frame_equal(*scores, rtol=1e-9)  # a pair's score depends on it alone: the same in a slice as in the whole
    counts = {}
    for done, of, unit, _ in told:
        counts.setdefault(unit, []).append((done, of))
    assert {"records", "rules", "keys", "pairs"} <= set(counts)  # load, rules, candidates' joins, scoring: each counts its own work
    for unit, seen in counts.items():  # up to its total, never back
        assert [d for d, _ in seen] == sorted(d for d, _ in seen) and seen[-1][0] == seen[-1][1] == seen[0][1], unit
    assert counts["records"][-1][0] == whole.n and counts["rules"][-1][0] == len(list(p.rules.each())) and len(counts["records"]) > 2  # from 0, a chunk at a time
    weighed = []
    from er.steps.budget import Budget
    from er.steps.candidates import _joined
    from er.steps.job import Job, Log
    probe = Job(whole.engine, s, p, Log(told=lambda *a, **k: weighed.append((*a, k["more"]))))
    g = len(p.fs.blockers)  # the joins weighed by the budget's pairs: a generator whose blocks are all oversized lists none
    plan = pd.DataFrame(dict(kind=["rule", *["generator"] * g], normal=[5, 0, *[10] * (g - 1)], oversized_blocks=[0, 1, *[0] * (g - 1)]))
    for i in range(g + 1):
        _joined(probe, 1000, Budget(plan, {}))(i, g, "keys")
    assert [x[0] for x in weighed] == sorted(x[0] for x in weighed) and weighed[0][0] == 0 and weighed[-1][0] == weighed[-1][1] > 0 and all(x[3] for x in weighed)
    told = [(*x[:3], x[3]["likely"]) for x in told if x[2] == "pairs"]
    total = whole.count("cands")
    assert len(told) == -(-total // 20) > 1 and [x[0] for x in told] == sorted({min(total, 20 * (i + 1)) for i in range(len(told))})
    assert {x[1:3] for x in told} == {(total, "pairs")} and told[-1][3] == whole.count(f"scores s WHERE match_weight >= {bits(p.fs.min_match_weight)} AND {named_sql(p.fs)}")
    assert pd.read_parquet(tmp_path / "b" / "gold.parquet").equals(pd.read_parquet(tmp_path / "c" / "gold.parquet"))
    views = lambda run: run.count("duckdb_views() WHERE NOT internal")
    assert views(sliced) == views(whole)  # each slice's lookups released: memory doesn't grow with the slices


def test_a_full_run_reads_the_records_it_cleaned_again_until_anything_they_rest_on_changes(tmp_path, population):
    from er import folder
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "ws"
    load = lambda run: next(x for x in run.steps if x["step"] == "load")["prepared"]
    rows = lambda run: run.engine.frame(f"SELECT * FROM records ORDER BY {run.uid}")
    first = build(tmp_path / "all.parquet", ws, s, p)
    gold = pd.read_parquet(ws / "gold.parquet")
    again = build(tmp_path / "all.parquet", ws, s, p, overwrite=True)
    assert (load(first), load(again)) == ("made", "kept")
    pd.testing.assert_frame_equal(rows(first), rows(again))  # as cleaning them again would make them
    pd.testing.assert_frame_equal(gold, pd.read_parquet(ws / "gold.parquet"))
    (kept,) = (ws / folder.PREPARED).iterdir()
    (kept / "records.parquet").write_bytes(b"not parquet")  # a copy that can't be read: made again
    assert load(build(tmp_path / "all.parquet", ws, s, p, overwrite=True)) == "made"
    for n in (1, 2):  # other records: other cleaned records, the last two kept
        g.df.iloc[n:].to_parquet(tmp_path / f"less{n}.parquet", index=False)
        assert load(build(tmp_path / f"less{n}.parquet", ws, s, p, overwrite=True)) == "made"
    assert len(list((ws / folder.PREPARED).iterdir())) == folder.KEEP_PREPARED
    assert load(build(tmp_path / "less1.parquet", ws, s, p, overwrite=True)) == "kept"  # read: the last used
    g.df.iloc[3:].to_parquet(tmp_path / "less3.parquet", index=False)
    assert load(build(tmp_path / "less3.parquet", ws, s, p, overwrite=True)) == "made"
    assert load(build(tmp_path / "less1.parquet", ws, s, p, overwrite=True)) == "kept"  # less2's went: used longest ago
    import duckdb
    def full_disk(f):
        raise duckdb.IOException("no space left on device")
    (ws / folder.PREPARED / ".k.2147483646.tmp").mkdir()  # left half written by a run long gone
    folder.keep_prepared(ws, "k", full_disk)  # a copy that can't be written: left out, the run goes on
    assert not [x for x in (ws / folder.PREPARED).iterdir() if x.name.startswith(".") or x.name == "k"]
    from dataclasses import replace
    from er.steps.load import _prepared_key
    key = lambda settings, inputs=first.inputs, ordered=False: _prepared_key(replace(first.job, settings=settings), first.pipeline, inputs, [], set(), ordered)
    base = key(s)
    assert key(replace(s, compute={"threads": "1"})) == base  # the compute limits change no record
    assert key(replace(s, columns={**s.columns, "phone": (("another_column",),)})) != base  # another mapping: cleaned again
    assert key(replace(s, flag_company=("X",))) != base  # another cleaning setting
    assert key(s, ordered=True) == base  # one file read in order: the rows read at once
    two = [*first.inputs, {**first.inputs[0], "sha256": "0" * 64}]
    assert key(s, two, True) != key(s, two, False) != base  # files in order: set aside as increments would


def test_a_file_s_columns_no_field_reads_never_enter_the_run(tmp_path, population):
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    g.df.assign(NOTE="x" * 50, MEMO="y").to_parquet(tmp_path / "wide.parquet", index=False)  # columns no field is mapped to
    build(tmp_path / "all.parquet", tmp_path / "a", s, p)
    wide = build(tmp_path / "wide.parquet", tmp_path / "b", s, p)
    assert {"NOTE", "MEMO"}.isdisjoint(wide.columns()) and {"NOTE", "MEMO"}.isdisjoint(pd.read_parquet(tmp_path / "b" / "state" / "records").columns)
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "a" / "gold.parquet"), pd.read_parquet(tmp_path / "b" / "gold.parquet"))


def test_a_run_over_a_log_an_older_version_wrote_keeps_its_runs_without_their_time(tmp_path, population):
    from er import folder
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    ws = tmp_path / "home" / "old"
    build(tmp_path / "in.parquet", ws, s, p)
    log = json.loads((ws / "steps.json").read_text(encoding="utf-8"))
    log["runs"] = [{k: v for k, v in x.items() if k in ("disabled", "part", "steps")} for x in log["runs"]]  # as an older version wrote it
    (ws / "steps.json").write_text(json.dumps(log), encoding="utf-8")
    build(tmp_path / "in.parquet", ws, s, p, overwrite=True)  # its write reads the old log into the new one's history
    history = folder.history(ws)
    assert [x["at"] for x in history][0] is None and history[-1]["at"]


def test_an_increment_scores_its_pairs_a_slice_at_a_time_as_a_full_run_does(tmp_path, population, monkeypatch):
    import shutil
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    new = np.random.default_rng(3).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    build(tmp_path / "old.parquet", tmp_path / "a", s, p)
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    update(tmp_path / "new.parquet", tmp_path / "a", s, p)
    import er.steps.score as S
    monkeypatch.setattr(S, "SCORE_PAIRS", 37)  # many slices: the batch's pairs never scored all at once
    slices, scored = [], S.scored_in_slices
    monkeypatch.setattr(S, "scored_in_slices", lambda job, scoring, pairs, into, **k: (slices.append(pairs), scored(job, scoring, pairs, into, **k))[1])
    update(tmp_path / "new.parquet", tmp_path / "b", s, p)
    assert "cands" in slices  # through the full run's slices
    key = lambda ws: pd.read_parquet(ws / "scored").drop(columns=["match_probability"]).round({"match_weight": 9}).sort_values(list(pd.read_parquet(ws / "scored").columns[:2])).reset_index(drop=True)
    assert len(key(tmp_path / "a")) and key(tmp_path / "a").equals(key(tmp_path / "b"))
    assert pd.read_parquet(tmp_path / "a" / "gold.parquet").equals(pd.read_parquet(tmp_path / "b" / "gold.parquet"))


def test_a_run_s_moves_wait_out_a_reader_holding_a_file_as_windows_refuses_them(tmp_path, monkeypatch):
    import os
    from er import folder
    out = tmp_path / "run"
    (out / "scored").mkdir(parents=True)
    (out / "scored" / "part-00000.parquet").write_text("old", encoding="utf-8")
    (out / "new.parquet").write_text("new", encoding="utf-8")
    (out / folder.PENDING).write_text(json.dumps([[str(out / "new.parquet"), str(out / "gold.parquet")], [None, str(out / "scored")]]), encoding="utf-8")
    real, refused = os.replace, []
    def held(a, b):  # a describe reading the file: refused twice, then let go
        if len(refused) < 2:
            refused.append(b)
            raise PermissionError(13, "in use by another process", b)
        return real(a, b)
    monkeypatch.setattr(os, "replace", held)
    folder.finish_writes(out)
    assert len(refused) == 2 and (out / "gold.parquet").read_text(encoding="utf-8") == "new" and not (out / "scored").exists() and not (out / folder.PENDING).exists()
