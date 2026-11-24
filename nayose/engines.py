"""Where nayose's SQL runs. The SQL is BigQuery's (nayose/sql/), and the two engines differ only here:

    BigQuery   runs it as written, in a session of the job's own, a run's tables in its dataset; the functions it
               calls by name (cl_*, er_hash, nfkc) are the functions dataset's, which the deploy makes (functions())
    DuckDB     translates it first (sqlglot, BigQuery → DuckDB), refusing a form whose translation changes what it
               gives (AVOID, avoided()), and calls twins of the same functions: for cl_*, DuckDB's own where
               both strings are a byte a character (native), else rapidfuzz; unicodedata for nfkc, numpy for one_byte_hash, a macro for er_hash

Both answer the same verbs: run (a statement, nothing back), rows, value, frame (small results only: a step's
tables stay in the engine); put (a small frame as a table, such as the model EM learns); read_parquet (input files
as a table).
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

from nayose import em, entities

STRINGS = Path(__file__).parent / "strings.js"  # the comparison functions in JavaScript, as BigQuery runs them

FUNCTIONS = {  # each character-level comparison the SQL calls as cl_<name>(a, b) and cl_<name>_cut(a, b, threshold)
    "jaro_winkler": (True, JaroWinkler.similarity),  # True: a similarity, passing at the threshold or above
    "levenshtein": (False, Levenshtein.distance),  # False: a distance, passing at the threshold or below
    "damerau_levenshtein": (False, DamerauLevenshtein.distance),
    "hamming": (False, Hamming.distance),
}

BUILT_IN = {"levenshtein": "EDIT_DISTANCE"}  # a comparison BigQuery has itself, on characters (Unicode code points), as the twin
# counts them: deployed as a SQL function over it, never JavaScript. (The SQL never names it: DuckDB's would count bytes.)

AVOID = {  # a form whose DuckDB translation gives another result than BigQuery's: what to write instead
    r"\bCOUNTIF\s*\(": "COUNTIF: DuckDB's COUNT_IF gives NULL where every test is NULL, BigQuery 0; write COUNT(CASE WHEN … THEN 1 END)",
    r"\bGROUP\s+BY\s+ALL\b": "GROUP BY ALL: it comes back as a column named ALL; name the columns",
    r"\bEDIT_DISTANCE\s*\(": "EDIT_DISTANCE: DuckDB's LEVENSHTEIN counts bytes, not characters; write cl_levenshtein",
    r"\bNORMALIZE\s*\(": "NORMALIZE: DuckDB has no NFKC; write nfkc(x)",
    r"\bCONCAT_WS\s*\(": "CONCAT_WS: its NULLs translate otherwise; write ARRAY_TO_STRING([…], separator)",
    r"\bUNPIVOT\b": "UNPIVOT: translated, it loses rows; write one SELECT per column, joined by UNION ALL",
}


def avoided(sql: str) -> list[str]:
    """What in `sql` (BigQuery's dialect) translates to DuckDB with another result: the forms of AVOID, and a decimal
    literal, which BigQuery reads as FLOAT64 and DuckDB as DECIMAL (write CAST(1.5 AS FLOAT64))."""
    out = [why for pattern, why in AVOID.items() if re.search(pattern, sql, flags=re.I)]
    for tree in sqlglot.parse(sql, read="bigquery"):
        for lit in tree.find_all(exp.Literal) if tree else ():
            if lit.is_number and re.search(r"[.eE]", lit.this):
                parent = lit.parent
                if not (isinstance(parent, exp.Cast) and parent.to.this == exp.DataType.Type.DOUBLE):
                    out.append(f"the decimal literal {lit.this}: DuckDB reads it as DECIMAL, BigQuery as FLOAT64; write CAST({lit.this} AS FLOAT64)")
    return out


@functools.lru_cache(maxsize=4096)  # each statement translated once: the stage files hold a few hundred
def duckdb_sql(sql: str) -> str:
    """`sql` (BigQuery's dialect) as DuckDB runs it, or ValueError naming what it holds that DuckDB would answer otherwise."""
    if bad := avoided(sql):
        raise ValueError("; ".join(bad) + f": {sql.strip()[:160]}")
    trees = [tree.transform(as_bigquery) for tree in sqlglot.parse(sql, read="bigquery")]
    return ";\n".join(t.sql(dialect="duckdb", unsupported_level=sqlglot.ErrorLevel.RAISE) for t in trees)


def as_bigquery(node: exp.Expression) -> exp.Expression:
    """Where sqlglot's translation answers otherwise, the node as BigQuery answers it:
    - DIV(a, b): DuckDB's a // b, each side and the whole in brackets (sqlglot writes DIV(x - y, 2) as x - y // 2);
    - a function's ANY TYPE parameter (a record's row, say): untyped, as a DuckDB macro's (sqlglot types it VARIANT);
    - UNNEST ... WITH OFFSET: counted from 0, as BigQuery counts (sqlglot writes DuckDB's WITH ORDINALITY, from 1);
    - array[OFFSET(i)] where i isn't a number: DuckDB's array[i + 1] (sqlglot moves a number's base only);
    - REGEXP_EXTRACT: the group's match where the pattern has one (sqlglot reads groups with Python's re, which can't
      read RE2's \\x{3000} or \\p{Nd}), and NULL where it doesn't match (DuckDB's gives '');
    - CLUSTER BY: BigQuery's storage order, what a filter on its columns prunes by; DuckDB keeps none, so it goes."""
    if isinstance(node, exp.ClusterProperty):
        return None
    if isinstance(node, exp.ColumnDef) and node.args.get("kind") is not None and node.args["kind"].this == exp.DataType.Type.VARIANT:
        node.set("kind", None)
        return node
    if isinstance(node, exp.Bracket) and node.args.get("offset") == 0 and not node.expressions[0].is_int:
        node.set("expressions", [exp.Add(this=exp.Paren(this=node.expressions[0]), expression=exp.Literal.number(1))])
        node.set("offset", 1)  # counted from 1 now, as DuckDB counts
        return node
    if isinstance(node, exp.Select) and not node.args.get("bigquery"):
        node.set("bigquery", True)
        for unnest in (u for u in node.find_all(exp.Unnest) if isinstance(u.args.get("offset"), exp.Identifier) and u.parent_select is node):
            name = unnest.args["offset"].name
            for col in [c for c in node.find_all(exp.Column) if c.name == name and not c.table and c.parent_select is node]:
                shifted = exp.Paren(this=exp.Sub(this=col.copy(), expression=exp.Literal.number(1)))
                col.replace(exp.alias_(shifted, name) if col.parent is node else shifted)  # a column selected keeps its name
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


def groups(pattern: str) -> int:  # the capturing groups of an RE2 pattern, counted by Python's re once RE2's own escapes are read
    python = re.sub(r"\\x\{([0-9a-fA-F]+)\}", lambda m: f"\\U{int(m[1], 16):08x}", pattern)
    return re.compile(re.sub(r"\\[pP](?:\{[^}]*\}|[A-Za-z])", r"\\w", python)).groups


def compare(name: str, cut: bool = False):
    """cl_<name>(a, b) for DuckDB, character-level and NULL-safe, as rapidfuzz scores it; with `cut`,
    cl_<name>_cut(a, b, threshold): the same score wherever it passes the threshold, and a failing one elsewhere, found
    without finishing the work. A similarity's cut is a hair below its threshold: rapidfuzz's scores are float32."""
    similarity, scorer = FUNCTIONS[name]

    def f(a: pa.Array, b: pa.Array, threshold: pa.Array | None) -> pa.Array:
        null = pc.or_(a.is_null(), b.is_null())
        x, y = pc.fill_null(a, "").to_pylist(), pc.fill_null(b, "").to_pylist()
        t = None if threshold is None or not len(threshold) else threshold[0].as_py()
        early = {} if t is None else {"score_cutoff": min(max(t - 1e-6, 0.0), 1.0) if similarity else max(int(t), 0)}
        scores = process.cpdist(x, y, scorer=scorer, **early)
        return pa.array(np.asarray(scores, dtype=float), mask=null.to_numpy(zero_copy_only=False))
    return (lambda a, b, threshold: f(a, b, threshold)) if cut else (lambda a, b: f(a, b, None))  # DuckDB counts the parameters


NATIVE = {"jaro_winkler": "jaro_winkler_similarity(a, b)", "levenshtein": "levenshtein(a, b)",
          "damerau_levenshtein": "damerau_levenshtein(a, b)", "hamming": "hamming(a, b)"}


def native(name: str, twin: str) -> str:
    """cl_<name> on DuckDB, as SQL over a and b. DuckDB's own comparisons count bytes, and a Python function is called a
    chunk at a time under one lock: where both strings are a byte a character (ASCII, or records.sql's one-byte copies)
    and filled, DuckDB's own answers, giving what the twin gives (`twin`, its call), which answers elsewhere: a
    similarity as float32; a cut's failing score as rapidfuzz's, 0 for a similarity and the threshold + 1 for a distance.
    Hamming: DuckDB's takes strings of one length only (rapidfuzz pads the shorter)."""
    score, cut = NATIVE[name], twin.endswith("t)")
    if FUNCTIONS[name][0]:
        value = f"CAST(CAST({score} AS FLOAT) AS DOUBLE)"
        out = f"CASE WHEN {score} >= least(greatest(t - 1e-6, 0), 1) THEN {value} ELSE 0 END" if cut else value
    else:
        out = f"CASE WHEN {score} <= greatest(floor(t), 0) THEN {score} ELSE greatest(floor(t), 0) + 1 END" if cut else score
    same = " AND length(a) = length(b)" if name == "hamming" else ""
    return (f"CASE WHEN a IS NULL OR b IS NULL THEN NULL WHEN a <> '' AND b <> '' AND strlen(a) = length(a) AND strlen(b) = length(b){same} "
            f"THEN CAST({out} AS DOUBLE) ELSE {twin} END")


def one_byte_hash(a: pa.Array) -> pa.Array:
    """Each character one ASCII byte, 33 + its code point mod 94, as BigQuery's one_byte_hash: two may share a byte, so
    an edit distance of the copies is never more than the strings' (records.sql)."""
    values = a.to_pylist()
    filled = [v for v in values if v is not None]
    points = np.frombuffer("".join(filled).encode("utf-32-le"), dtype=np.uint32)
    text = (33 + points % 94).astype(np.uint8).tobytes().decode("ascii")
    ends = np.cumsum([len(v) for v in filled], dtype=np.int64)
    parts = iter(text[s:e] for s, e in zip(np.concatenate(([0], ends[:-1])), ends))
    return pa.array([None if v is None else next(parts) for v in values], pa.string())


def nfkc(a: pa.Array) -> pa.Array:
    """Unicode NFKC, as BigQuery's NORMALIZE(x, NFKC) gives it: Arrow's (utf8proc), in C++ and the same on every Python.
    Python's unicodedata 16.0 gives each code point the same but one assigned after it (U+A7F1)."""
    return pc.utf8_normalize(a.cast(pa.string()), form="NFKC")


class DuckDB:
    """nayose's SQL on DuckDB, in process: a run's tables in the database file at `path` (None: in memory, a spill
    folder of its own). `compute`: DuckDB's settings (threads, memory_limit, temp_directory)."""
    name = "duckdb"

    def __init__(self, path: Path | None = None, compute: dict | None = None) -> None:
        self.con = duckdb.connect(str(path) if path else ":memory:")
        self.spill = None
        settings = {k: v for k, v in (compute or {}).items() if v not in ("", None)}
        if not path and "temp_directory" not in settings:  # spilled records in a folder only this job can read
            self.spill = tempfile.mkdtemp(prefix="nayose-spill-")
            settings["temp_directory"] = self.spill
        self.con.execute("SET enable_progress_bar = false")
        for key, value in settings.items():
            self.con.execute(f"SET {key} = '{value}'")
        # the portable hash: MD5's first 15 hex digits as an integer, as BigQuery's er_hash (functions())
        self.con.execute("CREATE OR REPLACE MACRO er_hash(x) AS ('0x' || substr(md5(coalesce(CAST(x AS VARCHAR), '')), 1, 15))::BIGINT")
        for name in FUNCTIONS:  # cl_*: DuckDB's own function where it answers as the twin does (native), else the twin
            self.con.create_function(f"twin_{name}", compare(name), ["VARCHAR", "VARCHAR"], "DOUBLE", type="arrow")
            self.con.create_function(f"twin_{name}_cut", compare(name, cut=True), ["VARCHAR", "VARCHAR", "DOUBLE"], "DOUBLE", type="arrow")
            self.con.execute(f"CREATE OR REPLACE MACRO cl_{name}(a, b) AS {native(name, f'twin_{name}(a, b)')}")
            self.con.execute(f"CREATE OR REPLACE MACRO cl_{name}_cut(a, b, t) AS {native(name, f'twin_{name}_cut(a, b, t)')}")
        self.con.create_function("nfkc", nfkc, ["VARCHAR"], "VARCHAR", type="arrow")
        self.con.create_function("one_byte_hash", one_byte_hash, ["VARCHAR"], "VARCHAR", type="arrow")
        self.con.create_function("fit_model", em.fit, ["VARCHAR", "VARCHAR", "VARCHAR"], "VARCHAR", null_handling="special")  # EM: Python, as on BigQuery
        self.con.create_function("entities_of", entities.of, ["VARCHAR"], "VARCHAR")  # decide's components: the same

    def run(self, sql: str, values: dict | None = None) -> None:
        self.con.execute(duckdb_sql(sql), values or None)

    def rows(self, sql: str, values: dict | None = None) -> list[tuple]:
        return self.con.execute(duckdb_sql(sql), values or None).fetchall()

    def value(self, sql: str, values: dict | None = None) -> object:
        return self.rows(sql, values)[0][0]

    def frame(self, sql: str, values: dict | None = None) -> pd.DataFrame:
        return self.con.execute(duckdb_sql(sql), values or None).df()

    def columns(self, table: str) -> list[tuple[str, str]]:  # a table's columns: (name, type)
        return [(r[0], r[1]) for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()]

    def put(self, table: str, frame: pd.DataFrame) -> None:  # a small frame as the table `table`, replacing it
        self.con.register("nayose_put", frame)
        try:
            self.con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM nayose_put')
        finally:
            self.con.unregister("nayose_put")

    def read_parquet(self, table: str, files: list[Path], columns: list[str] = ()) -> None:
        """Parquet files as the table `table`, each column of each file a name of its own (names), the files' columns
        joined by name, and each of `columns` they lack, missing. Text that isn't UTF-8 is refused. Copied once: the
        mapping reads it twice, and a file read in place each time is slower."""
        quote = lambda n: '"' + n.replace('"', '""') + '"'
        parts = [f"SELECT * FROM read_parquet(?) AS t({', '.join(map(quote, names(pq.read_schema(f).names)))})" for f in files]
        self.con.execute(f'CREATE OR REPLACE TABLE "{table}" AS ' + " UNION ALL BY NAME ".join(parts), [str(f) for f in files])
        have = {n.casefold() for n, _ in self.columns(table)}
        for c in (c for c in columns if c.casefold() not in have):
            self.con.execute(f'ALTER TABLE "{table}" ADD COLUMN {quote(c)} VARCHAR')

    @contextlib.contextmanager
    def scratch(self):  # a transaction rolled back: whatever its statements write is undone after
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
    """The statements the deploy runs once in `dataset` (project.dataset): each comparison of FUNCTIONS in JavaScript
    (cl_<name>, and cl_<name>_cut: the same score, its threshold unread), or over BigQuery's own (BUILT_IN), the
    portable hash (er_hash), nfkc,
    one_byte_hash, and the Python UDFs: EM's fit_model (nayose/em.py) and decide's entities_of (nayose/entities.py)."""
    library = STRINGS.read_text(encoding="utf-8")
    out = []
    for name in FUNCTIONS:
        if name in BUILT_IN:  # BigQuery's own, on characters as the twin counts them: no JavaScript
            out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}(a STRING, b STRING) AS (CAST({BUILT_IN[name]}(a, b) AS FLOAT64))")
            out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}_cut(a STRING, b STRING, threshold FLOAT64) AS "
                       f"(CAST(LEAST({BUILT_IN[name]}(a, b), FLOOR(threshold) + 1) AS FLOAT64))")  # past it, threshold + 1, as the cut twin
            continue
        body = f"{library}\nreturn a === null || b === null ? null : {name}(a, b);"
        for suffix, extra in (("", ""), ("_cut", ", threshold FLOAT64")):
            out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}{suffix}(a STRING, b STRING{extra}) RETURNS FLOAT64 "
                       f"LANGUAGE js AS r\"\"\"{body}\"\"\"")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.er_hash(x ANY TYPE) AS "
               "(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(COALESCE(CAST(x AS STRING), ''))), 1, 15)) AS INT64))")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.nfkc(x STRING) AS (NORMALIZE(x, NFKC))")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.one_byte_hash(x STRING) AS "
               "(CODE_POINTS_TO_STRING(ARRAY(SELECT 33 + MOD(c, 94) FROM UNNEST(TO_CODE_POINTS(x)) AS c WITH OFFSET AS i ORDER BY i)))")
    for module, name, args, entry in ((em, "fit_model", "counts STRING, settings STRING, stored STRING", "fit"), (entities, "entities_of", "pairs STRING", "of")):
        source = Path(module.__file__).read_text(encoding="utf-8")  # BigQuery's Python UDF: python-3.11, standard library only
        assert "'''" not in source, f"{module.__name__}: no triple single quotes, which end BigQuery's raw string"
        out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.{name}({args}) RETURNS STRING LANGUAGE python "
                   f"OPTIONS (runtime_version = 'python-3.11', entry_point = '{entry}') AS r'''{source}'''")
    return out


