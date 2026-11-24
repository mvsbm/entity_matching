"""Stage 1, records (nayose/mapping.sql, nayose/sql/records.sql): the same records as er/'s load step makes from the
same file, field by field, the kind and the copies too; kind_p and name_p to 9 decimals (BigQuery's SUM has no order,
so their last bit may move)."""
import math
from pathlib import Path

import pandas as pd
import pytest

import nayose
from nayose.engines import DuckDB

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = nayose.config()["input"]["columns"]


def er_records(path: Path) -> pd.DataFrame:  # er/'s load step on the file, with the method and settings a run uses
    from er.config import load_pipeline
    from er.settings import load_settings
    from er.steps.job import start
    from er.steps.load import load
    s = load_settings()
    job = start(s, load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns))
    load(job, path)
    return job.engine.frame("SELECT * FROM records").rename(columns={s.data.unique_id: "id"})


def nayose_records(path: Path) -> tuple[pd.DataFrame, DuckDB]:
    engine = DuckDB()
    nayose.records(engine, [path])
    return engine.con.execute("SELECT * FROM records").df(), engine


def same(old: pd.DataFrame, new: pd.DataFrame) -> list[str]:
    """The columns both hold where a record's value differs; floats compared to 9 decimals."""
    both = old.merge(new, on="id", how="outer", suffixes=("_er", "_nayose"), indicator=True)
    assert (both["_merge"] == "both").all(), both.loc[both["_merge"] != "both", "id"].tolist()[:5]
    out = []
    for c in sorted((set(old.columns) & set(new.columns)) - {"id"}):
        a, b = both[f"{c}_er"], both[f"{c}_nayose"]
        if pd.api.types.is_float_dtype(a) or pd.api.types.is_float_dtype(b):
            a, b = a.astype(float).round(9), b.astype(float).round(9)
        else:
            a, b = a.astype("string"), b.astype("string")
        if not (a.isna() == b.isna()).all() or not (a[a.notna()] == b[a.notna()]).all():
            out.append(c)
    return out


def test_the_records_of_a_generated_population_are_er_s(tmp_path, population):
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    new, engine = nayose_records(tmp_path / "in.parquet")
    assert same(er_records(tmp_path / "in.parquet"), new) == []
    assert len(new) == len(g.df) and engine.value("SELECT COUNT(*) FROM set_aside") == 0


def test_what_er_s_load_fixes_set_aside_and_reads_as_missing_nayose_does_alike(tmp_path):
    rows = []
    row = lambda i, **k: {c: None for c in COLUMNS} | {"CONT_ID": f"{i:05d}"} | k
    for i in range(270):  # a dummy phone 70 customers share, the rest each their own: a placeholder, read as missing
        rows.append(row(i, FULL_NAME_KANA=f"サトウ{chr(0x30A2 + i % 40)}{i}", PHONE_NUM_4="0000" if i < 70 else f"{i:04d}", CIF_ID=f"{10_000_000 + i}",
                        STD_ADDRESS=f"千代田区丸の内{i % 9 + 1}丁目{i % 7 + 1}番地{i % 5 + 1}号 ビル{i}F"))
    rows += [
        row(300, FULL_NAME_KANA="　 ", O_PERSON_NAME_KANA="すずき はなこ", PHONE_NUM_4="０３-１２３４", POST_CD="100-0005"),  # blank: the next source wins; hiragana, full width
        row(301, LAST_NAME_KANA="ﾀﾅｶ", GIVEN_NAME_KANA="ｲﾁﾛｳ", ORIGINAL_ADDRESS="東京都港区六本木6丁目10番1号"),  # half-width parts, joined
        row(302, NYS_CNV_P_NAME_KANA="株式会社ヤマダショウジ", PERSON_ORG_CODE="1"),  # a written legal form: company, against the flag
        row(303, FULL_NAME_KANA="ヤマダタロウ", NYS_CNV_P_NAME_KANA="ヤマダタロウ", PERSON_ORG_CODE="２ "),  # a company flag: a person's name doesn't override it
        row(304, NYS_CNV_P_NAME_KANA="カ)サトウショウテン"),  # a bank abbreviation first
        row(305, FULL_NAME_KANA="イトウジロウ", BIRTH_DATE="19900101"),
        row(305, FULL_NAME_KANA="イトウジロウ", BIRTH_DATE="19900102"),  # one ID, two contents: both set aside
        row(306, FULL_NAME_KANA="カトウケン"), row(306, FULL_NAME_KANA="カトウケン"),  # identical rows: kept once
    ]
    blank_id = row(0, FULL_NAME_KANA="ナナシ")
    blank_id["CONT_ID"] = "  "  # no ID: set aside
    pd.DataFrame([*rows, blank_id], columns=COLUMNS).astype("string").to_parquet(tmp_path / "in.parquet", index=False)
    new, engine = nayose_records(tmp_path / "in.parquet")
    assert same(er_records(tmp_path / "in.parquet"), new) == []
    assert new["phone"].isna().sum() >= 70 and engine.rows("SELECT field, value FROM placeholders") == [("phone", "0000")]
    assert sorted(engine.rows("SELECT CONT_ID, reason FROM set_aside")) == [("  ", "no ID"), ("00305", "the same ID with different content"), ("00305", "the same ID with different content")]
    by = new.set_index("id")
    assert by.loc["00300", "person_name"] == "スズキハナコ" and by.loc["00301", "person_name"] == "タナカイチロウ"
    assert (by.loc["00302", "kind"], by.loc["00302", "kind_flagged"]) == (2, True) and by.loc["00303", "kind"] == 2
    assert by.loc["00000", "address__address"] == "千代田区丸の内1-1-1" and not math.isnan(by.loc["00302", "kind_p"])


@pytest.mark.parametrize("path", [nayose.HERE / "mapping.sql"], ids=["mapping.sql"])
def test_the_mapping_parses_as_bigquery_and_translates(path):
    from nayose.engines import duckdb_sql
    for sql in nayose.statements(path.read_text(encoding="utf-8")):
        duckdb_sql(sql)
