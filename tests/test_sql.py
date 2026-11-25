"""nayose's SQL contract: BigQuery's dialect, run as written on BigQuery and translated for DuckDB. A form whose
translation would answer otherwise is refused by name; values reach a statement as named parameters; every stage
file parses as BigQuery and translates."""
import re
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
    assert duck.value("SELECT 3 * DIV(5 * 5 - 9, 2)") == 24  # BigQuery's DIV: its sides and itself whole
    assert duck.value("SELECT ARRAY_TO_STRING(ARRAY(SELECT CAST(i AS STRING) || x FROM UNNEST(['a', 'b']) AS x WITH OFFSET AS i ORDER BY i), ',')") == "0a,1b"  # from 0
    assert duck.rows("SELECT [10, 20, 30][OFFSET(i)], [10, 20, 30][OFFSET(1)] FROM UNNEST([0, 2]) AS i ORDER BY i") == [(10, 20), (30, 20)]  # OFFSET: from 0
    assert duck.rows("SELECT i FROM (SELECT i, x FROM UNNEST(['a', 'b']) AS x WITH OFFSET AS i) ORDER BY i") == [(0,), (1,)]  # selected, by its name
    # REGEXP_EXTRACT: the group's match, also where the regex holds RE2's own escapes; NULL where nothing matches
    assert duck.rows(r"SELECT REGEXP_EXTRACT('\u3000a12', r'^[\x{3000}]a(\p{Nd}+)$'), REGEXP_EXTRACT('x', r'^(\d+)$'), REGEXP_EXTRACT('a', r'a(b*)')") == [("12", None, "")]
    # a rewritten form's arguments are translated too: transform goes into no node it replaced
    assert duck.value("SELECT DIV(DIV(7 - 1, 2), 2)") == 1  # untranslated within: 3
    assert duck.rows("SELECT DIV([10, 20, 30][OFFSET(i)], 2) FROM UNNEST([0, 2]) AS i ORDER BY i") == [(5,), (15,)]
    assert duck.value("SELECT REGEXP_EXTRACT('a1', REGEXP_EXTRACT('zz', r'^q'))") is None  # the regex is NULL: no ''


def test_a_null_fingerprint_or_none_differs_from_the_method_s():  # NULL <> x is NULL, which IF reads as false
    duck = DuckDB()
    for stored in ("SELECT CAST(NULL AS STRING) AS fingerprint", "SELECT 'f' AS fingerprint WHERE FALSE"):
        duck.run(f"CREATE OR REPLACE TABLE method AS {stored}")
        with pytest.raises(Exception, match="changed since the run was built"):
            duck.run(nayose.UNCHANGED, {"fingerprint": "f"})
    duck.run("CREATE OR REPLACE TABLE method AS SELECT 'f' AS fingerprint")
    duck.run(nayose.UNCHANGED, {"fingerprint": "f"})


def test_a_stage_file_splits_into_its_statements_and_each_gets_the_values_it_names(tmp_path, monkeypatch):
    text = ("-- the first\nCREATE TABLE a AS\nSELECT @x AS x;\n\n-- the second; a comment's ; ends nothing\n"
            "/* the customer's ID */ SELECT @y + @x AS s, 'a' AS w\nFROM a;\n")  # past its apostrophe, @y and @x read
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


@pytest.mark.parametrize("now, was, said", [
    ("\ngenerators = ", "\nkeys = ", r"\[score\] keys is named \[score\] generators"),
    ("\nplaceholder_min = ", "\nmin_block = ", r"\[records\] min_block is named \[records\] placeholder_min"),
    ("\nfit_records = ", "\nfit_rows = ", r"\[fit\] fit_rows is named \[fit\] fit_records"),
    ("\nem_sessions = ", "\nsessions = ", r"\[fit\] sessions is named \[fit\] em_sessions"),
    ("{ field = ", "{ key = ", r"\[fit\] em_sessions' key is named field"),
    ("[report.looks]", "[report.patterns]", r"\[report.patterns\] is named \[report.looks\]"),
    ("\nsample_records = ", "\n# sample_records = ", r"\[report\] lacks sample_records"),
    ("\npatterns_shown = ", "\n# patterns_shown = ", r"\[report\] lacks patterns_shown")])
