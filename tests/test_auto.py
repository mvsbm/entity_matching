"""The rehearsal (nayose rehearse records): a generated file of the same size and shape, run and measured."""
import json
import os
import re
import time
import tomllib
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from er.io import alive


def test_a_rehearsal_runs_a_file_of_the_same_size_and_shape_and_measures_it(say, tmp_path, population, monkeypatch, fake_cli):
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    assert say("create", "workspace", "w")[0] == 0
    ws = tmp_path / "workspaces" / "w"
    assert say("load", "records", "all.parquet", "--workspace", ws)[0] == 0
    code, r = say("rehearse", "records", "--workspace", ws)  # the file loaded last: its shape, never its values
    assert code == 0 and r["ok"] and abs(r["records"] - len(g.df)) <= 0.1 * len(g.df)
    assert r["seconds"] > 0 and r["peak_memory_gb"] > 0 and r["peak_spill_gb"] >= 0 and r["pairs"] > 0 and {"load", "fit", "score", "write"} <= set(r["steps"])
    for f in ("full_name", "phone", "birth_date", "postal_code"):  # each field filled as the file is
        assert abs(r["shape"][f]["file"] - r["shape"][f]["rehearsal"]) < 0.05, (f, r["shape"][f])
    assert not (ws / "rehearsal").exists() and json.loads((ws / "rehearsal.json").read_text(encoding="utf-8"))["records"] == r["records"]  # what it made, gone; its result, kept
    assert "names repeat" in r["limit"]
    from er import auto
    seen, run_dir = tmp_path / "seen.toml", 'sys.argv[sys.argv.index("--workspace") + 1]'
    fake_cli('print(json.dumps({"event": "error", "error": "out of memory: could not allocate", "fix": "raise --compute memory_limit"}))\nsys.exit(2)')  # a run that stops as one out of memory does
    code, e = say("rehearse", "records", "--workspace", ws)
    assert code == 2 and "stopped here: out of memory" in e["error"] and e["fix"] == "raise --compute memory_limit" and not (ws / "rehearsal").exists()
    fake_cli(f'shutil.copy(os.path.join({run_dir}, "method.toml"), {str(seen)!r})\nprint(json.dumps({{"event": "step", "step": "load", "seconds": 1.0}}))\n'
             'print("Traceback (most recent call last):")\nprint("duckdb.IOException: No space left on device")\nsys.exit(1)')
    code, e = say("rehearse", "records", "--workspace", ws)  # it died without saying why: its last words
    assert code == 2 and "No space left on device" in e["error"] and (tmp_path / "seen.toml").read_text(encoding="utf-8") == (ws / "method.toml").read_text(encoding="utf-8")  # the workspace's method
    fake_cli('print(json.dumps({"event": "step", "step": "budget", "seconds": 0.1, "pairs": 7}))')
    code, done = say("rehearse", "records", "all.parquet", "--workspace", ws)  # the file named: kept in what to run next
    assert code == 0 and done["pairs"] == 7 and "all.parquet" in done["next"][0]["command"]
    say("add", "feature", "Name/Kanji name", "--type", "person name", "--script", "kanji", "--workspace", ws)
    (ws / "method.toml").write_text('trust = "none"\nadd_keys = [["person_name_2"], ["phone", "birth_date"]]\n', encoding="utf-8")
    fake_cli(f'shutil.copy(os.path.join({run_dir}, "method.toml"), {str(seen)!r})')
    assert say("rehearse", "records", "--workspace", ws)[0] == 0  # a key on a name added to the workspace: the generated file holds none
    assert (tmp_path / "seen.toml").read_text(encoding="utf-8") == 'trust = "none"\nadd_keys = [["phone", "birth_date"]]\n'
    monkeypatch.setattr(auto.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("no such program")))
    with pytest.raises(OSError):
        say("rehearse", "records", "--workspace", ws)
    assert not (ws / "rehearsal").exists() and not list(Path(auto.connect({})[0].execute("SELECT current_setting('temp_directory')").fetchall()[0][0]).glob(f"rehearsal-{os.getpid()}"))
    assert say("rehearse", "records", "--workspace", ws, "--pipeline", tmp_path / "none.toml")[0] == 2  # a pipeline file that isn't there: said


