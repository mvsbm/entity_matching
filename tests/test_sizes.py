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


def test_em_set_to_fields_is_kept_and_try_sample_offers_it_back(ran, capsys, monkeypatch):
    from er import cli, folder
    s, p, ws = ran
    method = (ws / folder.METHOD).read_text(encoding="utf-8") if (ws / folder.METHOD).exists() else None
    assert cli.main(["set", "fit", "--records", "2000", "--em", "birth_date, person_name", "--workspace", str(ws), "--pipeline", str(s.root / "tests" / "method.toml"), "--format", "json"]) == 0
    capsys.readouterr()
    try:
        assert folder.method(ws)["fit"] == {"records": 2000, "em": ["birth_date", "person_name"]}
        monkeypatch.setattr(sizes, "FIRST", 100)
        monkeypatch.setattr(sizes, "SETTLED", 10.0)
        assert cli.main(["try", "sample", "--workspace", str(ws), "--pipeline", str(s.root / "tests" / "method.toml"), "--format", "json"]) == 0
        r = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert r["em_set"] == "birth_date,person_name" and any("--em birth_date,person_name" in x["command"] for x in r["next"])  # its own fields, not the tuned rules
    finally:
        (ws / folder.METHOD).write_text(method, encoding="utf-8") if method is not None else (ws / folder.METHOD).unlink()


def test_choose_em_shows_the_fields_it_keeps_and_sets_each_run_to_choose_them_itself(ran, capsys):
    from er import cli, folder
    from er.config import adjust, em_candidates
    s, p, ws = ran
    method = (ws / folder.METHOD).read_text(encoding="utf-8") if (ws / folder.METHOD).exists() else None
    try:
        assert cli.main(["choose", "em", "--workspace", str(ws), "--records", "2000", "--pipeline", str(s.root / "tests" / "method.toml"), "--format", "json"]) == 0
        r = json.loads(capsys.readouterr().out.splitlines()[-1])
        cols = list(pd.read_parquet(ws / "state" / "records").columns)
        judged = [" + ".join(k.column for k in rule) for rule in em_candidates(index.to_file(s, p, cols))]
        assert [x["session"] for x in r["sessions"]] == [x for x in judged if x in {y["session"] for y in r["sessions"]}] and r["sessions"]
        assert "customer_id" not in judged and "given_name" not in judged  # an identifying field, and the given name alone, never judged
        assert r["kept"] == [x["field"] for x in r["sessions"] if x["kept"]] and r["kept"], r["sessions"]
        assert folder.method(ws)["fit"] == {"records": 2000, "em": "choose"} and r["next"][0]["command"].startswith("nayose rerun records")
        q = adjust(p, folder.method(ws))
        assert q.fs.model.em_choose and q.fit_rows == 2000  # the next run's fit chooses again, with the median and the fallback
    finally:
        (ws / folder.METHOD).write_text(method, encoding="utf-8") if method is not None else (ws / folder.METHOD).unlink(missing_ok=True)


def test_a_run_with_em_choose_keeps_each_session_s_verdict_in_its_model_and_the_report_shows_them(ran, tmp_path):
    from er.config import adjust
    from er.run import Run
    s, p, ws = ran
    g = pd.read_parquet(ws.parent / "all.parquet")
    g.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(adjust(p, {"fit": {"em": "choose"}}), s).full(tmp_path / "in.parquet", tmp_path / "w")
    choice = run.model["er"]["em_choice"]
    assert choice and all({"session", "pairs", "kept", "why"} <= set(x) for x in choice)
    assert set(run.model["er"]["em_pairs"]) == {x["session"] for x in choice if x["kept"]} or not any(x["kept"] for x in choice)
    from er.report import qa, report_text
    report = report_text(run, qa(run, [f for f in s.columns if f not in ("id", "entity")]), s.root / "tests" / "method.toml")
    assert "EM SESSIONS" in report and all(x["session"] in report for x in choice)


def test_a_floor_below_0_keeps_the_pairs_down_to_it_and_every_pair_the_default_kept(ran, tmp_path, capsys):
    import shutil
    import duckdb
    from er import cli
    s, p, ws = ran
    low = tmp_path / "low"
    shutil.copytree(ws, low)
    read = lambda w: duckdb.sql(f"SELECT * EXCLUDE (match_probability) FROM read_parquet('{w}/scored/*.parquet')").df()
    before = read(ws)
    pipeline = ["--pipeline", str(s.root / "tests" / "method.toml")]  # as the run was made
    assert cli.main(["set", "floor", "--points", "-10", "--workspace", str(low), *pipeline, "--format", "json"]) == 0
    assert cli.rerun_owed({"workspace": str(low), "pipeline": pipeline[1]})  # stored pairs change: the run owes a rerun
    assert cli.main(["rerun", "records", "--workspace", str(low), *pipeline, "--format", "json"]) == 0
    capsys.readouterr()
    after = read(low)
    model = lambda d: d[d["rule"].isna()]
    assert (model(after)["match_weight"] < 0).any() and (model(after)["match_weight"] >= -10).all()
    key = lambda d: d[d["match_weight"] >= 0].sort_values(list(d.columns[:2])).reset_index(drop=True)
    pd.testing.assert_frame_equal(key(after)[key(before).columns], key(before), check_dtype=False)  # at 0 and up: the same pairs and points


def test_keep_in_method_toml_is_a_number_and_changes_the_run_s_hash_only_when_set(ran):
    from er.config import adjust
    from er.run import run_config
    s, p, ws = ran
    assert run_config(adjust(p, {"keep": 0}), s) == run_config(p, s) != run_config(adjust(p, {"keep": -10}), s)
    assert adjust(p, {"keep": -10}).threshold.keep_from == -10
    for bad in ("low", True, float("inf")):
        with pytest.raises(InputError, match="keep"):
            adjust(p, {"keep": bad})
