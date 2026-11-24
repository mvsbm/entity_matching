"""The BigQuery engine: the steps' SQL, written in DuckDB's dialect, translated to BigQuery's (translate) and run in a
BigQuery session of the job's own, so the steps' working tables are the session's temporary tables, gone with it; the
records a job reads and the tables it writes live in the job's dataset. The character-level comparison functions
(cl_<name>, JavaScript: er/engine/udfs/strings.js) and the portable hash (er_hash) are functions in that dataset,
which the deploy creates (functions()).

A statement that holds a part only DuckDB has is refused by name (NotPortable), never sent half translated: every
statement a job sends translates (tests/test_bigquery.py), since what a step asks of where its tables are (their
columns, a table's existence, files read and written, slices, an index attached, the threads) is the engine's to
answer (er/engine/engine.py). What a BigQuery job still needs is that store: those answers on a dataset's tables.

google-cloud-bigquery is imported where this engine runs (a Cloud Run job's image), not on every machine."""
import importlib
import math
import re
from collections.abc import Iterator
from pathlib import Path

import sqlglot
from sqlglot import exp

UDFS = Path(__file__).parent / "udfs" / "strings.js"
FUNCTIONS = ("jaro_winkler", "jaro", "jaccard", "levenshtein", "damerau_levenshtein", "hamming")  # er.strings.FUNCTIONS less exact
DUCKDB_ONLY = {  # what refuses a statement, by the part that names it
    "DESCRIBE": r"^\s*DESCRIBE\b", "duckdb_tables()": r"\bduckdb_\w+\(", "current_setting()": r"\bcurrent_setting\(",
    "read_parquet()": r"\bread_parquet\(", "COPY … TO": r"^\s*COPY\b", "rowid": r"\browid\b", "ATTACH": r"^\s*(ATTACH|DETACH)\b",
    "a list function": r"\blist_\w+\(", "a SQL lambda": r"\blambda\s+\w+\s*:", "UNPIVOT … COLUMNS(*)": r"\bCOLUMNS\(",
    "arg_min/arg_max of n": r"\barg_(min|max)\([^()]*\([^()]*\)[^()]*,\s*\d+\)", "CALL": r"^\s*CALL\b", "a macro": r"\bCREATE\s+(OR\s+REPLACE\s+)?MACRO\b",
    "UNPIVOT … INTO NAME": r"\bINTO\s+NAME\b", "AS MATERIALIZED": r"\bAS\s+MATERIALIZED\b",  # sqlglot passes these through as they are
}


class NotPortable(ValueError):
    """A statement with a part only DuckDB has: named, so the job stops saying what a BigQuery job still lacks."""


def translate(sql: str, dataset: str) -> str:
    """`sql` (DuckDB's dialect) as BigQuery runs it in a session: a table the statement makes without a dataset is the
    session's temporary table; a comparison function or the portable hash is the dataset's (`dataset`, project.dataset).
    Refuses a part only DuckDB has (NotPortable, DUCKDB_ONLY)."""
    for part, pattern in DUCKDB_ONLY.items():
        if re.search(pattern, sql, flags=re.I | re.M):
            raise NotPortable(f"{part} is DuckDB's only: {sql.strip()[:120]}")
    out = []
    for tree in sqlglot.parse(sql, read="duckdb"):
        if tree is None:
            continue
        for create in tree.find_all(exp.Create):
            target = create.this.this if isinstance(create.this, exp.Schema) else create.this
            if create.args.get("kind") == "TABLE" and isinstance(target, exp.Table) and not target.db:
                create.set("properties", exp.Properties(expressions=[exp.TemporaryProperty()]))
        try:
            text = tree.sql(dialect="bigquery", unsupported_level=sqlglot.ErrorLevel.RAISE)
            sqlglot.parse_one(text, read="bigquery")  # what BigQuery's grammar refuses is refused here, not sent
        except (sqlglot.errors.UnsupportedError, sqlglot.errors.ParseError) as e:
            raise NotPortable(f"{str(e).splitlines()[0]}: {sql.strip()[:120]}") from None
        out.append(re.sub(r"\b(cl_\w+|er_hash)\(", lambda m: f"`{dataset}`.{m.group(1)}(", text, flags=re.I))
    return ";\n".join(out)


def functions(dataset: str) -> list[str]:
    """The statements the deploy runs once in `dataset` (project.dataset): each comparison function as rapidfuzz scores
    it, in JavaScript (cl_<name>, and cl_<name>_cut: the same score, its threshold unread), and the portable hash as
    er.config.hashed defines it (er_hash: MD5's first 60 bits). A NULL side gives NULL, as DuckDB's do."""
    library = UDFS.read_text(encoding="utf-8")
    out = []
    for name in FUNCTIONS:
        body = f"{library}\nreturn a === null || b === null ? null : {name}(a, b);"
        for suffix, extra in (("", ""), ("_cut", ", threshold FLOAT64")):
            out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}{suffix}(a STRING, b STRING{extra}) RETURNS FLOAT64 "
                       f"LANGUAGE js AS r\"\"\"{body}\"\"\"")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.er_hash(x ANY TYPE) AS "
               "(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(COALESCE(CAST(x AS STRING), ''))), 1, 15)) AS INT64))")
    return out


