"""Every job's tables on the tests' population, held to the results recorded in tests/fixtures/parity.json: each
table's digest (its rows in order, floats to 9 places).
A build with two crowds of 70 (one block gated and skipped, one kept), match runs and two rounds of people's
decisions; an update whose batch brings a placeholder past the line; lookups of stored records and of typed values.
A change that moves any is a change of results: say so in its pull request, and write the digests again
(NAYOSE_PARITY_WRITE=1)."""
import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd
import pytest

import nayose
from nayose.engines import DuckDB

GOLDEN = Path(__file__).parent / "fixtures" / "parity.json"
TABLES = {  # each table as compared: its rows in an order of their own
    "records": "SELECT * EXCEPT (name_p, batch, person_name__kana_fold_letters_lo, person_name__kana_fold_letters_hi) FROM records ORDER BY id",
    "model": "SELECT comparison, gamma, label, m, u, file_m, file_u, bits FROM model ORDER BY comparison, gamma",
    "fit": "SELECT probability, fit_rows, records, prior_bits FROM fit",
    "scored": "SELECT * FROM scored ORDER BY id_l, id_r",
    "rule_pairs": "SELECT * FROM rule_pairs ORDER BY l, r",
    "gated": "SELECT g, value, records, decision FROM gated ORDER BY g, value",
    "placeholders": "SELECT * FROM placeholders ORDER BY field, value",
    "gold": "SELECT * FROM gold ORDER BY id",
}


def digest(frame: pd.DataFrame) -> str:
    rounded = frame.apply(lambda c: c.round(9) if c.dtype.kind == "f" else c)
    return f"{len(frame)}:" + hashlib.sha256(rounded.to_csv(index=False, na_rep="").encode()).hexdigest()[:16]


def taken(engine: DuckDB, step: str, out: dict) -> None:
    for name, sql in TABLES.items():
        out[f"{step}.{name}"] = digest(engine.frame(sql))


