"""[threshold] keep_from: the pairs a run keeps below 0 points, and the run's fingerprint."""
from dataclasses import replace

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def ran(tmp_path_factory, population):
    s, p, g = population
    ws = tmp_path_factory.mktemp("keep_from") / "run"
    g.df.to_parquet(ws.parent / "all.parquet", index=False)
    from er.__main__ import main
    assert main(["build", str(ws.parent / "all.parquet"), "--out", str(ws), "--pipeline", str(s.root / "tests" / "method.toml")]) == 0
    return s, p, ws


def test_a_floor_below_0_keeps_the_pairs_down_to_it_and_every_pair_the_default_kept(ran, tmp_path, capsys):
    import duckdb
    from er.__main__ import main
    s, p, ws = ran
    low = tmp_path / "low"
    method = (s.root / "tests" / "method.toml").read_text(encoding="utf-8").replace("\n[threshold]\n", "\n[threshold]\nkeep_from = -10\n", 1)  # the floor, set in the pipeline
    (tmp_path / "low.toml").write_text(method, encoding="utf-8")
    assert main(["build", str(ws.parent / "all.parquet"), "--out", str(low), "--pipeline", str(tmp_path / "low.toml")]) == 0
    capsys.readouterr()
    read = lambda w: duckdb.sql(f"SELECT * EXCLUDE (match_probability) FROM read_parquet('{w}/scored/*.parquet')").df()
    before, after = read(ws), read(low)
    model = lambda d: d[d["rule"].isna()]
    assert (model(after)["match_weight"] < 0).any() and (model(after)["match_weight"] >= -10).all()
    key = lambda d: d[d["match_weight"] >= 0].sort_values(list(d.columns[:2])).reset_index(drop=True)
    pd.testing.assert_frame_equal(key(after)[key(before).columns], key(before), check_dtype=False)  # at 0 and up: the same pairs and points


def test_keep_from_changes_the_run_s_hash_only_when_set(ran):
    from er.steps.write import run_config
    s, p, ws = ran
    at = lambda bits: replace(p, threshold=replace(p.threshold, keep_from=bits))
    assert run_config(at(0.0), s) == run_config(p, s) != run_config(at(-10.0), s)
