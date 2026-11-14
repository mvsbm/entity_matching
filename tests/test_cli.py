"""nayose: each command as a user runs it, mistakes in words, the scheduler, the run's reports."""
import json
import math
import re
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
    (folder / ".a.csv.swp").write_text("x,y\n1,2\n", encoding="utf-8")
    assert say("check", "records", folder)[1]["records"] == len(g.df)  # a folder of CSV and TSV files, read together; hidden ones left alone
    box = tmp_path / "inbox"
    (box / "batches").mkdir(parents=True)
    g.df.iloc[:10].to_csv(box / "batches" / "new.csv", index=False)  # just written: perhaps still being copied in
    (box / "batches" / "._new.csv").write_bytes(b"\x00\x05\x16\x07 junk")  # macOS's copy of a file's attributes, beside it on a shared disk
    said = []
    assert inbox.one_pass(tmp_path / "run", box, 0, [], lambda *a, **k: said.append(a), settle=60) and not said
    assert inbox.one_pass(tmp_path / "run", box, 0, [], lambda *a, **k: said.append(a), settle=0) and said
    assert [x[0].split(":")[0] for x in said] == ["batches/new.csv"] and (box / "batches" / "._new.csv").exists()  # a hidden file is no batch


def test_nayose_prints_a_mistake_as_two_lines_and_exits_with_2(tmp_path):
    done = nayose("check", "records", tmp_path / "none.parquet")
    assert done.returncode == 2 and done.stderr.splitlines()[0].startswith("✗ no file matches")
    assert done.stderr.splitlines()[1].lstrip().startswith("fix: ") and "Traceback" not in done.stderr
    done = nayose("check", "records", tmp_path / "none.parquet", "--format", "json")
    error = json.loads(done.stdout.splitlines()[-1])
    assert done.returncode == 2 and error["event"] == "error" and error["exit"] == 2 and error["fix"]
    assert nayose("resolve", "records", tmp_path / "x.parquet").returncode == 2  # --workspace missing: the parser says so


def test_a_number_given_is_a_finite_one_and_a_mistyped_workspace_is_refused_unmade(say, tmp_path):
    assert say("create", "workspace", "w", "--home", tmp_path)[0] == 0
    for words in (("draw", "pairs", "--count", "inf"), ("draw", "pairs", "--count", "nan"), ("try", "method", "--line", "nan"), ("describe", "results", "--from=-inf"), ("list", "scored", "--page", "²")):
        code, e = say(*words, "--workspace", tmp_path / "w")
        assert code == 2 and ("not a number" in e["error"] or "a whole number" in e["error"]), words
    for words in (("set", "fit", "--records", "2000", "--em", "rules"), ("decide", "pair", "a", "b", "match"), ("answer", "kind", "a", "company")):
        assert say(*words, "--workspace", tmp_path / "typo")[0] == 2 and not (tmp_path / "typo").exists(), words  # a workspace mistyped: refused, no folder made


def test_a_long_command_shows_each_step_as_it_ends_and_how_long_is_left(monkeypatch):
    import io
    from er import emit
    clock = [100.0]
    monkeypatch.setattr(emit.time, "monotonic", lambda: clock[0])
    out = io.StringIO()  # not a terminal: a line every 30 seconds, never redrawn
    e = emit.Emit(out=out, title="resolve records · workspaces/w", order=("load", "score", "write"), last={"load": 10, "score": 100, "write": 5}, last_records=1000)
    e.step(dict(step="load", seconds=12.0, records=2000, set_aside=0))
    for gap, done in ((10, 100), (10, 200), (25, 450)):  # 10 pairs a second since the first count; the last 45 s into the step
        clock[0] += gap
        e.progress(done, 1000, "pairs")
    e.step(dict(step="score", seconds=45.0, pairs=1000))
    e.close()
    lines = out.getvalue().splitlines()
    assert lines[0] == "resolve records · workspaces/w" and lines[1].split() == ["✓", "load", "12s", "2,000", "records"]  # no zero said
    assert lines[2].split(None, 3)[1:3] == ["score", "45s"] and lines[2].endswith(
        "scoring the pairs · 450 of 1,000 pairs · about 55s left · about 1m 05s left in all")  # its own pace; write as last run's, at twice the records
    assert lines[3].split() == ["✓", "score", "45s", "pairs", "1,000"] and len(lines) == 4 and "\r" not in out.getvalue()
    out = io.StringIO()
    e = emit.Emit(out=out, title="resolve records", order=emit.RUN_ORDER)  # a first run: nothing to measure the rest by
    e.step(dict(step="load", seconds=1.0, records=10))
    clock[0] += 31
    e.progress(5, 10, "pairs")
    assert out.getvalue().splitlines()[-1].endswith("planning the work · 5 of 10 pairs")  # one count gives no pace: no time left said
    out = io.StringIO()
    e = emit.Emit(out=out, order=("load", "probe"))  # try method: the steps twice
    for step in ("load", "probe", "generate"):  # and one outside them
        e.step(dict(step=step, seconds=1.0))
    clock[0] += 31
    e.progress(5, 10, "records")
    assert out.getvalue().splitlines()[-1].split()[1:4] == ["load", "0.0s", "reading"]  # a count after the last step: the steps again
    e = emit.Emit(out=out, order=())  # a command whose steps aren't known: each as it ends, and what is under way unnamed
    e.step(dict(step="generate", seconds=1.0))
    clock[0] += 31
    e.progress(5, 10, "rows")
    assert out.getvalue().splitlines()[-1].endswith("working · 5 of 10 rows")
    assert emit.step_facts(dict(step="rules", seconds=1.0, kept=23)) == "kept 23"  # a batch's steps carry other facts: said as they are
    assert emit.step_facts(dict(step="candidates", seconds=1.0, gate_pairs=0, gate_seconds=0.1, generators=[])) == ""