def test_a_generated_file_takes_the_shape_it_is_given_across_its_parts(tmp_path, monkeypatch):
    from er import auto
    from er.settings import load_settings
    monkeypatch.setattr(auto, "CHUNK", 400)  # several parts, each with its own seed
    sh = dict(records=1500, fields={"full_name": 0.9, "address": 0.3, "phone": 0.5}, company=0.0)  # persons only; a third with an address
    assert auto.generated(sh, tmp_path / "a", lambda e: None) == len(df := pd.read_parquet(tmp_path / "a"))
    made = auto.shape(load_settings(), tmp_path / "a")
    assert len(list((tmp_path / "a").glob("part-*.parquet"))) >= 3 and df[load_settings().data.unique_id].is_unique
    assert all(abs(made["fields"].get(f, 0) - v) < 0.05 for f, v in sh["fields"].items()), made["fields"]
    assert "company_name" not in made["fields"]
    s0 = load_settings()
    shared = replace(s0, columns={**s0.columns, "company_name": s0.columns["full_name"]})  # one name column for both kinds: its share isn't the companies'
    assert auto.shape(shared, tmp_path / "a")["company"] is None and auto.shape(s0, tmp_path / "a")["company"] == 0.0
    auto.generated(dict(sh, fields={**sh["fields"], "company_name": 0.9}, company=None), tmp_path / "b", lambda e: None)
    assert 0.1 < auto.shape(load_settings(), tmp_path / "b")["fields"]["company_name"] < 0.35  # the generator's share of companies, not 90%


def test_generated_records_go_into_a_workspace_as_a_file_does_and_the_same_twice_copies_nothing(say, tmp_path):
    from er import folder
    assert say("create", "workspace", "w", "--home", tmp_path)[0] == 0
    ws = tmp_path / "w"
    code, r = say("generate", "records", "--records", "1000", "--difficulty", "easy", "--workspace", ws)
    filled = {f["field"]: f["filled"] for f in r["fields"]}
    assert code == 0 and r["records"] == 1000 and r["copied"] and Path(r["loaded"]).name == "0001-synthetic-easy-1000"
    assert all(filled.get(f) for f in r["needed"]["every"]) and all(any(filled.get(f) for f in grp) for grp in r["needed"]["one_of"])  # a run can start
    assert folder.loaded(ws)[0]["given"] == "synthetic-easy-1000.parquet" and not list(ws.glob(".synthetic-*"))  # one file, named for what it holds; nothing else left
    code, again = say("generate", "records", "--records", "1000", "--difficulty", "easy", "--workspace", ws)
    assert code == 0 and not again["copied"] and len(folder.parts(ws)) == 1  # the same records: held already
    for bad in ("0", "ten", "1.5"):
        code, e = say("generate", "records", "--records", bad, "--workspace", ws)
        assert code == 2 and "whole number" in e["error"]
    assert say("create", "workspace", "theirs", "--home", tmp_path)[0] == 0
    mapping = tmp_path / "theirs" / "columns.toml"
    mapping.write_text(mapping.read_text(encoding="utf-8").replace('id = "CONT_ID"', 'id = "REC_NO"'), encoding="utf-8")  # mapped to a file of their own
    code, e = say("generate", "records", "--records", "1000", "--workspace", tmp_path / "theirs")
    assert code == 2 and "other columns" in e["error"] and not list((tmp_path / "theirs").glob(".synthetic-*")) and not folder.parts(tmp_path / "theirs")


def test_each_difficulty_is_harder_to_match_than_the_one_before():
    from er import cli
    from er.generate import generate, load_reference, load_spec, profile
    from er.settings import load_settings
    s = load_settings()
    path, ref = s.root / "config" / "generator.toml", load_reference(s.paths["reference"])
    levels = next(p.choices for c in cli.COMMANDS if (c.verb, c.noun) == ("generate", "records") for p in c.params if p.name == "difficulty")
    assert set(levels) == set(tomllib.loads(path.read_text(encoding="utf-8"))["difficulty"])  # the command offers the levels the generator has
    got = [profile(generate(replace(load_spec(path, x)[0], entities=2000), *ref)) for x in levels]
    direct, lost = [x["direct (exact rules)"] for x in got], [x["nothing in common"] for x in got]
    assert direct == sorted(direct, reverse=True) and lost == sorted(lost) and len(set(direct)) == len(set(lost)) == len(levels), (direct, lost)
    assert load_spec(path, "medium")[0] == load_spec(path)[0]  # medium: the generator as calibrated


