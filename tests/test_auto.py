"""The rehearsal (nayose rehearse records): a generated file of the same size and shape, run and measured."""
import json



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
    assert say("rehearse", "records", "--workspace", ws, "--pipeline", tmp_path / "none.toml")[0] == 2  # a pipeline file that isn't there: said