def test_a_config_written_with_an_older_key_is_refused_with_its_name_now(tmp_path, monkeypatch, now, was, said):
    text = (nayose.HERE / "config.toml").read_text(encoding="utf-8")
    assert now in text
    (tmp_path / "config.toml").write_text(text.replace(now, was), encoding="utf-8")
    monkeypatch.setenv("NAYOSE_CONFIG", str(tmp_path / "config.toml"))
    with pytest.raises(nayose.InputError, match=f"^config.toml: {said}"):
        nayose.config()


def test_the_fingerprint_follows_the_functions_the_deploy_makes(monkeypatch):  # em.py, strings.js, the hash
    import nayose.engines
    before = nayose.fingerprint()
    monkeypatch.setattr(nayose.engines, "functions", lambda dataset: ["CREATE FUNCTION another"])
    assert nayose.fingerprint() != before


@pytest.mark.parametrize("path", sorted(nayose.SQL.glob("*.sql")), ids=lambda p: p.name)
def test_every_statement_of_every_stage_parses_as_bigquery_and_translates(path):
    import sqlglot
    for sql in nayose.statements(path.read_text(encoding="utf-8")):
        assert sqlglot.parse_one(sql, read="bigquery") is not None
        duckdb_sql(sql)  # refused by name if it holds a form DuckDB would answer otherwise


def test_a_condition_is_a_line_of_the_leading_comments_outside_any_block_comment():
    assert nayose.when("-- the first\n-- when: @a  -- why\nSELECT 1") == "@a"
    assert nayose.when("/* a note */\n-- when: @b\nSELECT 1") == "@b" and nayose.when("/* a */ -- when: @c\nSELECT 1") == "@c"
    assert nayose.when("/* a note\n-- when: @a\n*/\nSELECT 1") is None  # a block comment's text
    assert nayose.when("/* a */ SELECT 1 /*\n-- when: @a\n*/") is None
    for sql, refused in (("-- when: @a\n-- when: @b\nSELECT 1", "one condition at most"),
                         ("SELECT 1\n-- when: @a\nFROM t", "stands in its leading comments"),
                         ("-- when: @a\nCREATE TEMP FUNCTION f(x INT64) AS (x)", "a function holds no condition")):
        with pytest.raises(ValueError, match=refused):
            nayose.when(sql)


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
    engine = BigQuery("p.run_main", client=client, bigquery=module)
    assert engine.value("SELECT COUNT(*) AS n FROM records WHERE w >= @t AND s IN UNNEST(@s)", {"t": 6.0, "s": ["a", "b"]}) == 3
    engine.run("CREATE TEMP TABLE x AS SELECT cl_jaro_winkler(a, b) AS j, er_hash(a) AS h, nfkc(a) AS n, my_cl_x(a) FROM records")
    (first_sql, first), (second_sql, second) = client.sent
    assert first_sql.startswith("SELECT COUNT(*) AS n FROM records")  # as written: no translation
    assert first.create_session and first.default_dataset == "p.run_main"
    assert first.query_parameters == [("t", "FLOAT64", 6.0), ("s", "STRING", ["a", "b"])]
    assert not second.create_session and second.connection_properties[0].value == "s1"
    assert "`p.run_main`.cl_jaro_winkler(a, b)" in second_sql and "`p.run_main`.er_hash(a)" in second_sql and "`p.run_main`.nfkc(a)" in second_sql
    assert "my_cl_x(a)" in second_sql  # only the functions' own names


