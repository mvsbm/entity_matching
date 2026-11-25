"""Where nayose's SQL runs. The SQL is BigQuery's (nayose/sql/), and the two engines differ only here:

    BigQuery   runs it as written, in a session of the job's own. A run's tables are in its dataset, and so are the
               functions it calls by name (cl_*, er_hash, nfkc), which the deploy makes there (functions()).
    DuckDB     translates it first (sqlglot, BigQuery → DuckDB), refusing a form whose translation changes what it
               gives (AVOID, avoided()). It calls twins of the same functions: for cl_*, DuckDB's own where both
               strings are one byte a character (native), else rapidfuzz; Arrow's utf8_normalize for nfkc; numpy for
               one_byte_hash; a macro for er_hash.

Both answer the same verbs: run (a statement, nothing back), rows, value, frame (small results only: a step's
tables stay in the engine); put (a small frame as a table, such as the model EM learns); read_parquet (input files
as a table).

Here too are the statements the deploy runs: functions() and procedures().
"""
import contextlib
import functools
import importlib
import re
import shutil
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sqlglot
from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein, Hamming, JaroWinkler, Levenshtein
from sqlglot import exp

import nayose
from nayose import TEMP_FUNCTION, WRITE, em, entities

STRINGS = Path(__file__).parent / "strings.js"  # the comparison functions in JavaScript, as BigQuery runs them

FUNCTIONS = {  # each character-level comparison the SQL calls as cl_<name>(a, b) and cl_<name>_cut(a, b, threshold)
    "jaro_winkler": (True, JaroWinkler.similarity),  # True: a similarity, passing at the threshold or above
    "levenshtein": (False, Levenshtein.distance),  # False: a distance, passing at the threshold or below
    "damerau_levenshtein": (False, DamerauLevenshtein.distance),
    "hamming": (False, Hamming.distance),
}

# A comparison BigQuery has itself, counting characters (Unicode code points) as the twin does: deployed as a SQL
# function over it, never JavaScript. The method's SQL never names it, as DuckDB's own would count bytes.
BUILT_IN = {"levenshtein": "EDIT_DISTANCE"}

AVOID = {  # a form whose DuckDB translation gives another result than BigQuery's: what to write instead
    r"\bCOUNTIF\s*\(": "COUNTIF: DuckDB's COUNT_IF gives NULL where every test is NULL, BigQuery 0; "
                       "write COUNT(CASE WHEN … THEN 1 END)",
    r"\bGROUP\s+BY\s+ALL\b": "GROUP BY ALL: it comes back as a column named ALL; name the columns",
    r"\bEDIT_DISTANCE\s*\(": "EDIT_DISTANCE: DuckDB's LEVENSHTEIN counts bytes, not characters; write cl_levenshtein",
    r"\bNORMALIZE\s*\(": "NORMALIZE: DuckDB has no NFKC; write nfkc(x)",
    r"\bCONCAT_WS\s*\(": "CONCAT_WS: its NULLs translate otherwise; write ARRAY_TO_STRING([…], separator)",
    r"\bUNPIVOT\b": "UNPIVOT: translated, it loses rows; write one SELECT per column, joined by UNION ALL",
}


def avoided(sql: str) -> list[str]:
    """Return what in `sql` (BigQuery's dialect) DuckDB would answer otherwise once translated.

    That is the forms of AVOID, and a decimal literal, which BigQuery reads as FLOAT64 and DuckDB as DECIMAL
    (write CAST(1.5 AS FLOAT64)).
    """
    out = [why for pattern, why in AVOID.items() if re.search(pattern, sql, flags=re.I)]
    for tree in sqlglot.parse(sql, read="bigquery"):
        for lit in tree.find_all(exp.Literal) if tree else ():
            if lit.is_number and re.search(r"[.eE]", lit.this):
                parent = lit.parent
                if not (isinstance(parent, exp.Cast) and parent.to.this == exp.DataType.Type.DOUBLE):
                    out.append(f"the decimal literal {lit.this}: DuckDB reads it as DECIMAL, BigQuery as FLOAT64; "
                               f"write CAST({lit.this} AS FLOAT64)")
    return out