def test_a_rehearsal_stopped_midway_leaves_nothing_behind(tmp_path, monkeypatch, fake_cli):
    from er import auto
    from er.settings import load_settings
    s = load_settings()
    temp = Path(auto.connect(s.compute)[0].execute("SELECT current_setting('temp_directory')").fetchall()[0][0])
    stale = temp / "rehearsal-999999"  # what a rehearsal killed outright left: its process is gone
    stale.mkdir(parents=True, exist_ok=True)
    pid = tmp_path / "pid"  # a run that goes on and on
    fake_cli(f'open({str(pid)!r}, "w").write(str(os.getpid()))\nprint(json.dumps({{"event": "step", "step": "load", "seconds": 1.0}}), flush=True)\ntime.sleep(60)')
    def emit(e):  # the progress can't be passed on: the page that asked is gone
        if e["step"].startswith("rehearse"):
            raise BrokenPipeError("gone")
    ws, t = tmp_path / "ws", time.perf_counter()
    ws.mkdir()
    with pytest.raises(BrokenPipeError):
        auto.rehearse(ws, dict(records=300, fields={"full_name": 0.9}, company=0.0), s, None, emit)
    assert time.perf_counter() - t < 30 and not stale.exists() and not (ws / "rehearsal").exists() and not (ws / "rehearsal.json").exists()
    assert not alive(int(pid.read_text(encoding="utf-8")))  # the run stopped with it


