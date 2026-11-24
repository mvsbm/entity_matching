"""An update and a lookup (records.sql, fit.sql, score.sql on a batch; lookup.sql) against er/'s, on the tests'
population: a batch whose records bring a placeholder past the line (one phone on 72 records, two of them the run's
already), its pairs, rule pairs, entities and u as er/'s increment makes them, the run's two read as missing; lookups
of stored records and of typed values as er/'s; and a batch given twice adding nothing. (er/'s lookup reads a run's
record as it was before a later batch made one of its values a placeholder, its index never told: nayose reads it as
its increment scored it, missing. So the lookups are compared on an update that brings none.)"""
import pandas as pd
import pytest

import nayose
from nayose.engines import DuckDB


@pytest.mark.parametrize("crowd", [True, False], ids=["a batch's placeholder", "lookups"])
def test_an_update_and_lookups_are_er_s_and_a_batch_given_twice_adds_nothing(tmp_path, population, crowd):
    from er.config import load_pipeline
    from er.jobs import index
    from er.jobs.build import build
    from er.jobs.update import update
    from er.settings import load_settings
    _, _, g = population
    s = load_settings()
    p = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    first, rest = g.df.iloc[: len(g.df) // 2].copy(), g.df.iloc[len(g.df) // 2:].copy()
    first.loc[first.index[:2], "PHONE_NUM_4"] = "4321"
    many = g.df.head(70).copy().assign(CONT_ID=[f"9{i:09d}" for i in range(70)], PHONE_NUM_4="4321", CIF_ID=None) if crowd else g.df.head(0)
    first.to_parquet(tmp_path / "first.parquet", index=False)
    pd.concat([rest, many]).to_parquet(tmp_path / "batch.parquet", index=False)
    run = tmp_path / "run"
    build(tmp_path / "first.parquet", run, s, p)
    update(tmp_path / "batch.parquet", run, s, p)
    engine = DuckDB()
    nayose.build(engine, [tmp_path / "first.parquet"])
    nayose.update(engine, [tmp_path / "batch.parquet"])

    uid = s.data.unique_id
    ids = {f"{uid}_l": "id_l", f"{uid}_r": "id_r"}
    old = pd.read_parquet(run / "scored").rename(columns=ids).sort_values(["id_l", "id_r"], ignore_index=True)
    new = engine.frame("SELECT * FROM scored ORDER BY id_l, id_r")[list(old.columns)]
    assert len(new) == len(old) and new.astype("string").fillna("").equals(old.astype("string").fillna(""))
    rules = pd.read_parquet(run / "rule_kept").rename(columns={f"{uid}_l": "l", f"{uid}_r": "r"}).sort_values(["l", "r"], ignore_index=True)
    assert engine.frame("SELECT l, r, rule FROM rule_pairs ORDER BY l, r").equals(rules[["l", "r", "rule"]])
    gold = pd.read_parquet(run / "gold.parquet").rename(columns={uid: "id"}).sort_values("id", ignore_index=True)
    assert engine.frame("SELECT id, cluster_id, customer_kind FROM gold ORDER BY id").astype("string").equals(gold[["id", "cluster_id", "customer_kind"]].astype("string"))
    if crowd:
        assert engine.rows("SELECT field, value FROM placeholders") == [("phone", "4321")]
        assert engine.value("SELECT COUNT(*) FROM records WHERE batch = 0 AND phone IS NULL AND id IN UNNEST(@two)", {"two": list(first[uid][:2])}) == 2
        return

    drop = lambda x: {k: drop(v) for k, v in x.items() if k not in ("seconds", "index")} if isinstance(x, dict) else [drop(v) for v in x] if isinstance(x, list) else x
    for rid in list(g.df[uid].sample(5, random_state=3)):
        want, got = drop(index.look_up(run, s, p, record=rid)), nayose.lookup(engine, record=rid)
        assert {**got, "record": {k: v for k, v in got["record"].items() if k != "id"}} == {**want, "record": {k: v for k, v in want["record"].items() if k != uid}}
    for values in ({"FULL_NAME_KANA": first["FULL_NAME_KANA"].dropna().iloc[0], "PHONE_NUM_4": "1234"}, {"POST_CD": first["POST_CD"].dropna().iloc[0]}):
        want, got = drop(index.look_up(run, s, p, values=values)), nayose.lookup(engine, values=values)
        assert {**got, "record": {k: v for k, v in got["record"].items() if k != "id"}} == {**want, "record": {k: v for k, v in want["record"].items() if k != uid}}
    assert engine.value("SELECT COUNT(*) FROM records") == len(g.df)  # a lookup writes nothing

    before = engine.value("SELECT COUNT(*) FROM scored")
    nayose.update(engine, [tmp_path / "batch.parquet"])
    assert engine.value("SELECT COUNT(*) FROM scored") == before and engine.value("SELECT COUNT(*) FROM set_aside WHERE reason = 'already in the run'") == len(rest)