@functools.lru_cache(maxsize=4096)  # each statement translated once: the stage files hold a few hundred
def duckdb_sql(sql: str) -> str:
    """Return `sql` (BigQuery's dialect) as DuckDB runs it; raise ValueError for what DuckDB would answer otherwise."""
    if bad := avoided(sql):
        raise ValueError("; ".join(bad) + f": {sql.strip()[:160]}")
    trees = [tree.transform(as_bigquery) for tree in sqlglot.parse(sql, read="bigquery")]
    return ";\n".join(t.sql(dialect="duckdb", unsupported_level=sqlglot.ErrorLevel.RAISE) for t in trees)


def as_bigquery(node: exp.Expression) -> exp.Expression:
    """Return the node so that DuckDB answers it as BigQuery does, where sqlglot's translation would answer otherwise:

    - DIV(a, b): DuckDB's a // b, each side and the whole in brackets (sqlglot writes DIV(x - y, 2) as x - y // 2);
    - a function's ANY TYPE parameter (a record's row, say): untyped, as a DuckDB macro's (sqlglot types it VARIANT);
    - UNNEST ... WITH OFFSET: counted from 0, as BigQuery counts (sqlglot writes DuckDB's WITH ORDINALITY, from 1);
    - array[OFFSET(i)] where i isn't a number: DuckDB's array[i + 1] (sqlglot moves a number's base only);
    - REGEXP_EXTRACT: the group's match where the pattern has one (sqlglot reads groups with Python's re, which can't
      read RE2's \\x{3000} or \\p{Nd}), and NULL where it doesn't match (DuckDB's gives '');
    - CLUSTER BY: BigQuery's storage order, what a filter on its columns prunes by; DuckDB keeps none, so it goes."""
    if isinstance(node, exp.ClusterProperty):
        return None
    kind = node.args.get("kind") if isinstance(node, exp.ColumnDef) else None
    if kind is not None and kind.this == exp.DataType.Type.VARIANT:
        node.set("kind", None)
        return node
    if isinstance(node, exp.Bracket) and node.args.get("offset") == 0 and not node.expressions[0].is_int:
        node.set("expressions", [exp.Add(this=exp.Paren(this=node.expressions[0]), expression=exp.Literal.number(1))])
        node.set("offset", 1)  # counted from 1 now, as DuckDB counts
        return node
    if isinstance(node, exp.Select) and not node.args.get("bigquery"):
        node.set("bigquery", True)
        offsets_from_zero(node)
        return node
    if isinstance(node, exp.IntDiv) and not node.args.get("bigquery"):
        node.set("bigquery", True)  # done: transform visits it again inside the brackets
        node.set("this", exp.Paren(this=node.this))
        node.set("expression", exp.Paren(this=node.expression))
        return exp.Paren(this=node)
    if isinstance(node, (exp.RegexpExtract, exp.RegexpExtractAll)) and not node.args.get("bigquery"):
        pattern = node.expression
        if (pattern.is_string or isinstance(pattern, exp.RawString)) and groups(pattern.name) == 1:
            node.set("group", exp.Literal.number(1))
        node.set("bigquery", True)  # done: transform visits it again inside the IF
        if isinstance(node, exp.RegexpExtract):
            return exp.If(this=exp.RegexpLike(this=node.this.copy(), expression=pattern.copy()), true=node)
    return node


def offsets_from_zero(select: exp.Select) -> None:
    """Count each WITH OFFSET of `select` from 0, as BigQuery does (DuckDB's WITH ORDINALITY counts from 1)."""
    offsets = [u for u in select.find_all(exp.Unnest)
               if isinstance(u.args.get("offset"), exp.Identifier) and u.parent_select is select]
    for unnest in offsets:
        name = unnest.args["offset"].name
        uses = [c for c in select.find_all(exp.Column) if c.name == name and not c.table and c.parent_select is select]
        for col in uses:
            shifted = exp.Paren(this=exp.Sub(this=col.copy(), expression=exp.Literal.number(1)))
            col.replace(exp.alias_(shifted, name) if col.parent is select else shifted)  # a selected one keeps its name


def groups(pattern: str) -> int:
    """Return how many capturing groups an RE2 pattern has, counted by Python's re once RE2's own escapes are read."""
    python = re.sub(r"\\x\{([0-9a-fA-F]+)\}", lambda m: f"\\U{int(m[1], 16):08x}", pattern)
    return re.compile(re.sub(r"\\[pP](?:\{[^}]*\}|[A-Za-z])", r"\\w", python)).groups