JOBS = {  # each job BigQuery runs as a procedure of the run's dataset: its stages in order, and what values() is told
    "build": [("functions", {}), ("mapping", {}), ("records", {}), ("fit", {"refit": True}), ("score", {}), ("decide", {}), ("report", {})],
    "update": [("functions", {}), ("mapping", {}), ("records", {}), ("fit", {"refit": False}), ("score", {}), ("decide", {}), ("report", {})],
    "decide": [("functions", {}), ("decide", {})],
    "match": [("functions", {}), ("match", {})],
}  # no lookup: nayose.lookup's statements, each step in a session of its own (BigQuery.scratch), write temporary tables alone
ARGUMENTS = {"match": {"threshold": "FLOAT64"}}  # a procedure's own values: given when it is called, not declared
RUN_TABLES = ("records", "placeholders", "this_batch", "set_aside", "fit_sample", "fit_prior", "em_patterns", "u_outside", "u_counted",
              "u_near", "u_sampled", "u_filled", "model", "fit", "rule_keys", "every_key", "rule_pairs", "cands", "gated", "scored", "gold")  # a build starts without them; decisions stay
TEMP_FUNCTION = re.compile(r"^((?:\s*--[^\n]*\n)*\s*)CREATE OR REPLACE TEMP FUNCTION (\w+)", re.I)


