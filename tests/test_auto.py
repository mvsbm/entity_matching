"""The rehearsal (nayose rehearse records): a generated file of the same size and shape, run and measured."""
import json
import os
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
    auto.generated(dict(sh, fields={**sh["fields"], "company_name": 0.9}, company=None), tmp_path / "b", lambda e: None)  # one name column for both kinds
    assert 0.1 < auto.shape(load_settings(), tmp_path / "b")["fields"]["company_name"] < 0.35  # the generator's share of companies, not 90%