def compare(name: str, cut: bool = False):
    """Return cl_<name>(a, b) for DuckDB, as rapidfuzz scores it: by character, and NULL where either side is NULL.

    With `cut`, return cl_<name>_cut(a, b, threshold): the same score wherever it passes the threshold, and a failing
    score elsewhere, found without finishing the work. A similarity's cut is a hair below its threshold, as
    rapidfuzz's scores are float32.
    """
    similarity, scorer = FUNCTIONS[name]

    def f(a: pa.Array, b: pa.Array, threshold: pa.Array | None) -> pa.Array:
        null = pc.or_(a.is_null(), b.is_null())
        x, y = pc.fill_null(a, "").to_pylist(), pc.fill_null(b, "").to_pylist()
        t = None if threshold is None or not len(threshold) else threshold[0].as_py()
        early = {} if t is None else {"score_cutoff": min(max(t - 1e-6, 0.0), 1.0) if similarity else max(int(t), 0)}
        scores = process.cpdist(x, y, scorer=scorer, **early)
        return pa.array(np.asarray(scores, dtype=float), mask=null.to_numpy(zero_copy_only=False))
    if cut:  # two separate signatures: DuckDB counts a function's parameters
        return lambda a, b, threshold: f(a, b, threshold)
    return lambda a, b: f(a, b, None)


NATIVE = {"jaro_winkler": "jaro_winkler_similarity(a, b)", "levenshtein": "levenshtein(a, b)",
          "damerau_levenshtein": "damerau_levenshtein(a, b)", "hamming": "hamming(a, b)"}


def native(name: str, cut: bool) -> str:
    """Return cl_<name> on DuckDB as SQL over a and b: DuckDB's own comparison where it gives what the twin gives.

    DuckDB's own comparisons count bytes, and a Python function is called a chunk at a time under one lock. So where
    both strings are filled and one byte a character (ASCII, or records.sql's one-byte copies), DuckDB's own answers,
    giving what the twin gives: a similarity as float32, and a cut's failing score (cl_<name>_cut, `cut`) as
    rapidfuzz's, 0 for a similarity and the threshold + 1 for a distance. The twin answers everywhere else. DuckDB's
    hamming takes strings of one length only, where rapidfuzz pads the shorter.
    """
    score, twin = NATIVE[name], f"twin_{name}_cut(a, b, t)" if cut else f"twin_{name}(a, b)"
    if FUNCTIONS[name][0]:
        value = f"CAST(CAST({score} AS FLOAT) AS DOUBLE)"
        out = f"CASE WHEN {score} >= least(greatest(t - 1e-6, 0), 1) THEN {value} ELSE 0 END" if cut else value
    else:
        cap = "greatest(floor(t), 0)"
        out = f"CASE WHEN {score} <= {cap} THEN {score} ELSE {cap} + 1 END" if cut else score
    same = " AND length(a) = length(b)" if name == "hamming" else ""
    one_byte = f"a <> '' AND b <> '' AND strlen(a) = length(a) AND strlen(b) = length(b){same}"
    return f"CASE WHEN a IS NULL OR b IS NULL THEN NULL WHEN {one_byte} THEN CAST({out} AS DOUBLE) ELSE {twin} END"


def one_byte_hash(a: pa.Array) -> pa.Array:
    """Return each string with each character as one ASCII byte, 33 + its code point mod 94, as BigQuery's gives it.

    Two characters may share a byte, so an edit distance between the copies is never more than between the strings
    (records.sql).
    """
    values = a.to_pylist()
    filled = [v for v in values if v is not None]
    points = np.frombuffer("".join(filled).encode("utf-32-le"), dtype=np.uint32)
    text = (33 + points % 94).astype(np.uint8).tobytes().decode("ascii")
    ends = np.cumsum([len(v) for v in filled], dtype=np.int64)
    parts = iter(text[s:e] for s, e in zip(np.concatenate(([0], ends[:-1])), ends))
    return pa.array([None if v is None else next(parts) for v in values], pa.string())


def nfkc(a: pa.Array) -> pa.Array:
    """Return each string in Unicode NFKC, as BigQuery's NORMALIZE(x, NFKC) gives it.

    Arrow's (utf8proc) is in C++ and the same on every Python. Python's unicodedata 16.0 gives every code point the
    same but one assigned since (U+A7F1).
    """
    return pc.utf8_normalize(a.cast(pa.string()), form="NFKC")


