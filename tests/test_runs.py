"""Runs: a full run, increments, writes cut short, the probe, describe matching."""
import json
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from er.config import (InputError, Resolver, bits)
from er.match import named_sql
from er.strings import connect



def test_a_run_refuses_a_resolver_it_cannot_apply(population):
    from er.run import Run
    s, p, _ = population  # choose.py could adopt the constrained resolver; the run would then cluster otherwise
    constrained = Resolver(method="constrained", cannot_link=("given_name",))
    for q in (replace(p, fs=replace(p.fs, resolver=constrained)), replace(p, rules=replace(p.rules, resolver=constrained))):
        with pytest.raises(InputError, match="connected components only"):
            Run(q, s)


def test_a_run_ignores_record_order_refuses_a_used_folder_and_an_increment_keeps_every_cluster(tmp_path, population):
    from er.match import scaled_prior
    from er.report import qa
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    g.df.sample(frac=1, random_state=1).to_parquet(tmp_path / "shuffled.parquet", index=False)
    first = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    sheet = qa(first, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    assert len(sheet) and {"person_name_l", "person_name_r", "address_l", "address_r", "phone_l", "name", "name_bits"} <= set(sheet.columns)
    lam = scaled_prior(first.scoring, first.n)  # the prior and each field's bits add up to the score a reviewer sees
    bits = sheet[[f"{c.name}_bits" for c in p.fs.model.comparisons]].sum(axis=1) + math.log2(lam / (1 - lam))
    assert np.allclose(bits, sheet["match_weight"], atol=0.05)
    Run(p, s, model=first.model).full(tmp_path / "shuffled.parquet", tmp_path / "b")
    gold = [pd.read_parquet(tmp_path / d / "gold.parquet") for d in ("a", "b")]
    pd.testing.assert_frame_equal(*gold)  # clusters, and the stage and rule that resolved each record
    assert gold[0]["cluster_id"].nunique() < len(gold[0])

    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    Run(p, s, model=first.model).full(tmp_path / "old.parquet", tmp_path / "c")
    before = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c")
    after = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    assert sorted(after.index) == sorted(g.df[uid]) and after.index.is_unique
    assert after.reindex(before.index).groupby(before.to_numpy()).nunique().eq(1).all()  # no stored cluster is split
    assert Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c").added == 0  # a retry adds nothing twice
    pd.testing.assert_series_equal(pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"], after)

    with pytest.raises(InputError, match="already holds a run"):  # a full run never mixes with an earlier one
        Run(p, s, model=first.model).full(tmp_path / "all.parquet", tmp_path / "c")
    Run(p, s, model=first.model).full(tmp_path / "all.parquet", tmp_path / "c", overwrite=True)
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "c" / "gold.parquet"), gold[0])
    assert [f.name for f in (tmp_path / "c" / "state" / "records").iterdir()] == ["part-00000.parquet"]

    g.df.drop(columns="PHONE_NUM_4").to_parquet(tmp_path / "no_phone.parquet", index=False)
    with pytest.raises(InputError, match="fitted on other comparison levels") as e:  # the model compares the phone; this file has none
        Run(p, s, model=first.model).full(tmp_path / "no_phone.parquet", tmp_path / "d")
    assert "without --model" in e.value.fix


def test_an_interrupted_increment_completes_when_run_again(tmp_path, population, monkeypatch):
    import os
    import shutil
    from er.run import Run
    s, p, g = population
    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    Run(p, s).full(tmp_path / "old.parquet", tmp_path / "clean")
    shutil.copytree(tmp_path / "clean", tmp_path / "cut")
    Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "clean")

    renames, replace_ = [], os.replace
    def cut_short(a, b):  # dies halfway through the renames: gold and the clusters replaced, the batch's records not
        renames.append(b)
        if len(renames) == 5:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(os, "replace", cut_short)
    with pytest.raises(KeyboardInterrupt):
        Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "cut")
    monkeypatch.undo()
    again = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "cut")  # first finishes the interrupted write
    assert again.added == 0  # so the batch is in the run already: nothing to add
    pd.testing.assert_frame_equal(*(pd.read_parquet(tmp_path / d / "gold.parquet") for d in ("clean", "cut")))
    assert not list((tmp_path / "cut").rglob("*.tmp"))