@pytest.fixture(scope="module")
def got(tmp_path_factory, population) -> dict:
    g = population
    tmp, out = tmp_path_factory.mktemp("parity"), {}
    named = g.df[g.df["FULL_NAME_KANA"].notna()]
    crowd, kin = named.head(70).copy(), named.iloc[70:140].copy()
    crowd["CONT_ID"], kin["CONT_ID"] = [f"9{i:09d}" for i in range(70)], [f"8{i:09d}" for i in range(70)]
    crowd["GIVEN_NAME_KANA"], crowd["POST_CD"] = "タロウ", "1000005"
    kin["FULL_NAME_KANA"], kin["GIVEN_NAME_KANA"], kin["POST_CD"], kin["CIF_ID"] = "ヤマダ ハナコ", "ハナコ", "1500001", ["80000001", "80000002"] * 35
    pd.concat([g.df, crowd, kin]).to_parquet(tmp / "in.parquet", index=False)
    engine = DuckDB()
    nayose.build(engine, [tmp / "in.parquet"])
    taken(engine, "build", out)
    nayose.match(engine, 6.0)
    out["match"] = digest(engine.frame("SELECT * FROM matched"))
    said = engine.frame("SELECT id_l, id_r, CASE WHEN rule IS NOT NULL OR match_weight >= 12 THEN 'match' ELSE 'no_match' END AS decision FROM matched")
    flipped = said.assign(decision=said["decision"].where(said.index % 3 > 0, said["decision"].map({"match": "no_match", "no_match": "match"})))
    for i, d in enumerate([said, flipped]):
        d.to_parquet(tmp / f"d{i}.parquet", index=False)
        nayose.decide(engine, [tmp / f"d{i}.parquet"])
        out[f"decide{i}.gold"] = digest(engine.frame(TABLES["gold"]))
    nayose.match(engine, 6.0)
    out["match_again"] = digest(engine.frame("SELECT * FROM matched"))

    first, rest = g.df.iloc[: len(g.df) // 2].copy(), g.df.iloc[len(g.df) // 2:].copy()
    first.loc[first.index[:2], "PHONE_NUM_4"] = "4321"
    many = g.df.head(70).copy().assign(CONT_ID=[f"9{i:09d}" for i in range(70)], PHONE_NUM_4="4321", CIF_ID=None)
    first.to_parquet(tmp / "first.parquet", index=False)
    pd.concat([rest, many]).to_parquet(tmp / "batch.parquet", index=False)
    engine = DuckDB()
    nayose.build(engine, [tmp / "first.parquet"])
    nayose.update(engine, [tmp / "batch.parquet"])
    taken(engine, "update", out)
    for rid in list(g.df["CONT_ID"].sample(5, random_state=3)):
        out[f"lookup.{rid}"] = hashlib.sha256(json.dumps(nayose.lookup(engine, record=rid), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    for i, values in enumerate(({"FULL_NAME_KANA": first["FULL_NAME_KANA"].dropna().iloc[0], "PHONE_NUM_4": "1234"}, {"POST_CD": first["POST_CD"].dropna().iloc[0]})):
        out[f"lookup.values{i}"] = hashlib.sha256(json.dumps(nayose.lookup(engine, values=values), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    if os.environ.get("NAYOSE_PARITY_WRITE"):
        GOLDEN.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


def test_every_job_s_tables_are_as_recorded(got):
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert {k: v for k, v in got.items() if want.get(k) != v} == {} and set(got) == set(want)


def test_a_lookup_writes_none_of_the_run_s_tables_even_without_a_transaction(tmp_path, population):
    import contextlib
    named = population.df[population.df["FULL_NAME_KANA"].notna()]
    population.df.to_parquet(tmp_path / "in.parquet", index=False)
    engine = DuckDB()
    nayose.build(engine, [tmp_path / "in.parquet"])
    tables = [t for (t,) in engine.con.execute("SELECT table_name FROM duckdb_tables() WHERE NOT temporary ORDER BY 1").fetchall()]
    run = lambda: {t: digest(engine.con.execute(f'SELECT * FROM "{t}" ORDER BY ALL').df()) for t in tables}
    before = run()
    asks = [dict(record=named["CONT_ID"].iloc[3]), dict(values={"FULL_NAME_KANA": named["FULL_NAME_KANA"].iloc[5], "PHONE_NUM_4": "1234"})]
    rolled_back = [nayose.lookup(engine, **a) for a in asks]

    @contextlib.contextmanager
    def session():  # as BigQuery's scratch: nothing undone, only the temporary tables gone after
        yield
        for (t,) in engine.con.execute("SELECT table_name FROM duckdb_tables() WHERE temporary").fetchall():
            engine.con.execute(f'DROP TABLE temp."{t}"')
    engine.scratch, sent, run_sql = session, [], engine.run
    engine.run = lambda sql, values=None: (sent.append(sql), run_sql(sql, values))[1]
    assert [nayose.lookup(engine, **a) for a in asks] == rolled_back and run() == before
    assert not [s for s in sent if re.match(r"(?:\s*--[^\n]*\n)*\s*CREATE (OR REPLACE )?(VIEW|TABLE)", s)]  # every table made temporary: on BigQuery a view reads the run's
    for sql in ("INSERT INTO scored SELECT * FROM batch_scored", "INSERT records SELECT 1", "DELETE records WHERE TRUE", "TRUNCATE TABLE records",
                "MERGE INTO records USING x ON TRUE WHEN MATCHED THEN DELETE", "ALTER TABLE records ADD COLUMN x INT64", "DROP TABLE records"):
        with pytest.raises(ValueError, match="would write the run's|can't tell what"):  # a write it can't make temporary: refused
            nayose.scratched(sql, set())
    for sql in ("CREATE TABLE x AS SELECT 1", "CREATE OR REPLACE TABLE `x` CLUSTER BY k AS SELECT 1 AS k", "/* c */ CREATE  OR REPLACE VIEW x AS SELECT 1"):
        assert nayose.scratched(sql, set()).lstrip("/* c */ ").startswith("CREATE OR REPLACE TEMP TABLE x AS SELECT 1")