class DuckDB:
    """Run nayose's SQL on DuckDB, in process, after translating it (duckdb_sql), with twins of BigQuery's functions.

    A run's tables are in the database file at `path`, or in memory with a spill folder of its own when `path` is
    None. `compute` holds DuckDB's settings (threads, memory_limit, temp_directory). With `read_only`, only
    temporary objects can be made.
    """
    name = "duckdb"
    MISSING = (duckdb.CatalogException,)  # what a query of a table the run lacks raises

    def __init__(self, path: Path | None = None, compute: dict | None = None, read_only: bool = False) -> None:
        self.con = duckdb.connect(str(path) if path else ":memory:", read_only=read_only)
        self.spill = None
        settings = {k: v for k, v in (compute or {}).items() if v not in ("", None)}
        if not path and "temp_directory" not in settings:  # spilled records in a folder only this job can read
            self.spill = tempfile.mkdtemp(prefix="nayose-spill-")
            settings["temp_directory"] = self.spill
        self.con.execute("SET enable_progress_bar = false")
        for key, value in settings.items():
            self.con.execute(f"SET {key} = '{value}'")
        # the portable hash: MD5's first 15 hex digits as an integer, as BigQuery's er_hash (functions())
        self.con.execute("CREATE OR REPLACE TEMP MACRO er_hash(x) AS "
                         "('0x' || substr(md5(coalesce(CAST(x AS VARCHAR), '')), 1, 15))::BIGINT")
        for name in FUNCTIONS:  # cl_*: DuckDB's own function where it answers as the twin does (native), else the twin
            self.con.create_function(f"twin_{name}", compare(name), ["VARCHAR", "VARCHAR"], "DOUBLE", type="arrow")
            self.con.create_function(f"twin_{name}_cut", compare(name, cut=True), ["VARCHAR", "VARCHAR", "DOUBLE"],
                                     "DOUBLE", type="arrow")
            self.con.execute(f"CREATE OR REPLACE TEMP MACRO cl_{name}(a, b) AS {native(name, cut=False)}")
            self.con.execute(f"CREATE OR REPLACE TEMP MACRO cl_{name}_cut(a, b, t) AS {native(name, cut=True)}")
        self.con.create_function("nfkc", nfkc, ["VARCHAR"], "VARCHAR", type="arrow")
        self.con.create_function("one_byte_hash", one_byte_hash, ["VARCHAR"], "VARCHAR", type="arrow")
        # EM and decide's components: the same Python as BigQuery's Python UDFs
        three = ["VARCHAR", "VARCHAR", "VARCHAR"]
        self.con.create_function("fit_model", em.fit, three, "VARCHAR", null_handling="special")
        self.con.create_function("entities_of", entities.of, ["VARCHAR"], "VARCHAR")

    def run(self, sql: str, values: dict | None = None) -> None:
        self.con.execute(duckdb_sql(sql), values or None)

    def rows(self, sql: str, values: dict | None = None) -> list[tuple]:
        return self.con.execute(duckdb_sql(sql), values or None).fetchall()

    def value(self, sql: str, values: dict | None = None) -> object:
        return self.rows(sql, values)[0][0]

    def frame(self, sql: str, values: dict | None = None) -> pd.DataFrame:
        return self.con.execute(duckdb_sql(sql), values or None).df()

    def columns(self, table: str) -> list[tuple[str, str]]:
        """Return a table's columns, as (name, type)."""
        return [(r[0], r[1]) for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()]

    def put(self, table: str, frame: pd.DataFrame) -> None:
        """Make a small frame the table `table`, replacing it."""
        self.con.register("nayose_put", frame)
        try:
            self.con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM nayose_put')
        finally:
            self.con.unregister("nayose_put")

    def read_parquet(self, table: str, files: list[Path], columns: list[str] = ()) -> None:
        """Load Parquet files as the temporary table `table`, their columns joined by name.

        Each column of each file gets a name of its own (names), and each of `columns` the files lack is added, as
        missing. Text that isn't UTF-8 is refused. The files are copied once, as the mapping reads them twice and a
        file read in place each time is slower. The table is temporary: nothing reads it past the job that loads it,
        so the run's file keeps no copy.
        """
        def quote(n: str) -> str:
            return '"' + n.replace('"', '""') + '"'

        parts = [f"SELECT * FROM read_parquet(?) AS t({', '.join(map(quote, names(pq.read_schema(f).names)))})"
                 for f in files]
        self.con.execute(f'CREATE OR REPLACE TEMP TABLE "{table}" AS ' + " UNION ALL BY NAME ".join(parts),
                         [str(f) for f in files])
        have = {n.casefold() for n, _ in self.columns(table)}
        for c in (c for c in columns if c.casefold() not in have):
            self.con.execute(f'ALTER TABLE "{table}" ADD COLUMN {quote(c)} VARCHAR')

    @contextlib.contextmanager
    def scratch(self):
        """Run what follows in a transaction that is rolled back, so whatever its statements write is undone after."""
        self.run("BEGIN TRANSACTION")
        try:
            yield
        finally:
            self.run("ROLLBACK")

    def close(self) -> None:
        self.con.close()
        if self.spill:
            shutil.rmtree(self.spill, ignore_errors=True)