def test_text_says_a_result_in_short_and_verbose_says_all_of_it(tmp_path, population, capsys, monkeypatch):
    from er import folder
    from er.brief import text
    from er.cli import COMMANDS, main
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    said = lambda *words: (main([*map(str, words)]), capsys.readouterr().out.splitlines())[1]
    assert said("create", "workspace", "w")[:2] == [f"✓ created {Path('workspaces/w')}", "next"]  # as the system writes a path
    said("load", "records", "all.parquet", "--workspace", "workspaces/w")
    out = said("check", "records", "--workspace", "workspaces/w")  # its own file: none given
    assert out[0] == "check records · workspaces/w" and next(x for x in out if x.startswith("✓ ")).startswith(f"✓ ready: {len(g.df):,} records") and any(x.split()[:5] == ["nayose", "resolve", "records", "--workspace", "workspaces/w"] for x in out)
    out = said("resolve", "records", "--workspace", "workspaces/w")
    ran = [x["step"] for x in folder.runs(Path("workspaces/w"))[-1]["steps"]]
    assert out[0] == "resolve records · workspaces/w" and [x.split()[1] for x in out if x.startswith("  ✓ ")] == ran  # each step once, in order
    at = next(i for i, x in enumerate(out) if x.startswith(f"✓ {len(g.df):,} records → "))
    assert out.index("next") - at <= 7 and len(out) - out.index("next") - 1 <= 3  # the result in a few lines, then at most 3 commands
    c = next(c for c in COMMANDS if c.name == "describe workspace")
    main(["describe", "workspace", "workspaces/w", "--format", "json"])
    r = {k: v for k, v in json.loads(capsys.readouterr().out.splitlines()[-1]).items() if k not in ("event", "command")}
    full = said("describe", "workspace", "workspaces/w", "--verbose")
    assert full == text(c, r).splitlines() and len(full) > len(said("describe", "workspace", "workspaces/w"))