VIEW = re.compile(r"\A(?:\s*--[^\n]*\n)*\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b", re.I)


def in_dataset(sql: str, dataset: str) -> str:
    """A view's statement, each table it names (a WITH's aside) the dataset's: BigQuery reads a view's body without
    a default dataset."""
    tree, (project, name) = sqlglot.parse_one(sql, read="bigquery"), dataset.split(".")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not t.args.get("db") and t.name not in ctes:
            t.set("db", exp.to_identifier(name))
            t.set("catalog", exp.to_identifier(project))
    return tree.sql(dialect="bigquery")


def procedures(dataset: str, functions: str, mapping: Path | None = None) -> list[str]:
    """The statements the deploy runs in `dataset` (project.dataset), after functions(): the method's own SQL functions
    (each file's CREATE TEMP FUNCTION), the dataset's; then one procedure a job (JOBS), its stages' statements in order
    (mapping: the deployment's mapping.sql), the values they read (@name: nayose.values, config.toml's) declared at
    its top as v_name, the dataset the one whose tables they name. Every call of a method's function names its
    dataset: `functions`' for the JavaScript and Python ones, `dataset`'s for the SQL ones."""
    import nayose
    path = lambda stage: (mapping or nayose.HERE / "mapping.sql") if stage == "mapping" else nayose.SQL / f"{stage}.sql"
    made, bodies = {}, {}
    for job, stages in JOBS.items():
        body, declared = [], {}
        for stage, told in stages:
            declared |= nayose.values(stage, **told)
            for sql in nayose.statements(path(stage).read_text(encoding="utf-8")):
                if m := TEMP_FUNCTION.match(sql):
                    made.setdefault(m[2], TEMP_FUNCTION.sub(lambda x: f"{x[1]}CREATE OR REPLACE FUNCTION `{dataset}`.{x[2]}", sql, count=1))
                else:
                    sql = re.sub(r"@(\w+)", r"v_\1", sql)
                    body.append(in_dataset(sql, dataset) if VIEW.match(sql) else sql)
        bodies[job] = (body, {k: v for k, v in declared.items() if k not in ARGUMENTS.get(job, {})})
    own = re.compile(r"(?<![\w.`])(" + "|".join(sorted(made, key=len, reverse=True)) + r")\s*\(")
    ours = lambda sql: own.sub(lambda m: f"`{dataset}`.{m[1]}(", BigQuery.CALLS.sub(lambda m: f"`{functions}`.{m[1]}(", sql))
    out = [ours(sql) for sql in made.values()]
    project, name = dataset.split(".")
    for job, (body, declared) in bodies.items():
        args = ", ".join(f"v_{k} {kind}" for k, kind in ARGUMENTS.get(job, {}).items())
        head = [f"DECLARE v_{k} {bigquery_type(v)} DEFAULT {bigquery_literal(v)}" for k, v in declared.items()]
        head += [f"SET @@dataset_project_id = '{project}'", f"SET @@dataset_id = '{name}'"]
        head += [f"DROP TABLE IF EXISTS {x}" for x in RUN_TABLES] if job == "build" else []
        method = nayose.fingerprint(mapping=mapping)  # what an update needs unchanged since the build
        head += [nayose.UNCHANGED.replace("@fingerprint", bigquery_literal(method))] if job == "update" else []
        body = [*body, nayose.METHOD.replace("@fingerprint", bigquery_literal(method))] if job == "build" else body
        out.append(f"CREATE OR REPLACE PROCEDURE `{dataset}`.{job}({args})\nBEGIN\n" + ";\n".join([*head, *map(ours, body)]) + ";\nEND")
    return out