def functions(dataset: str) -> list[str]:
    """Return the statements that make the method's non-SQL functions in `dataset` (project.dataset), run once a deploy.

    They are: each comparison of FUNCTIONS, as cl_<name> and cl_<name>_cut (the same score; the threshold isn't read),
    in JavaScript or over BigQuery's own function (BUILT_IN); the portable hash er_hash; nfkc; one_byte_hash; and the
    Python UDFs, EM's fit_model (nayose/em.py) and decide's entities_of (nayose/entities.py).
    """
    library = STRINGS.read_text(encoding="utf-8")
    out = []
    for name in FUNCTIONS:
        if name in BUILT_IN:  # BigQuery's own, counting characters as the twin does: no JavaScript
            own, made = BUILT_IN[name], f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}"
            out.append(f"{made}(a STRING, b STRING) AS (CAST({own}(a, b) AS FLOAT64))")
            # past the threshold, threshold + 1, as the cut twin gives
            out.append(f"{made}_cut(a STRING, b STRING, threshold FLOAT64) AS "
                       f"(CAST(LEAST({own}(a, b), FLOOR(threshold) + 1) AS FLOAT64))")
            continue
        body = f"{library}\nreturn a === null || b === null ? null : {name}(a, b);"
        for suffix, extra in (("", ""), ("_cut", ", threshold FLOAT64")):
            out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}{suffix}(a STRING, b STRING{extra}) "
                       f"RETURNS FLOAT64 LANGUAGE js AS r\"\"\"{body}\"\"\"")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.er_hash(x ANY TYPE) AS "
               "(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(COALESCE(CAST(x AS STRING), ''))), 1, 15)) AS INT64))")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.nfkc(x STRING) AS (NORMALIZE(x, NFKC))")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.one_byte_hash(x STRING) AS "
               "(CODE_POINTS_TO_STRING(ARRAY(SELECT 33 + MOD(c, 94) "
               "FROM UNNEST(TO_CODE_POINTS(x)) AS c WITH OFFSET AS i ORDER BY i)))")
    python_udfs = ((em, "fit_model", "counts STRING, settings STRING, stored STRING", "fit"),
                   (entities, "entities_of", "pairs STRING", "of"))
    for module, name, args, entry in python_udfs:
        source = Path(module.__file__).read_text(encoding="utf-8")  # python-3.11 there, and the standard library only
        assert "'''" not in source, f"{module.__name__}: no triple single quotes, which end BigQuery's raw string"
        out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.{name}({args}) RETURNS STRING LANGUAGE python "
                   f"OPTIONS (runtime_version = 'python-3.11', entry_point = '{entry}') AS r'''{source}'''")
    return out


# Each job BigQuery runs as a procedure of the run's dataset: its stages in order, each with what values_of() is told.
# There is no lookup procedure: nayose.lookup runs its own statements, each step in a session of its own
# (BigQuery.scratch), writing temporary tables alone.
JOBS = {
    "build": [("functions", {}), ("mapping", {}), ("records", {}), ("fit", {"refit": True}), ("score", {}),
              ("decide", {}), ("report", {})],
    "update": [("functions", {}), ("mapping", {}), ("records", {}), ("score", {}),
               ("decide", {}), ("report", {})],
    "decide": [("functions", {}), ("decide", {})],
    "match": [("functions", {}), ("match", {})],
}
ARGUMENTS = {"match": {"threshold": "FLOAT64"}}  # a procedure's own values: given when it is called, not declared
KEPT = ("decisions",)  # people's decisions: a build keeps them, as the CLI's build does


