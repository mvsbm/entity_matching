"""Stage 1 (nayose/sql/functions.sql, nayose/mapping.sql, nayose/sql/records.sql): each value read as recorded
(tests/fixtures/expected.json), what was fixed counted alike; a hand-made file's records as recorded, field by field,
the kind and the copies too (their digest, floats to 9 decimals: BigQuery's SUM has no order)."""
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import nayose
from nayose.engines import DuckDB
from test_parity import digest

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = nayose.config()["input"]["columns"]


EXPECTED = json.loads((ROOT / "tests" / "fixtures" / "expected.json").read_text(encoding="utf-8"))


def nayose_records(path: Path) -> tuple[pd.DataFrame, DuckDB]:
    engine = DuckDB()
    nayose.records(engine, [path])
    return engine.con.execute("SELECT * FROM records").df(), engine


def test_what_the_reader_fixes_sets_aside_and_reads_as_missing_is_as_recorded(tmp_path):
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
    said = digest(new.drop(columns=["batch", "person_name__kana_fold_letters_lo", "person_name__kana_fold_letters_hi"]).sort_values("id", ignore_index=True))
    if os.environ.get("NAYOSE_PARITY_WRITE"):
        (ROOT / "tests" / "fixtures" / "expected.json").write_text(json.dumps({**EXPECTED, "handmade_records": said}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert said == json.loads((ROOT / "tests" / "fixtures" / "expected.json").read_text(encoding="utf-8"))["handmade_records"]
    assert new["phone"].isna().sum() >= 70 and engine.rows("SELECT field, value FROM placeholders") == [("phone", "0000")]
    assert sorted(engine.rows("SELECT CONT_ID, reason FROM set_aside")) == [  # as the file gave them, to be fixed and added again
        ("  ", "no ID"), ("00305", "the same ID with different content"), ("00305", "the same ID with different content")]
    by = new.set_index("id")
    assert by.loc["00300", "person_name"] == "スズキハナコ" and by.loc["00301", "person_name"] == "タナカイチロウ"
    assert (by.loc["00302", "kind"], by.loc["00302", "kind_flagged"]) == (2, True) and by.loc["00303", "kind"] == 2
    assert by.loc["00000", "address__address"] == "千代田区丸の内1-1-1" and not math.isnan(by.loc["00302", "kind_p"])


@pytest.mark.parametrize("path", [nayose.HERE / "mapping.sql"], ids=["mapping.sql"])
def test_the_mapping_parses_as_bigquery_and_translates(path):
    from nayose.engines import duckdb_sql
    for sql in nayose.statements(path.read_text(encoding="utf-8")):
        duckdb_sql(sql)


@pytest.mark.parametrize("bad", ["CREATE OR REPLACE TABLE mapped AS SELECT 1 AS id;",
                                 "/* kept */ INSERT INTO records SELECT * FROM mapped;",
                                 "CREATE OR REPLACE TEMP TABLE helper AS SELECT 1 AS x; DELETE FROM decisions WHERE TRUE;",
                                 "WITH gone AS (SELECT 1 AS x)\nDELETE FROM decisions WHERE TRUE;",
                                 "-- a helper of its own\nCREATE TEMP FUNCTION blank(v STRING) AS (v IS NULL);",
                                 "CREATE OR REPLACE TEMP TABLE Placeholders AS SELECT 'x' AS v;",
                                 "CREATE OR REPLACE TEMP TABLE given AS SELECT 1 AS v;  -- decide.sql's, people's decisions",
                                 "CREATE OR REPLACE TEMP TABLE helper AS SELECT 1 AS x;  # a note",
                                 "SELECT 1 AS x;\n# the end",
                                 "/* a note;\n*/\nSELECT 1 AS x;"])  # its ';' ends the statement inside the comment
def test_a_mapping_that_makes_more_than_temporary_tables_of_its_own_is_refused_by_the_deploy_and_by_a_job(tmp_path, monkeypatch, bad):
    from nayose.engines import procedures
    given = tmp_path / "mapping.sql"
    given.write_text((nayose.HERE / "mapping.sql").read_text(encoding="utf-8") + "\n" + bad + "\n", encoding="utf-8")
    with pytest.raises(nayose.InputError, match="^mapping.sql: "):
        procedures("p.run", given)
    monkeypatch.setenv("NAYOSE_MAPPING", str(given))
    engine = DuckDB()
    with pytest.raises(nayose.InputError, match="^mapping.sql: "):
        nayose.records(engine, [tmp_path / "none.parquet"])  # refused before the file is read, so none is needed
    assert engine.con.execute("SELECT COUNT(*) FROM duckdb_tables()").fetchone()[0] == 0  # nor anything written


def test_a_mapping_in_the_documented_form_is_accepted(tmp_path):
    from nayose.engines import procedures
    text = (nayose.HERE / "mapping.sql").read_text(encoding="utf-8").replace("TEMP TABLE mapped", "TEMPORARY TABLE mapped")
    given = tmp_path / "mapping.sql"
    given.write_text(text + "\nSELECT IF(COUNT(*) = 0, ERROR('no records'), 0) FROM mapped;  -- a check of its own\n"
                     "/* the customer's ID, see #3 @x */ SELECT read_value(CONT_ID, TRUE, @nulls) AS id, 'a' AS w FROM input;\n", encoding="utf-8")
    assert len(nayose.mapping_statements(given)) == len(nayose.statements(text)) + 2
    build = next(s for s in procedures("p.run", given) if "PROCEDURE `p.run`.build(" in s)  # past the apostrophe, @nulls declared
    assert "TRUE, v_nulls) AS id, 'a' AS w FROM `p.run`.input" in build and "@nulls" not in build


VALUES = ["ヤマダタロウ", "ヤマダ　タロウ", " サトウ", "サトウ ", "　", "  ", "NULL", " NULL ", "－", "譁ｰ縺励＞", "abc\x01", "タ​ナカ", "a\tb",
          "ﾔﾏﾀﾞ", "�", "", None, "東京" * 100, "①", "😀", "Ｓｕｚｕｋｉ", "plain", " plain", "１２.０", " ", "ア　",
          '["大分県"]', '　["大分県"]　', "[1] ", "[株]", '["a", "b"]', "[]", "['大分市']", "[0708612]", ' ["x"] ',
          '["\\u5927", "b"]', '[null, "  ", "z"]', "['a',]", '["a",]', "[true]", "[[1]]", '[1, "a"]', "['a', 1]", "[12345.0]", "[1.5E+11]",
          '["", null]', "[{[]}]", "12345.0", "1.23457E+11", "100", "3.5"]  # every kind of value the intake treats apart


def test_each_value_is_read_as_recorded():
    nulls = nayose.config()["input"]["nulls"]
    engine = DuckDB()
    nayose.stage(engine, "functions")
    for numeric in (False, True):  # a column of text, a column of numbers
        got = [r[0] for r in engine.rows("SELECT read_value(v, @numeric, @nulls) FROM UNNEST(@values) AS v WITH OFFSET AS i ORDER BY i",
                                         {"numeric": numeric, "nulls": nayose.null_regex(nulls), "values": VALUES})]
        want = EXPECTED["read_value"]["numbers" if numeric else "text"]
        assert [(v, g, w) for v, g, w in zip(VALUES, got, want) if g != w] == []


def test_the_reader_names_each_column_its_own_and_refuses_text_that_isn_t_utf8(tmp_path):
    pq.write_table(pa.table({"id": ["1"], "TEL": ["0311112222"], "tel": ["09033334444"], "": ["c"]}), tmp_path / "names.parquet")
    engine = DuckDB()
    engine.read_parquet("input", [tmp_path / "names.parquet"], ["CIF_ID"])  # a column the file lacks, missing
    assert engine.rows("SELECT * FROM input") == [("1", "0311112222", "09033334444", "c", None)]
    assert [n for n, _ in engine.columns("input")] == ["id", "TEL", "tel_2", "column_4", "CIF_ID"]
    bad = pa.Array.from_buffers(pa.string(), 1, [None, pa.py_buffer(np.array([0, 6], np.int32).tobytes()), pa.py_buffer("ヤマダ".encode("cp932"))])
    pq.write_table(pa.table({"id": ["a"], "name": bad}), tmp_path / "x.parquet")
    with pytest.raises(Exception, match="(?i)utf-?8"):  # BigQuery's load refuses it too: what it said is gone either way
        engine.read_parquet("input", [tmp_path / "x.parquet"])


def test_records_without_an_id_are_set_aside_and_the_rest_of_the_batch_kept(tmp_path):
    rows = pd.DataFrame({c: [""] * 5 for c in COLUMNS})
    rows[nayose.config()["input"]["id"]] = ["", "  ", "a1", "a2", "a3"]  # two without an ID: both read as missing
    rows["FULL_NAME_KANA"] = ["ヤマダタロウ", "サトウハナコ", "スズキイチロウ", "タナカジロウ", "イトウサブロウ"]
    rows.to_parquet(tmp_path / "in.parquet", index=False)
    engine = DuckDB()
    nayose.records(engine, [tmp_path / "in.parquet"])
    assert sorted(engine.rows("SELECT id FROM records")) == [("a1",), ("a2",), ("a3",)]
    assert engine.rows("SELECT reason, COUNT(*) FROM set_aside GROUP BY reason") == [("no ID", 2)]


def test_a_space_nfkc_makes_is_stripped_from_every_name_copy(tmp_path):  # U+00A0, U+2000-200A: a space only once read
    row = {c: None for c in COLUMNS} | {"CONT_ID": "00001", "FULL_NAME_KANA": "ヤマダ タロウ", "NYS_CNV_P_NAME_KANA": "ヤマダ タロウ"}
    pd.DataFrame([row], columns=COLUMNS).astype("string").to_parquet(tmp_path / "in.parquet", index=False)
    new, _ = nayose_records(tmp_path / "in.parquet")
    assert " " not in new.loc[0, "person_name"] and " " not in new.loc[0, "any_name"]
