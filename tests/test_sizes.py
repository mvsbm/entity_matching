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


def test_a_run_with_em_choose_keeps_each_session_s_verdict_in_its_model_and_the_report_shows_them(ran, tmp_path):
    from er.config import em_candidates
    from er.run import Run
    s, p, ws = ran
    g = pd.read_parquet(ws.parent / "all.parquet")
    g.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(replace(p, fs=replace(p.fs, model=replace(p.fs.model, em_choose=em_candidates(p)))), s).full(tmp_path / "in.parquet", tmp_path / "w")
    choice = run.model["er"]["em_choice"]
    assert choice and all({"session", "pairs", "kept", "why"} <= set(x) for x in choice)
    assert set(run.model["er"]["em_pairs"]) == {x["session"] for x in choice if x["kept"]} or not any(x["kept"] for x in choice)
    from er.report import qa, report_text
    report = report_text(run, qa(run, [f for f in s.columns if f not in ("id", "entity")]), s.root / "tests" / "method.toml")
    assert "EM SESSIONS" in report and all(x["session"] in report for x in choice)


def test_a_floor_below_0_keeps_the_pairs_down_to_it_and_every_pair_the_default_kept(ran, tmp_path, capsys):
    import duckdb
    from er import cli
    s, p, ws = ran
    low = tmp_path / "low"
    method = (s.root / "tests" / "method.toml").read_text(encoding="utf-8").replace("\n[threshold]\n", "\n[threshold]\nkeep_from = -10\n", 1)  # the floor, set in the pipeline
    (tmp_path / "low.toml").write_text(method, encoding="utf-8")
    assert cli.main(["resolve", "records", str(ws.parent / "all.parquet"), "--workspace", str(low), "--pipeline", str(tmp_path / "low.toml"), "--format", "json"]) == 0
    capsys.readouterr()
    read = lambda w: duckdb.sql(f"SELECT * EXCLUDE (match_probability) FROM read_parquet('{w}/scored/*.parquet')").df()
    before, after = read(ws), read(low)
    model = lambda d: d[d["rule"].isna()]
    assert (model(after)["match_weight"] < 0).any() and (model(after)["match_weight"] >= -10).all()
    key = lambda d: d[d["match_weight"] >= 0].sort_values(list(d.columns[:2])).reset_index(drop=True)
    pd.testing.assert_frame_equal(key(after)[key(before).columns], key(before), check_dtype=False)  # at 0 and up: the same pairs and points


def test_keep_from_changes_the_run_s_hash_only_when_set(ran):
    from er.run import run_config
    s, p, ws = ran
    at = lambda bits: replace(p, threshold=replace(p.threshold, keep_from=bits))
    assert run_config(at(0.0), s) == run_config(p, s) != run_config(at(-10.0), s)