def in_dataset(sql: str, dataset: str) -> str:
    """Return a view's statement with each table it names (a WITH's names aside) as the dataset's.

    BigQuery reads a view's body without a default dataset.
    """
    tree, (project, name) = sqlglot.parse_one(sql, read="bigquery"), dataset.split(".")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not t.args.get("db") and t.name not in ctes:
            t.set("db", exp.to_identifier(name))
            t.set("catalog", exp.to_identifier(project))
    return tree.sql(dialect="bigquery")


def stage_statements(stage: str, mapping: Path | None) -> list[str]:
    """Return a stage's statements: its file's, or, for the stage mapping, the deployment's mapping, checked."""
    if stage == "mapping":
        return nayose.mapping_statements(mapping or nayose.mapping())  # the one fingerprint() hashes
    return nayose.statements((nayose.SQL / f"{stage}.sql").read_text(encoding="utf-8"))


def procedures(dataset: str, mapping: Path | None = None) -> list[str]:
    """Return the statements the deploy runs in `dataset` (project.dataset), after functions().

    First, the method's own SQL functions: each stage file's CREATE TEMP FUNCTION, made as one of the dataset's. Then
    one procedure a job (JOBS): its stages' statements in order, with the values they read (@name, from
    nayose.values_of) declared at its top as v_name. `mapping` is the deployment's mapping.sql. Every call of the
    method's functions names the dataset, where the deploy made them.
    """
    sql_functions: dict[str, str] = {}  # the method's SQL functions by name, as the deploy makes them, in the order met
    jobs = {job: job_statements(job, stages, dataset, mapping, sql_functions) for job, stages in JOBS.items()}
    own = calls_of(sql_functions)
    fingerprint = bigquery_literal(nayose.fingerprint(mapping_file=mapping))  # what an update needs unchanged
    return [*(qualified(sql, own, dataset) for sql in sql_functions.values()),
            *(procedure(job, *parts, dataset, fingerprint, own) for job, parts in jobs.items())]


def job_statements(job: str, stages: list, dataset: str, mapping: Path | None,
                   sql_functions: dict[str, str]) -> tuple[list[str], dict, list[str]]:
    """Return one job's statements for its procedure, the values they read, and the run's tables they write.

    A CREATE TEMP FUNCTION goes to `sql_functions` instead, made as a function of the dataset. Each @name becomes
    v_name. A statement with a `-- when:` condition is wrapped in IF ... END IF. A view names its tables with their
    dataset (in_dataset). The tables written are the run's (not temporary, and not KEPT), in the order first written.
    """
    body, declared, written = [], {}, {}
    for stage, told in stages:
        declared |= nayose.values_of(stage, **told)
        for sql in stage_statements(stage, mapping):
            if function := TEMP_FUNCTION.match(sql):
                def in_the_dataset(x: re.Match) -> str:
                    return f"{x['lead']}CREATE OR REPLACE FUNCTION `{dataset}`.{x['name']}"
                made = TEMP_FUNCTION.sub(in_the_dataset, sql, count=1)
                sql_functions.setdefault(function["name"], made)
                continue
            sql = nayose.PARAMETER.sub(r"v_\1", sql)  # in comments too: a -- when: condition is read from them
            guard = nayose.when(sql)  # read before in_dataset, whose SQL keeps no comment
            head = WRITE.match(sql)
            if head and "VIEW" in head["verb"].upper():
                sql = in_dataset(sql, dataset)
            elif head and "TEMP" not in head["verb"].upper() and head["table"] not in KEPT:
                written.setdefault(head["table"])
            body.append(f"IF {guard} THEN\n{sql};\nEND IF" if guard else sql)
    arguments = ARGUMENTS.get(job, {})
    return body, {k: v for k, v in declared.items() if k not in arguments}, list(written)


