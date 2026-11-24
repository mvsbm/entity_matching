"""The keys a run lists pairs by, as the method names them, and the values read as missing."""

import pandas as pd
import pytest

from er.config import InputError


def _placeholders(population, rows: dict) -> tuple:  # steps.load.placeholders on a table of these columns, as load leaves records
    from types import SimpleNamespace
    from er.steps.job import start
    from er.steps.load import placeholders
    s, p, g = population
    job = start(s, p)
    df = pd.DataFrame(rows, dtype="string")
    job.engine.register("er_rows", df)
    job.engine.run("CREATE TABLE records AS SELECT * FROM er_rows")
    run = SimpleNamespace(job=job, engine=job.engine, notes=job.log.notes, placeholders=placeholders(job, p, "records", {}))
    return run, job.engine.frame("SELECT * FROM records ORDER BY 1")


def test_a_placeholder_is_found_on_records_without_an_id_beside_another_and_read_as_missing_in_every_field_of_its_columns(population):
    s, p, g = population
    uid, n = s.data.unique_id, 1000
    rows = {uid: [f"r{i:04d}" for i in range(n)], "customer_id": [None] * n,  # no record with a customer ID: each a customer of its own
            "person_name": ["テスト"] * 200 + [f"ナマエ{i}" for i in range(n - 200)], "full_name": ["テスト"] * 200 + [f"ナマエ{i}" for i in range(n - 200)],
            "birth_date": ["19000101"] * 200 + ["11111111"] * 200 + [f"19{50 + i % 50:02d}{1 + i % 12:02d}{1 + i % 28:02d}" for i in range(n - 400)]}
    run, out = _placeholders(population, rows)
    assert set(run.placeholders) == {"person_name", "birth_date"} and set(run.placeholders["birth_date"]) == {"19000101", "11111111"}  # neither hides the other
    assert out["person_name"].iloc[:200].isna().all() and out["full_name"].iloc[:200].isna().all()  # the name read into full_name too: no rule reads it
    assert out["full_name"].iloc[200:].notna().all()


def test_copies_of_one_customer_s_record_are_no_crowd_and_a_known_placeholder_is_not_new_again(population):
    s, p, g = population
    uid = s.data.unique_id
    rows = {uid: [f"c{i:03d}" for i in range(70)], "customer_id": ["C1"] * 70, "person_name": ["サトウハナコ"] * 70, "phone": ["1234"] * 70}
    run, out = _placeholders(population, rows)
    assert "person_name" not in run.placeholders and "phone" not in run.placeholders and out["person_name"].notna().all()  # one customer's 70 copies
    from er.steps.load import placeholders
    run.job.log.notes.clear()
    run.engine.run("UPDATE records SET phone = '1234'")
    placeholders(run.job, p, "records", {"phone": ["1234"]})
    assert out is not None and not any(x.startswith("phone:") for x in run.job.log.notes)  # read as missing as before, and not said again
    assert run.engine.value("SELECT count(*) FROM records WHERE phone IS NOT NULL") == 0


def test_a_short_phone_held_by_many_records_each_is_kept_and_a_dummy_far_past_them_is_still_read_as_missing(population):
    s, p, g = population
    uid = s.data.unique_id
    phones = [f"{i % 100:04d}" for i in range(20_000)] + ["9999"] * 3_000  # 100 values, 200 customers each, as 4 digits on a large file; one dummy
    rows = {uid: [f"r{i:05d}" for i in range(len(phones))], "customer_id": [None] * len(phones), "phone": phones}
    run, out = _placeholders(population, rows)
    assert run.placeholders == {"phone": ["9999"]} and out["phone"].notna().sum() == 20_000


@pytest.fixture(scope="module")
def ran(population, tmp_path_factory):
    from er.jobs.build import build
    s, p, g = population
    d = tmp_path_factory.mktemp("keys")
    g.df.to_parquet(d / "in.parquet", index=False)
    return s, p, g, d, build(d / "in.parquet", d / "ws", s, p)


def test_a_run_lists_by_every_key_the_method_names_and_keeps_none_of_its_own(ran):
    s, p, g, d, run = ran
    listed = [x["name"] for x in next(x for x in run.steps if x["step"] == "candidates")["generators"]]
    assert sorted(listed) == sorted(b.name for b in run.pipeline.fs.blockers) == sorted(b.name for b in p.fs.blockers)
    assert not (d / "ws" / "state" / "keys.json").exists() and not {"keys", "probe", "gap"} & {x["step"] for x in run.steps}


def test_a_pipeline_with_a_table_it_does_not_read_is_refused(ran, population):
    from er.config import pipeline_from
    import tomllib
    s, p, g, d, run = ran
    cfg = tomllib.loads((s.root / "config" / "pipeline.toml").read_text(encoding="utf-8"))
    with pytest.raises(InputError, match=r"\[keys\] sets nothing") as e:
        pipeline_from({**cfg, "keys": {"records": 50_000}}, s.standardize, s.chains)
    assert e.value.fix == "delete [keys]"
    with pytest.raises(InputError, match=r"\[budget\]: max_block_size sets nothing") as e:
        pipeline_from({**cfg, "budget": {**cfg["budget"], "max_block_size": 5000}}, s.standardize, s.chains)
    assert e.value.fix == "delete max_block_size from [budget]"

