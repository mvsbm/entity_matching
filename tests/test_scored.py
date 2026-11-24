"""Stage 3, score (nayose/sql/score.sql): the pairs a match run offers people equal er/'s, row by row: the rules' pairs and
their rule, every pair from keep_from bits up, its sources, its levels and its weight to the last bit; and an oversized
block (one given name and postal code on 70 records) gated as er/ gates it."""
import json

import pandas as pd

import nayose
from nayose.engines import DuckDB


def test_the_scored_pairs_and_the_gate_are_er_s(tmp_path, population):
    from er.config import load_pipeline
    from er.jobs.build import build
    from er.settings import load_settings
    s, _, g = population
    crowd = g.df[g.df["FULL_NAME_KANA"].notna()].head(70).copy()
    crowd["CONT_ID"] = [f"9{i:09d}" for i in range(len(crowd))]
    crowd["GIVEN_NAME_KANA"], crowd["POST_CD"] = "タロウ", "1000005"  # given_name_postal's block of 70: no placeholder, a key too big
    pd.concat([g.df, crowd]).to_parquet(tmp_path / "in.parquet", index=False)
    er = load_settings()
    run = build(tmp_path / "in.parquet", tmp_path / "run", er, load_pipeline(er.root / "config" / "pipeline.toml", er.standardize, er.chains, er.columns))
    engine = DuckDB()
    nayose.records(engine, [tmp_path / "in.parquet"])
    nayose.fit(engine)
    nayose.score(engine)
    uid = er.data.unique_id
    old = pd.read_parquet(tmp_path / "run" / "scored").rename(columns={f"{uid}_l": "id_l", f"{uid}_r": "id_r"})
    new = engine.frame("SELECT * FROM scored")
    key = ["id_l", "id_r"]
    cols = ["match_weight", "match_probability", "sources", "rule", "named", *(c for c in old.columns if c.startswith("gamma_"))]
    both = old.merge(new, on=key, how="outer", suffixes=("_er", "_nayose"), indicator=True)
    assert (both["_merge"] == "both").all() and len(both) == len(old)
    assert [c for c in cols if not both[f"{c}_er"].astype("string").fillna("").equals(both[f"{c}_nayose"].astype("string").fillna(""))] == []
    gate = next(x for x in run.steps if x["step"] == "candidates")
    decided = dict(engine.rows("SELECT decision = 'kept', COUNT(*) FROM gated GROUP BY 1"))
    assert (decided.get(True, 0), decided.get(False, 0)) == (gate["oversized_kept"], gate["oversized_skipped"]) and sum(decided.values()) > 0
    assert json.loads(engine.value("SELECT TO_JSON_STRING(ARRAY_AGG(DISTINCT rule IGNORE NULLS)) FROM rule_pairs"))  # the rules found some