def procedure(job: str, body: list[str], declared: dict, written: list[str], dataset: str, fingerprint: str,
              own: re.Pattern) -> str:
    """Return the CREATE PROCEDURE statement of one job, from its statements (job_statements).

    The procedure declares its values, then sets the dataset as the default. A build first drops every table it
    writes, so it starts as an empty run, and last stores the method's fingerprint; an update first refuses a run
    whose fingerprint differs.
    """
    project, name = dataset.split(".")
    arguments = ", ".join(f"v_{k} {kind}" for k, kind in ARGUMENTS.get(job, {}).items())
    head = [f"DECLARE v_{k} {bigquery_type(v)} DEFAULT {bigquery_literal(v)}" for k, v in declared.items()]
    head += [f"SET @@dataset_project_id = '{project}'", f"SET @@dataset_id = '{name}'"]
    if job == "build":
        head += [f"DROP TABLE IF EXISTS {x}" for x in written]
        body = [*body, nayose.METHOD.replace("@fingerprint", fingerprint)]
    if job == "update":
        head.append(nayose.UNCHANGED.replace("@fingerprint", fingerprint))
    statements = ";\n".join([*head, *(qualified(sql, own, dataset) for sql in body)])
    return f"CREATE OR REPLACE PROCEDURE `{dataset}`.{job}({arguments})\nBEGIN\n{statements};\nEND"


def method_functions() -> set[str]:
    """Return the names of the SQL functions nayose/sql/ makes (its CREATE TEMP FUNCTIONs)."""
    return {made["name"] for f in nayose.SQL.glob("*.sql") for sql in nayose.statements(f.read_text(encoding="utf-8"))
            if (made := TEMP_FUNCTION.match(sql))}


def calls_of(names, flags: int = 0) -> re.Pattern:
    """Return the pattern of a call of any of these functions, by its name alone (not yet qualified with a dataset)."""
    return re.compile(r"(?<![\w.`])(" + "|".join(sorted(names, key=len, reverse=True)) + r")\s*\(", flags)


def qualified(sql: str, own: re.Pattern, dataset: str) -> str:
    """Return `sql` with each call of the method's functions named with `dataset`, where the deploy made them.

    That is its SQL functions (`own`), and its JavaScript and Python ones (BigQuery.CALLS).
    """
    return own.sub(lambda m: f"`{dataset}`.{m[1]}(", BigQuery.CALLS.sub(lambda m: f"`{dataset}`.{m[1]}(", sql))


def bigquery_type(v: object) -> str:
    """Return a value's BigQuery type, for the values values_of() gives."""
    if isinstance(v, bool):
        return "BOOL"
    if isinstance(v, list):
        return f"ARRAY<{bigquery_type(v[0]) if v else 'STRING'}>"
    return "INT64" if isinstance(v, int) else "FLOAT64" if isinstance(v, float) else "STRING"


def bigquery_literal(v: object) -> str:
    """Return a value written as BigQuery SQL; a string's characters are escaped one by one where they must be."""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, list):
        return f"{bigquery_type(v)}[{', '.join(map(bigquery_literal, v))}]"
    if isinstance(v, float):
        not_finite = v != v or v in (float("inf"), float("-inf"))
        return f"CAST('{v!r}' AS FLOAT64)" if not_finite else f"CAST({v!r} AS FLOAT64)"
    if isinstance(v, int):
        return str(v)
    said = {"\\": "\\\\", "'": "\\'"}
    return "'" + "".join(said.get(ch) or (ch if ch.isprintable() else f"\\U{ord(ch):08x}") for ch in str(v)) + "'"