def test_the_commands_that_read_a_run_say_when_the_workspace_holds_none(say, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    say("create", "workspace", "w")
    for words in (("describe", "results"), ("list", "scored"), ("list", "entities"), ("describe", "merging"), ("set", "merging", "--conditions", '{"when": []}')):
        code, e = say(*words, "--workspace", "workspaces/w")
        assert code == 2 and e["error"] == f"no run in {Path('workspaces/w')}" and e["fix"], words  # never a traceback


def test_describe_records_says_what_a_column_holds_instead_and_its_one_command_sets_it_right(say, tmp_path, monkeypatch):
    import shlex
    monkeypatch.chdir(tmp_path)
    people, n = ["ヤマダタロウ", "サトウハナコ", "スズキイチロウ", "タナカミドリ", "イシイカホ", "ワタナベケン", "コバヤシユミ", "カトウマコト"], 400
    df = pd.DataFrame({"CONT_ID": [f"{i:08d}" for i in range(n)], "FULL_NAME_KANA": [people[i % 8] for i in range(n)],
                  "NYS_CNV_P_NAME_KANA": [people[i % 8].replace("イイ", "イー") for i in range(n)],  # each record's own name, converted: no company's
                  "PHONE_NUM_4": [f"{i * 37 % 10_000:04d}" for i in range(n)], "POST_CD": [f"{i * 7919 % 10**7:07d}" for i in range(n)],
                  "SOURCE_ADDR_CD": [f"{9_000_000_000 + i}" for i in range(n)],
                  "BIRTH_DATE": [f"{60 + i % 40}-{1 + i % 12:02d}-{1 + i % 28:02d}" for i in range(n)]})
    df.to_parquet("f.parquet", index=False)
    say("create", "workspace", "w")
    at = ("--workspace", "workspaces/w")
    hint = lambda r: {x["feature"]: x["hint"] for x in r["slots"]}
    code, r = say("load", "records", "f.parquet", *at)
    h = hint(r)
    assert h["Name/Company name"]["act"] == "names" and h["Name/Company name"]["says"].startswith("mostly people's names")
    assert any(w["fix"] == "nayose set names by-kind --workspace workspaces/w" for w in say("check", "records", *at)[1]["ready"]["warns"])  # check records says it too
    assert r["next"][0]["command"] == "nayose set names by-kind --workspace workspaces/w"  # the fix first
    assert h["Birth date/Birth date"] is None and h["Name/Full name"] is None  # 93-05-25 is a birth date; people's names where people's go
    assert say("set", "names", "by-kind", *at)[1]["names"] == "by-kind" and 'kind = "company"' in Path("workspaces/w/columns.toml").read_text(encoding="utf-8")
    assert not any("set names" in w["fix"] for w in say("check", "records", *at)[1]["ready"]["warns"])  # the description kept from before: not said again
    assert hint(say("describe", "records", *at)[1])["Name/Company name"]["level"] == "info"  # said, and nothing left to do
    say("set", "feature", "Phone/Phone=POST_CD", "Address/Postal code=", *at)  # postal codes read as the phone
    h = hint(say("describe", "records", *at)[1])["Phone/Phone"]
    assert h["act"] == "move" and h["to"] == "Address/Postal code" and h["says"].startswith("values look like postal code")
    assert say(*shlex.split(h["command"])[1:])[0] == 0  # the command it names, as a person would paste it
    slots = {x["feature"]: x["columns"] for x in say("list", "features", *at)[1]["slots"]}
    assert slots["Address/Postal code"] == "POST_CD" and slots["Phone/Phone"].startswith("no column")
    assert not any(x["hint"] for x in say("describe", "records", *at)[1]["slots"] if x["feature"] != "Name/Company name")
    say("set", "feature", "Phone/Phone=POST_CD+PHONE_NUM_4", *at)  # joined: judged whole, no one column of it moved
    h = hint(say("describe", "records", *at)[1])["Phone/Phone"]
    assert h["says"].startswith("only 0% look right") and h["example"] and "act" not in h and h["example"] not in h["says"]  # a value, apart from what reports carry
    say("set", "feature", "Name/Full name/Given name=POST_CD", "Name/Full name/Family name=FULL_NAME_KANA", *at)  # postal codes as the given name, a family name joined to it
    h = hint(say("describe", "records", *at)[1])["Name/Full name/Given name"]
    assert h["act"] == "off" and say(*shlex.split(h["command"])[1:])[0] == 0  # the family name goes with it: the command takes both off
    slots = {x["feature"]: x["columns"] for x in say("list", "features", *at)[1]["slots"]}
    assert slots["Name/Full name/Given name"].startswith("no column") and slots["Name/Full name/Family name"].startswith("no column")
    df.assign(BIRTH_DATE=[("19" if i % 2 else "") + x for i, x in enumerate(df["BIRTH_DATE"])]).to_parquet("mixed.parquet", index=False)
    assert hint(say("describe", "records", "mixed.parquet", *at)[1])["Birth date/Birth date"]["says"].startswith("written 2 ways (99-99-99, 9999-99-99)")


def test_a_mapping_reads_back_as_written_and_two_changes_at_once_both_land(say, tmp_path, monkeypatch):
    import threading
    import time
    from er import brief, cli, settings
    from er.settings import COLUMNS, load_settings, own_columns, set_columns
    monkeypatch.chdir(tmp_path)
    say("create", "workspace", "w")
    at, ws = ("--workspace", "workspaces/w"), tmp_path / "workspaces" / "w"
    cols = lambda: load_settings(columns=ws / COLUMNS).columns
    say("set", "feature", "Name/Full name=SEI+MEI", "Name/Full name/Family name=", "Name/Full name/Given name=", *at)  # a full name of two columns, no parts
    say("set", "feature", "Phone/Phone=TEL", *at)
    assert cols()["full_name"] == (("SEI", "MEI"),) and cols()["given_name"] == ()  # read back as one full name, through a change elsewhere
    code, e = say("set", "feature", "Name/Full name/Family name=SEI", *at)
    assert code == 2 and "joined to the given name" in e["error"]  # no given name to join it to: refused, never dropped
    assert say("set", "feature", "Name/Full name/Given name=MEI", "Name/Full name/Family name=SEI,SEI2", *at)[0] == 2  # one column: a second would be dropped
    assert say("set", "feature", "Name/Full name/Given name=MEI", "Name/Full name/Family name=SEI", *at)[0] == 0
    assert cols()["person_name"][-1] == ("SEI", "MEI") and cols()["given_name"] == (("MEI",),)
    assert say("set", "feature", "Name/Full name/Given name=", *at)[0] == 2  # the family name would lose what it is joined to: refused
    say("set", "feature", "Name/Full name/Family name=", *at)
    say("set", "feature", "Phone/Phone=TEL", *at)
    assert cols()["full_name"] == (("SEI", "MEI"),) and cols()["given_name"] == (("MEI",),)  # a full name of two columns beside a given name: still the full name

    real = settings.replace_text
    def slow(*a, **k):  # each change read the file before the other wrote it
        time.sleep(0.3)
        real(*a, **k)
    monkeypatch.setattr(settings, "replace_text", slow)
    go = threading.Barrier(2)
    def change(mapping: str) -> None:
        go.wait()
        assert cli.main(["set", "feature", mapping, *at, "--format", "json"]) == 0
    threads = [threading.Thread(target=change, args=(m,)) for m in ("Phone/Phone=TEL_NEW", "Address/City=CITY_NEW")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert cols()["phone"] == (("TEL_NEW",),) and cols()["city"] == (("CITY_NEW",),)  # one at a time: neither lost
    monkeypatch.undo()

    project = tmp_path / "settings.toml"  # an array written over several lines: its lines are no header
    project.write_text(settings.settings_path().read_text(encoding="utf-8").replace('address = [["STD_ADDRESS"], ["ORIGINAL_ADDRESS"]]',
                                                                                  'address = [\n  ["STD_ADDRESS"],\n  ["ORIGINAL_ADDRESS"]\n]')
                       .replace('kind_flag = "PERSON_ORG_CODE"', 'kind_flag = [\n  ["PERSON_ORG_CODE"],\n]'), encoding="utf-8")
    mine = tmp_path / "mine.toml"
    mine.write_text(own_columns(project), encoding="utf-8")
    assert load_settings(columns=mine).columns["address"] == (("STD_ADDRESS",), ("ORIGINAL_ADDRESS",))
    set_columns(mine, {"phone": (("TEL",),)})
    set_columns(mine, {"address": (("ADDR",),)})  # every line of its value replaced
    assert load_settings(columns=mine).columns["address"] == (("ADDR",),) and load_settings(columns=mine).columns["phone"] == (("TEL",),)
    mine.write_text("".join(x for x in mine.read_text(encoding="utf-8").splitlines(keepends=True) if not x.startswith("birth_date")), encoding="utf-8")
    set_columns(mine, {"birth_date": (("DOB",),)})  # a new field: after every line of the last one's value
    assert load_settings(columns=mine).columns["birth_date"] == (("DOB",),) and load_settings(columns=mine).columns["kind_flag"] == (("PERSON_ORG_CODE",),)

    shared = [dict(field=f, filled=0.2, looks_right=0.9, alternatives=[dict(columns=["NAME"], found=True)]) for f in ("person_name", "company_name")]
    assert "  ! person name and company name are 20% filled together" in brief.file_lines(dict(fields=shared, needed=dict(one_of=[["person_name", "company_name"]])))  # one column: counted once, as check records does


def test_a_name_column_both_kinds_share_is_scored_once_as_mapped_or_by_kind(say, tmp_path, population, monkeypatch):
    s, p, g = population
    monkeypatch.chdir(tmp_path)
    person, u = g.df["NYS_CNV_P_NAME_KANA"].isna() & g.df["FULL_NAME_KANA"].notna(), s.data.unique_id
    g.df.assign(NYS_CNV_P_NAME_KANA=g.df["NYS_CNV_P_NAME_KANA"].where(~person, g.df["FULL_NAME_KANA"])).to_parquet("shared.parquet", index=False)  # every person's name in the company column too
    con = duckdb.connect()
    con.register("truth", g.truth)
    said = {}
    for how in ("as-mapped", "by-kind"):
        say("create", "workspace", how)
        say("set", "names", how, "--workspace", f"workspaces/{how}")
        assert say("resolve", "records", "shared.parquet", "--workspace", f"workspaces/{how}")[0] == 0
        said[how] = con.execute(f"""SELECT count(*) FILTER (WHERE x.ENTITY_ID <> y.ENTITY_ID AND s.match_weight >= 6), avg(s.match_weight) FILTER (WHERE x.ENTITY_ID = y.ENTITY_ID)
            FROM read_parquet('workspaces/{how}/scored/*.parquet') s JOIN truth x ON x.CONT_ID = s.{u}_l JOIN truth y ON y.CONT_ID = s.{u}_r""").fetchall()[0]
    assert said["by-kind"][0] == 0 and said["as-mapped"][0] == 0  # a person's name scored once, not as a company's too, either way
    assert abs(said["by-kind"][1] - said["as-mapped"][1]) < 2


def test_a_run_an_earlier_reader_read_takes_no_batch_until_it_runs_again(say, tmp_path, population, monkeypatch):
    from er import folder, intake
    s, p, g = population
    monkeypatch.chdir(tmp_path)
    g.df.iloc[:440].assign(PHONE_NUM_4=[f'["{x}"]' if isinstance(x, str) else x for x in g.df["PHONE_NUM_4"].iloc[:440]]).to_parquet("first.parquet", index=False)
    g.df.iloc[440:].to_parquet("batch.parquet", index=False)
    say("create", "workspace", "w")
    at = ("--workspace", "workspaces/w")
    with monkeypatch.context() as m:  # the run read as the reader before this one: phones kept as ["1201"]
        m.setattr(intake, "READER", 1)
        m.setattr(intake, "unlisted", lambda v: None)
        assert say("resolve", "records", "first.parquet", *at)[0] == 0
    code, e = say("add", "records", "batch.parquet", *at)  # its phones read 1201: they would never agree with the run's
    assert code == 2 and "rerun records" in e["fix"] and len(folder.parts(Path("workspaces/w"))) == 1  # the batch not kept
    assert say("rerun", "records", *at)[0] == 0 and intake.report(folder.parts(Path("workspaces/w"))[0])["fixed"].get("lists")  # read again, once: the lists as their item
    assert say("add", "records", "batch.parquet", *at)[0] == 0


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
    say("decide", "pair", pair["id_l"], pair["id_r"], "no_match", "--workspace", run)  # taken back
    say("apply", "decisions", "--workspace", run)
    people = next(x for x in say("describe", "matching", "--workspace", run)["nodes"] if x["id"] == "people")
    assert people["decided"] == 1  # one pair decided twice: once, as last said
    say("decide", "pair", pair["id_l"], pair["id_r"], "match", "--workspace", run)
    say("apply", "decisions", "--workspace", run)
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
    scored = next(x for x in json.loads((run / "steps.json").read_text(encoding="utf-8"))["runs"][0]["steps"] if x["step"] == "score")
    assert patterns["pairs"] == sum(scored["reached"][patterns["fields"][0]].values())
    assert sum(x["merged"] for x in patterns["patterns"]) == len(pd.read_parquet(run / "matches"))  # no decision yet said no
    assert all(x["merged"] + x["wait"] + x["held"] + x["apart"] == x["pairs"] and min(x["wait"], x["held"], x["apart"]) >= 0 and 0 < len(x["examples"]) <= 3 for x in patterns["patterns"])
    sheet = pd.read_parquet(run / "review.parquet")
    assert sum(x["wait"] for x in patterns["patterns"]) == (sheet["why"] == "decide").sum()  # what waits is what the sheet asks
    matched = say("match", "records", tmp_path / "new.parquet", "--workspace", run)
    assert len(matched["records"]) == len(g.df) - half and set(matched["counts"]) <= {"joins an entity", "a new entity"}
    added = say("add", "records", tmp_path / "new.parquet", "--workspace", run)
    assert added["summary"][0][1].startswith(f"{len(g.df):,}")
    again = say("match", "records", tmp_path / "new.parquet", "--workspace", run)  # every record in the run already: each said so
    assert set(again["counts"]) == {"already in the run"} and len(again["records"]) == len(g.df) - half
    from er import folder
    before = folder.parts(run)
    assert say("add", "records", tmp_path / "new.parquet", "--workspace", run)["summary"][0][0] == "nothing new" and folder.parts(run) == before  # no copy kept
    g.df.head(50).rename(columns={uid: "customer_no"}).to_parquet(tmp_path / "renamed.parquet", index=False)
    assert main(["add", "records", str(tmp_path / "renamed.parquet"), "--workspace", str(run), "--format", "json"]) == 2
    e = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert f"write customer_no as {uid} in it" in e["fix"] and folder.parts(run) == before  # a batch has the run's columns; the run's file stays the last
    name = s.columns["person_name"][0][0]
    g.df.head(50).rename(columns={uid: "customer_no", name: "name_kana"}).to_parquet(tmp_path / "renamed2.parquet", index=False)
    assert main(["match", "records", str(tmp_path / "renamed2.parquet"), "--workspace", str(run), "--format", "json"]) == 2  # a preview: the same advice
    fix = json.loads(capsys.readouterr().out.splitlines()[-1])["fix"]
    assert fix.count(f"customer_no as {uid}") == 1 and "name_kana" not in fix and "set columns" not in fix  # what a run needs and lacks, once: a name it reads elsewhere isn't
    assert say("load", "records", tmp_path / "new.parquet", "--workspace", run)  # loaded again, as step 2 does: every record of it in the run
    loaded = folder.parts(run)[-1]
    assert say("add", "records", loaded, "--workspace", run)["summary"][0] == ["nothing new", "every ID of new.parquet is in the run already"]
    assert folder.parts(run) == before  # a file loaded before stays
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
    assert [x["step"] for x in seen] == ["load", "budget", "fit", "rules", "keys", "candidates", "score", "cluster", "probe", "gap", "write"]  # step by step
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
    assert 'normalize = ["nfkc", "katakana", "strip_spaces"]' in line("person_name") and "# municipality + town + chome" in line("town_code")  # options, comments stay
    assert len(after.splitlines()) == len(before.splitlines()) and line("birth_date").startswith("birth_date = []") and "#" in line("birth_date")
    with pytest.raises(InputError, match="id must name one column"):
        set_columns(f, {"id": (("A",), ("B",))})
    assert f.read_text(encoding="utf-8") == after and not (tmp_path / "config" / "settings.toml.tmp").exists()


def test_describe_says_what_a_run_folder_holds_and_what_joined_an_entity(tmp_path, population):
    from er import match
    from er.report import describe_entity, describe_workspace
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    match.SCORED_U.clear()  # the fit samples u itself, as a first run in a process does: an earlier test's run left it nothing to compare
    out = tmp_path / "run"
    run = Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    gold = pd.read_parquet(out / "gold.parquet")
    d = describe_workspace(run.con, out, uid)
    assert (d["records"], d["entities"]) == (len(gold), gold["cluster_id"].nunique()) and d["runs"][0]["what"] == "full run"
    assert d["runs"][0]["records"] == len(gold) and {"load", "fit", "score"} <= set(d["runs"][0]["steps"])  # each step's seconds: the next run's estimate
    step = {x["step"]: x for x in run.steps}  # where the time went: the fit's two parts, the gate, each string function's seconds and values
    assert {"sample_seconds", "file_u_seconds"} <= set(step["fit"]) and {"gate_seconds", "gate_pairs"} <= set(step["candidates"])
    assert step["fit"]["compared"]["all"]["wall"] > 0 and "jaro_winkler" not in step["score"].get("compared", {})  # names: compared by DuckDB itself
    section = (out / "report.txt").read_text(encoding="utf-8").split("TIME IN COMPARISONS")[1].split("MODEL")[0]
    shown = bool(re.search(r"^\s+fit\s+all of them\s", section, re.M))
    assert shown == (step["fit"]["compared"]["all"]["wall"] >= 0.01)  # the fit's time in string functions, from a hundredth of a second, whatever the machine's speed
    from er import strings
    strings._enter(("t",), 0); strings._enter(("t",), 1)  # two calls at once, 0–2 and 1–3: three seconds of wall, not four
    strings._leave(("t",), 1.5, 2, 5); strings._leave(("t",), 1.5, 3, 5)
    assert strings.SPENT.pop("t") == [3.0, 10, 2, 3.0]
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
    pd.DataFrame({"uid_l": ["1", "3"], "uid_r": ["2", "4"], "decision": ["match\u3000", "\u3000No_Match "]}, dtype="string").to_parquet(tmp_path / "typed.parquet")
    con = duckdb.connect()
    decisions(tmp_path / "typed.parquet", con, "uid_l", "uid_r", into="d")  # typed on a Japanese keyboard: full-width spaces around
    assert sorted(x for x, in con.execute("SELECT decision FROM d").fetchall()) == ["match", "no_match"]
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
    (inbox / "batches" / "d_bad.parquet").write_text("CONT_ID\n1\n", encoding="utf-8")  # a CSV, named as Parquet: read as it comes, and short of fields
    for k, f in enumerate(sorted((inbox / "batches").iterdir())):
        os.utime(f, (1_000 + k, 1_000 + k))  # arrival order
    serve = lambda: nayose("serve", "inbox", inbox, "--workspace", run, "--settle", "0")  # files written just now: taken at once
    done = serve()
    assert done.returncode == 0, done.stderr
    jobs = [(e["file"], e["outcome"]) for e in schedule.ledger(run)]
    assert jobs == [("a_first.parquet", "done"), ("b_new.parquet", "done"), ("c_again.parquet", "done"), ("d_bad.parquet", "failed")]
    assert len(pd.read_parquet(run / "gold.parquet")) == len(g.df)  # the first batch the full run, the second an increment
    parked = list((inbox / "failed" / "batches").glob("*.error.txt"))
    assert len(parked) == 1 and "holds none of these fields" in parked[0].read_text(encoding="utf-8")
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
    assert "no row has a decision" in next((inbox / "failed" / "decisions").glob("*untouched.parquet.error.txt")).read_text(encoding="utf-8")
    gold = pd.read_parquet(run / "gold.parquet").set_index(uid)
    assert (gold.loc[answers[uid], "kind_by"] == "people").all()  # the answers went in by a rerun


def test_an_oversized_block_is_checked_on_a_sample_and_a_placeholder_is_skipped(tmp_path, population):
    from er.report import describe_matching
    from er.run import Run
    from er.strings import connect
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    dummy = df.index[:100]
    df.loc[dummy, ["PHONE_NUM_4", "GIVEN_NAME_KANA", "POST_CD"]] = ["0000", "タロウ", "1500042"]  # a dummy phone, and one given name and postal code: blocks of 100
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run", pipeline_file=s.root / "config" / "final.toml")  # no stop
    assert any("phone = 0000" in x and "placeholder" in x for x in run.examples)  # most of the pairs sharing a phone: read as missing, no block
    assert not run.gated["value"].str.contains("0000").any()
    block = run.gated[run.gated["value"].str.contains("タロウ") & (run.gated["generator"] == "given_name_postal")]
    assert len(block) == 1 and block["decision"].iloc[0].startswith("skipped") and block["records"].iloc[0] == 100
    assert any("タロウ" in x and "skipped" in x for x in run.examples) and not any("タロウ" in x for x in run.notes)
    shown = next(n for n in describe_matching(connect(s.compute)[0], tmp_path / "run", p, s)["nodes"] if n["id"] == "candidates")["skipped"]
    assert dict(key="given_name_postal", value=block["value"].iloc[0], records=100, pairs=4950) in shown["largest"]  # as qa.md lists it
    assert "タロウ" not in json.dumps(json.loads((tmp_path / "run" / "steps.json").read_text(encoding="utf-8")), ensure_ascii=False)  # counts, no record's value
    check = nayose("check", "records", tmp_path / "in.parquet")
    assert check.returncode == 0 and "checked by sampling" in check.stdout

    same = pd.concat([g.df.iloc[[0]]] * 70, ignore_index=True)  # 70 copies of one record: every key's block oversized
    same[uid] = [f"copy{i:03d}" for i in range(70)]
    pd.concat([g.df, same]).to_parquet(tmp_path / "copies.parquet", index=False)
    run = Run(p, s).full(tmp_path / "copies.parquet", tmp_path / "copies")
    gold = pd.read_parquet(tmp_path / "copies" / "gold.parquet").set_index(uid)
    assert gold.loc[same[uid], "cluster_id"].nunique() == 1  # the sample shows they match: kept and joined
    assert (run.gated["decision"] == "kept").any()


def test_a_customer_id_held_by_many_records_is_a_placeholder_every_step_and_the_lookup_read_as_missing(tmp_path, population):
    from er import index
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    many = df.index[:70]
    df.loc[many, "CIF_ID"] = "00000000"  # one customer ID on 70 people: a placeholder
    df.loc[many, "PHONE_NUM_4"] = [f"{1000 + i % 7}" for i in range(len(many))]  # 7 phones: ID and phone together, blocks of 10
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    kept, ids = pd.read_parquet(tmp_path / "run" / "rule_kept"), set(df.loc[many, uid])
    inside = kept[kept[f"{uid}_l"].isin(ids) & kept[f"{uid}_r"].isin(ids)]
    assert not inside["rule"].str.contains("CIF").any()  # X1, X3, F3: none pairs them by it
    assert any(x.startswith("customer_id: 1 value held by 64+ records read as missing") for x in run.notes)
    assert json.loads((tmp_path / "run" / "state" / "placeholders.json").read_text(encoding="utf-8")) == {"customer_id": ["00000000"]}
    stored = pd.read_parquet(tmp_path / "run" / "state" / "records")
    assert stored.loc[stored[uid].isin(ids), [c for c in stored if c == "customer_id" or c.startswith("customer_id__")]].isna().all().all()
    index.build(tmp_path / "run", s, p)
    assert index.look_up(tmp_path / "run", s, p, values={"CIF_ID": "00000000", "PHONE_NUM_4": "9999"}, at_least=-1e9, most=10**6)["found"] == 0  # typed: missing too
    assert "found" in index.look_up(tmp_path / "run", s, p, values={"PHONE_NUM_4": "9999"}, at_least=-1e9, most=10**6)  # a field with placeholders not typed: missing already

    first, batch = df.drop(index=many[40:]), df.loc[many[40:]].assign(CIF_ID="11111111")  # 40 hold 11111111 in the run; 30 more come
    first.loc[many[:40], "CIF_ID"] = "11111111"
    first.to_parquet(tmp_path / "first.parquet", index=False)
    batch.drop(columns=["BIRTH_DATE"]).to_parquet(tmp_path / "batch.parquet", index=False)  # a batch without the birth dates the run compares
    Run(p, s).full(tmp_path / "first.parquet", tmp_path / "inc")
    added = Run(p, s).increment(tmp_path / "batch.parquet", tmp_path / "inc")
    assert added.added == 30 and json.loads((tmp_path / "inc" / "state" / "placeholders.json").read_text(encoding="utf-8")) == {"customer_id": ["11111111"]}
    assert any("pairs the run joined on it before stay until it runs again" in x for x in added.notes)
    new = pd.read_parquet(sorted((tmp_path / "inc" / "state" / "records").glob("part-*.parquet"))[-1])
    assert new["customer_id"].isna().all() and ("birth_date" not in new or new["birth_date"].isna().all())


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


def test_the_generator_makes_direct_matches_rare_households_their_own_entities_and_reports_how_hard_it_is():
    from er.generate import check, generate, halfwidth, load_reference, load_spec, profile, split_by_entity
    import unicodedata
    s = load_settings()
    spec, split = load_spec(s.root / "config" / "generator.toml")
    spec = replace(spec, entities=8_000)
    g = generate(spec, *load_reference(s.paths["reference"]))
    check(spec, g)  # CONT_ID unique, digits, fill rates, no customer ID shared by two entities
    t = g.with_truth.assign(household=g.with_truth["ENTITY_ID"].str.removesuffix("H"))
    member = t["ENTITY_ID"].str.endswith("H")
    people = (g.truth.drop_duplicates("ENTITY_ID")["KIND"] == "person").sum()
    share = spec.households["share"]
    assert t.loc[member, "KIND"].eq("person").all() and 0.8 * share < t.loc[member, "ENTITY_ID"].nunique() / people <= share
    both = t[member].merge(t[~member], on="household", suffixes=("", "_b"))  # each member's record beside each of its household's
    assert (both["GIVEN_NAME_KANA"] != both["GIVEN_NAME_KANA_b"]).mean() > 0.9 and (both["BIRTH_DATE"] != both["BIRTH_DATE_b"]).all()
    assert (both["LAST_NAME_KANA"] == both["LAST_NAME_KANA_b"]).mean() > 0.3  # one family name, each record with its own typos
    assert ((both["PHONE_NUM_4"] == both["PHONE_NUM_4_b"]) & (both["ADDR_CD"] == both["ADDR_CD_b"])).mean() > 0.03  # what F1 joins on
    assert t.assign(split=split_by_entity(g.truth, split)).groupby("household")["split"].nunique().max() == 1
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
    assert any(w["what"].startswith("birth date is") for w in r["ready"]["warns"])  # a nearly empty field, said with what to do
    assert not any("company name" in w["what"] for w in r["ready"]["warns"])  # filled only for companies, by design: with the person's name, it is full
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
    assert code == 0 and (top["down_to"], top["up_to"]) == (20.0, None)  # every range, the empty ones too
    assert sum(x["pairs"] for x in r["ranges"] if x["down_to"] >= trust["next"]["down_to"]) == trust["pairs"] > 0  # what people check first, as the trust line counts it: past the empty 20+
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


def test_describe_review_sees_a_false_pair_above_the_line_as_the_line_does(tmp_path):
    """The line steps down once the range just below it is clean: a false pair above it holds back no range below,
    a false pair below it holds back that range and every one under it; a range above the line merges, none left."""
    from er.config import adjust, load_pipeline
    from er.review_state import review_workload, trust_state
    from er.strings import connect
    s = load_settings()
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    p = adjust(load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns), {"trust": 12.0})
    (tmp_path / "matches").mkdir()
    (tmp_path / "decisions").mkdir()
    w = np.r_[np.full(400, 25.0), np.full(400, 15.0), np.full(1000, 10.0), np.full(1000, 7.0), np.full(500, 3.0)]
    m = pd.DataFrame({l: [f"{i:08d}" for i in range(len(w))], r: [f"{10_000_000 + i:08d}" for i in range(len(w))], "match_weight": w})
    m.to_parquet(tmp_path / "matches" / "part-00000.parquet", index=False)
    decide = lambda rows: rows[[l, r]].assign(decision="no_match").to_parquet(tmp_path / "decisions" / "part-00000.parquet", index=False)
    con = connect(s.compute)[0]

    decide(m.head(1))  # an audit above the line said different
    st, got = trust_state(con, tmp_path, p, uid), review_workload(con, tmp_path, p, uid)
    by = {x["down_to"]: x for x in got["ranges"]}
    assert st["next"]["down_to"] == 8.0 and by[8.0]["reviews_left"] == st["needed"] - st["checked"] == 300  # as the line counts it
    assert by[20.0]["reviews_left"] == by[12.0]["reviews_left"] == 0  # above the line: merging
    assert by[8.0]["chance_clean"] is not None and by[6.0]["reviews_left"] == 300 and by[0.0]["reviews_left"] == 300

    decide(m[m["match_weight"] == 10.0].head(1))  # one below the line: that range and every one under it, whole
    got = review_workload(con, tmp_path, p, uid)
    by = {x["down_to"]: x for x in got["ranges"]}
    assert (by[8.0]["reviews_left"], by[6.0]["reviews_left"], by[0.0]["reviews_left"]) == (999, 1000, 500) and by[8.0]["chance_clean"] is None
    assert by[8.0]["reviews_to_here"] == 999 and got["ranges"][-1]["reviews_to_here"] == 2499


def test_check_records_judges_a_person_s_and_a_company_s_name_together_once_per_column():
    from types import SimpleNamespace
    from er.cli import ready_for
    room = dict(pairs_needed=10, pairs_fit=100)
    run = lambda person, company: SimpleNamespace(pipeline=SimpleNamespace(fields=SimpleNamespace(one_of=(("person_name", "company_name"),))),
                                                  present={"person_name": person, "company_name": company}, _count=lambda t: 0)
    field = lambda f, x: dict(field=f, filled=x, looks_right=1.0, columns="")
    both = [field("person_name", 0.2), field("company_name", 0.15)]
    said = lambda r: [w["what"] for w in ready_for(r, both, None, room, None)["warns"]]
    assert not said(run((("NAME",),), (("CORP",),)))  # each filled for its kind: 35% together, enough
    assert said(run((("NAME",),), (("NAME",),))) == ["person name and company name are 20% filled together"]  # one column: counted once
    alone = [field("person_name", 0.1)]
    assert [w["what"] for w in ready_for(run((("NAME",),), ()), alone, None, room, None)["warns"]] == ["person name is 10% filled"]  # the only name, nearly empty


def test_a_result_s_nested_numbers_print_plainly_and_a_settings_folder_is_said(tmp_path):
    from er.brief import cell
    from er.config import toml_of
    assert cell({"file": 0.5, "peak_gb": 2}) == "file 0.50 peak gb 2"
    with pytest.raises(InputError, match="can't be read"):
        toml_of(tmp_path)


def test_a_run_in_a_workspace_on_a_file_without_a_needed_field_says_to_map_it_there(say, tmp_path, population, monkeypatch):
    s, p, g = population
    g.df.rename(columns={s.data.unique_id: "customer_no"}).to_parquet(tmp_path / "theirs.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    say("create", "workspace", "w")
    code, e = say("resolve", "records", "theirs.parquet", "--workspace", "workspaces/w")
    assert code == 2 and e["fix"].startswith("map it in the workspace") and "nayose set columns id=customer_no --workspace workspaces/w" in e["fix"]
    g.df.rename(columns={s.data.unique_id: "id"}).to_parquet(tmp_path / "ids.parquet", index=False)  # its ID column named as the field: read as id_2
    code, e = say("resolve", "records", "ids.parquet", "--workspace", "workspaces/w", "--overwrite")
    assert code == 2 and "set columns id=id --workspace" in e["fix"] and "id_2" not in e["error"] + e["fix"]  # the file's own name for it


def test_a_file_with_columns_named_as_the_run_names_its_own_runs(say, tmp_path, population):
    s, p, g = population
    df = g.df.assign(KIND=(["Person", "Company"] * len(g.df))[:len(g.df)], Address="somewhere")  # unmapped, named as fields and kinds are
    df.to_parquet(tmp_path / "theirs.parquet", index=False)
    code, r = say("resolve", "records", tmp_path / "theirs.parquet", "--workspace", tmp_path / "run")
    notes = [v for w, v in r["summary"] if w == "note"]
    assert code == 0 and any("column KIND read as KIND_2" in n for n in notes) and any("column Address read as Address_2" in n for n in notes)
    flag = s.columns["kind_flag"][0][0]
    df.assign(KIND=df[flag] if flag in df else "1").to_parquet(tmp_path / "flagged.parquet", index=False)
    say("create", "workspace", "w", "--home", tmp_path)
    assert say("set", "columns", "kind_flag=KIND", "--workspace", tmp_path / "w")[0] == 0  # the person/company flag, mapped, named as the run's kind
    assert say("resolve", "records", tmp_path / "flagged.parquet", "--workspace", tmp_path / "w")[0] == 0


def test_the_commands_the_tests_start_run_this_checkout_s_code(tmp_path):  # from a git worktree too, not the venv's checkout
    import subprocess
    import sys
    got = subprocess.run([sys.executable, "-c", "import er; print(er.__file__)"], cwd=tmp_path, capture_output=True, encoding="utf-8", check=True).stdout
    assert Path(got.strip()).resolve().is_relative_to(Path(__file__).resolve().parents[1])


def test_the_page_s_state_is_the_cli_s_a_file_it_can_t_run_counts_said_once_and_each_entity_named(say, tmp_path, population):
    s, p, g = population
    uid = s.data.unique_id
    home = tmp_path / "home"
    assert say("create", "workspace", "short", "--home", home)[0] == 0
    (tmp_path / "short.csv").write_text(f"{uid},NAME_X,TEL\n0001,ヤマダタロウ,1234\n0002,スズキハナコ,5678\n", encoding="utf-8")
    assert say("load", "records", tmp_path / "short.csv", "--workspace", home / "short")[0] == 0  # read: its name column not mapped
    ready = say("describe", "workspace", home / "short")[1]["ready"]
    assert not ready["run"] and "name" in ready["why"] and ready["fix"]  # not ready, and why in its own words

    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    assert say("create", "workspace", "w", "--home", home)[0] == 0
    assert say("resolve", "records", tmp_path / "all.parquet", "--workspace", home / "w")[0] == 0
    assert say("describe", "workspace", home / "w")[1]["ready"]["run"]
    compared = say("describe", "results", "--workspace", home / "w")[1]["candidates"]
    nodes = {x["id"]: x for x in say("describe", "matching", "--workspace", home / "w")[1]["nodes"]}
    assert compared == nodes["candidates"]["pairs"]  # one number of pairs compared, wherever it is said
    gold = pd.read_parquet(home / "w" / "gold.parquet")
    company = gold[gold["kind"] == 2].groupby("cluster_id").filter(lambda c: len(c) == 1)[uid].iloc[0]
    named = say("list", "entities", "--workspace", home / "w", "--record", company, "--smallest", "1")[1]["entities"]
    assert named and named[0]["names"]  # a company's entity named by its company name


def test_two_people_of_one_household_are_labelled_and_a_copy_of_one_is_not(tmp_path, population):
    from er.explain import explain_pair
    from er.results import list_scored
    from er.run import Run
    from er.strings import connect
    s, p, g = population
    uid = s.data.unique_id
    cols = ["GIVEN_NAME_KANA", "LAST_NAME_KANA", "PHONE_NUM_4", "ADDR_CD"]
    one = g.df[g.df[cols].notna().all(axis=1) & g.df["BIRTH_DATE"].isna()].iloc[0]
    given = "ハナコ" if not str(one["GIVEN_NAME_KANA"]).startswith("ハ") else "タロウ"  # 2 edits or more from theirs, all three sounds of the end apart
    member = one.copy()
    member[[uid, "GIVEN_NAME_KANA", "FULL_NAME_KANA", "O_PERSON_NAME_KANA"]] = ["member", given, one["LAST_NAME_KANA"] + given, one["LAST_NAME_KANA"] + "　" + given]
    copy = one.copy()
    copy[uid] = "copy"
    pd.concat([g.df, pd.DataFrame([member, copy])], ignore_index=True).to_parquet(tmp_path / "in.parquet", index=False)
    Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run", pipeline_file=s.root / "config" / "final.toml")  # with its reports, as nayose runs it
    said = lambda x: explain_pair(tmp_path / "run", p, s, one[uid], x)["household"]
    assert said("member") and not said("copy")  # the copy: the same given name
    con, db = connect(s.compute)
    listed = {(x["first"], x["second"]): x["household"] for x in list_scored(con, db, tmp_path / "run", s, p, record="member", count=500)["pairs"]}
    assert listed.get(tuple(sorted((one[uid], "member")))) is True
    sheet = pd.read_parquet(tmp_path / "run" / "review.parquet")
    assert "household" in sheet and sheet["household"].dtype == bool


def test_a_run_s_progress_follows_this_version_s_steps_when_the_last_run_lacked_one(tmp_path):
    from er import cli, emit, folder
    ws = tmp_path / "ws"
    (ws / "state").mkdir(parents=True)
    old = [{"step": x, "seconds": 1.0, **({"records": 10} if x == "load" else {})} for x in emit.RUN_ORDER if x != "keys"]  # a run before the keys step
    (ws / folder.STEPS).write_text(json.dumps({"runs": [{"steps": old}]}), encoding="utf-8")
    got = cli.last_run(str(ws), "rerun records")
    assert got["order"] == emit.RUN_ORDER and "keys" in got["order"] and got["last"]["candidates"] == 1.0


def test_the_fit_a_workspace_sets_is_the_sample_and_the_em_its_runs_use(population):
    from er.config import InputError, adjust
    s, p, g = population
    q = adjust(p, {"fit": {"records": 64000, "em": "keys"}})
    assert q.fit_rows == 64000 and q.fs.model.em_from_keys and q.fs.model.em_median
    assert adjust(p, {"fit": {"records": 2000}}).fs.model == p.fs.model  # the size alone: EM as it was
    for bad in ({"records": 10}, {"em": "both"}, {"records": True}, {"size": 2000}):
        with pytest.raises(InputError, match="fit takes"):
            adjust(p, {"fit": bad})
    from er.run import run_config
    assert run_config(q, s) == run_config(p, s) != run_config(adjust(p, {"line": 9}), s)  # an increment and a lookup score with the stored model: the fit owes them no rerun


def test_a_comparison_s_own_copy_is_no_step_a_setting_may_name(tmp_path):
    from er.config import COPIES
    from er.settings import load_settings, settings_path
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    for step in COPIES:  # what the comparisons make for themselves: every place that reads a chain refuses it alike
        (tmp_path / "settings.toml").write_text(settings_path().read_text(encoding="utf-8").replace('fold = ["kana_fold"]', f'fold = ["kana_fold", "{step}"]'), encoding="utf-8")
        with pytest.raises(Exception, match="unknown normalizers"):
            load_settings(tmp_path / "settings.toml")
