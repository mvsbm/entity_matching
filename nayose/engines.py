"""Where nayose's SQL runs. The SQL is BigQuery's (nayose/sql/), and the two engines differ only here:

    BigQuery   runs it as written, in a session of the job's own, a run's tables in its dataset; the functions it
               calls by name (cl_*, er_hash, nfkc) are the functions dataset's, which the deploy makes (functions())
    DuckDB     translates it first (sqlglot, BigQuery → DuckDB), refusing a form whose translation changes what it
               gives (AVOID, avoided()), and calls Python twins of the same functions: rapidfuzz for cl_*,
               unicodedata for nfkc, a macro for er_hash

Both answer the same verbs: run (a statement, nothing back), rows, value, frame (small results only: a step's
tables stay in the engine); put (a small frame as a table, such as the model EM learns); read_parquet (input files
as a table).
"""
import functools
import importlib
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import sqlglot
from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein, Hamming, JaroWinkler, Levenshtein
from sqlglot import exp

STRINGS = Path(__file__).parent / "strings.js"  # the comparison functions in JavaScript, as BigQuery runs them

FUNCTIONS = {  # each character-level comparison the SQL calls as cl_<name>(a, b) and cl_<name>_cut(a, b, threshold)
    "jaro_winkler": (True, JaroWinkler.similarity),  # True: a similarity, passing at the threshold or above
    "levenshtein": (False, Levenshtein.distance),  # False: a distance, passing at the threshold or below
    "damerau_levenshtein": (False, DamerauLevenshtein.distance),
    "hamming": (False, Hamming.distance),
}

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


@functools.cache
def duckdb_sql(sql: str) -> str:
    """`sql` (BigQuery's dialect) as DuckDB runs it, or ValueError naming what it holds that DuckDB would answer otherwise."""
    if bad := avoided(sql):
        raise ValueError("; ".join(bad) + f": {sql.strip()[:160]}")
    return ";\n".join(sqlglot.transpile(sql, read="bigquery", write="duckdb", unsupported_level=sqlglot.ErrorLevel.RAISE))


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


def nfkc(a: pa.Array) -> pa.Array:  # Unicode NFKC, as BigQuery's NORMALIZE(x, NFKC) gives it
    return pa.array([None if v is None else unicodedata.normalize("NFKC", v) for v in a.to_pylist()], pa.string())


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
        for name in FUNCTIONS:
            self.con.create_function(f"cl_{name}", compare(name), ["VARCHAR", "VARCHAR"], "DOUBLE", type="arrow")
            self.con.create_function(f"cl_{name}_cut", compare(name, cut=True), ["VARCHAR", "VARCHAR", "DOUBLE"], "DOUBLE", type="arrow")
        self.con.create_function("nfkc", nfkc, ["VARCHAR"], "VARCHAR", type="arrow")

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

    def read_parquet(self, table: str, files: list[Path]) -> None:  # Parquet files as the table `table`, columns by name
        self.con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM read_parquet(?, union_by_name = true)', [[str(f) for f in files]])

    def close(self) -> None:
        self.con.close()
        if self.spill:
            shutil.rmtree(self.spill, ignore_errors=True)


def functions(dataset: str) -> list[str]:
    """The statements the deploy runs once in `dataset` (project.dataset): each comparison of FUNCTIONS in JavaScript
    (cl_<name>, and cl_<name>_cut: the same score, its threshold unread), the portable hash (er_hash) and nfkc."""
    library = STRINGS.read_text(encoding="utf-8")
    out = []
    for name in FUNCTIONS:
        body = f"{library}\nreturn a === null || b === null ? null : {name}(a, b);"
        for suffix, extra in (("", ""), ("_cut", ", threshold FLOAT64")):
            out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}{suffix}(a STRING, b STRING{extra}) RETURNS FLOAT64 "
                       f"LANGUAGE js AS r\"\"\"{body}\"\"\"")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.er_hash(x ANY TYPE) AS "
               "(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(COALESCE(CAST(x AS STRING), ''))), 1, 15)) AS INT64))")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.nfkc(x STRING) AS (NORMALIZE(x, NFKC))")
    return out


class BigQuery:
    """nayose's SQL on BigQuery, as written, in one session of the job's own (its temporary tables die with it). A
    run's tables are in `dataset` (project.dataset), so a statement names them alone; the functions it calls are
    `functions`' (project.dataset, the deploy's: functions()). `client`: a google.cloud.bigquery.Client (made when not
    given); `bigquery`: the module its job configurations come from (imported when not given)."""
    name = "bigquery"
    CALLS = re.compile(r"(?<![\w.`])(" + "|".join([*(f"cl_{n}(?:_cut)?" for n in FUNCTIONS), "er_hash", "nfkc"]) + r")\s*\(", re.I)

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

    def columns(self, table: str) -> list[tuple[str, str]]:  # a table's columns: (name, type)
        return [(f.name, f.field_type) for f in self.client.get_table(f"{self.dataset}.{table}").schema]

    def put(self, table: str, frame: pd.DataFrame) -> None:  # a small frame as the dataset's table `table` (a load job)
        config = self.bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        self.client.load_table_from_dataframe(frame, f"{self.dataset}.{table}", job_config=config).result()

    def read_parquet(self, table: str, files: list[str]) -> None:  # Parquet files in Cloud Storage (gs://…) as the dataset's table
        config = self.bigquery.LoadJobConfig(source_format="PARQUET", write_disposition="WRITE_TRUNCATE")
        self.client.load_table_from_uri(list(files), f"{self.dataset}.{table}", job_config=config).result()

    def close(self) -> None:  # the session ended, its temporary tables with it
        if self.session:
            self.client.query("CALL BQ.ABORT_SESSION()", job_config=self._config(None)).result()
            self.session = None


def kind(v: object) -> str:  # a parameter's BigQuery type
    return "BOOL" if isinstance(v, bool) else "INT64" if isinstance(v, int) else "FLOAT64" if isinstance(v, float) else "STRING"