class BigQuery:
    """Run nayose's SQL on BigQuery as written, in one session of the job's own, whose temporary tables die with it.

    A run's tables are in `dataset` (project.dataset), so a statement names them alone; so are the functions it calls,
    which the deploy made (functions(), procedures()). `client` is a google.cloud.bigquery.Client, made when not
    given; `bigquery` is the module its job configurations come from, imported when not given.
    """
    name = "bigquery"
    # a call of the method's JavaScript, Python and portable functions, which functions() makes
    CALLS = calls_of([*(f"cl_{n}(?:_cut)?" for n in FUNCTIONS), "er_hash", "nfkc", "one_byte_hash", "fit_model",
                      "entities_of"], re.I)

    def __init__(self, dataset: str, client: object = None, bigquery: object = None) -> None:
        self.bigquery = bigquery or importlib.import_module("google.cloud.bigquery")
        self.client = client or self.bigquery.Client(project=dataset.split(".")[0])
        self.dataset, self.session = dataset, None
        try:  # what a query of a table the dataset lacks raises; the client library brings it
            self.MISSING = (importlib.import_module("google.api_core.exceptions").NotFound,)
        except ImportError:  # a test's fake client, without the library: no such error to catch
            self.MISSING = ()

    OWN = calls_of(method_functions())  # a call of the method's SQL functions: the deploy made each in the dataset

    def _job(self, sql: str, values: dict | None = None) -> object:
        """Run `sql` with its calls qualified, in the job's session (the first query makes it); return its result."""
        text = qualified(sql, self.OWN, self.dataset)
        job = self.client.query(text, job_config=self._config(values))
        result = job.result()
        if self.session is None:
            self.session = job.session_info.session_id
        return result

    def _config(self, values: dict | None) -> object:
        """Return a query's configuration: in the job's session, the dataset the default, `values` its parameters."""
        bq = self.bigquery
        session = [bq.ConnectionProperty("session_id", self.session)] if self.session else []
        config = bq.QueryJobConfig(create_session=self.session is None, default_dataset=self.dataset,
                                   connection_properties=session)

        def parameter(name: str, v: object) -> object:
            if isinstance(v, list):
                return bq.ArrayQueryParameter(name, bigquery_type(v[0]) if v else "STRING", v)
            return bq.ScalarQueryParameter(name, bigquery_type(v), v)

        config.query_parameters = [parameter(name, v) for name, v in (values or {}).items()]
        return config

    def run(self, sql: str, values: dict | None = None) -> None:
        if TEMP_FUNCTION.match(sql):  # the deploy made it in the dataset (procedures): no need to make it again
            return
        self._job(sql, values)

    def rows(self, sql: str, values: dict | None = None) -> list[tuple]:
        return [tuple(r.values()) for r in self._job(sql, values)]

    def value(self, sql: str, values: dict | None = None) -> object:
        return self.rows(sql, values)[0][0]

    def frame(self, sql: str, values: dict | None = None) -> pd.DataFrame:
        return self._job(sql, values).to_dataframe()

    def columns(self, table: str) -> list[tuple[str, str]]:
        """Return a table's columns, as (name, type); a repeated column's type ends in []."""
        schema = self.client.get_table(f"{self.dataset}.{table}").schema
        return [(f.name, f.field_type + ("[]" if f.mode == "REPEATED" else "")) for f in schema]

    def put(self, table: str, frame: pd.DataFrame) -> None:
        """Make a small frame the dataset's table `table`, by a load job."""
        config = self.bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        self.client.load_table_from_dataframe(frame, f"{self.dataset}.{table}", job_config=config).result()

    def read_parquet(self, table: str, files: list[str], columns: list[str] = ()) -> None:
        """Load Parquet files in Cloud Storage (gs://…) as the dataset's table, adding each of `columns` they lack."""
        config = self.bigquery.LoadJobConfig(source_format="PARQUET", write_disposition="WRITE_TRUNCATE")
        self.client.load_table_from_uri(list(files), f"{self.dataset}.{table}", job_config=config).result()
        for c in columns:
            self.run(f"ALTER TABLE `{table}` ADD COLUMN IF NOT EXISTS `{c}` STRING")

    @contextlib.contextmanager
    def scratch(self):
        """Run what follows in a session of its own, whose temporary tables end with it (a lookup writes no other)."""
        self.close()
        try:
            yield
        finally:
            self.close()

    def close(self) -> None:
        """End the session, and its temporary tables with it."""
        if self.session:
            self.client.query("CALL BQ.ABORT_SESSION()", job_config=self._config(None)).result()
            self.session = None


CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200d\u2060\ufeff]")  # controls and invisible spaces


def names(header: list[str]) -> list[str]:
    """Return the header with each column a name of its own, as both engines read names whatever their case.

    A blank name is numbered (column_4); one that repeats another but for its case gets a suffix past every name the
    header gives (TEL, tel → TEL, tel_2).
    """
    given = [CONTROL.sub("", h).strip() or f"column_{i + 1}" for i, h in enumerate(header)]
    out, seen, low = [], set(), {g.casefold() for g in given}
    for base in given:
        name, k = base, 1
        while name.casefold() in seen or (k > 1 and name.casefold() in low):
            k += 1
            name = f"{base}_{k}"
        out.append(name)
        seen.add(name.casefold())
    return out
