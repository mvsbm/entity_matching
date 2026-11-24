"""nayose's SQL contract: BigQuery's dialect, run as written on BigQuery and translated for DuckDB. A form whose
translation would answer otherwise is refused by name; values reach a statement as named parameters; every stage
file parses as BigQuery and translates."""
from types import SimpleNamespace

import pytest

import nayose
from nayose.engines import BigQuery, DuckDB, avoided, duckdb_sql


@pytest.mark.parametrize("sql, why", [
    ("SELECT COUNTIF(x = 'a') FROM t", "COUNTIF"),
    ("SELECT a, count(*) FROM t GROUP BY ALL", "GROUP BY ALL"),
    ("SELECT EDIT_DISTANCE(a, b) FROM t", "EDIT_DISTANCE"),
    ("SELECT NORMALIZE(a, NFKC) FROM t", "NORMALIZE"),
    ("SELECT CONCAT_WS('+', a, b) FROM t", "CONCAT_WS"),
    ("SELECT * FROM t UNPIVOT (v FOR c IN (a, b))", "UNPIVOT"),
    ("SELECT w + 0.5 FROM t", "decimal literal 0.5"),
])
def test_a_form_whose_translation_answers_otherwise_is_refused_by_name(sql, why):
    assert any(why in x for x in avoided(sql))
    with pytest.raises(ValueError, match=why.split()[0]):
        duckdb_sql(sql)


def test_what_is_written_instead_translates_and_answers_as_bigquery_would():
    duck = DuckDB()
    duck.run("CREATE TABLE t AS SELECT * FROM UNNEST([STRUCT(CAST(NULL AS STRING) AS z, 2 AS n), STRUCT(CAST(NULL AS STRING), 3)])")
    assert duck.value("SELECT COUNT(CASE WHEN z = 'y' THEN 1 END) FROM t") == 0  # BigQuery's COUNTIF here: 0
    assert duck.value("SELECT CAST(1.5 AS FLOAT64) * n FROM t WHERE n = @n", {"n": 2}) == 3.0
    assert isinstance(duck.value("SELECT CAST(1.5 AS FLOAT64) FROM t LIMIT 1"), float)  # a FLOAT64, not a DECIMAL
    assert duck.value("SELECT ARRAY_TO_STRING(['a', NULL, 'b'], ' + ')") == "a + b"
    # REGEXP_EXTRACT: the group's match, also where the pattern holds RE2's own escapes; NULL where nothing matches
    assert duck.rows(r"SELECT REGEXP_EXTRACT('\u3000a12', r'^[\x{3000}]a(\p{Nd}+)$'), REGEXP_EXTRACT('x', r'^(\d+)$'), REGEXP_EXTRACT('a', r'a(b*)')") == [("12", None, "")]


def test_a_stage_file_splits_into_its_statements_and_each_gets_the_values_it_names(tmp_path, monkeypatch):
    text = "-- the first\nCREATE TABLE a AS\nSELECT @x AS x;\n\n-- the second; a comment's ; ends nothing\nSELECT @y + @x AS s\nFROM a;\n"
    assert [s.splitlines()[-1] for s in nayose.statements(text)] == ["SELECT @x AS x", "FROM a"]
    with pytest.raises(ValueError, match="closing"):
        nayose.statements("SELECT 1")
    (tmp_path / "s.sql").write_text(text, encoding="utf-8")
    monkeypatch.setattr(nayose, "SQL", tmp_path)
    sent = []
    nayose.stage(SimpleNamespace(run=lambda sql, values: sent.append(values)), "s", x=1, y=2, z=3)
    assert sent == [{"x": 1}, {"x": 1, "y": 2}]  # z: named by neither
    with pytest.raises(ValueError, match="@y"):
        nayose.stage(SimpleNamespace(run=lambda *a: None), "s", x=1)


def test_the_fingerprint_follows_every_stage_file_and_the_values(tmp_path):
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql" / "a.sql").write_text("SELECT 1;\n")
    first = nayose.fingerprint(tmp_path)
    (tmp_path / "config.toml").write_text("[a]\nx = 1\n")
    second = nayose.fingerprint(tmp_path)
    (tmp_path / "sql" / "a.sql").write_text("SELECT 2;\n")
    assert len({first, second, nayose.fingerprint(tmp_path)}) == 3


@pytest.mark.parametrize("path", sorted(nayose.SQL.glob("*.sql")), ids=lambda p: p.name)
def test_every_statement_of_every_stage_parses_as_bigquery_and_translates(path):
    import sqlglot
    for sql in nayose.statements(path.read_text(encoding="utf-8")):
        assert sqlglot.parse_one(sql, read="bigquery") is not None
        duckdb_sql(sql)  # refused by name if it holds a form DuckDB would answer otherwise


class Recorded:  # a BigQuery client that records what it was sent
    class Job:
        def __init__(self):
            self.session_info = SimpleNamespace(session_id="s1")

        def result(self):
            return [{"n": 3}]

    def __init__(self):
        self.sent = []

    def query(self, sql, job_config=None):
        self.sent.append((sql, job_config))
        return self.Job()


def test_bigquery_runs_the_sql_as_written_in_one_session_with_the_dataset_s_tables_and_functions():
    module = SimpleNamespace(QueryJobConfig=lambda **k: SimpleNamespace(**k), ConnectionProperty=lambda key, value: SimpleNamespace(key=key, value=value),
                             ScalarQueryParameter=lambda name, kind, value: (name, kind, value), ArrayQueryParameter=lambda name, kind, value: (name, kind, value))
    client = Recorded()
    engine = BigQuery("p.run_main", "p.nayose", client=client, bigquery=module)
    assert engine.value("SELECT COUNT(*) AS n FROM records WHERE w >= @t AND s IN UNNEST(@s)", {"t": 6.0, "s": ["a", "b"]}) == 3
    engine.run("CREATE TEMP TABLE x AS SELECT cl_jaro_winkler(a, b) AS j, er_hash(a) AS h, nfkc(a) AS n, my_cl_x(a) FROM records")
    (first_sql, first), (second_sql, second) = client.sent
    assert first_sql.startswith("SELECT COUNT(*) AS n FROM records")  # as written: no translation
    assert first.create_session and first.default_dataset == "p.run_main"
    assert first.query_parameters == [("t", "FLOAT64", 6.0), ("s", "STRING", ["a", "b"])]
    assert not second.create_session and second.connection_properties[0].value == "s1"
    assert "`p.nayose`.cl_jaro_winkler(a, b)" in second_sql and "`p.nayose`.er_hash(a)" in second_sql and "`p.nayose`.nfkc(a)" in second_sql
    assert "my_cl_x(a)" in second_sql  # only the functions' own names