def test_auto_mode_tries_every_step_and_writes_a_report_that_holds_no_value(say, tmp_path, population, monkeypatch):
    s, p, g = population
    uid, name = s.data.unique_id, s.columns["full_name"][0][0]
    df = g.df.copy()
    planted = {uid: "0004815162342", name: "ヤマモトマサヒコ", s.columns["phone"][0][0]: "090-4815-1623"}  # an ID, a kana name, a phone
    for c, v in planted.items():
        df.loc[0, c] = v
    df.to_parquet(tmp_path / "all.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    code, r = say("try", "everything", "all.parquet", "--trials", "1")
    ws = Path(r["workspace"])
    text = (ws / "auto" / "report.md").read_text(encoding="utf-8")
    assert code == 0 and r["ok"] and all(x["ok"] for x in r["steps"]) and r["redacted"] == 0 and r["values"] > 0 and text == r["markdown"]
    assert [x["step"] for x in r["steps"]][:5] == ["workspace", "load", "check", "rehearse", "resolve"] and "review" in [x["step"] for x in r["steps"]]
    for section in ("## Steps", "## The file", "## Will a run go through", "## The rehearsal, beside the real run", "## The run (report.txt)",
                    "## The method", "## How much people must check", "## Privacy check"):
        assert section in text, section
    assert not any(v in text for v in planted.values()) and str(tmp_path) not in text and "all.parquet" not in text  # no value, no path, no file name
    facts = json.loads((ws / "auto" / "report.json").read_text(encoding="utf-8"))
    assert facts["privacy"] == {"values": r["values"], "redacted": 0} and not any(v in json.dumps(facts, ensure_ascii=False) for v in planted.values())
    assert (ws / "method.toml").read_text(encoding="utf-8").strip() == 'trust = "none"'  # strict as made: it never lowers the line or adopts a method
    assert say("describe", "workspace", ws)[1]["auto"]["markdown"] == text  # the page's Overview shows it


def test_the_report_check_redacts_any_value_long_digits_and_kana_no_column_holds():
    from er.auto import HIDDEN, scrub
    text = "stopped at 0012345678 (sample 1,234,567) · FULL_NAME_KANA: ヤマダタロウ said サトウ · Sato and Satoshi · code a1234567b"
    out, n = scrub(text, {"ヤマダタロウ", "Sato"}, {"FULL_NAME_KANA", "サトウ様"})
    assert out == f"stopped at {HIDDEN} (sample 1,234,567) · FULL_NAME_KANA: {HIDDEN} said サトウ · {HIDDEN} and Satoshi · code a1234567b" and n == 3
    assert scrub("カナ", set(), set()) == (HIDDEN, 1)  # kana no column name holds: a value it can't tell from one
    assert scrub("code 1572846 · id 1572846", set(), set(), frozenset({"1572846"})) == ("code 1572846 · id 1572846", 0)  # a commit all digits: the report's own


def test_auto_mode_writes_its_report_when_a_step_stops_and_waits_out_no_busy_workspace(say, tmp_path, monkeypatch):
    from er import auto
    monkeypatch.chdir(tmp_path)
    pd.DataFrame({"CONT_ID": [f"{i:04d}" for i in range(50)], "NOTE": ["x"] * 50}).to_parquet(tmp_path / "bare.parquet", index=False)
    code, e = say("try", "everything", "bare.parquet")  # no name of any kind: the check stops it
    ws = next((tmp_path / "workspaces").glob("auto-*"))
    text = (ws / "auto" / "report.md").read_text(encoding="utf-8")
    assert code == 2 and not e["ok"] and [x["step"] for x in e["steps"]] == ["workspace", "load", "check"] and not e["steps"][-1]["ok"]
    assert "✗ check" in text and "fix:" in text and "## Privacy check" in text
    real, taken = auto.nayose, []
    def other(words, step, emit):  # another auto mode takes the name first; then the workspace this one makes is busy
        if step == "workspace" and not taken:
            taken.append(Path(words[4]) / words[2])
            assert real(words, step, emit)[0] == 0
        if step == "load":
            return 75, dict(event="error", error="another job is writing to it", fix="wait"), []
        return real(words, step, emit)
    monkeypatch.setattr(auto, "nayose", other)
    code, e = say("try", "everything", "bare.parquet")
    assert code == 75 and [x["step"] for x in e["steps"]] == ["workspace", "load"] and taken[0].is_dir() and Path(e["workspace"]).name != taken[0].name
    def crash(words, step, emit):  # the check crashes: its words go to a log beside the report, never into it
        return (1, dict(event="error", error="crashed: KeyError", fix="its own words are in auto/check.log in the workspace"), ["KeyError: '0012345678'"]) \
            if step == "check" else real(words, step, emit)
    monkeypatch.setattr(auto, "nayose", crash)
    code, e = say("try", "everything", "bare.parquet")
    ws = Path(e["workspace"])
    assert code == 2 and "0012345678" in (ws / "auto" / "check.log").read_text(encoding="utf-8") and "0012345678" not in Path(e["report"]).read_text(encoding="utf-8")
    def stop(words, step, emit):  # Ctrl-C while it loads: what ran is reported
        if step == "load":
            raise KeyboardInterrupt
        return real(words, step, emit)
    monkeypatch.setattr(auto, "nayose", stop)
    code, e = say("try", "everything", "bare.parquet")
    assert code == 130 and [x["step"] for x in e["steps"]] == ["workspace", "stopped"] and "✗ stopped" in Path(e["report"]).read_text(encoding="utf-8")


def test_a_command_that_crashes_says_its_kind_alone_and_one_that_can_t_report_is_stopped(tmp_path, monkeypatch, fake_cli):
    from er import auto
    fake_cli('print("Traceback (most recent call last):")\nprint("KeyError: \'0012345678\'")\nsys.exit(1)')
    code, e, said = auto.nayose(["check", "records", "x"], "check", lambda e: None)
    assert code == 1 and e["error"] == "crashed: KeyError" and "0012345678" not in json.dumps(e) and "0012345678" in said[-1]  # its words, for the log only
    assert e["fix"] == "its own words are in auto/check.log in the workspace"
    pid = tmp_path / "pid"
    fake_cli(f'open({str(pid)!r}, "w").write(str(os.getpid()))\nprint(json.dumps({{"event": "step", "step": "load", "seconds": 1.0}}), flush=True)\ntime.sleep(60)')
    def emit(e):
        raise BrokenPipeError("the page is gone")
    t = time.perf_counter()
    with pytest.raises(BrokenPipeError):
        auto.nayose(["resolve", "records"], "resolve", emit)
    assert time.perf_counter() - t < 20 and not alive(int(pid.read_text(encoding="utf-8")))  # asked to stop, and gone


def test_a_file_without_a_header_puts_no_value_in_the_report_through_its_column_names(say, tmp_path, monkeypatch):
    import random
    rnd = random.Random(1)
    family, given = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺"], ["花子", "一郎", "美咲", "大輔", "陽子", "健太"]
    rows = lambda first: [first] + [f"{i:07d},{rnd.choice(family)}{rnd.choice(given)},サトウハナコ,大阪府大阪市北区{rnd.randint(1, 9)}-{rnd.randint(1, 9)},"
                                    f"06-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)},19{rnd.randint(50, 99)}/0{rnd.randint(1, 9)}/1{rnd.randint(0, 9)}" for i in range(2, 300)]
    planted = ["0000001", "山田太郎", "ヤマダタロウ", "東京都千代田区丸の内1-2-3", "03-1234-5678", "1980/01/02"]
    plain = ["10234", "Ito", "taro@example.com", "株式会社ヤマダ", "S55.1.2", "〒100-0001"]  # a short ID and name; the reader says nothing (no 7 digits alone)
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "nohead.csv").write_text("\n".join(rows(",".join(planted))) + "\n", encoding="utf-8")  # the reader says a header may be missing
    (tmp_path / "words.csv").write_text("\n".join(r.split(",", 1)[1] for r in rows(",".join(planted))) + "\n", encoding="utf-8")  # no number in its first line
    (tmp_path / "plain.csv").write_text("\n".join(rows(",".join(plain))) + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "in")
    for given_as in (".", str(tmp_path / "words.csv"), str(tmp_path / "plain.csv")):  # a folder named ".", a file named in full
        code, r = say("try", "everything", given_as, "--home", str(tmp_path / "home"))
        ws = Path(r["workspace"])
        text, facts = (ws / "auto" / "report.md").read_text(encoding="utf-8"), (ws / "auto" / "report.json").read_text(encoding="utf-8")
        assert code == 2 and r["redacted"] > 0 and "## Privacy check" in text
        assert not any(v in text or v in facts for v in planted + plain), [v for v in planted + plain if v in text or v in facts]
        assert re.search(r"took \d+ min \d+ s", text) and "<file>" not in text.split("## Steps")[0]  # the path put aside, no word garbled
        assert "nohead.csv" not in text + facts and "words.csv" not in text + facts and "plain.csv" not in text + facts and str(tmp_path) not in text + facts