def test_an_overwrite_cut_short_keeps_the_old_run_and_people_s_answers(tmp_path, population, monkeypatch):
    import os
    import er.folder
    from er.folder import finish_writes
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    pd.DataFrame({uid: g.df[uid].astype("string")[:5], "kind": [1] * 5}).to_parquet(tmp_path / "answers.parquet")
    Run(p, s, kind_labels=tmp_path / "answers.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    before = pd.read_parquet(tmp_path / "run" / "gold.parquet")
    lit = er.folder.lit
    def full_disk(path):  # the new gold can't be written
        if "gold" in str(path):
            raise OSError("No space left on device")
        return lit(path)
    monkeypatch.setattr(er.folder, "lit", full_disk)
    with pytest.raises(OSError):
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    monkeypatch.undo()
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "run" / "gold.parquet"), before)  # the old run stands
    assert len(pd.read_parquet(tmp_path / "run" / "kind_answers")) == 5  # and people's answers with it

    moves, replace_ = [], os.replace
    def cut_short(a, b):  # dies after the first of the moves that replace the old run
        moves.append(b)
        if len(moves) == 3:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(os, "replace", cut_short)
    with pytest.raises(KeyboardInterrupt):
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    monkeypatch.undo()
    finish_writes(tmp_path / "run")  # what the next run, increment or decisions do first
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "run" / "gold.parquet"), before)
    assert len(pd.read_parquet(tmp_path / "run" / "kind_answers")) == 5
    assert len(pd.read_parquet(tmp_path / "run" / "state" / "records")) == len(g.df) and not (tmp_path / "run" / ".full.tmp").exists()


def test_an_increment_refuses_a_changed_pipeline_and_steps_json_says_what_went_in(tmp_path, population):
    import hashlib
    import json
    from er.run import Run
    s, p, g = population
    new = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    Run(p, s).full(tmp_path / "old.parquet", tmp_path / "run")
    entry = json.loads((tmp_path / "run" / "steps.json").read_text(encoding="utf-8"))["runs"][-1]
    assert entry["inputs"][0]["sha256"] == hashlib.sha256((tmp_path / "old.parquet").read_bytes()).hexdigest() and entry["code"] and entry["config"]
    changed = replace(p, fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 1))
    with pytest.raises(InputError, match="changed since the full run"):
        Run(changed, s).increment(tmp_path / "new.parquet", tmp_path / "run")  # the batch would be resolved otherwise
    Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "run")  # the run's own pipeline: it goes on