class BigQuery:
    """SQL on BigQuery, with DuckDB's engine's verbs (er/engine/engine.py), in one session: the first statement opens it,
    every one after runs in it. `dataset` (project.dataset) holds what the job reads and writes, and the functions.
    `client`: a google.cloud.bigquery.Client (made from `project` when not given); `bigquery`: the module its job
    configurations come from (google.cloud.bigquery, imported when not given)."""
    name = "bigquery"

    def __init__(self, dataset: str, project: str | None = None, location: str | None = None, client: object = None,
                 bigquery: object = None) -> None:
        self.bigquery = bigquery or importlib.import_module("google.cloud.bigquery")
        self.client = client or self.bigquery.Client(project=project, location=location)
        self.dataset, self.session = dataset, None
        self.registered: dict[str, str] = {}  # a name SQL reads → the dataset's table holding the frame registered under it

    def _job(self, sql: str, params: list | None = None) -> object:
        text = translate(sql, self.dataset)
        for name, table in self.registered.items():  # a registered frame, read by its name: the dataset's table holding it
            text = re.sub(rf"(?<![\w.`]){re.escape(name)}(?![\w`])", f"`{table}`", text)
        config = self._config(params)
        job = self.client.query(text, job_config=config)
        result = job.result()
        if self.session is None:
            self.session = job.session_info.session_id
        return result

    def _config(self, params: list | None) -> object:
        bq = self.bigquery
        config = bq.QueryJobConfig(create_session=self.session is None,
                                   connection_properties=[bq.ConnectionProperty("session_id", self.session)] if self.session else [])
        if params:  # DuckDB's ? placeholders, in order: BigQuery's positional parameters
            config.query_parameters = [bq.ArrayQueryParameter(None, "STRING", v) if isinstance(v, list) else bq.ScalarQueryParameter(None, _kind(v), v)
                                       for v in params]
        return config

    def run(self, sql: str, params: list | None = None) -> None:
        self._job(sql, params)

    def rows(self, sql: str, params: list | None = None) -> list[tuple]:
        return [tuple(r.values()) for r in self._job(sql, params)]

    def value(self, sql: str, params: list | None = None) -> object:
        return self.rows(sql, params)[0][0]

    def row(self, sql: str, params: list | None = None) -> tuple:
        return self.rows(sql, params)[0]

    def first(self, sql: str, params: list | None = None) -> tuple | None:
        got = self.rows(sql, params)
        return got[0] if got else None

    def frame(self, sql: str, params: list | None = None):
        return self._job(sql, params).to_dataframe()

    def arrow(self, sql: str, params: list | None = None):
        return self._job(sql, params).to_arrow()

    def numpy(self, sql: str, params: list | None = None) -> dict:
        table = self.arrow(sql, params)
        return {c: table[c].to_numpy() for c in table.column_names}

    def batches(self, sql: str, rows: int) -> Iterator:  # the Storage Read API's batches, as they come
        return self._job(sql).to_arrow_iterable(max_queue_size=2)

    def register(self, name: str, data: object) -> None:
        """A frame or an Arrow table SQL reads by `name`: loaded into a table of the dataset (a load job), which
        unregister drops. shortcut: one load job a frame, fine for the small ones a step registers (a sample, a
        sheet), not for a step that registers every record (the load step's chunks: a job of many tasks loads once)."""
        table = f"{self.dataset}.er_registered_{re.sub(r'[^A-Za-z0-9_]', '_', name)}"
        load = self.client.load_table_from_dataframe if hasattr(data, "to_parquet") else self.client.load_table_from_arrow
        load(data, table).result()
        self.registered[name] = table

    def unregister(self, name: str) -> None:
        table = self.registered.pop(name)
        self.client.delete_table(table, not_found_ok=True)

    def view(self, name: str, sql: str) -> None:  # computed once, here: BigQuery's sessions hold no temporary view
        self.run(f"CREATE OR REPLACE TABLE {name} AS {sql}")

    def cursor(self) -> "BigQuery":  # the client is shared by threads; the session too
        return self

    def room(self) -> float:  # no memory of the job's holds a step's tables
        return math.inf

    def spill_room(self) -> float:
        return math.inf

    def close(self) -> None:  # the frames registered dropped, the session ended (its temporary tables with it)
        for name in list(self.registered):
            self.unregister(name)
        if self.session:
            self.client.query("CALL BQ.ABORT_SESSION()", job_config=self._config(None)).result()
            self.session = None


def _kind(v: object) -> str:  # a scalar parameter's BigQuery type
    return "BOOL" if isinstance(v, bool) else "INT64" if isinstance(v, int) else "FLOAT64" if isinstance(v, float) else "STRING"