def test_the_cost_estimator_bills_the_columns_a_statement_reads_whole_and_an_update_all_its_table():
    from scripts.estimate_cost import measured
    engine = DuckDB()
    engine.run("CREATE TABLE t AS SELECT CAST(MOD(x, 10) AS STRING) || 'a' AS a, 'cdef' AS b, x AS n FROM UNNEST(GENERATE_ARRAY(1, 3000000)) AS x")
    got = measured(engine)
    engine.rows("SELECT COUNT(*) FROM t WHERE a = '5b' LIMIT 1")  # a WHERE and a LIMIT cut nothing: column a, whole
    engine.run("UPDATE t SET n = 0 WHERE a = '5b'")  # every column of t
    assert [g["billed"] for g in got] == [3e6 * (2 + 2), 3e6 * ((2 + 2) + (2 + 4) + 8)]


def test_a_statement_s_empty_twin_makes_the_same_columns():  # a `-- when: NOT …` twin, made when its statement isn't run
    import sqlglot
    from nayose import SQL, WRITE, statements, when
    for f in SQL.glob("*.sql"):
        made = {}
        for s in statements(f.read_text(encoding="utf-8")):
            if when(s) and (m := WRITE.match(s)) and m.group(2).upper().startswith("CREATE"):
                tree = sqlglot.parse_one(s, read="bigquery")
                tree = tree.expressions[0] if isinstance(tree, sqlglot.exp.Block) else tree  # a comment after its ';'
                made.setdefault(m.group(3), []).append([e.alias_or_name for e in tree.expression.selects])
        for name, lists in made.items():
            assert all(x == lists[0] or x == ["*"] for x in lists), (f.name, name, lists)


def test_records_sql_names_a_record_s_fields_alike_each_time():  # made's UNION ALL pairs its two sides' columns by position
    import sqlglot
    from sqlglot import exp
    from nayose import SQL, statements
    trees = [sqlglot.parse_one(s, read="bigquery") for s in statements((SQL / "records.sql").read_text(encoding="utf-8"))]
    trees = [t.expressions[0] if isinstance(t, exp.Block) else t for t in trees]  # a comment after its ';'
    columns = next([c.name for c in t.this.expressions] for t in trees if isinstance(t, exp.Create) and t.this.this.name == "records")
    fields = columns[:columns.index("company_name") + 1] + ["batch"]  # a record's fields, before the copies made from them
    made = next(c.this for t in trees for c in t.find_all(exp.CTE) if c.alias == "made")
    redone = [t.expression for t in trees if isinstance(t, exp.Create) and t.this.name == "redone"]
    assert len(redone) == 2 and all([e.alias_or_name for e in s.selects] == fields for s in [made.left, made.right, *redone])


def test_a_row_a_function_reads_is_of_a_narrow_table():  # BigQuery may bill a row passed whole as every column of its table
    import sqlglot
    from sqlglot import exp
    from nayose import SQL, statements
    from nayose.engines import TEMP_FUNCTION
    for f in SQL.glob("*.sql"):
        for s in statements(f.read_text(encoding="utf-8")):
            if TEMP_FUNCTION.match(s):
                continue
            tree = sqlglot.parse_one(s, read="bigquery")
            wide = {t.alias for t in tree.find_all(exp.Table) if t.alias and t.name == "records"}  # records: every column of a record
            passed = {a.name for c in tree.find_all(exp.Func) for a in c.iter_expressions() if isinstance(a, exp.Column) and not a.table}
            assert not wide & passed, (f.name, s.strip()[:80], wide & passed)


def test_score_sql_names_only_the_rules_and_generators_it_lists():  # a misspelt name would make no key, or skip a rule's test
    import sqlglot
    from sqlglot import exp
    from nayose import SQL, WRITE, statements
    made = {m["table"]: sqlglot.parse_one(s, read="bigquery")
            for s in statements((SQL / "score.sql").read_text(encoding="utf-8")) if (m := WRITE.match(s))}
    names = lambda table: {x.this for x in made[table].find_all(exp.Literal) if x.is_string}  # noqa: E731
    rules, generators = names("rules"), names("generators")
    assert names("made_rule_keys") == rules and names("made_keys") == generators  # each listed one makes its keys
    assert names("batch_pairs") and names("batch_pairs") <= rules  # the fuzzy rules' tests