def test_answers_given_wrong_stop_the_run(tmp_path, population):
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    with pytest.raises(InputError, match="no file matches"):
        Run(p, s, kind_labels=tmp_path / "answres.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    pd.DataFrame({"kind": [1]}).to_parquet(tmp_path / "no_ids.parquet")
    with pytest.raises(InputError, match="needs the columns"):
        Run(p, s, kind_labels=tmp_path / "no_ids.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    (tmp_path / "sheet.parquet").write_text(f"{s.data.unique_id},kind\n0000000001,1\n", encoding="utf-8")  # a sheet saved as CSV: the same door as records
    with pytest.raises(InputError, match="not a Parquet file"):
        Run(p, s, kind_labels=tmp_path / "sheet.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    with pytest.raises(InputError, match="no run in"):
        Run(p, s).increment(tmp_path / "all.parquet", tmp_path / "empty")


def test_the_probe_counts_the_matches_no_key_lists_as_the_truth_does(tmp_path, population):
    from er.cluster import merge
    from er.config import adjust
    from er.report import scored_again
    from er.run import Run
    s, p, g = population
    uid, ent = s.data.unique_id, s.data.entity_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    few = adjust(p, {"drop_keys": [b.name for b in p.fs.blockers if b.name not in ("cif", "person_name", "company_name")]})  # a method that misses
    out = tmp_path / "run"
    probe = next(x for x in Run(few, s).full(tmp_path / "all.parquet", out).steps if x["step"] == "probe")["strata"]
    con, db = connect(s.compute)  # the truth: every true pair scored as the run scores, at its line, that its likely links don't join
    truth = g.truth[[uid, ent]].merge(g.truth[[uid, ent]], on=ent).query(f"{uid}_x < {uid}_y")
    con.register("er_t", truth.rename(columns={f"{uid}_x": l, f"{uid}_y": r})[[l, r]])
    scored_again(con, db, out, uid, "er_t", "er_ts")
    links = " UNION ALL ".join(f"SELECT {l}, {r} FROM read_parquet('{out / x}/*.parquet')" + (" WHERE match_weight >= 8" if x == "proposed" else "")
                               for x in ("matches", "proposed", "rule_kept") if any((out / x).glob("*.parquet")))
    con.execute(f"CREATE TABLE er_one AS SELECT {uid}, {uid} AS cluster_id FROM read_parquet('{out}/gold.parquet')")
    merge(con, db, "er_one", f"({links})", "er_joined", uid)
    missed = con.execute(f"""SELECT s.{l}, s.{r} FROM er_ts s JOIN er_joined a ON a.{uid} = s.{l} JOIN er_joined b ON b.{uid} = s.{r}
        WHERE s.match_weight >= {few.fs.min_match_weight} AND {named_sql(few.fs)} AND a.cluster_id <> b.cluster_id""").fetchall()
    phone = g.df.set_index(uid)[s.columns["phone"][0][0]]
    shared = {(a, b) for a, b in missed if pd.notna(phone[a]) and phone[a] == phone[b]}
    by = {x["stratum"]: x for x in probe}
    assert shared and by["phone"]["drawn"] == 1.0 and by["phone"]["hits"] == by["phone"]["missed"] == len(shared)  # every pair drawn: exactly the truth
    assert {tuple(x[:2]) for x in by["phone"]["examples"]} == shared
    apart = sorted(shared)[0]  # people say one of them is different: no match missed, then
    pd.DataFrame({l: [apart[0]], r: [apart[1]], "decision": ["no_match"]}).to_parquet(tmp_path / "apart.parquet")
    Run(few, s).decide(tmp_path / "apart.parquet", out)
    again = next(x for x in Run(few, s).full(tmp_path / "all.parquet", out, overwrite=True).steps if x["step"] == "probe")["strata"]
    phone_again = next(x for x in again if x["stratum"] == "phone")
    assert phone_again["hits"] == len(shared) - 1 and apart not in {tuple(x[:2]) for x in phone_again["examples"]}
    sampled = next(x for x in Run(replace(few, probe=replace(few.probe, pairs=200)), s).full(tmp_path / "all.parquet", tmp_path / "run2").steps
                   if x["step"] == "probe")["strata"][0]
    assert sampled["drawn"] < 1 and sampled["low"] <= len(shared) <= sampled["high"]  # a share drawn: its interval holds the truth
    full = next(x for x in Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run3").steps if x["step"] == "probe")["strata"]
    assert all(x["hits"] <= by[x["stratum"]]["hits"] for x in full)  # the tuned method's keys miss no more


def test_a_key_for_the_matches_the_probe_found_is_proposed_tried_and_adopted(say, tmp_path, population, capsys):
    import tomllib
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    few = [b.name for b in p.fs.blockers if b.name not in ("cif", "person_name", "company_name")]
    (ws / "method.toml").write_text(f"drop_keys = {json.dumps(few)}\n", encoding="utf-8")  # a method that misses matches

    assert say("resolve", "records", tmp_path / "all.parquet", "--workspace", ws)[0] == 0
    code, d = say("describe", "method", "--workspace", ws)
    adds = [x for x in d["proposals"] if "add_keys" in x["change"]]
    assert code == 0 and adds and adds[0]["adds"]["lists"] > 0  # a key that lists matches the probe found no key lists
    key = adds[0]["change"]["add_keys"][0]
    code, t = say("try", "method", "--add", "+".join(key), "--workspace", ws)
    assert code == 0 and t["method"]["add_keys"] == [key] and sum(t["variant"]["missed"].values()) < sum(t["base"]["missed"].values())
    assert say("try", "method", "--add", "nope", "--workspace", ws)[0] == 2  # a field the pipeline doesn't declare: refused
    assert say("adopt", "method", "--trial", t["trial"], "--workspace", ws)[0] == 0
    assert tomllib.loads((ws / "method.toml").read_text(encoding="utf-8"))["add_keys"] == [key]
    log = json.loads((ws / "steps.json").read_text(encoding="utf-8"))["runs"][-1]["steps"]
    assert sum(x["keys_missed"] for x in next(x for x in log if x["step"] == "probe")["strata"]) == sum(t["variant"]["missed"].values())
    (ws / "method.toml").write_text((ws / "method.toml").read_text(encoding="utf-8") + 'trust = "none"\n', encoding="utf-8")
    code, t = say("try", "method", "--line", 14, "--workspace", ws)  # nothing merges by itself, yet a trial shows what the method does
    assert code == 0 and t["base"]["matched"] > t["variant"]["matched"] > 0
    assert say("reset", "method", "--workspace", ws)[0] == 0
    assert tomllib.loads((ws / "method.toml").read_text(encoding="utf-8")) == {"trust": "none"}  # the method as tuned; the trust line people earned stays
    (ws / "method.toml").write_text('trust = "none\n', encoding="utf-8")  # a method.toml that doesn't read: reset is still the way out
    assert say("reset", "method", "--workspace", ws)[0] == 0 and not (ws / "method.toml").exists()


def test_describe_matching_draws_the_pipeline_with_the_run_s_numbers(tmp_path, population):
    import duckdb
    from er.report import GRAPH_NODES, describe_matching
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    nodes = {n["id"]: n for n in describe_matching(duckdb.connect(), out, p, s)["nodes"]}
    assert list(nodes) == list(GRAPH_NODES)
    kept = pd.read_parquet(out / "rule_kept")["rule"].value_counts().to_dict()
    assert {r["name"]: r["pairs"] for r in nodes["rules"]["rules"] if r["pairs"]} == kept
    step = next(x for x in json.loads((out / "steps.json").read_text(encoding="utf-8"))["runs"][0]["steps"] if x["step"] == "candidates")
    assert {x["name"]: x["pairs"] for x in nodes["candidates"]["generators"]} == {x["name"]: x["pairs"] for x in step["generators"]}
    gold = pd.read_parquet(out / "gold.parquet")
    assert nodes["accept"]["accepted"] == len(pd.read_parquet(out / "matches")) and nodes["customers"]["count"] == gold["cluster_id"].nunique()
    levels = [lv for c in nodes["score"]["comparisons"] for lv in c["levels"] if lv["m"]]
    assert levels and all(math.isclose(lv["bits"], math.log2(lv["m"] / lv["u"])) for lv in levels)  # each level's worth, as fitted
    assert all(c["missing"] + sum(lv["pairs"] for lv in c["levels"]) == nodes["score"]["pairs"] for c in nodes["score"]["comparisons"])  # each pair stops at one step
    for r in nodes["rules"]["rules"]:  # the model's points for each rule's pairs: every pair in one of three ranges
        assert r["scores"] is None or sum(r["scores"].values()) == r["pairs"]
    links = len(pd.read_parquet(out / "matches"))
    assert sum(x["links"] for x in nodes["candidates"]["by_keys"]) == links and nodes["candidates"]["possible"] == len(gold) * (len(gold) - 1) // 2
    sheet = pd.read_parquet(out / "review.parquet")
    people = nodes["people"]
    assert sum(n for _, n in nodes["accept"]["review_bands"]) == people["sheet"] == people["below"] + people["unnamed"] == (sheet["why"] == "decide").sum()
    assert sum(p["pairs"] for p in people["patterns"]) <= people["sheet"]
    group = nodes["group"]
    assert sum(group["joined"].values()) == sum(z["records"] * z["customers"] for z in group["sizes"] if z["records"] > 1)  # who joined each joined record
    assert group["look"]["single_links"]["customers"] <= sum(z["customers"] for z in group["sizes"] if z["records"] >= 3)
    from er.report import describe_key
    for name in [g["name"] for g in nodes["candidates"]["generators"] if g["method"] in ("same value", "sorted neighbours") and g["matched"]][:3]:
        k = describe_key(out, p, s, name)
        assert k["matched"] >= k["only"] and len(k["examples"]) <= 3
        if k["sizes"] is not None:  # equal values: records per value, and one value's records, the link behind it among them
            assert sum(z["records"] * z["values"] for z in k["sizes"] if z["records"] < 10) <= len(gold)
            assert k["group"] is None or set(k["group"]["pair"]) <= {x["id"] for x in k["group"]["records"]} or k["group"]["more"]
        else:  # sorted neighbours: the records around a link, in its order
            assert k["around"] is None or [x["sorted_as"] for x in k["around"]["records"]] == sorted(x["sorted_as"] for x in k["around"]["records"])
    assert all(f["example"] for f in nodes["prepare"]["fields"] if f["filled"])  # a real value for every field the file fills
    bare = {n["id"]: n for n in describe_matching(duckdb.connect(), None, p, s)["nodes"]}  # no run yet: the methods only
    assert bare["records"]["count"] is None and bare["rules"]["rules"][0]["pairs"] is None and bare["score"]["comparisons"][0]["levels"][0]["bits"] is None


def test_scoring_in_slices_gives_the_scores_scoring_all_at_once_gives_and_each_long_step_says_how_far_it_is(tmp_path, population):
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    first = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    told = []
    whole = Run(p, s, model=first.model).full(tmp_path / "all.parquet", tmp_path / "b")
    sliced = Run(p, s, model=first.model, score_pairs=300, chunk_rows=100, told=lambda *a, **k: told.append((*a, k))).full(tmp_path / "all.parquet", tmp_path / "c")
    scores = [r.con.execute(f"SELECT * FROM scores ORDER BY {r.l}, {r.r}").df() for r in (whole, sliced)]
    pd.testing.assert_frame_equal(*scores, rtol=1e-9)  # a pair's score depends on it alone: the same in a slice as in the whole
    counts = {}
    for done, of, unit, _ in told:
        counts.setdefault(unit, []).append((done, of))
    assert {"records", "rules", "keys", "pairs"} <= set(counts)  # load, rules, candidates' joins, scoring: each counts its own work
    for unit, seen in counts.items():  # up to its total, never back
        assert [d for d, _ in seen] == sorted(d for d, _ in seen) and seen[-1][0] == seen[-1][1] == seen[0][1], unit
    assert counts["records"][-1][0] == whole.n and counts["rules"][-1][0] == len(list(p.rules.each())) and len(counts["records"]) > 2  # from 0, a chunk at a time
    weighed = []
    probe = Run(p, s, told=lambda *a, **k: weighed.append((*a, k["more"])))
    probe.n, g = 1000, len(p.fs.blockers)  # the joins weighed by the budget's pairs: a generator whose blocks are all oversized lists none
    probe.plan = pd.DataFrame(dict(kind=["rule", *["generator"] * g], normal=[5, 0, *[10] * (g - 1)], oversized_blocks=[0, 1, *[0] * (g - 1)]))
    for i in range(g + 1):
        probe._joined()(i, g, "keys")
    assert [x[0] for x in weighed] == sorted(x[0] for x in weighed) and weighed[0][0] == 0 and weighed[-1][0] == weighed[-1][1] > 0 and all(x[3] for x in weighed)
    told = [(*x[:3], x[3]["likely"]) for x in told if x[2] == "pairs"]
    total = whole._count("cands")
    assert len(told) == -(-total // 300) > 1 and [x[0] for x in told] == sorted({min(total, 300 * (i + 1)) for i in range(len(told))})
    assert {x[1:3] for x in told} == {(total, "pairs")} and told[-1][3] == whole._count(f"scores s WHERE match_weight >= {bits(p.fs.min_match_weight)} AND {named_sql(p.fs)}")
    assert pd.read_parquet(tmp_path / "b" / "gold.parquet").equals(pd.read_parquet(tmp_path / "c" / "gold.parquet"))
    views = lambda run: run._count("duckdb_views() WHERE NOT internal")
    assert views(sliced) == views(whole)  # each slice's lookups released: memory doesn't grow with the slices


def test_a_full_run_reads_the_records_it_cleaned_again_until_anything_they_rest_on_changes(tmp_path, population):
    from er import folder
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "ws"
    load = lambda run: next(x for x in run.steps if x["step"] == "load")["prepared"]
    rows = lambda run: run.con.execute(f"SELECT * FROM records ORDER BY {run.uid}").df()
    first = Run(p, s).full(tmp_path / "all.parquet", ws)
    gold = pd.read_parquet(ws / "gold.parquet")
    again = Run(p, s).full(tmp_path / "all.parquet", ws, overwrite=True)
    assert (load(first), load(again)) == ("made", "kept")
    pd.testing.assert_frame_equal(rows(first), rows(again))  # as cleaning them again would make them
    pd.testing.assert_frame_equal(gold, pd.read_parquet(ws / "gold.parquet"))
    assert load(Run(p, s).rerun(ws)) == "kept"  # the run's one file, read again in order: the same records
    pd.testing.assert_frame_equal(gold, pd.read_parquet(ws / "gold.parquet"))
    (kept,) = (ws / folder.PREPARED).iterdir()
    (kept / "records.parquet").write_bytes(b"not parquet")  # a copy that can't be read: made again
    assert load(Run(p, s).full(tmp_path / "all.parquet", ws, overwrite=True)) == "made"
    for n in (1, 2):  # other records: other cleaned records, the last two kept
        g.df.iloc[n:].to_parquet(tmp_path / f"less{n}.parquet", index=False)
        assert load(Run(p, s).full(tmp_path / f"less{n}.parquet", ws, overwrite=True)) == "made"
    assert len(list((ws / folder.PREPARED).iterdir())) == folder.KEEP_PREPARED
    assert load(Run(p, s).full(tmp_path / "less1.parquet", ws, overwrite=True)) == "kept"  # read: the last used
    g.df.iloc[3:].to_parquet(tmp_path / "less3.parquet", index=False)
    assert load(Run(p, s).full(tmp_path / "less3.parquet", ws, overwrite=True)) == "made"
    assert load(Run(p, s).full(tmp_path / "less1.parquet", ws, overwrite=True)) == "kept"  # less2's went: used longest ago
    import duckdb
    def full_disk(f):
        raise duckdb.IOException("no space left on device")
    (ws / folder.PREPARED / ".k.2147483646.tmp").mkdir()  # left half written by a run long gone
    folder.keep_prepared(ws, "k", full_disk)  # a copy that can't be written: left out, the run goes on
    assert not [x for x in (ws / folder.PREPARED).iterdir() if x.name.startswith(".") or x.name == "k"]
    from dataclasses import replace
    base = first._prepared_key([], set(), False)
    first.settings = replace(s, compute={"threads": "1"})
    assert first._prepared_key([], set(), False) == base  # the compute limits change no record
    first.settings = replace(s, columns={**s.columns, "phone": (("another_column",),)})
    assert first._prepared_key([], set(), False) != base  # another mapping: cleaned again
    first.settings = replace(s, flag_company=("X",))
    assert first._prepared_key([], set(), False) != base  # another cleaning setting
    first.settings = s
    assert first._prepared_key([], set(), True) == base  # one file read in order: the rows read at once
    first.inputs = [*first.inputs, {**first.inputs[0], "sha256": "0" * 64}]
    assert first._prepared_key([], set(), True) != first._prepared_key([], set(), False)  # files in order: set aside as increments would
    first.labels = pd.DataFrame({first.uid: ["1"], "kind": ["2"]})
    assert first._prepared_key([], set(), False) != base  # people's person/company answers: cleaned again


def test_a_file_s_columns_no_field_reads_never_enter_the_run(tmp_path, population):
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    g.df.assign(NOTE="x" * 50, MEMO="y").to_parquet(tmp_path / "wide.parquet", index=False)  # columns no field is mapped to
    Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    wide = Run(p, s).full(tmp_path / "wide.parquet", tmp_path / "b")
    assert {"NOTE", "MEMO"}.isdisjoint(wide.columns()) and {"NOTE", "MEMO"}.isdisjoint(pd.read_parquet(tmp_path / "b" / "state" / "records").columns)
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "a" / "gold.parquet"), pd.read_parquet(tmp_path / "b" / "gold.parquet"))
