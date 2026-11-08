"""nayose: each command as a user runs it, mistakes in words, the scheduler, the run's reports."""
import json
import math
from pathlib import Path
from dataclasses import replace

import duckdb
import numpy as np
import pandas as pd
import pytest

from er.config import (InputError)
from er.settings import load_settings

from conftest import nayose


def _mapping(tmp_path: Path, s, **fields: str) -> Path:  # the project's mapping with some fields mapped to other columns, as a workspace's columns.toml
    from er.settings import set_columns, own_columns, settings_path
    f = tmp_path / "columns.toml"
    f.write_text(own_columns(settings_path()), encoding="utf-8")
    set_columns(f, {k: [[v]] for k, v in fields.items()})  # each field one column
    return f


def test_a_run_says_what_is_wrong_in_words_people_can_act_on(say, tmp_path, population, capsys, monkeypatch):
    from splink.internals.exceptions import SplinkException

    from er import folder, inbox
    from er.run import Run
    s, p, g = population
    monkeypatch.chdir(tmp_path)

    phone, postal = s.columns["phone"][0][0], [c for alt in s.columns["postal_code"] for c in alt]
    g.df.assign(**{c: None for c in postal}).to_parquet(tmp_path / "nopostal.parquet", index=False)  # mapped, but never filled
    run = Run(p, s).full(tmp_path / "nopostal.parquet", tmp_path / "run")
    assert [x["stratum"] for x in next(x for x in run.steps if x["step"] == "probe")["strata"]] == ["phone"]  # an empty group: nothing to draw
    g.df.head(0).to_parquet(tmp_path / "empty.parquet", index=False)
    with pytest.raises(InputError, match="no record, only its header"):
        Run(p, s).full(tmp_path / "empty.parquet", tmp_path / "run0")
    with pytest.raises(InputError, match="both read"):  # one column for two compared fields: one value counted twice
        Run(p, load_settings(columns=_mapping(tmp_path, s, postal_code=phone))).full(tmp_path / "nopostal.parquet", tmp_path / "run1")
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    for words in (("check", "records", tmp_path / "all.parquet", "--compute", "memory_limit=lots"), ("check", "records", tmp_path / "all.parquet", "--compute", "memroy_limit=8GB"),
                  ("resolve", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w", "--model", tmp_path / "none.json"),
                  ("serve", "inbox", tmp_path / "box", "--workspace", tmp_path / "w", "--settle", "1m")):
        code, e = say(*words)
        assert code == 2 and e["fix"], words  # a mistake people fix: two lines, never a traceback
    def short(*_, **__):  # out of memory inside Splink, which wraps DuckDB's error in its own
        try:
            raise duckdb.OutOfMemoryException("Out of Memory Error: failed to allocate")
        except duckdb.OutOfMemoryException as inner:
            raise SplinkException("Error executing the following sql") from inner
    with monkeypatch.context() as m:
        m.setattr(Run, "full", short)
        code, e = say("resolve", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w")
        assert code == 2 and "out of memory" in e["error"] and "memory_limit" in e["fix"]
    (tmp_path / "w2").mkdir()
    _mapping(tmp_path / "w2", s, postal_code=phone)  # the page's step 2 says what the run would refuse
    assert any("both read" in x for x in say("describe", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w2")[1]["turned_off"])
    (tmp_path / "w3").mkdir()
    _mapping(tmp_path / "w3", s, kind_flag=s.columns["company_name"][0][0])  # a name column in the person/company flag: warned
    slots = say("describe", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w3")[1]["slots"]
    flag = [x["looks_right"] for x in slots if x["feature"].endswith("/Person or company")]
    assert flag and flag[0] < 0.5
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "method.toml").write_text('trust = "none\n', encoding="utf-8")
    code, e = say("describe", "method", "--workspace", tmp_path / "ws")
    assert code == 2 and "not valid TOML" in e["error"]
    (tmp_path / "ws" / "method.toml").write_text('trust = "none"  # 人が確かめる\n', encoding="cp932")
    code, e = say("describe", "method", "--workspace", tmp_path / "ws")
    assert code == 2 and "not UTF-8" in e["error"]
    (tmp_path / "ws" / "method.toml").write_text('trust = "none"\n', encoding="utf-8-sig")  # as Notepad saves it
    assert folder.method(tmp_path / "ws") == {"trust": "none"}
    folder = tmp_path / "csvs"
    folder.mkdir()
    g.df.iloc[:200].to_csv(folder / "a.csv", index=False)
    g.df.iloc[200:].to_csv(folder / "b.tsv", sep="\t", index=False)
    (folder / "__MACOSX").mkdir()
    (folder / "__MACOSX" / "._a.csv").write_bytes(b"\x00\x05\x16\x07 junk")
    (folder / ".a.csv.swp").write_text("x,y\n1,2\n")
    assert say("check", "records", folder)[1]["records"] == len(g.df)  # a folder of CSV and TSV files, read together; hidden ones left alone
    box = tmp_path / "inbox"
    (box / "batches").mkdir(parents=True)
    g.df.iloc[:10].to_csv(box / "batches" / "new.csv", index=False)  # just written: perhaps still being copied in
    said = []
    assert inbox.one_pass(tmp_path / "run", box, 0, [], lambda *a, **k: said.append(a), settle=60) and not said
    assert inbox.one_pass(tmp_path / "run", box, 0, [], lambda *a, **k: said.append(a), settle=0) and said


def test_nayose_prints_a_mistake_as_two_lines_and_exits_with_2(tmp_path):
    done = nayose("check", "records", tmp_path / "none.parquet")
    assert done.returncode == 2 and done.stderr.splitlines()[0].startswith("error: no file matches")
    assert done.stderr.splitlines()[1].startswith("fix: ") and "Traceback" not in done.stderr
    done = nayose("check", "records", tmp_path / "none.parquet", "--format", "json")
    error = json.loads(done.stdout.splitlines()[-1])
    assert done.returncode == 2 and error["event"] == "error" and error["exit"] == 2 and error["fix"]
    assert nayose("resolve", "records", tmp_path / "x.parquet").returncode == 2  # --workspace missing: the parser says so


def test_every_command_has_its_help(capsys):
    from er.cli import COMMANDS, parser
    for c in COMMANDS:
        with pytest.raises(SystemExit) as done:
            parser().parse_args([c.verb, c.noun, "--help"])
        shown = capsys.readouterr().out
        assert done.value.code == 0 and c.help in shown and c.example in shown


def test_nayose_takes_a_file_from_the_check_to_people_s_answers(tmp_path, population, capsys):
    from er.cli import COMMANDS, main
    s, p, g = population
    uid, half = s.data.unique_id, len(g.df) // 2
    g.df.iloc[:half].to_parquet(tmp_path / "first.parquet", index=False)
    g.df.iloc[half:].to_parquet(tmp_path / "new.parquet", index=False)
    run, declared = tmp_path / "run", {c.name: set(c.result) for c in COMMANDS}

    def say(*words: object) -> dict:  # one command, as JSON; its result checked against its declaration
        code = main([*map(str, words), "--format", "json"])
        said = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
        assert code == 0 and said[-1]["event"] == "result", said[-1]
        r = said[-1]
        assert set(r) - {"event", "command"} <= declared[r["command"]] and "next" in r
        return r

    assert say("check", "records", tmp_path / "first.parquet")["records"] == half
    g.df.iloc[:half].drop(columns=["PHONE_NUM_4"]).to_parquet(tmp_path / "no_phone.parquet", index=False)
    off = say("check", "records", tmp_path / "no_phone.parquet")["turned_off"]  # the full check: what a run would turn off
    assert off and say("describe", "records", tmp_path / "no_phone.parquet")["turned_off"] == off  # the same, from the mapping alone
    assert say("resolve", "records", tmp_path / "first.parquet", "--workspace", run)["summary"][0][0] == "records"
    pair = say("list", "pairs", "--workspace", run, "--open")["pairs"][0]
    say("decide", "pair", pair["id_r"], pair["id_l"], "match", "--workspace", run)  # either order
    pending = lambda: {(x["id_l"], x["id_r"]) for x in say("list", "pairs", "--workspace", run, "--pending")["pairs"]}
    assert (pair["id_l"], pair["id_r"]) in pending()  # written in, not applied: still listed
    assert say("apply", "decisions", "--workspace", run)["matches"] == 1
    assert (pair["id_l"], pair["id_r"]) not in pending()
    assert say("apply", "decisions", "--workspace", run)["decisions"] == 0  # given twice: nothing new
    gold = pd.read_parquet(run / "gold.parquet").set_index(uid)
    assert gold.loc[pair["id_l"], "cluster_id"] == gold.loc[pair["id_r"], "cluster_id"]
    record = say("list", "kinds", "--workspace", run, "--open")["kinds"][0]["id"]
    say("answer", "kind", record, "company", "--workspace", run)
    assert record in {x["id"] for x in say("list", "kinds", "--workspace", run, "--pending")["kinds"]}  # written in, not applied: still listed
    assert record not in {x["id"] for x in say("list", "kinds", "--workspace", run, "--open")["kinds"]}
    say("apply", "answers", "--workspace", run)
    kinds = say("list", "kinds", "--workspace", run, "--pending")
    assert kinds["applied"] == 1 and record not in {x["id"] for x in kinds["kinds"]}  # applied: off the sheet a rerun drew, counted
    assert pd.read_parquet(run / "gold.parquet").set_index(uid).loc[record, ["kind", "kind_by"]].tolist() == [2, "people"]
    entity = say("describe", "entity", pair["id_l"], "--workspace", run)
    assert {pair["id_l"], pair["id_r"]} <= {x["id"] for x in entity["records"]} and any(x["by"] == "people: match" for x in entity["links"])
    n = len(entity["records"])
    assert len(entity["pairs"]) == n * (n - 1) // 2 and {(x["id_l"], x["id_r"]) for x in entity["weakest"]} <= {(x["id_l"], x["id_r"]) for x in entity["links"]}
    why = say("explain", "pair", pair["id_r"], pair["id_l"], "--workspace", run)
    assert (why["id_l"], why["id_r"]) == (pair["id_l"], pair["id_r"]) and why["same_customer"] and why["found"]["people"] == "match"
    assert why["pairs_all"] == half * (half - 1) // 2 and abs(why["prior"] - math.log2(why["pairs_same"] / (why["pairs_all"] - why["pairs_same"]))) < 0.05  # the start, in counts
    for c in why["comparisons"]:  # the step Python's scorers pass first is the step Splink's SQL reached
        tests = [x for x in why["tests"] if x["comparison"] == c["comparison"]]
        first = next((x["step"] for x in tests if x["passed"]), None)
        assert c["reached"] == first or (first is None and c["reached"] in ("else", "missing")), (c, tests)
    assert abs(why["weight"] - why["prior"] - why["common"] - sum(c["bits"] for c in why["comparisons"])) < 0.05
    assert all(x["prep"][-1][1:] == [x["a"], x["b"]] for x in why["tests"] if x["prep"])  # each normalizer step shown ends at the value compared
    ids = [x["id"] for x in entity["records"]]
    compared = say("compare", "records", ids[0], *ids[1:], "--workspace", run)  # one record against the rest of its customer
    assert [x["id"] for x in compared["candidates"]] == ids[1:] and compared["records"][0]["id"] == ids[0]
    for k in compared["candidates"]:  # each comparison's step: the one its first passing test sets; the first record's side first
        for c in k["comparisons"]:
            tests = [x for x in k["tests"] if x["comparison"] == c["comparison"]]
            first = next((x["step"] for x in tests if x["passed"]), None)
            assert c["reached"] == first or (first is None and c["reached"] in ("else", "missing")), (c, tests)
        assert all(x["raw"][0] == compared["records"][0][x["field"]] for x in k["tests"] if x["field"] in compared["records"][0])
    patterns = say("list", "patterns", "--workspace", run)
    scored = next(x for x in json.loads((run / "steps.json").read_text())["runs"][0]["steps"] if x["step"] == "score")
    assert patterns["pairs"] == sum(scored["reached"][patterns["fields"][0]].values())
    assert sum(x["merged"] for x in patterns["patterns"]) == len(pd.read_parquet(run / "matches"))  # no decision yet said no
    assert all(x["merged"] + x["wait"] + x["held"] + x["apart"] == x["pairs"] and min(x["wait"], x["held"], x["apart"]) >= 0 and 0 < len(x["examples"]) <= 3 for x in patterns["patterns"])
    sheet = pd.read_parquet(run / "review.parquet")
    assert sum(x["wait"] for x in patterns["patterns"]) == (sheet["why"] == "decide").sum()  # what waits is what the sheet asks
    matched = say("match", "records", tmp_path / "new.parquet", "--workspace", run)
    assert len(matched["records"]) == len(g.df) - half and set(matched["counts"]) <= {"joins an entity", "a new entity"}
    added = say("add", "records", tmp_path / "new.parquet", "--workspace", run)
    assert added["summary"][0][1].startswith(f"{len(g.df):,}")
    assert say("describe", "workspace", run)["records"] == len(g.df)
    graph = say("describe", "matching", "--workspace", run)
    assert {n["id"] for n in graph["nodes"]} >= {"rules", "candidates", "score", "group"} and graph["edges"]


def test_split_entity_splits_only_at_a_link_that_alone_holds_it_and_the_split_stays(say, tmp_path, population, capsys):
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = tmp_path / "run"

    assert say("resolve", "records", tmp_path / "all.parquet", "--workspace", run)[0] == 0
    gold = pd.read_parquet(run / "gold.parquet")
    uid, sizes = s.data.unique_id, gold["cluster_id"].value_counts()
    held = None  # an entity a link alone holds together: two records, their one link
    for cluster in sizes.loc[lambda n: n == 2].index:
        _, e = say("describe", "entity", cluster, "--workspace", run)
        held = held or (e["weakest"] and (cluster, (e["weakest"][0]["id_l"], e["weakest"][0]["id_r"])))
    assert held, "no entity held by a single link"
    other = next(c for c in sizes.loc[lambda n: n == 2].index if c != held[0])  # another, closed into a triangle by people's "same"
    c, d = sorted(gold.loc[gold["cluster_id"] == other, uid])
    x = gold.loc[gold["cluster_id"].map(sizes) == 1, uid].iloc[0]
    pd.DataFrame({f"{uid}_l": sorted([c, x])[:1] + sorted([d, x])[:1], f"{uid}_r": sorted([c, x])[1:] + sorted([d, x])[1:],
                  "decision": ["match", "match"]}).to_parquet(tmp_path / "same.parquet", index=False)
    assert say("apply", "decisions", "--file", tmp_path / "same.parquet", "--workspace", run)[0] == 0
    code, refused = say("split", "entity", other, "--between", c, d, "--workspace", run)
    assert code != 0 and "other links still join them" in refused["error"]  # x still joins them: it would split nothing
    code, refused = say("split", "entity", held[0], "--between", held[1][0], "not-a-record", "--workspace", run)
    assert code != 0 and "not both records of the entity" in refused["error"]
    cluster, (a, b) = held
    code, _ = say("split", "entity", cluster, "--between", a, b, "--workspace", run)
    after = pd.read_parquet(run / "gold.parquet").set_index(s.data.unique_id)["cluster_id"]
    assert code == 0 and after[a] != after[b]  # split where that link held it
    assert say("rerun", "records", "--workspace", run)[0] == 0  # and it stays split: people's "different" is kept
    again = pd.read_parquet(run / "gold.parquet").set_index(s.data.unique_id)["cluster_id"]
    assert again[a] != again[b]


def test_a_nearly_empty_field_is_kept_and_the_fit_skips_what_it_cannot_learn_from(tmp_path, population):
    from er.run import Run
    s, p, g = population
    sparse = g.df.copy()
    sparse.loc[sparse.index[10:], ["STD_ADDRESS", "ORIGINAL_ADDRESS"]] = None  # no two records share an address
    sparse.to_parquet(tmp_path / "sparse.parquet", index=False)
    seen = []
    run = Run(p, s, echo=seen.append).full(tmp_path / "sparse.parquet", tmp_path / "run")
    assert [x["step"] for x in seen] == ["load", "budget", "fit", "rules", "candidates", "score", "cluster", "probe", "write"]  # step by step
    assert "address" in run.model["er"]["skipped"] and any("sharing address" in x for x in run.notes)
    sparse.assign(PHONE_NUM_4=None).to_parquet(tmp_path / "bare.parquet", index=False)  # nothing left to learn from
    with pytest.raises(InputError, match="can't be estimated|share phone or address"):  # whichever check finds nothing first
        Run(p, s).full(tmp_path / "bare.parquet", tmp_path / "bare")


def test_an_increment_keeps_the_open_review_queue(tmp_path, population):
    from er.report import qa
    from er.run import Run
    s, p, g = population
    p = replace(p, threshold=replace(p.threshold, margin_steps=4), fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 6))  # a wide band
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    new = np.random.default_rng(2).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    fields = [f for f in s.columns if f not in ("id", "entity")]
    run = Run(p, s).full(tmp_path / "old.parquet", tmp_path / "c")
    first = qa(run, fields)["review_sheet"]
    first.to_parquet(tmp_path / "c" / "review.parquet")
    open_ = first[first["why"] == "decide"]
    assert len(open_) >= 2
    first.loc[open_.index[:1], "decision"] = "no_match"  # one decided and given back; the rest still open
    first.loc[open_.index[:1]].to_parquet(tmp_path / "given.parquet")
    Run(p, s).decide(tmp_path / "given.parquet", tmp_path / "c")
    inc = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c")
    sheet = qa(inc, fields, previous=tmp_path / "c" / "review.parquet")["review_sheet"]
    pairs = set(map(tuple, sheet.loc[sheet["why"] == "decide", [l, r]].to_numpy()))
    gold = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    still = {(a, b) for a, b in open_.iloc[1:][[l, r]].to_numpy() if gold[a] != gold[b]}
    assert still and still <= pairs  # still open after the increment
    assert tuple(open_.iloc[0][[l, r]]) not in pairs  # decided: gone


def test_a_run_folder_takes_one_writer_at_a_time(tmp_path, population):
    import threading
    from er.folder import run_lock
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    held, done = threading.Event(), threading.Event()

    def other_job():  # another job holds the folder, in a thread of its own
        with run_lock(tmp_path / "run"):
            held.set()
            done.wait(30)
    job = threading.Thread(target=other_job)
    job.start()
    assert held.wait(30)
    with pytest.raises(InputError, match="another job is writing"):
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")
    done.set()
    job.join(30)
    with run_lock(tmp_path / "run"), run_lock(tmp_path / "run"):  # the thread holding it may take it again (a rerun's full run)
        Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")  # released by the other: free again


def test_matching_a_batch_names_the_entities_adding_it_would_give_and_writes_nothing(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid, half = s.data.unique_id, len(g.df) // 2
    g.df.iloc[:half].to_parquet(tmp_path / "first.parquet", index=False)
    pd.concat([g.df.iloc[half:], g.df.iloc[:1]]).to_parquet(tmp_path / "batch.parquet", index=False)  # one already in the run
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "first.parquet", out)
    files = lambda: {f: f.read_bytes() for f in out.rglob("*") if f.is_file() and f.name != ".lock"}
    before = files()
    m = Run(p, s).match(tmp_path / "batch.parquet", out)
    assert files() == before
    assert m.loc[m[uid] == g.df.iloc[0][uid], "status"].item() == "already in the run"
    assert set(m["status"]) == {"joins an entity", "a new entity", "already in the run"} and len(m) == len(g.df) - half + 1
    Run(p, s).increment(tmp_path / "batch.parquet", out)
    gold = pd.read_parquet(out / "gold.parquet").set_index(uid)["cluster_id"]
    assert (gold.loc[m[uid]].to_numpy() == m["entity"].to_numpy()).all()  # the entities the increment then gave


def test_a_rerun_reads_the_run_s_files_in_order_and_keeps_what_the_increments_kept(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid, n = s.data.unique_id, len(g.df)
    other = next(c for c in g.df.columns if c != uid)
    resent = g.df.iloc[:1].assign(**{other: "changed"})  # an ID of the run, sent again with other content
    for i, part in enumerate([g.df.iloc[:n // 2], g.df.iloc[n // 2:3 * n // 4], pd.concat([g.df.iloc[3 * n // 4:], resent])]):
        part.to_parquet(tmp_path / f"{i}.parquet", index=False)
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "0.parquet", out)
    for i in (1, 2):
        Run(p, s).increment(tmp_path / f"{i}.parquet", out)
    added = pd.read_parquet(out / "gold.parquet")
    Run(p, s).rerun(out)
    again = pd.read_parquet(out / "gold.parquet")
    Run(p, s).full([tmp_path / f"{i}.parquet" for i in range(3)], tmp_path / "fresh")
    assert again.equals(pd.read_parquet(tmp_path / "fresh" / "gold.parquet"))  # a full run on the same files, in order
    assert sorted(again[uid]) == sorted(added[uid])
    aside = pd.read_parquet(out / "set_aside")
    assert aside.loc[aside[uid] == resent[uid].item(), "reason"].tolist() == ["already in the run"]
    (tmp_path / "1.parquet").unlink()
    with pytest.raises(InputError, match="1.parquet: gone since the run read it"):
        Run(p, s).rerun(out)


def test_one_answer_is_typed_into_the_sheet_and_waits_for_a_busy_folder(tmp_path, population):
    import threading
    from er.folder import Busy, run_lock, type_in
    from er.run import Run
    s, p, g = population
    l, r = f"{s.data.unique_id}_l", f"{s.data.unique_id}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out = tmp_path / "run"
    Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    a, b = pd.read_parquet(out / "review.parquet").iloc[0][[l, r]]
    type_in(out, "review.parquet", "decision", "match", **{l: a, r: b})
    sheet = pd.read_parquet(out / "review.parquet")
    assert sheet.iloc[0]["decision"] == "match" and sheet["decision"].iloc[1:].isna().all()
    type_in(out, "review.parquet", "decision", None, **{l: a, r: b})
    assert pd.read_parquet(out / "review.parquet")["decision"].isna().all()
    with pytest.raises(InputError, match="no row for"):
        type_in(out, "review.parquet", "decision", "match", **{l: b, r: "nobody"})
    held, done = threading.Event(), threading.Event()

    def other_job():  # a run writing to the folder, in a thread of its own
        with run_lock(out):
            held.set()
            done.wait(30)
    job = threading.Thread(target=other_job)
    job.start()
    assert held.wait(30)
    with pytest.raises(Busy):
        type_in(out, "review.parquet", "decision", "match", **{l: a, r: b})
    done.set()
    job.join(30)


def test_set_columns_rewrites_the_fields_lines_and_keeps_the_rest(tmp_path):
    import shutil
    from er.settings import set_columns
    root = load_settings().root
    (tmp_path / "config").mkdir()
    (tmp_path / "pyproject.toml").touch()
    f = tmp_path / "config" / "settings.toml"
    shutil.copy(root / "config" / "settings.toml", f)
    before = f.read_text(encoding="utf-8")
    set_columns(f, {"phone": (("TEL4",),), "person_name": (("NAME",), ("SEI", "MEI")), "town_code": (("TOWN",),), "birth_date": ()})
    s = load_settings(f)
    assert s.columns["phone"] == (("TEL4",),) and s.columns["person_name"] == (("NAME",), ("SEI", "MEI")) and s.columns["birth_date"] == ()  # no column, still declared
    after = f.read_text(encoding="utf-8")
    line = lambda name: next(x for x in after.split("\n[columns]\n", 1)[1].splitlines() if x.startswith(f"{name} ="))
    assert 'normalize = ["nfkc", "strip_spaces"]' in line("person_name") and "# municipality + town + chome" in line("town_code")  # options, comments stay
    assert len(after.splitlines()) == len(before.splitlines()) and line("birth_date").startswith("birth_date = []") and "#" in line("birth_date")
    with pytest.raises(InputError, match="id must name one column"):
        set_columns(f, {"id": (("A",), ("B",))})
    assert f.read_text(encoding="utf-8") == after and not (tmp_path / "config" / "settings.toml.tmp").exists()


def test_describe_says_what_a_run_folder_holds_and_what_joined_an_entity(tmp_path, population):
    from er.report import describe_entity, describe_workspace
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out = tmp_path / "run"
    run = Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    gold = pd.read_parquet(out / "gold.parquet")
    d = describe_workspace(run.con, out, uid)
    assert (d["records"], d["entities"]) == (len(gold), gold["cluster_id"].nunique()) and d["runs"][0]["what"] == "full run"
    assert d["pairs"]["decide"] + d["pairs"]["audit"] == len(pd.read_parquet(out / "review.parquet")) and not d["write_owed"]
    assert d["summary"][0][0] == "records"
    big = d["largest"][0]
    e = describe_entity(run.con, out, uid, big["entity"], run.fields)
    assert len(e["records"]) == big["records"] and len(e["links"]) >= big["records"] - 1  # a cluster is joined by its links
    last = e["records"][uid].max()  # an entity past the cap: its first records, the one asked for among them, and its size
    few = describe_entity(run.con, out, uid, last, run.fields, most=1)
    assert big["records"] > 1 and few["records"][uid].tolist() == [last] and few["size"] == big["records"]
    assert set(e["links"]["by"]) <= {*(r.name for _, _, r in p.rules.each()), "fs"} and e["size"] == big["records"]
    with pytest.raises(InputError, match="no record of the run"):
        describe_entity(run.con, out, uid, "nobody", run.fields)


def test_a_sheet_given_back_with_no_answer_or_a_kind_in_words_is_refused(tmp_path):
    import duckdb
    from er.source import answers, decisions
    pd.DataFrame({"uid_l": ["1"], "uid_r": ["2"], "decision": [None]}, dtype="string").to_parquet(tmp_path / "untouched.parquet")
    with pytest.raises(InputError, match="no row has a decision"):
        decisions(tmp_path / "untouched.parquet", duckdb.connect(), "uid_l", "uid_r", into="d")
    for kinds, error in ([None, None], "no row is answered"), (["2 company", None], r"a kind is 1, 2 or 0, not \['2 company'\]"):
        pd.DataFrame({"uid": ["1", "2"], "kind": kinds}, dtype="string").to_parquet(tmp_path / "kinds.parquet")
        with pytest.raises(InputError, match=error):
            answers(tmp_path / "kinds.parquet", duckdb.connect(), "uid")
    pd.DataFrame({"uid": ["1", "2"], "kind": ["2.0", None]}, dtype="string").to_parquet(tmp_path / "kinds.parquet")
    assert len(answers(tmp_path / "kinds.parquet", duckdb.connect(), "uid")) == 1  # a spreadsheet's 2.0 is 2


def test_a_run_and_its_reports_land_together_even_when_the_write_is_cut_short(tmp_path, population, monkeypatch):
    import er.folder
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out, real = tmp_path / "run", er.folder.finish_writes

    def killed(folder):  # the process dies once the moves owed are saved, before it does them
        if (folder / "pending.json").exists():
            raise SystemExit("killed")
        real(folder)
    monkeypatch.setattr(er.folder, "finish_writes", killed)
    with pytest.raises(SystemExit):
        Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    monkeypatch.setattr(er.folder, "finish_writes", real)
    again = Run(p, s).increment(tmp_path / "all.parquet", out)  # the retry: the next job finishes the moves, and finds nothing new
    assert again.added == 0 and (out / "gold.parquet").exists()
    assert {"qa.md", "report.txt", "review.parquet", "kind_review.parquet"} <= {f.name for f in out.iterdir()} and not list(out.rglob("*.tmp"))


def test_the_scheduler_serves_the_inbox_in_order_and_parks_what_people_must_fix(tmp_path, population):
    import os
    import shutil
    import sys
    from er import inbox as schedule
    s, p, g = population
    uid = s.data.unique_id
    made = []
    code, _, _, tries = schedule.attempt(lambda: made.append(1) or [sys.executable, "-c", "import sys; sys.exit(1)"], retries=2, wait=0)
    assert (code, tries, len(made)) == (1, 3, 3)  # an unexpected failure is tried again, its command made again: the folder may hold the run now

    inbox, run = tmp_path / "inbox", tmp_path / "run"
    (inbox / "batches").mkdir(parents=True)
    new = np.random.default_rng(3).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(inbox / "batches" / "a_first.parquet", index=False)
    g.df[new].to_parquet(inbox / "batches" / "b_new.parquet", index=False)
    shutil.copy(inbox / "batches" / "b_new.parquet", inbox / "batches" / "c_again.parquet")  # the same content, twice
    (inbox / "batches" / "d_bad.parquet").write_text("CONT_ID\n1\n")  # a CSV, named as Parquet: read as it comes, and short of fields
    for k, f in enumerate(sorted((inbox / "batches").iterdir())):
        os.utime(f, (1_000 + k, 1_000 + k))  # arrival order
    serve = lambda: nayose("serve", "inbox", inbox, "--workspace", run, "--settle", "0")  # files written just now: taken at once
    done = serve()
    assert done.returncode == 0, done.stderr
    jobs = [(e["file"], e["outcome"]) for e in schedule.ledger(run)]
    assert jobs == [("a_first.parquet", "done"), ("b_new.parquet", "done"), ("c_again.parquet", "done"), ("d_bad.parquet", "failed")]
    assert len(pd.read_parquet(run / "gold.parquet")) == len(g.df)  # the first batch the full run, the second an increment
    parked = list((inbox / "failed" / "batches").glob("*.error.txt"))
    assert len(parked) == 1 and "holds none of these fields" in parked[0].read_text()
    assert not list((inbox / "batches").glob("*.parquet"))

    sheet = pd.read_parquet(run / "review.parquet")
    (inbox / "decisions").mkdir(exist_ok=True)
    sheet.iloc[:1].assign(decision="match").to_parquet(inbox / "decisions" / "reviewed.parquet")
    assert serve().returncode == 0 and schedule.ledger(run)[-1]["outcome"] == "done"
    assert (run / "decisions").exists()
    from er.folder import inputs
    assert [f.parents[1].name for f in inputs(run)] == ["0001-a_first", "0002-b_new"]  # copied into the workspace and read there (part/read/): found there, wherever the batch went
    before = len(schedule.ledger(run))
    assert serve().returncode == 0 and len(schedule.ledger(run)) == before  # nothing waiting: nothing done

    from er.folder import run_lock
    g.df[~new].head(10).to_parquet(inbox / "batches" / "e_busy.parquet", index=False)  # records the run holds: nothing new
    with run_lock(run):  # someone runs nayose on the folder by hand
        busy = nayose("serve", "inbox", inbox, "--workspace", run, "--retries", "0", "--settle", "0")
    assert busy.returncode != 0 and (schedule.ledger(run)[-1]["outcome"], schedule.ledger(run)[-1]["exit"]) == ("stopped", 75)
    assert (inbox / "batches" / "e_busy.parquet").exists()  # it waits in the inbox, not parked in failed/
    assert serve().returncode == 0 and schedule.ledger(run)[-1]["outcome"] == "done"

    sheet.assign(decision=pd.NA).to_parquet(inbox / "decisions" / "untouched.parquet")  # given back as it was sent
    answers = pd.DataFrame({uid: g.df[uid].head(3), "kind": ["1", "1", "2"]})
    answers.to_parquet(inbox / "answers" / "three.parquet")
    for k, f in enumerate(("untouched", "three")):
        os.utime(next(inbox.rglob(f"{f}.parquet")), (2_000 + k, 2_000 + k))  # arrival order
    assert serve().returncode == 0
    assert [(e["file"], e["outcome"]) for e in schedule.ledger(run)[-2:]] == [("untouched.parquet", "failed"), ("three.parquet", "done")]
    assert "no row has a decision" in next((inbox / "failed" / "decisions").glob("*untouched.parquet.error.txt")).read_text()
    gold = pd.read_parquet(run / "gold.parquet").set_index(uid)
    assert (gold.loc[answers[uid], "kind_by"] == "people").all()  # the answers went in by a rerun


def test_an_oversized_block_is_checked_on_a_sample_and_a_placeholder_is_skipped(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    dummy = df.index[:100]
    df.loc[dummy, ["PHONE_NUM_4", "ADDRESS_ONE"]] = ["0000", "東京都"]  # a dummy phone on 100 records: one block of 100
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")  # no stop
    block = run.gated[run.gated["value"].str.contains("0000") & (run.gated["generator"] == "phone_prefecture")]
    assert len(block) == 1 and block["decision"].iloc[0].startswith("skipped") and block["records"].iloc[0] == 100
    assert any("0000" in x and "skipped" in x for x in run.examples) and not any("0000" in x for x in run.notes)
    check = nayose("check", "records", tmp_path / "in.parquet")
    assert check.returncode == 0 and "checked by sampling" in check.stdout

    same = pd.concat([g.df.iloc[[0]]] * 70, ignore_index=True)  # 70 copies of one record: every key's block oversized
    same[uid] = [f"copy{i:03d}" for i in range(70)]
    pd.concat([g.df, same]).to_parquet(tmp_path / "copies.parquet", index=False)
    run = Run(p, s).full(tmp_path / "copies.parquet", tmp_path / "copies")
    gold = pd.read_parquet(tmp_path / "copies" / "gold.parquet").set_index(uid)
    assert gold.loc[same[uid], "cluster_id"].nunique() == 1  # the sample shows they match: kept and joined
    assert (run.gated["decision"] == "kept").any()


def test_a_rule_never_trusts_a_value_held_by_an_oversized_block(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    many = df.index[:70]
    df.loc[many, ["CIF_ID", "FULL_NAME_KANA"]] = ["9999999999999", "ヤマダタロウ"]  # one customer ID and name on 70 records
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    kept = pd.read_parquet(tmp_path / "run" / "rule_kept")
    ids = set(df.loc[many, uid])
    by_x1 = kept[(kept["rule"] == "X1_CIF_PERSON_NAME") & kept[f"{uid}_l"].isin(ids) & kept[f"{uid}_r"].isin(ids)]
    assert by_x1.empty and any("X1_CIF_PERSON_NAME doesn't trust" in x for x in run.notes)


def test_the_run_report_holds_no_record_value(tmp_path, population):
    import re
    from er.report import qa, report_text
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    df.loc[df.index[:100], ["PHONE_NUM_4", "ADDRESS_ONE"]] = ["0000", "東京都"]  # placeholders: notes that quote a value
    df.loc[df.index[100:170], ["CIF_ID", "FULL_NAME_KANA"]] = ["9999999999999", "ヤマダタロウ"]
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    tables = qa(run, [f for f in s.columns if f not in ("id", "entity")])
    text = report_text(run, tables, s.root / "config" / "final.toml")
    assert any("9999999999999" in x for x in run.examples) and any("0000" in x for x in run.examples)
    assert not re.search(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]", text)  # no kana or kanji: no name, address or town
    assert not any(v in text for c in (uid, "CIF_ID") for v in df[c].dropna())  # no record ID, no customer ID
    expected = (1 - pd.read_parquet(tmp_path / "run" / "matches")["match_probability"]).sum()
    assert next(x for x in run.steps if x["step"] == "cluster")["expected_false"] == round(expected, 2)
    assert f"about {expected:,.{1 if expected >= 1 else 2}f} of them false" in text and "MODEL" in text and "birth_date" in text


def test_the_runaway_guard_stops_only_what_would_not_fit(tmp_path, population, monkeypatch):
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    monkeypatch.setattr(Run, "capacity", lambda self: 10)
    with pytest.raises(InputError, match="more than fit in memory"):
        Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")


def test_the_generator_makes_direct_matches_rare_and_reports_how_hard_it_is():
    from er.generate import check, generate, halfwidth, load_reference, load_spec, profile
    import unicodedata
    s = load_settings()
    spec = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=8_000)
    g = generate(spec, *load_reference(s.paths["reference"]))
    check(spec, g)  # CONT_ID unique, digits, fill rates
    hard = profile(g)
    assert 0.004 <= hard["direct (exact rules)"] <= 0.02  # calibrated to about 1% on the full population
    assert hard["same customer ID"] < 0.05 and 0.05 < hard["nothing in common"] < 0.2
    assert halfwidth("ガッコウ") == "ｶﾞｯｺｳ" and unicodedata.normalize("NFKC", halfwidth("ガッコウ")) == "ガッコウ"


def test_test_is_counted_once_per_population(tmp_path):
    from er.io import append_leaderboard, test_evaluations
    data = replace(load_settings().data, labels_dir=tmp_path / "labels", experiments_dir=tmp_path / "experiments")
    data.labels_dir.mkdir()
    uid, ent = data.unique_id, data.entity_id
    labels = lambda ids: pd.DataFrame({uid: ids, ent: ["E"] * len(ids)}).to_parquet(data.labels_dir / "test.parquet", index=False)
    labels(["1", "2"])
    append_leaderboard(data, "fs:FINAL", ("config", 1), "test", {})
    labels(["3", "4"])  # a newly generated population: a test nobody has seen
    append_leaderboard(data, "fs:FINAL", ("config", 2), "test", {})
    assert test_evaluations(data)["configs_on_test"].max() == 1
    append_leaderboard(data, "fs:FINAL", ("config", 3), "test", {})  # the same population, a second configuration
    assert test_evaluations(data)["configs_on_test"].max() == 2
    (data.labels_dir / "test.parquet").unlink()  # a development round of choose.py: train and val only, test never read
    dev = replace(data, datasets=("train", "val"))
    append_leaderboard(dev, "fs:x", ("config", 4), "val", {})
    assert test_evaluations(dev).empty


def test_check_records_says_whether_a_run_will_go_through_and_what_to_look_at_first(say, tmp_path, population, monkeypatch):
    from er.run import Run
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    code, r = say("check", "records", tmp_path / "all.parquet")
    c = r["capacity"]
    assert code == 0 and r["ready"]["ok"] and not r["ready"]["stops"] and c["pairs_needed"] > 0 and c["pairs_fit"] >= c["pairs_needed"]
    assert c["headroom"] == round(c["pairs_fit"] / c["pairs_needed"], 1) and c["memory_limit_gb"] > 0 and c["spill_folder"]
    assert any(w["what"].startswith("birth_date is") for w in r["ready"]["warns"])  # a nearly empty field, said with what to do
    assert not any("company_name" in w["what"] for w in r["ready"]["warns"])  # filled only for companies, by design: with the person's name, it is full
    needed = c["pairs_needed"]
    monkeypatch.setattr(Run, "capacity", lambda self: 10)  # room for 10 pairs: the file's won't fit
    code, r = say("check", "records", tmp_path / "all.parquet")
    assert code == 0 and not r["ready"]["ok"] and "more than fit in memory" in r["ready"]["stops"][0]["what"] and r["ready"]["stops"][0]["fix"]
    monkeypatch.setattr(Run, "capacity", lambda self: int(needed / 1.04))  # its headroom rounds to 1.0, yet the run would stop
    code, r = say("check", "records", tmp_path / "all.parquet")
    assert r["capacity"]["headroom"] == 1.0 and not r["ready"]["ok"]
    monkeypatch.setattr(Run, "capacity", lambda self: int(needed * 1.5))
    code, r = say("check", "records", tmp_path / "all.parquet")
    assert r["ready"]["ok"] and any(w["what"] == "the pairs fill 67% of the room DuckDB has" for w in r["ready"]["warns"])


def test_describe_review_counts_what_people_must_check_range_by_range(say, tmp_path, population, monkeypatch):
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    assert say("create", "workspace", "w")[0] == 0  # strict: nothing merges by points
    assert say("resolve", "records", "all.parquet", "--workspace", "workspaces/w")[0] == 0
    trust = say("describe", "workspace", "workspaces/w")[1]["trust"]
    code, r = say("describe", "review", "--workspace", "workspaces/w", "--seconds", "20")
    top = r["ranges"][0]
    assert code == 0 and (top["down_to"], top["up_to"]) == (20.0, None) and top["pairs"] == trust["pairs"]  # the range people check first, as the trust line counts it
    assert [x["down_to"] for x in r["ranges"]] == sorted(p.trust.steps, reverse=True)
    assert all(x["sample"] == min(p.trust.checks, x["pairs"]) and x["reviews_left"] == x["sample"] for x in r["ranges"])  # none decided yet
    assert [x["reviews_to_here"] for x in r["ranges"]] == list(np.cumsum([x["reviews_left"] for x in r["ranges"]]))
    assert all(x["bound"] is None or x["bound"] == round(1 - 0.05 ** (1 / x["sample"]), 4) for x in r["ranges"])  # what a clean sample proves
    assert r["hours"]["to_each_line"][-1] == round(r["ranges"][-1]["reviews_to_here"] * 20 / 3600, 1) and r["kinds"]["measure"] > 0
    assert say("describe", "review", "--workspace", "workspaces/w", "--seconds", "fast")[0] == 2  # not a number: said, not a traceback
    assert say("describe", "review", "--workspace", "workspaces/w", "--seconds", "inf")[0] == 2 and say("describe", "review", "--workspace", "workspaces/w", "--seconds", "0")[0] == 2

    ws, uid = tmp_path / "workspaces" / "w", s.data.unique_id
    l, r_ = f"{uid}_l", f"{uid}_r"
    pairs = pd.concat([pd.read_parquet(ws / x)[[l, r_, "match_weight"]] for x in ("matches", "proposed", "rule_kept") if any((ws / x).glob("*.parquet"))])
    sheet = pd.read_parquet(ws / "review.parquet")
    paired = set(pairs[l]) | set(pairs[r_])
    alone = sorted(set(pd.read_parquet(ws / "gold.parquet")[uid]) - paired)[:2]  # two records no method paired: a pair with no name compared, planted
    sheet = pd.concat([sheet, pd.DataFrame({l: [alone[0]], r_: [alone[1]], "why": ["decide"]})]).astype({l: "string", r_: "string"})
    sheet.to_parquet(ws / "review.parquet", index=False)
    unnamed = sheet[(sheet["why"] == "decide") & ~sheet.set_index([l, r_]).index.isin(pairs.set_index([l, r_]).index)]
    assert len(unnamed) == say("describe", "review", "--workspace", "workspaces/w")[1]["unnamed"] > 0
    r = say("describe", "review", "--workspace", "workspaces/w")[1]
    first = next(i for i, x in enumerate(r["ranges"]) if x["pairs"])  # the highest range with pairs: one of them people say is different
    lo, hi = r["ranges"][first]["down_to"], r["ranges"][first]["up_to"] or math.inf
    false = pairs[(pairs["match_weight"] >= lo) & (pairs["match_weight"] < hi)].head(1)
    pd.concat([false[[l, r_]].assign(decision="no_match"), unnamed[[l, r_]].head(1).assign(decision="match")]).to_parquet(tmp_path / "decided.parquet")
    assert say("apply", "decisions", "--file", "decided.parquet", "--workspace", "workspaces/w")[0] == 0
    code, after = say("describe", "review", "--workspace", "workspaces/w")
    top = after["ranges"][first]
    assert code == 0 and (top["checked"], top["different"], top["chance_clean"]) == (1, 1, None) and after["unnamed"] == r["unnamed"] - 1  # a decided pair waits no more
    assert all(x["reviews_left"] == x["pairs"] - x["checked"] for x in after["ranges"])  # the line never passes a range found false: all of it, and below
    (ws / "method.toml").unlink()
    assert say("describe", "review", "--workspace", "workspaces/w")[0] == 2  # no trust line: it merges as tuned, said