STRING = re.compile(r"r?'(?:[^'\\]|\\.)*'")  # a string literal: a regex in one can't be split


@pytest.mark.parametrize("path", sorted([*nayose.SQL.glob("*.sql"), nayose.HERE / "mapping.sql"]), ids=lambda p: p.name)
def test_every_line_of_the_sql_is_at_most_120_characters_its_strings_aside(path):  # CONTRIBUTING.md, rule 9
    lines = path.read_text(encoding="utf-8").splitlines()
    measured = [line if line.lstrip().startswith("--") else STRING.sub("''", line) for line in lines]  # a comment whole
    wide = [n for n, line in enumerate(measured, 1) if len(line) > 120]
    assert not wide, f"{path.name}: lines {wide} are over 120 characters"


def test_a_regexp_extract_within_another_is_translated_too():  # NULL where nothing matches, as BigQuery's, at any depth
    import duckdb
    from nayose.engines import duckdb_sql
    sql = "SELECT REGEXP_EXTRACT(COALESCE(REGEXP_EXTRACT('abc', r'[0-9]+'), 'z9'), r'[0-9]') AS x"
    assert duckdb.sql(duckdb_sql(sql)).fetchall() == [("9",)]  # untranslated, the inner gives '' and COALESCE keeps it


# The stage files in the order the jobs run them, and the mapping: a table each reads is made by one before it.
IN_ORDER = [nayose.SQL / f"{name}.sql" for name in ("functions", "records", "fit", "score", "decide", "report", "match", "lookup")]
IN_ORDER.insert(1, nayose.HERE / "mapping.sql")


def selected(scope, tables: dict) -> set[str]:
    """Return the names a query's scope gives its reader: a * read as its sources' columns."""
    from sqlglot import exp
    query = scope.expression
    if isinstance(query, exp.SetOperation):
        return selected(scope.set_operation_scopes[0], tables)
    if isinstance(query, exp.Unnest):  # its alias's names, or its STRUCTs' fields
        alias = query.args.get("alias")
        return {c.name for c in alias.columns} if alias and alias.columns else {
            e.alias_or_name for s in [*query.find_all(exp.Struct)][:1] for e in s.expressions}
    names = set()
    for e in query.selects:
        star = e if isinstance(e, exp.Star) else e.this if isinstance(e, exp.Column) and isinstance(e.this, exp.Star) else None
        if star is None:
            names.add(e.alias_or_name)
            continue
        read = [scope.sources[e.table]] if isinstance(e, exp.Column) and e.table else scope.sources.values()
        names |= {c for source in read for c in columns_of(source, tables)} - {c.name for c in star.args.get("except_") or []}
    return names


def columns_of(source, tables: dict) -> set[str]:
    """Return the columns a FROM source gives: a WITH's, a subquery's or an UNNEST's (selected), or a table's (`tables`)."""
    from sqlglot.optimizer.scope import Scope
    return selected(source, tables) if isinstance(source, Scope) else tables.get(source.name.lower(), set())


