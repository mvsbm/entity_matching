"""The rehearsal (nayose rehearse records): a generated file of the same size and shape, run and measured."""
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest


def test_a_rehearsal_runs_a_file_of_the_same_size_and_shape_and_measures_it(say, tmp_path, population, monkeypatch):
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
    assert not (ws / "rehearsal").exists() and json.loads((ws / "rehearsal.json").read_text())["records"] == r["records"]  # what it made, gone; its result, kept
    assert "names repeat" in r["limit"]
    from er import auto
    fake = tmp_path / "python"  # a run that stops as one out of memory does: said, as the real file's would be
    fake.write_text('#!/bin/sh\necho \'{"event": "error", "error": "out of memory: could not allocate", "fix": "raise --compute memory_limit"}\'\nexit 2\n')
    fake.chmod(0o755)
    monkeypatch.setattr(auto.sys, "executable", str(fake))
    code, e = say("rehearse", "records", "--workspace", ws)
    assert code == 2 and "stopped here: out of memory" in e["error"] and e["fix"] == "raise --compute memory_limit" and not (ws / "rehearsal").exists()
    fake.write_text(f'#!/bin/sh\ncp "$7/method.toml" {tmp_path}/seen.toml\necho \'{{"event": "step", "step": "load", "seconds": 1.0}}\'\n'
                    'echo "Traceback (most recent call last):"\necho "duckdb.IOException: No space left on device"\nexit 1\n')
    code, e = say("rehearse", "records", "--workspace", ws)  # it died without saying why: its last words
    assert code == 2 and "No space left on device" in e["error"] and (tmp_path / "seen.toml").read_text() == (ws / "method.toml").read_text()  # the workspace's method
    fake.write_text('#!/bin/sh\necho \'{"event": "step", "step": "budget", "seconds": 0.1, "pairs": 7}\'\nexit 0\n')
    code, done = say("rehearse", "records", "all.parquet", "--workspace", ws)  # the file named: kept in what to run next
    assert code == 0 and done["pairs"] == 7 and "all.parquet" in done["next"][0]["command"]
    say("add", "feature", "Name/Kanji name", "--type", "person name", "--script", "kanji", "--workspace", ws)
    (ws / "method.toml").write_text('trust = "none"\nadd_keys = [["person_name_2"], ["phone", "birth_date"]]\n', encoding="utf-8")
    fake.write_text(f'#!/bin/sh\ncp "$7/method.toml" {tmp_path}/seen.toml\nexit 0\n')
    assert say("rehearse", "records", "--workspace", ws)[0] == 0  # a key on a name added to the workspace: the generated file holds none
    assert (tmp_path / "seen.toml").read_text() == 'trust = "none"\nadd_keys = [["phone", "birth_date"]]\n'
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


def test_a_rehearsal_stopped_midway_leaves_nothing_behind(tmp_path, monkeypatch):
    from er import auto
    from er.settings import load_settings
    s = load_settings()
    temp = Path(auto.connect(s.compute)[0].execute("SELECT current_setting('temp_directory')").fetchall()[0][0])
    stale = temp / "rehearsal-999999"  # what a rehearsal killed outright left: its process is gone
    stale.mkdir(parents=True, exist_ok=True)
    fake = tmp_path / "python"  # a run that goes on and on
    fake.write_text(f'#!/bin/sh\necho $$ > {tmp_path}/pid\necho \'{{"event": "step", "step": "load", "seconds": 1.0}}\'\nexec sleep 60\n')
    fake.chmod(0o755)
    monkeypatch.setattr(auto.sys, "executable", str(fake))
    def emit(e):  # the progress can't be passed on: the page that asked is gone
        if e["step"].startswith("rehearse"):
            raise BrokenPipeError("gone")
    ws, t = tmp_path / "ws", time.perf_counter()
    ws.mkdir()
    with pytest.raises(BrokenPipeError):
        auto.rehearse(ws, dict(records=300, fields={"full_name": 0.9}, company=0.0), s, None, emit)
    assert time.perf_counter() - t < 30 and not stale.exists() and not (ws / "rehearsal").exists() and not (ws / "rehearsal.json").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid").read_text()), 0)  # the run stopped with it


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
            return 75, dict(event="error", error="another job is writing to it", fix="wait")
        return real(words, step, emit)
    monkeypatch.setattr(auto, "nayose", other)
    code, e = say("try", "everything", "bare.parquet")
    assert code == 75 and [x["step"] for x in e["steps"]] == ["workspace", "load"] and taken[0].is_dir() and Path(e["workspace"]).name != taken[0].name
