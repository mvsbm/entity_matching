import json
from dataclasses import replace

import pandas as pd
import pytest

from er import index, sizes
from er.config import InputError
from er.match import fit_model
from er.run import BLOCKS


@pytest.fixture(scope="module")
def ran(tmp_path_factory, population):
    s, p, g = population
    ws = tmp_path_factory.mktemp("sizes") / "run"
    g.df.to_parquet(ws.parent / "all.parquet", index=False)
    from er import cli
    assert cli.main(["resolve", "records", str(ws.parent / "all.parquet"), "--workspace", str(ws), "--pipeline", str(s.root / "tests" / "method.toml"), "--format", "json"]) == 0
    return s, p, ws


def test_a_kept_pair_rescored_from_its_levels_has_the_points_the_run_gave_it(ran):
    s, p, ws = ran
    model = json.loads((ws / "state" / "scoring.json").read_text(encoding="utf-8"))["model"]
    n = len(pd.read_parquet(ws / "state" / "records"))
    import duckdb
    con = duckdb.connect()
    got = con.execute(f"SELECT max(abs(({sizes.score_sql(*sizes.weights(model, n))}) - match_weight)), count(*) FROM read_parquet('{ws}/scored/*.parquet')").fetchall()[0]
    assert got[1] > 0 and got[0] < 1e-9
    assert isinstance(json.loads((ws / "state" / BLOCKS).read_text(encoding="utf-8")), dict)  # the blocks the run listed, for the check


def test_the_keys_way_learns_in_the_method_s_keys_as_a_run_s_fit_does_not_those_the_run_kept(ran):
    s, p, ws = ran
    cols = list(pd.read_parquet(ws / "state" / "records").columns)
    first = next(b for b in p.fs.blockers if hasattr(b, "keys"))
    (ws / "state" / "keys.json").write_text(json.dumps({}), encoding="utf-8")  # a run that kept no key of the method
    try:
        assert index.fitted(ws, s, p, cols).fs.blockers == ()
        way = sizes.models(index.to_file(s, p, cols))["keys"]
        assert first.keys in way.em_rules and way.em_rules == fit_model(replace(index.to_file(s, p, cols).fs, model=replace(p.fs.model, em_from_keys=True))).em_rules
    finally:
        (ws / "state" / "keys.json").unlink()


def test_sizes_settle_at_the_first_of_two_quiet_steps(ran, monkeypatch):
    s, p, ws = ran
    monkeypatch.setattr(sizes, "FIRST", 100)
    monkeypatch.setattr(sizes, "SETTLED", 10.0)  # every step after the first changes nothing
    r = sizes.grow(ws, s, p)
    for way in r["chosen"]:
        fitted = [x["records"] for x in r["steps"] if x["em"] == way and "error" not in x]
        assert r["settled"][way] == fitted[1] and len(fitted) == 3, (way, fitted)  # the second size, the first quiet one; the third confirmed it, and no fourth was fitted
    assert r["settled"] and all(x["floor"] == r["floor"] for x in r["steps"])


def test_a_model_adjusting_by_term_frequency_is_refused(ran, monkeypatch):
    s, p, ws = ran
    monkeypatch.setattr(index, "run_model", lambda ws: {"er": {"tf": True}})
    with pytest.raises(InputError, match="term frequency"):
        sizes.grow(ws, s, p)


def test_a_fit_set_after_the_run_owes_a_rerun_but_no_increment_refuses(ran, capsys):
    from er import cli, folder
    s, p, ws = ran
    look = lambda: (cli.main(["describe", "workspace", str(ws), "--format", "json"]), json.loads(capsys.readouterr().out.splitlines()[-1]))[1]
    assert not look()["rerun_owed"]
    method = (ws / folder.METHOD).read_text(encoding="utf-8") if (ws / folder.METHOD).exists() else None
    assert cli.main(["set", "fit", "--records", "64000", "--em", "keys", "--workspace", str(ws), "--format", "json"]) == 0
    capsys.readouterr()
    try:
        assert look()["rerun_owed"]  # the next run fits otherwise
        from er.config import adjust
        from er.run import run_config
        assert (ws / "state" / "config.txt").read_text(encoding="utf-8") == run_config(adjust(p, folder.method(ws)), s)  # an increment and a lookup take it as it was
    finally:
        (ws / folder.METHOD).write_text(method, encoding="utf-8") if method is not None else (ws / folder.METHOD).unlink()
