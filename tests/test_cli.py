"""nayose: each command as a user runs it, mistakes in words, the scheduler, the run's reports."""
import json
import re
from pathlib import Path
from dataclasses import replace

import duckdb
import numpy as np
import pandas as pd
import pytest

from er.engine.duckdb import DuckDB
from er.config import (InputError)
from er.settings import load_settings

from conftest import nayose


def _mapping(tmp_path: Path, s, **fields: str) -> Path:  # the project's settings with some fields mapped to other columns, as a private settings file
    config = (s.root / "config" / "settings.toml").read_text(encoding="utf-8")
    for k, v in fields.items():  # each field one column
        config, n = re.subn(rf"^({k} = \{{ sources = )\[\[.*?\]\]", rf'\1[["{v}"]]', config, count=1, flags=re.M)
        assert n == 1, k
    f = tmp_path / "settings.toml"
    f.write_text(config, encoding="utf-8")
    return f


def test_a_run_says_what_is_wrong_in_words_people_can_act_on(say, tmp_path, population, capsys, monkeypatch):
    from er.jobs.build import build
    s, p, g = population
    monkeypatch.chdir(tmp_path)

    phone, postal = s.columns["phone"][0][0], [c for alt in s.columns["postal_code"] for c in alt]
    g.df.assign(**{c: None for c in postal}).to_parquet(tmp_path / "nopostal.parquet", index=False)  # mapped, but never filled
    from design.probe import probe
    run = build(tmp_path / "nopostal.parquet", tmp_path / "run", s, p)
    assert [x["stratum"] for x in probe(run)] == ["phone"]  # an empty group: nothing to draw
    g.df.head(0).to_parquet(tmp_path / "empty.parquet", index=False)
    with pytest.raises(InputError, match="no record, only its header"):
        build(tmp_path / "empty.parquet", tmp_path / "run0", s, p)
    with pytest.raises(InputError, match="both read"):  # one column for two compared fields: one value counted twice
        build(tmp_path / "nopostal.parquet", tmp_path / "run1", load_settings(_mapping(tmp_path, s, postal_code=phone)), p)
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    for words in (("resolve", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w", "--compute", "memory_limit=lots"),
                  ("resolve", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w", "--compute", "memroy_limit=8GB"),
                  ("resolve", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w", "--model", tmp_path / "none.json")):
        code, e = say(*words)
        assert code == 2 and e["fix"], words  # a mistake people fix: two lines, never a traceback
    def short(*_, **__):  # out of memory in DuckDB
        raise duckdb.OutOfMemoryException("Out of Memory Error: failed to allocate")
    with monkeypatch.context() as m:
        m.setattr("er.cli.build", short)
        code, e = say("resolve", "records", tmp_path / "all.parquet", "--workspace", tmp_path / "w")
        assert code == 2 and "out of memory" in e["error"] and "memory_limit" in e["fix"]


def test_nayose_prints_a_mistake_as_two_lines_and_exits_with_2(tmp_path):
    done = nayose("resolve", "records", tmp_path / "none.parquet", "--workspace", tmp_path / "w")
    assert done.returncode == 2 and done.stderr.splitlines()[0].startswith("✗ no file matches")
    assert done.stderr.splitlines()[1].lstrip().startswith("fix: ") and "Traceback" not in done.stderr
    done = nayose("resolve", "records", tmp_path / "none.parquet", "--workspace", tmp_path / "w", "--format", "json")
    error = json.loads(done.stdout.splitlines()[-1])
    assert done.returncode == 2 and error["event"] == "error" and error["exit"] == 2 and error["fix"]
    assert nayose("resolve", "records", tmp_path / "x.parquet").returncode == 2  # --workspace missing: the parser says so


def test_a_number_given_is_a_finite_one_and_a_mistyped_workspace_is_refused_unmade(say, tmp_path):
    (tmp_path / "w").mkdir()
    for words in (("match", "record", "X=1", "--count", "inf"), ("match", "record", "X=1", "--count", "nan"), ("match", "record", "X=1", "--from=-inf"), ("match", "record", "X=1", "--count", "²")):
        code, e = say(*words, "--workspace", tmp_path / "w")
        assert code == 2 and ("not a number" in e["error"] or "a whole number" in e["error"]), words
    from er import cli
    for c in cli.COMMANDS:  # every command given a workspace mistyped: refused, and no folder made
        if not any(p.name == "workspace" for p in c.params) or c.name in cli.MAKES:
            continue  # the commands that make a workspace
        words = [c.verb, c.noun]
        for p in c.params:
            if p.name == "workspace":
                words += ["--workspace", tmp_path / "typo"]
            elif p.positional and not p.optional:
                words += ["a", "b"] if p.kind == "many" else [p.choices[0] if p.choices else tmp_path / "none.csv" if p.kind == "path" else "x"]
            elif p.required:
                words += [f"--{p.name}", p.choices[0] if p.choices else "2000"]
        try:
            code = say(*words)[0]
        except SystemExit as e:  # the parser's refusal
            code = e.code
        assert code == 2 and not (tmp_path / "typo").exists(), c.name


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
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    said = lambda *words: (main([*map(str, words)]), capsys.readouterr().out.splitlines())[1]
    out = said("resolve", "records", "all.parquet", "--workspace", "workspaces/w")
    ran = [x["step"] for x in folder.runs(Path("workspaces/w"))[-1]["steps"]]
    assert out[0] == "resolve records · workspaces/w" and [x.split()[1] for x in out if x.startswith("  ✓ ")] == ran  # each step once, in order
    at = next(i for i, x in enumerate(out) if x.startswith(f"✓ {len(g.df):,} records → "))
    assert out.index("next") - at <= 7 and len(out) - out.index("next") - 1 <= 3  # the result in a few lines, then at most 3 commands
    sheet = pd.read_parquet(Path("workspaces/w") / "review.parquet")
    sheet.head(1)[[f"{uid}_l", f"{uid}_r"]].assign(decision="match").to_parquet("d.parquet", index=False)
    said("apply", "decisions", "--file", "d.parquet", "--workspace", "workspaces/w")
    c = next(c for c in COMMANDS if c.name == "apply decisions")
    main(["apply", "decisions", "--file", "d.parquet", "--workspace", "workspaces/w", "--format", "json"])  # given again: nothing new, the same result each time
    r = {k: v for k, v in json.loads(capsys.readouterr().out.splitlines()[-1]).items() if k not in ("event", "command")}
    full, lines = said("apply", "decisions", "--file", "d.parquet", "--workspace", "workspaces/w", "--verbose"), text(c, r).splitlines()
    assert full[-len(lines):] == lines and len(full) > len(said("apply", "decisions", "--file", "d.parquet", "--workspace", "workspaces/w"))


def test_the_commands_that_read_a_run_say_when_the_workspace_holds_none(say, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("workspaces/w").mkdir(parents=True)
    pd.DataFrame({load_settings().data.unique_id: ["1"], "FULL_NAME_KANA": ["ヤマダタロウ"]}).to_parquet("one.parquet", index=False)
    for words in (("build", "index"), ("apply", "decisions"), ("match", "records", "one.parquet")):
        code, e = say(*words, "--workspace", "workspaces/w")
        assert code == 2 and "no run" in e["error"] and e["fix"], words  # never a traceback


def test_a_name_column_both_kinds_share_is_scored_once_as_mapped_or_by_kind(say, tmp_path, population, monkeypatch):
    s, p, g = population
    monkeypatch.chdir(tmp_path)
    person, u = g.df["NYS_CNV_P_NAME_KANA"].isna() & g.df["FULL_NAME_KANA"].notna(), s.data.unique_id
    g.df.assign(NYS_CNV_P_NAME_KANA=g.df["NYS_CNV_P_NAME_KANA"].where(~person, g.df["FULL_NAME_KANA"])).to_parquet("shared.parquet", index=False)  # every person's name in the company column too
    by_kind = (s.root / "config" / "settings.toml").read_text(encoding="utf-8")
    for f, kind in (("full_name", "person"), ("person_name", "person"), ("company_name", "company")):  # each name kept on the side its record's kind leans to
        by_kind, n = re.subn(rf"^({f} = \{{ .*?) \}}", rf'\1, kind = "{kind}" }}', by_kind, count=1, flags=re.M)
        assert n == 1, f
    Path("by-kind.toml").write_text(by_kind, encoding="utf-8")  # a private settings file, as ER_SETTINGS names one
    engine = DuckDB(duckdb.connect())
    engine.register("truth", g.truth)
    said = {}
    for how in ("as-mapped", "by-kind"):
        if how == "by-kind":
            monkeypatch.setenv("ER_SETTINGS", str(Path("by-kind.toml").resolve()))
        assert say("resolve", "records", "shared.parquet", "--workspace", f"workspaces/{how}")[0] == 0
        said[how] = engine.row(f"""SELECT count(*) FILTER (WHERE x.ENTITY_ID <> y.ENTITY_ID AND s.match_weight >= 6), avg(s.match_weight) FILTER (WHERE x.ENTITY_ID = y.ENTITY_ID)
            FROM read_parquet('workspaces/{how}/scored/*.parquet') s JOIN truth x ON x.CONT_ID = s.{u}_l JOIN truth y ON y.CONT_ID = s.{u}_r""")
    assert said["by-kind"][0] == 0 and said["as-mapped"][0] == 0  # a person's name scored once, not as a company's too, either way
    assert abs(said["by-kind"][1] - said["as-mapped"][1]) < 2


def test_every_command_has_its_help(capsys):
    from er.cli import COMMANDS, parser
    for c in COMMANDS:
        with pytest.raises(SystemExit) as done:
            parser().parse_args([c.verb, c.noun, "--help"])
        shown = capsys.readouterr().out
        assert done.value.code == 0 and c.help in shown and c.example in shown


def test_nayose_takes_a_file_from_a_run_to_people_s_decisions_and_a_batch(tmp_path, population, capsys):
    from er import folder
    from er.cli import COMMANDS, main
    s, p, g = population
    uid, half = s.data.unique_id, len(g.df) // 2
    l, r = f"{uid}_l", f"{uid}_r"
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

    assert say("resolve", "records", tmp_path / "first.parquet", "--workspace", run)["summary"][0][0] == "records"
    sheet = pd.read_parquet(run / "review.parquet")
    pair = sheet.iloc[0]
    decisions = tmp_path / "decisions.parquet"
    pd.DataFrame({l: [pair[r]], r: [pair[l]], "decision": ["match"]}).to_parquet(decisions, index=False)  # either order
    assert say("apply", "decisions", "--workspace", run, "--file", decisions)["matches"] == 1
    assert say("apply", "decisions", "--workspace", run, "--file", decisions)["decisions"] == 0  # given twice: nothing new
    gold = pd.read_parquet(run / "gold.parquet").set_index(uid)
    assert gold.loc[pair[l], "cluster_id"] == gold.loc[pair[r], "cluster_id"]
    matched = say("match", "records", tmp_path / "new.parquet", "--workspace", run)
    assert len(matched["records"]) == len(g.df) - half and set(matched["counts"]) <= {"joins an entity", "a new entity"}
    added = say("add", "records", tmp_path / "new.parquet", "--workspace", run)
    assert added["summary"][0][1].startswith(f"{len(g.df):,}")
    again = say("match", "records", tmp_path / "new.parquet", "--workspace", run)  # every record in the run already: each said so
    assert set(again["counts"]) == {"already in the run"} and len(again["records"]) == len(g.df) - half
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
    assert fix.count(f"customer_no as {uid}") == 1 and "name_kana" not in fix  # what a run needs and lacks, once: a name it reads elsewhere isn't


def test_a_nearly_empty_field_is_kept_and_the_fit_skips_what_it_cannot_learn_from(tmp_path, population):
    from er.jobs.build import build
    s, p, g = population
    sparse = g.df.copy()
    sparse.loc[sparse.index[10:], ["STD_ADDRESS", "ORIGINAL_ADDRESS"]] = None  # no two records share an address
    sparse.to_parquet(tmp_path / "sparse.parquet", index=False)
    seen = []
    run = build(tmp_path / "sparse.parquet", tmp_path / "run", s, p, echo=seen.append)
    assert [x["step"] for x in seen] == ["load", "budget", "fit", "rules", "candidates", "score", "cluster", "write"]  # step by step
    assert "address" in run.model["er"]["skipped"] and any("sharing address" in x for x in run.notes)
    sparse.assign(PHONE_NUM_4=None).to_parquet(tmp_path / "bare.parquet", index=False)  # nothing left to learn from
    with pytest.raises(InputError, match="can't be estimated|share phone or address"):  # whichever check finds nothing first
        build(tmp_path / "bare.parquet", tmp_path / "bare", s, p)


def test_an_increment_keeps_the_open_review_queue(tmp_path, population):
    from er.report import qa
    from er.jobs.build import build
    from er.jobs.decide import decide
    from er.jobs.update import update
    s, p, g = population
    p = replace(p, threshold=replace(p.threshold, margin_steps=4), fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 6))  # a wide band
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    new = np.random.default_rng(2).random(len(g.df)) < 0.2
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    fields = [f for f in s.columns if f not in ("id", "entity")]
    run = build(tmp_path / "old.parquet", tmp_path / "c", s, p)
    first = qa(run, fields)["review_sheet"]
    first.to_parquet(tmp_path / "c" / "review.parquet")
    open_ = first[first["why"] == "decide"]
    assert len(open_) >= 2
    first.loc[open_.index[:1], "decision"] = "no_match"  # one decided and given back; the rest still open
    first.loc[open_.index[:1]].to_parquet(tmp_path / "given.parquet")
    decide(tmp_path / "given.parquet", tmp_path / "c", s, p)
    inc = update(tmp_path / "new.parquet", tmp_path / "c", s, p)
    sheet = qa(inc, fields, previous=tmp_path / "c" / "review.parquet")["review_sheet"]
    pairs = set(map(tuple, sheet.loc[sheet["why"] == "decide", [l, r]].to_numpy()))
    gold = pd.read_parquet(tmp_path / "c" / "gold.parquet").set_index(uid)["cluster_id"]
    still = {(a, b) for a, b in open_.iloc[1:][[l, r]].to_numpy() if gold[a] != gold[b]}
    assert still and still <= pairs  # still open after the increment
    assert tuple(open_.iloc[0][[l, r]]) not in pairs  # decided: gone


def test_a_run_folder_takes_one_writer_at_a_time(tmp_path, population):
    import threading
    from er.folder import run_lock
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    held, done = threading.Event(), threading.Event()

    def other_job():  # another job holds the folder, in a thread of its own
        with run_lock(tmp_path / "run", make=True):
            held.set()
            done.wait(30)
    job = threading.Thread(target=other_job)
    job.start()
    assert held.wait(30)
    with pytest.raises(InputError, match="another job is writing"):
        build(tmp_path / "all.parquet", tmp_path / "run", s, p)
    done.set()
    job.join(30)
    with run_lock(tmp_path / "run"), run_lock(tmp_path / "run"):  # the thread holding it may take it again (a rerun's full run)
        build(tmp_path / "all.parquet", tmp_path / "run", s, p)  # released by the other: free again


def test_matching_a_batch_names_the_entities_adding_it_would_give_and_writes_nothing(tmp_path, population):
    from er.jobs.build import build
    from er.jobs.update import update, would_join
    s, p, g = population
    uid, half = s.data.unique_id, len(g.df) // 2
    g.df.iloc[:half].to_parquet(tmp_path / "first.parquet", index=False)
    pd.concat([g.df.iloc[half:], g.df.iloc[:1]]).to_parquet(tmp_path / "batch.parquet", index=False)  # one already in the run
    out = tmp_path / "run"
    build(tmp_path / "first.parquet", out, s, p)
    files = lambda: {f: f.read_bytes() for f in out.rglob("*") if f.is_file() and f.name != ".lock"}
    before = files()
    m = would_join(tmp_path / "batch.parquet", out, s, p)
    assert files() == before
    assert m.loc[m[uid] == g.df.iloc[0][uid], "status"].item() == "already in the run"
    assert set(m["status"]) == {"joins an entity", "a new entity", "already in the run"} and len(m) == len(g.df) - half + 1
    update(tmp_path / "batch.parquet", out, s, p)
    gold = pd.read_parquet(out / "gold.parquet").set_index(uid)["cluster_id"]
    assert (gold.loc[m[uid]].to_numpy() == m["entity"].to_numpy()).all()  # the entities the increment then gave


def test_a_sheet_given_back_with_no_decision_is_refused_and_one_typed_with_wide_spaces_is_read(tmp_path):
    import duckdb
    from er.source import decisions
    pd.DataFrame({"uid_l": ["1"], "uid_r": ["2"], "decision": [None]}, dtype="string").to_parquet(tmp_path / "untouched.parquet")
    with pytest.raises(InputError, match="no row has a decision"):
        decisions(tmp_path / "untouched.parquet", DuckDB(duckdb.connect()), "uid_l", "uid_r", into="d")
    pd.DataFrame({"uid_l": ["1", "3"], "uid_r": ["2", "4"], "decision": ["match\u3000", "\u3000No_Match "]}, dtype="string").to_parquet(tmp_path / "typed.parquet")
    engine = DuckDB(duckdb.connect())
    decisions(tmp_path / "typed.parquet", engine, "uid_l", "uid_r", into="d")  # typed on a Japanese keyboard: full-width spaces around
    assert sorted(x for x, in engine.rows("SELECT decision FROM d")) == ["match", "no_match"]


def test_a_run_and_its_reports_land_together_even_when_the_write_is_cut_short(tmp_path, population, monkeypatch):
    import er.folder
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    out, real = tmp_path / "run", er.folder.finish_writes

    def killed(folder):  # the process dies once the moves owed are saved, before it does them
        if (folder / "pending.json").exists():
            raise SystemExit("killed")
        real(folder)
    monkeypatch.setattr(er.folder, "finish_writes", killed)
    with pytest.raises(SystemExit):
        build(tmp_path / "all.parquet", out, s, p, pipeline_file=s.root / "config" / "final.toml")
    monkeypatch.setattr(er.folder, "finish_writes", real)
    again = update(tmp_path / "all.parquet", out, s, p)  # the retry: the next job finishes the moves, and finds nothing new
    assert again.added == 0 and (out / "gold.parquet").exists()
    assert {"qa.md", "report.txt", "review.parquet"} <= {f.name for f in out.iterdir()} and not list(out.rglob("*.tmp"))


def test_an_oversized_block_is_checked_on_a_sample_and_a_placeholder_is_skipped(tmp_path, population):
    from er.jobs.build import build
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    dummy = df.index[:100]
    df.loc[dummy, ["PHONE_NUM_4", "GIVEN_NAME_KANA", "POST_CD"]] = ["0000", "タロウ", "1500042"]  # a dummy phone, and one given name and postal code: blocks of 100
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = build(tmp_path / "in.parquet", tmp_path / "run", s, p, pipeline_file=s.root / "config" / "final.toml")  # no stop
    assert any("phone = 0000" in x and "placeholder" in x for x in run.examples)  # most of the pairs sharing a phone: read as missing, no block
    assert not run.gated["value"].str.contains("0000").any()
    block = run.gated[run.gated["value"].str.contains("タロウ") & (run.gated["generator"] == "given_name_postal")]
    assert len(block) == 1 and block["decision"].iloc[0].startswith("skipped") and block["records"].iloc[0] == 100
    assert any("タロウ" in x and "skipped" in x for x in run.examples) and not any("タロウ" in x for x in run.notes)
    assert "タロウ" not in json.dumps(json.loads((tmp_path / "run" / "steps.json").read_text(encoding="utf-8")), ensure_ascii=False)  # counts, no record's value

    same = pd.concat([g.df.iloc[[0]]] * 70, ignore_index=True)  # 70 copies of one record: every key's block oversized
    same[uid] = [f"copy{i:03d}" for i in range(70)]
    pd.concat([g.df, same]).to_parquet(tmp_path / "copies.parquet", index=False)
    run = build(tmp_path / "copies.parquet", tmp_path / "copies", s, p)
    gold = pd.read_parquet(tmp_path / "copies" / "gold.parquet").set_index(uid)
    assert gold.loc[same[uid], "cluster_id"].nunique() == 1  # the sample shows they match: kept and joined
    assert (run.gated["decision"] == "kept").any()


def test_a_customer_id_held_by_many_records_is_a_placeholder_every_step_and_the_lookup_read_as_missing(tmp_path, population):
    from er.jobs import index
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    many = df.index[:70]
    df.loc[many, "CIF_ID"] = "00000000"  # one customer ID on 70 people: a placeholder
    df.loc[many, "PHONE_NUM_4"] = [f"{1000 + i % 7}" for i in range(len(many))]  # 7 phones: ID and phone together, blocks of 10
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = build(tmp_path / "in.parquet", tmp_path / "run", s, p)
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
    build(tmp_path / "first.parquet", tmp_path / "inc", s, p)
    added = update(tmp_path / "batch.parquet", tmp_path / "inc", s, p)
    assert added.added == 30 and json.loads((tmp_path / "inc" / "state" / "placeholders.json").read_text(encoding="utf-8")) == {"customer_id": ["11111111"]}
    assert any("pairs the run joined on it before stay until a full run" in x for x in added.notes)
    new = pd.read_parquet(sorted((tmp_path / "inc" / "state" / "records").glob("part-*.parquet"))[-1])
    assert new["customer_id"].isna().all() and ("birth_date" not in new or new["birth_date"].isna().all())


def test_the_diagnosis_names_what_limits_the_run_the_most_pairs_first_each_with_its_fix(tmp_path, population):
    from er.match import _ranked, review_floor, search_floor
    from er.report import SHOWN, diagnosis, diagnosis_lines, qa
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    run = build(tmp_path / "in.parquet", tmp_path / "run", s, p)
    tables, lo, m = qa(run, [f for f in s.columns if f not in ("id", "entity")]), review_floor(run.pipeline), run.scoring["er"]
    said = lambda: diagnosis_lines(diagnosis(run, tables, lo))[1:-1]
    top = {c["output_column_name"]: max(g for g, _ in _ranked(c)) for c in run.scoring["comparisons"]}
    assert said() and len(said()) <= SHOWN
    tables["fill"].loc[tables["fill"]["field"] == "birth_date", "filled"] = 0.1  # a compared field mostly empty, and a column like it
    run.unmapped = pd.DataFrame([dict(column="BORN", filled=0.9, distinct=0.5, looks_like="birth_date", share=0.8)])
    run.engine.run(f"UPDATE scores SET gamma_birth = -1, match_weight = {lo - 1} WHERE rowid IN (SELECT rowid FROM scores LIMIT 5)")
    assert any("birth_date 10% filled" in x and "add BORN to birth_date's sources in config/settings.toml [columns]" in x for x in said())
    m["em_given"] = [dict(session="phone", pairs=100, given_share=0.1)]  # EM taught by households
    assert any(x.startswith("  EM learned households from phone (10%") and "[model] em_rules" in x for x in said())
    near = lambda: next((int(x.split()[0].replace(",", "")) for x in said() if "agree exactly on a name and another field" in x and "the model expects" in x), 0)
    was = near()  # near misses: three pairs from the review floor moved below it, agreeing on the name and the phone
    run.engine.run(f"UPDATE scores SET gamma_name = {top['name']}, gamma_phone = {top['phone']}, match_weight = {lo - 1} WHERE rowid IN (SELECT rowid FROM scores WHERE match_weight >= {lo} LIMIT 3)")
    assert near() == was + 3
    m["filled"]["m"].append(["phone", "exact"])  # a level that learned nothing, holding pairs
    assert any("levels that learned nothing hold pairs" in x and "phone exact" in x for x in said())
    run.gated = pd.DataFrame([dict(generator="phone", value="x", records=900, pairs=404_550, sampled=2000, best=search_floor(run.pipeline) - 1, hits=0, decision="skipped: over capacity")])
    assert any("1 oversized blocks skipped (404,550 pairs)" in x for x in said())
    m["em_pairs"] = {"phone": 40}  # a thin session
    assert any("EM learned from few pairs: phone 40" in x for x in said()) and len(said()) <= SHOWN
    stakes = said()
    assert stakes[0].startswith("  1 oversized blocks skipped")  # the most pairs first
    assert stakes[-1].startswith("  EM learned from few pairs")  # advice, no pairs: last


def test_the_run_report_holds_no_record_value(tmp_path, population):
    import re
    from er.report import qa, report_text
    from er.jobs.build import build
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    df.loc[df.index[:100], ["PHONE_NUM_4", "ADDRESS_ONE"]] = ["0000", "東京都"]  # placeholders: notes that quote a value
    df.loc[df.index[100:170], ["CIF_ID", "FULL_NAME_KANA"]] = ["9999999999999", "ヤマダタロウ"]
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = build(tmp_path / "in.parquet", tmp_path / "run", s, p)
    tables = qa(run, [f for f in s.columns if f not in ("id", "entity")])
    text = report_text(run, tables, s.root / "config" / "final.toml")
    assert any("9999999999999" in x for x in run.examples) and any("0000" in x for x in run.examples)
    assert not re.search(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]", text)  # no kana or kanji: no name, address or town
    assert not any(v in text for c in (uid, "CIF_ID") for v in df[c].dropna())  # no record ID, no customer ID
    expected = (1 - pd.read_parquet(tmp_path / "run" / "matches")["match_probability"]).sum()
    assert next(x for x in run.steps if x["step"] == "cluster")["expected_false"] == round(expected, 2)
    assert f"about {expected:,.{1 if expected >= 1 else 2}f} of them false" in text and "MODEL" in text and "birth_date" in text


@pytest.fixture(scope="module")
def reported(tmp_path_factory, population):  # one full run with a column no field reads, and its report.txt
    from er.jobs.build import build
    s, p, g = population
    d = tmp_path_factory.mktemp("reported")
    g.df.assign(SPARE_PHONE=g.df["PHONE_NUM_4"]).to_parquet(d / "in.parquet", index=False)
    run = build(d / "in.parquet", d / "run", s, p, pipeline_file=s.root / "config" / "final.toml")
    return run, (d / "run" / "report.txt").read_text(encoding="utf-8"), d / "run"


def section(text: str, name: str) -> list[str]:  # a report.txt section's lines, its header first
    return text.split(f"\n{name}")[1].split("\n\n")[0].splitlines()


def test_the_run_report_names_each_column_no_field_reads_and_what_it_looks_like(reported, population):
    _, text, _ = reported
    rows = {x.split()[0]: x.split() for x in section(text, "COLUMNS NOT MAPPED")[2:]}
    assert rows["SPARE_PHONE"][3] == "phone" and "PHONE_NUM_4" not in rows and "CONT_ID" not in rows  # a column a field reads: not listed
    shares = [float(x[4].rstrip("%")) for x in rows.values() if len(x) == 5]
    assert len(shares) > 1 and shares == sorted(shares, reverse=True)  # best fit first
    assert not any(re.search(rf"(?<![0-9a-z]){v}(?![0-9a-z])", text) for v in population[2].df["PHONE_NUM_4"].dropna().unique())  # its values never (a commit hash may hold the digits)


def test_the_run_report_counts_each_score_bands_patterns(reported):
    from er.match import review_floor
    run, text, out = reported
    lines = section(text, "PATTERNS BY SCORE")
    assert lines[1].split()[:3] == ["band", "pairs", "bits"] and [c.name for c in run.pipeline.fs.model.comparisons] == lines[1].split()[3:]
    lo = review_floor(run.pipeline)
    stored = dict(duckdb.sql(f"SELECT match_weight >= {lo}, count(*) FROM read_parquet('{out}/scored/*.parquet') WHERE match_weight >= 0 AND sources IS NOT NULL GROUP BY 1").fetchall())
    shown: dict[bool, int] = {}
    for x in lines[2:]:
        w = x.split()
        if m := re.fullmatch(r"\s+(0 to \S+|\S+ and up): [\d,]+ patterns more, ([\d,]+) pairs", x):  # the rest of a band
            up, n = m.group(1).endswith("and up"), m.group(2)
        else:
            up, n = w[1] == "and", w[3]
        shown[up] = shown.get(up, 0) + int(n.replace(",", ""))
    assert shown == stored and len(lines) > 3


def test_the_run_report_says_what_each_em_session_learned_from(reported):
    run, text, _ = reported
    em = run.model["er"]["em_pairs"]
    assert em and all(n > 0 for n in em.values())
    line = next(x for x in section(text, "MODEL")[:2] if "EM learned from:" in x)
    assert all(f"{f} {n:,} pairs" in line for f, n in em.items())


def test_the_runaway_guard_stops_only_what_would_not_fit(tmp_path, population, monkeypatch):
    from er.jobs.build import build
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    monkeypatch.setattr("er.steps.budget.capacity", lambda engine: 10)
    with pytest.raises(InputError, match="more than fit in memory"):
        build(tmp_path / "in.parquet", tmp_path / "run", s, p)


def test_the_generator_makes_direct_matches_rare_households_their_own_entities_and_reports_how_hard_it_is():
    from design.generate import check, generate, halfwidth, load_reference, load_spec, profile, split_by_entity
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
    code, e = say("resolve", "records", "theirs.parquet", "--workspace", "workspaces/w")
    assert code == 2 and "config/settings.toml [columns]" in e["fix"] and 'id = "customer_no"' in e["fix"]
    g.df.rename(columns={s.data.unique_id: "id"}).to_parquet(tmp_path / "ids.parquet", index=False)  # its ID column named as the field: read as id_2
    code, e = say("resolve", "records", "ids.parquet", "--workspace", "workspaces/w", "--overwrite")
    assert code == 2 and 'id = "id"' in e["fix"] and "id_2" not in e["error"] + e["fix"]  # the file's own name for it


def test_a_file_with_columns_named_as_the_run_names_its_own_runs(say, tmp_path, population):
    s, p, g = population
    df = g.df.assign(KIND=(["Person", "Company"] * len(g.df))[:len(g.df)], Address="somewhere")  # unmapped, named as fields and kinds are
    df.to_parquet(tmp_path / "theirs.parquet", index=False)
    code, r = say("resolve", "records", tmp_path / "theirs.parquet", "--workspace", tmp_path / "run")
    notes = [v for w, v in r["summary"] if w == "note"]
    assert code == 0 and any("column KIND read as KIND_2" in n for n in notes) and any("column Address read as Address_2" in n for n in notes)


def test_the_commands_the_tests_start_run_this_checkout_s_code(tmp_path):  # from a git worktree too, not the venv's checkout
    import subprocess
    import sys
    got = subprocess.run([sys.executable, "-c", "import er; print(er.__file__)"], cwd=tmp_path, capture_output=True, encoding="utf-8", check=True).stdout
    assert Path(got.strip()).resolve().is_relative_to(Path(__file__).resolve().parents[1])


def test_two_people_of_one_household_are_labelled_and_a_copy_of_one_is_not(tmp_path, population):
    from er.report import households
    from er.jobs.build import build
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
    run = build(tmp_path / "in.parquet", tmp_path / "run", s, p, pipeline_file=s.root / "config" / "final.toml")  # with its reports, as nayose runs it
    pairs = f"""SELECT * FROM (VALUES ('{one[uid]}', 'member'), ('{one[uid]}', 'copy')) t("{uid}_l", "{uid}_r")"""
    assert households(run.engine, "records", pairs, uid, run.pipeline) == {(one[uid], "member")}  # the copy: the same given name
    sheet = pd.read_parquet(tmp_path / "run" / "review.parquet")
    assert "household" in sheet and sheet["household"].dtype == bool


def test_a_run_s_progress_follows_this_version_s_steps_when_the_last_run_lacked_one(tmp_path):
    from er import cli, emit, folder
    ws = tmp_path / "ws"
    (ws / "state").mkdir(parents=True)
    old = [{"step": x, "seconds": 1.0, **({"records": 10} if x == "load" else {})} for x in emit.RUN_ORDER if x != "keys"]  # a run before the keys step
    (ws / folder.STEPS).write_text(json.dumps({"runs": [{"steps": old}]}), encoding="utf-8")
    got = cli.last_run(str(ws), "resolve records")
    assert got["order"] == emit.RUN_ORDER and "keys" in got["order"] and got["last"]["candidates"] == 1.0


def test_em_on_fields_learns_one_session_blocked_on_each_and_the_fit_owes_an_increment_no_rerun(population, tmp_path):
    from er.config import Key
    from er.jobs.build import build
    from er.steps.write import run_config
    s, p, g = population
    q = replace(p, fit_rows=30000, fs=replace(p.fs, model=replace(p.fs.model, em_rules=((Key("birth_date"),), (Key("person_name", ("kana_fold",)),)))))
    assert run_config(q, s) == run_config(p, s) != run_config(replace(p, fs=replace(p.fs, min_match_weight=9)), s)  # an increment scores with the stored model
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    run = build(tmp_path / "in.parquet", tmp_path / "w", s, q)
    assert not {"birth_date", "person_name"} & set(run.model["er"]["skipped"])  # both sessions found pairs to learn from


def test_a_comparison_s_own_copy_is_no_step_a_setting_may_name(tmp_path):
    from er.config import COPIES
    from er.settings import load_settings, settings_path
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    for step in COPIES:  # what the comparisons make for themselves: every place that reads a chain refuses it alike
        (tmp_path / "settings.toml").write_text(settings_path().read_text(encoding="utf-8").replace('fold = ["kana_fold"]', f'fold = ["kana_fold", "{step}"]'), encoding="utf-8")
        with pytest.raises(Exception, match="unknown normalizers"):
            load_settings(tmp_path / "settings.toml")


def test_a_result_s_values_reach_json_as_python_s_own():
    from er.emit import plain
    got = plain({"a": np.int64(3), 1: [True, None, "x", 2.5, float("nan"), np.float32(1.5), pd.NA, np.str_("y"), np.bool_(False), (np.nan, pd.NaT)]})
    assert got == {"a": 3, "1": [True, None, "x", 2.5, None, 1.5, None, "y", False, [None, None]]}
    assert [type(x) for x in (got["a"], *got["1"][:4], got["1"][7], got["1"][8])] == [int, bool, type(None), str, float, str, bool]  # numpy's scalars as Python's