def test_a_report_keeps_the_names_a_real_file_gives_its_columns_and_its_own_words(say, tmp_path, population, monkeypatch):
    s, p, g = population
    df = g.df.copy()
    name = s.columns["full_name"][0][0]
    for c in ("姓", "名", "セイ", "メイ", "カナ", "フリガナ", "郵便番号"):  # names Japanese files give their columns
        df[c] = df[name]
    df["NOTE"] = (["file", "true", "false", "records", "workspace"] * len(df))[:len(df)]  # plain words, as a flag column holds them
    df["BALANCE"], df["VISIT_TIME"], df["CUST_TYPE"] = "12.34", "04:19", (["Person", "Company"] * len(df))[:len(df)]  # numbers and times like the report's own
    df["taro.yamada@example.jp"] = "x"  # one header cell that is a value: it alone is put aside
    (tmp_path / "Yamada Shoji list.csv").write_text(df.to_csv(index=False) + "x,y\n", encoding="utf-8")  # a row it can't read: its part named in a note
    monkeypatch.chdir(tmp_path)
    from er import auto
    real = auto.nayose
    monkeypatch.setattr(auto, "nayose", lambda words, step, emit: (2, dict(event="error", error="the project's mapping names columns the generator doesn't write", fix=""), [])
                        if step == "rehearse" else real(words, step, emit))  # a rehearsal that can't start: the real run still goes
    code, r = say("try", "everything", "Yamada Shoji list.csv", "--trials", "0")
    text = Path(r["report"]).read_text(encoding="utf-8")
    facts = (Path(r["workspace"]) / "auto" / "report.json").read_text(encoding="utf-8")
    assert code == 0 and [x["ok"] for x in r["steps"] if x["step"] in ("rehearse", "resolve")] == [False, True]
    assert "taro.yamada@example.jp" not in text + facts and text.count("[redacted]") == r["redacted"] > 0  # that header alone
    assert not re.search(r"\[redacted\][^|\n]*\[redacted\]", text.split("## Steps")[1].split("## The file")[0])  # the report's own numbers intact
    assert all(f"| {c} |" in text for c in ("姓", "名", "セイ", "メイ", "カナ", "フリガナ", "郵便番号", "NOTE"))  # each column by its name
    assert "Yamada" not in text + facts and "<part>" in facts  # the file's name, and its part's, put aside
    monkeypatch.setattr("er.auto.nayose", lambda words, step, emit: (_ for _ in ()).throw(KeyboardInterrupt))
    from er.cli import main
    assert main(["try", "everything", "Yamada Shoji list.csv", "--format", "json"]) == 130  # stopped as its workspace was being made: said, no report


def test_the_value_check_catches_ids_beside_kana_and_values_beside_kanji():
    from er.auto import HIDDEN, scrub
    out, n = scrub("番号0012345678 · ＩＤ１２３４５６７ · 山田Taro · 𠮷田 · " + "長" * 200, {"Taro", "長" * 200}, {"番号", "ＩＤ", "山田"})
    assert out == f"番号{HIDDEN} · ＩＤ{HIDDEN} · 山田{HIDDEN} · {HIDDEN} · {HIDDEN}" and n == 5, out
