"""Stage 2, fit (nayose/sql/comparisons.sql, fit.sql, u.sql, nayose/em.py): the model nayose learns equals the one
er/ learns from the same records, to the last bit: λ, each level's m and u as fitted on the sample, and u measured
again on the file."""
import copy
import json
from dataclasses import replace

import pytest

import nayose
from nayose import em
from nayose.engines import DuckDB


def er_fitted(path, fit_rows: int | None = None, fit_u: float | None = None, file_u: float | None = None):
    from er.config import load_pipeline
    from er.settings import load_settings
    from er.steps.fit import fit
    from er.steps.job import start
    from er.steps.load import load
    s = load_settings()
    p = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    model = replace(p.fs.model, **{k: v for k, v in (("fit_u_max_pairs", fit_u), ("u_max_pairs", file_u)) if v})
    p = replace(p, fs=replace(p.fs, model=model), **({"fit_rows": fit_rows} if fit_rows else {}))
    job = start(s, p)
    loaded = load(job, path)
    return fit(job, loaded.n)


def levels(model_json: dict) -> dict:  # (comparison, label) → (m, u)
    return {(c["output_column_name"], lv["label_for_charts"]): (lv["m_probability"], lv["u_probability"])
            for c in model_json["comparisons"] for lv in c["comparison_levels"] if not lv.get("is_null_level")}


@pytest.mark.parametrize("sizes", [{}, {"fit_rows": 300, "fit_u_max_pairs": 2000, "u_max_pairs": 5000}], ids=["whole", "sampled"])
def test_the_model_is_er_s_to_the_last_bit(tmp_path, population, monkeypatch, sizes):
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    old = er_fitted(tmp_path / "in.parquet", sizes.get("fit_rows"), sizes.get("fit_u_max_pairs"), sizes.get("u_max_pairs"))
    c = copy.deepcopy(nayose.config())
    c["fit"].update(sizes)  # a sample cut from the file, and u sampled on both: the hash's draw, as er's
    monkeypatch.setattr(nayose, "config", lambda: c)
    engine = DuckDB()
    nayose.records(engine, [tmp_path / "in.parquet"])
    em.fit(engine)
    lam, fit_rows, notes = engine.rows("SELECT probability, fit_rows, notes FROM fit")[0]
    assert lam == old.model["probability_two_random_records_match"] and fit_rows == old.model["er"]["fit_rows"]
    for table, want in (("model", old.model), ("scoring", old.scoring)):
        assert {(x, label): (m, u) for x, label, m, u in engine.rows(f"SELECT comparison, label, m, u FROM {table}")} == levels(want)
    notes = json.loads(notes)
    assert {k: notes[k] for k in ("filled", "skipped", "adjusted", "em_pairs")} == {k: old.model["er"][k] for k in ("filled", "skipped", "adjusted", "em_pairs")}