def test_no_column_is_read_bare_where_a_from_item_of_its_name_is_in_scope():  # BigQuery reads the item's whole row
    """BigQuery's analyzer gives a FROM item's name (a range variable) precedence over a column's, so a column read
    bare where an item of its name is in scope is read as that item's row, a STRUCT; DuckDB reads the column. A row
    read on purpose (x and y passed to a comparison) is no clash: no source in scope has a column of its name. An
    UNNEST's name is its element on both engines."""
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import Scope, build_scope, traverse_scope
    c = nayose.config()
    tables = {"input": set(c["input"]["columns"]), "name_weights": {"term", "coef"},
              "given": {"id_l", "id_r", "decision", "why"}, "method": {"fingerprint"}}  # what Python makes
    clashes = []
    for path in IN_ORDER:
        for sql in nayose.statements(path.read_text(encoding="utf-8")):
            tree = sqlglot.parse_one(sql, read="bigquery")
            tree = tree.expressions[0] if isinstance(tree, exp.Block) else tree  # a comment after its ';'
            for scope in traverse_scope(tree):
                unknown = {t.name for t in scope.sources.values() if isinstance(t, exp.Table)} - set(tables)
                assert not unknown, f"{path.name} reads {unknown}, whose columns this test doesn't know: {sql[:80]}"
                for col in scope.columns:
                    item = None if col.table else scope.sources.get(col.name)
                    if item is None or isinstance(item, Scope) and isinstance(item.expression, exp.Unnest):
                        continue
                    if any(col.name in columns_of(source, tables) for source in scope.sources.values()):
                        clashes.append(f"{path.name}: {col.name} in {str(col.parent)[:60]}")
            if isinstance(tree, exp.Create) and tree.kind in ("TABLE", "VIEW"):  # the table it makes, for those after
                schema = tree.this if isinstance(tree.this, exp.Schema) else None
                made = schema.this if schema else tree.this
                tables[made.name.lower()] = ({d.name for d in schema.expressions} if schema
                                             else selected(build_scope(tree.expression), tables))
    assert not clashes, clashes


# GoogleSQL's reserved keywords, from https://cloud.google.com/bigquery/docs/reference/standard-sql/lexical#reserved_keywords
RESERVED = set("""
ALL AND ANY ARRAY AS ASC ASSERT_ROWS_MODIFIED AT BETWEEN BY CASE CAST COLLATE CONTAINS CREATE CROSS CUBE CURRENT DEFAULT
DEFINE DESC DISTINCT ELSE END ENUM ESCAPE EXCEPT EXCLUDE EXISTS EXTRACT FALSE FETCH FOLLOWING FOR FROM FULL GRAPH_TABLE
GROUP GROUPING GROUPS HASH HAVING IF IGNORE IN INNER INTERSECT INTERVAL INTO IS JOIN LATERAL LEFT LIKE LIMIT LOOKUP MERGE
NATURAL NEW NO NOT NULL NULLS OF ON OR ORDER OUTER OVER PARTITION PRECEDING PROTO QUALIFY RANGE RECURSIVE RESPECT RIGHT
ROLLUP ROWS SELECT SET SOME STRUCT TABLESAMPLE THEN TO TREAT TRUE UNBOUNDED UNION UNNEST USING WHEN WHERE WINDOW WITH
WITHIN""".split())


def reserved(sql: str) -> set[str]:
    """Return the names in `sql` that BigQuery refuses: its reserved keywords, unless backquoted.

    A column, an alias, a WITH's or a table's name, a function's parameter: each is an identifier. A named parameter
    (@name) may be a reserved keyword: "A named query parameter can start with an identifier or a reserved keyword"
    (the same page), and a procedure declares it as v_name."""
    import sqlglot
    from sqlglot import exp
    return {node.name for tree in sqlglot.parse(sql, read="bigquery") if tree
            for node in tree.find_all(exp.Identifier) if not node.quoted and node.name.upper() in RESERVED}


@pytest.mark.parametrize("path", IN_ORDER, ids=lambda p: p.name)
def test_no_name_is_a_reserved_keyword_unless_backquoted(path):
    assert not {n for sql in nayose.statements(path.read_text(encoding="utf-8")) for n in reserved(sql)}


def test_no_name_of_the_tables_python_makes_is_a_reserved_keyword():  # tests/test_deploy.py checks what its fake clients are sent
    sent = []  # decide's statements, as a build runs them
    nayose.decide(SimpleNamespace(run=lambda sql, values=None: sent.append(sql), value=lambda sql, values=None: True), [])
    assert sent and not {n for s in sent for n in reserved(s)}