def bigquery_type(v: object) -> str:  # a value's BigQuery type, as values() gives it
    if isinstance(v, bool):
        return "BOOL"
    if isinstance(v, list):
        return f"ARRAY<{bigquery_type(v[0]) if v else 'STRING'}>"
    return "INT64" if isinstance(v, int) else "FLOAT64" if isinstance(v, float) else "STRING"


def bigquery_literal(v: object) -> str:  # a value as BigQuery SQL: a string escaped character by character where it must be
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, list):
        return f"{bigquery_type(v)}[{', '.join(map(bigquery_literal, v))}]"
    if isinstance(v, float):
        return f"CAST('{v!r}' AS FLOAT64)" if v != v or v in (float("inf"), float("-inf")) else f"CAST({v!r} AS FLOAT64)"
    if isinstance(v, int):
        return str(v)
    said = {"\\": "\\\\", "'": "\\'"}
    return "'" + "".join(said.get(ch) or (ch if ch.isprintable() else f"\\U{ord(ch):08x}") for ch in str(v)) + "'"


class BigQuery:
    """nayose's SQL on BigQuery, as written, in one session of the job's own (its temporary tables die with it). A
    run's tables are in `dataset` (project.dataset), so a statement names them alone; the functions it calls are
    `functions`' (project.dataset, the deploy's: functions()). `client`: a google.cloud.bigquery.Client (made when not
    given); `bigquery`: the module its job configurations come from (imported when not given)."""
    name = "bigquery"
    CALLS = re.compile(r"(?<![\w.`])(" + "|".join([*(f"cl_{n}(?:_cut)?" for n in FUNCTIONS), "er_hash", "nfkc", "one_byte_hash", "fit_model", "entities_of"]) + r")\s*\(", re.I)

    def __init__(self, dataset: str, functions: str, client: object = None, bigquery: object = None) -> None:
        self.bigquery = bigquery or importlib.import_module("google.cloud.bigquery")
        self.client = client or self.bigquery.Client(project=dataset.split(".")[0])
        self.dataset, self.functions, self.session = dataset, functions, None

    def _job(self, sql: str, values: dict | None = None) -> object:
        text = self.CALLS.sub(lambda m: f"`{self.functions}`.{m.group(1)}(", sql)
        job = self.client.query(text, job_config=self._config(values))
        result = job.result()
        if self.session is None:
            self.session = job.session_info.session_id
        return result

    def _config(self, values: dict | None) -> object:
        bq = self.bigquery
        config = bq.QueryJobConfig(create_session=self.session is None, default_dataset=self.dataset,
                                   connection_properties=[bq.ConnectionProperty("session_id", self.session)] if self.session else [])
        config.query_parameters = [bq.ArrayQueryParameter(name, kind(v[0]) if v else "STRING", v) if isinstance(v, list)
                                   else bq.ScalarQueryParameter(name, kind(v), v) for name, v in (values or {}).items()]
        return config

    def run(self, sql: str, values: dict | None = None) -> None:
        self._job(sql, values)

    def rows(self, sql: str, values: dict | None = None) -> list[tuple]:
        return [tuple(r.values()) for r in self._job(sql, values)]

    def value(self, sql: str, values: dict | None = None) -> object:
        return self.rows(sql, values)[0][0]

    def frame(self, sql: str, values: dict | None = None) -> pd.DataFrame:
        return self._job(sql, values).to_dataframe()

    def columns(self, table: str) -> list[tuple[str, str]]:  # a table's columns: (name, type; a repeated one's ending in [])
        return [(f.name, f.field_type + ("[]" if f.mode == "REPEATED" else "")) for f in self.client.get_table(f"{self.dataset}.{table}").schema]

    def put(self, table: str, frame: pd.DataFrame) -> None:  # a small frame as the dataset's table `table` (a load job)
        config = self.bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        self.client.load_table_from_dataframe(frame, f"{self.dataset}.{table}", job_config=config).result()

    def read_parquet(self, table: str, files: list[str], columns: list[str] = ()) -> None:
        """Parquet files in Cloud Storage (gs://…) as the dataset's table, each of `columns` they lack, missing."""
        config = self.bigquery.LoadJobConfig(source_format="PARQUET", write_disposition="WRITE_TRUNCATE")
        self.client.load_table_from_uri(list(files), f"{self.dataset}.{table}", job_config=config).result()
        for c in columns:
            self.run(f"ALTER TABLE `{table}` ADD COLUMN IF NOT EXISTS `{c}` STRING")

    @contextlib.contextmanager
    def scratch(self):  # a session of its own: its temporary tables end with it (a lookup writes no other)
        self.close()
        try:
            yield
        finally:
            self.close()

    def close(self) -> None:  # the session ended, its temporary tables with it
        if self.session:
            self.client.query("CALL BQ.ABORT_SESSION()", job_config=self._config(None)).result()
            self.session = None


CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200d\u2060\ufeff]")


def names(header: list[str]) -> list[str]:
    """Each column a name of its own: a blank one numbered (column_4), one that repeats another but for case suffixed
    past every name the header gives (TEL, tel → TEL, tel_2): both engines read names case aside."""
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


def kind(v: object) -> str:  # a parameter's BigQuery type
    return "BOOL" if isinstance(v, bool) else "INT64" if isinstance(v, int) else "FLOAT64" if isinstance(v, float) else "STRING"

