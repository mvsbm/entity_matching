"""The DuckDB engine: SQL in DuckDB's dialect on an in-process connection, the character-level comparison functions
registered as Python UDFs (cl_<name>, rapidfuzz), files on the local disk. What every engine offers is in
er/engine/engine.py."""
import getpass
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from rapidfuzz import process

from er.strings import FUNCTIONS


def size_bytes(text: str) -> int:  # one of DuckDB's sizes: "8.0 GiB", "512.0 MiB", "1.5 GB"
    num, unit = re.match(r"([\d.]+)\s*([A-Za-z]*)", text).groups()
    scale = {"": 1, "b": 1, "bytes": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "pb": 1e15, "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40, "pib": 2**50}
    return int(float(num) * scale[unit.lower()])


class DuckDB:
    """SQL on one DuckDB connection (`con`). The verbs say what comes back: run nothing, value one value, row the first
    row, first the first row or None, rows every row, frame a pandas frame, numpy columns as arrays, arrow an Arrow
    table, batches Arrow batches as they come. The last four are for small results, or results read in chunks: no
    step pulls a table that grows with the records into Python whole. register puts a frame (or an Arrow table) where
    SQL reads it by name, unregister takes it away."""
    name = "duckdb"

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con
        # the portable hash (er.config.hashed): MD5's first 15 hex digits as an integer, as BigQuery computes it too
        con.execute("CREATE OR REPLACE MACRO er_hash(x) AS ('0x' || substr(md5(coalesce(CAST(x AS VARCHAR), '')), 1, 15))::BIGINT")

    def run(self, sql: str, params: list | None = None) -> None:
        self.con.execute(sql, params)

    def value(self, sql: str, params: list | None = None) -> object:
        return self.con.execute(sql, params).fetchall()[0][0]

    def row(self, sql: str, params: list | None = None) -> tuple:
        return self.con.execute(sql, params).fetchall()[0]

    def first(self, sql: str, params: list | None = None) -> tuple | None:
        return self.con.execute(sql, params).fetchone()

    def rows(self, sql: str, params: list | None = None) -> list[tuple]:
        return self.con.execute(sql, params).fetchall()

    def frame(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params).df()

    def numpy(self, sql: str, params: list | None = None) -> dict[str, np.ndarray]:
        return self.con.execute(sql, params).fetchnumpy()

    def arrow(self, sql: str, params: list | None = None) -> pa.Table:
        return self.con.execute(sql, params).fetch_arrow_table()

    def batches(self, sql: str, rows: int) -> Iterator[pa.RecordBatch]:
        """The rows of `sql` in Arrow batches of about `rows`, read on a cursor of their own: statements on the engine
        go on alongside (a step writes each cleaned batch while the next is read)."""
        return self.con.cursor().sql(sql).to_arrow_reader(rows)

    def register(self, name: str, data: object) -> None:  # a frame, an Arrow table, or a relation of this connection
        self.con.register(name, data)

    def unregister(self, name: str) -> None:
        self.con.unregister(name)

    def view(self, name: str, sql: str) -> None:  # `sql` readable by name until unregistered: nothing is computed until read
        self.con.register(name, self.con.sql(sql))

    def cursor(self) -> "DuckDB":  # the same database on a cursor of its own, for another thread
        return DuckDB(self.con.cursor())

    # Where a step's tables and files are, and what the engine is: asked of the engine, not written into a step's SQL,
    # so that SQL holds no part only DuckDB has (er.engine.bigquery translates the rest). Each answers on the connection
    # itself: what a step sends is only its SQL.

    def columns(self, x: str) -> list[tuple[str, str]]:  # a table's, a view's or a query's columns, in order: (name, DuckDB's type)
        return [(r[0], r[1]) for r in self.con.execute(f"DESCRIBE SELECT * FROM {x}").fetchall()]

    def exists(self, table: str) -> bool:  # whether this connection holds the table
        return bool(self.con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [table]).fetchall()[0][0])

    def read(self, files: str | Path | list, *, by_name: bool = False, filename: bool = False, row_numbers: bool = False) -> str:
        """Parquet files as a relation SQL reads: one file, a glob, or a list (`by_name`: their columns matched by name;
        `filename`: each row's file, in filename; `row_numbers`: its row in the file, in file_row_number)."""
        from er.config import lit  # here: er.config reads this module's functions
        given = f"[{', '.join(lit(f) for f in files)}]" if isinstance(files, list) else lit(files)
        options = "".join(f", {o} = true" for o, on in (("union_by_name", by_name), ("filename", filename), ("file_row_number", row_numbers)) if on)
        return f"read_parquet({given}{options})"

    def write(self, sql: str, dest: str | Path, compression: str | None = None) -> None:  # the rows of `sql` as a Parquet file
        from er.config import lit
        self.con.execute(f"COPY ({sql}) TO {lit(dest)} (FORMAT parquet{f', COMPRESSION {compression}' if compression else ''})")

    def threads(self) -> int:  # the threads a query runs on
        return int(self.con.execute("SELECT current_setting('threads')").fetchall()[0][0])

    def memory(self) -> str:  # the memory limit, as DuckDB says it
        return self.con.execute("SELECT current_setting('memory_limit')").fetchall()[0][0]

    def slices(self, table: str, size: int, n: int | None = None) -> list[str]:
        """Conditions that each hold one slice of `table`'s rows (`n` of them, counted when not given), `size` rows
        each, in the order they were made: a step holds one slice at a time; at least one, for none. DuckDB's rowid
        ranges: the table is made fresh, its rowids dense."""
        n = self.con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0] if n is None else n
        return [f"rowid >= {start} AND rowid < {start + size}" for start in range(0, max(n, 1), size)]

    def attach(self, alias: str, path: str | Path, read_only: bool = False, row_group_size: int | None = None) -> None:
        """A database file (an index's) whose tables SQL reads as alias.table, until detach(alias)."""
        from er.config import lit
        options = ", ".join(([] if not read_only else ["READ_ONLY"]) + ([] if row_group_size is None else [f"ROW_GROUP_SIZE {row_group_size}"]))
        self.con.execute(f"ATTACH {lit(path)} AS {alias}{f' ({options})' if options else ''}")

    def detach(self, alias: str) -> None:
        self.con.execute(f"DETACH {alias}")

    def room(self) -> float:
        """The bytes a step's tables may take: DuckDB's memory limit plus the room it may spill to (spill_room)."""
        return size_bytes(self.memory()) + self.spill_room()

    def spill_room(self) -> float:
        """The bytes DuckDB may spill: its temp directory's free space, capped as DuckDB caps it (max_temp_directory_size:
        by default 90% of that space)."""
        temp, cap = self.con.execute("SELECT current_setting('temp_directory'), current_setting('max_temp_directory_size')").fetchall()[0]
        free = shutil.disk_usage(temp if temp and os.path.isdir(temp) else ".").free
        return 0.9 * free if "%" in cap else min(free, size_bytes(cap))

    def close(self) -> None:
        self.con.close()


def udf(function: str, cut: bool = False) -> Callable[..., pa.Array]:  # vectorized, character-level, NULL-safe
    """cl_<function>(a, b), and cl_<function>_cut(a, b, threshold): the same score wherever it passes the threshold
    (a similarity at or above it, a distance at or below), and a value that fails it elsewhere, found without finishing
    the work (rapidfuzz's score_cutoff: an edit distance stops once it is past the threshold), so a condition on it
    passes and fails exactly the same pairs, in less time on long values."""
    info = FUNCTIONS[function]
    scorer = info.scorer
    # one thread per call: DuckDB already calls this on all its threads, and a pool per call costs more than it saves
    # (Damerau–Levenshtein on 1M records: rules 15 s → 4 s, its calls of ~20 values each starting a pool)

    def f(a: pa.Array, b: pa.Array, threshold: pa.Array | None) -> pa.Array:
        null = pc.or_(a.is_null(), b.is_null())
        x, y = pc.fill_null(a, "").to_pylist(), pc.fill_null(b, "").to_pylist()
        # a similarity's cut a hair below its threshold: the scores are float32, which round a value just under it up to it
        # kept in rapidfuzz's range: no similarity is past 0 to 1, no distance under 0, so a threshold outside passes or fails as before
        t = None if threshold is None or not len(threshold) else threshold[0].as_py()
        early = {} if t is None else {"score_cutoff": min(max(t - 1e-6, 0.0), 1.0) if info.similarity else max(int(t), 0)}
        scores = process.cpdist(x, y, scorer=scorer, **early)
        return pa.array(np.asarray(scores, dtype=float), mask=null.to_numpy(zero_copy_only=False))  # NULL never satisfies a condition
    return (lambda a, b, threshold: f(a, b, threshold)) if cut else (lambda a, b: f(a, b, None))  # DuckDB counts the parameters


COMPUTE = ("threads", "memory_limit", "temp_directory", "max_temp_directory_size")  # the limits [compute] and --compute may set



def connect(compute: dict | None = None) -> "DuckDB":
    """The DuckDB engine on a connection of its own, every cl_<function> registered. `compute` (config/settings.toml
    [compute]) sets threads, memory_limit, temp_directory and max_temp_directory_size: past the memory limit, DuckDB
    spills to that folder (none set: one of the person's own in the system's temporary folder, never the folder a job starts from). A limit
    no job sets, or one DuckDB refuses, is an InputError."""
    from er.config import InputError, lit  # here, not above: er.config reads this module's functions
    con = DuckDB(duckdb.connect())
    con.con.execute("SET enable_progress_bar = false")  # a long query's bar would land in stdout, between the JSON lines
    limits = {k: v for k, v in (compute or {}).items() if v not in ("", None)}
    if "temp_directory" not in limits:  # a folder of each person's, only theirs: spilled records stay private, and no one else's blocks it
        try:
            who = getpass.getuser()
        except (KeyError, OSError):  # a uid with no name, as in a container
            who = str(os.getuid()) if hasattr(os, "getuid") else "user"
        (spill := Path(tempfile.gettempdir()) / f"er-spill-{who}").mkdir(mode=0o700, exist_ok=True)
        if hasattr(os, "getuid") and ((st := spill.lstat()).st_uid != os.getuid() or st.st_mode & 0o077):  # made before, by someone else, open to them, or a link
            raise InputError(f"{spill}: the spill folder isn't yours alone, so spilled records could be read by others",
                             fix="give --compute temp_directory=<a folder of your own> (or [compute] temp_directory), or remove that folder")
        limits["temp_directory"] = str(spill)
    where = "--compute, or config/settings.toml [compute]"
    for key, value in limits.items():
        if key not in COMPUTE:
            raise InputError(f"{key}: not a limit a job sets ({where})", fix=f"one of {', '.join(COMPUTE)}, as KEY=VALUE")
        try:
            con.con.execute(f"SET {key} = {lit(value)}")
        except duckdb.Error as e:
            raise InputError(f"{key}={value} ({where}): {str(e).splitlines()[0]}", fix="e.g. memory_limit=8GB threads=4 temp_directory=/a/folder/with/room") from None
    for name, info in FUNCTIONS.items():
        if info.scorer:
            con.con.create_function(f"cl_{name}", udf(name), ["VARCHAR", "VARCHAR"], "DOUBLE", type="arrow")
            con.con.create_function(f"cl_{name}_cut", udf(name, cut=True), ["VARCHAR", "VARCHAR", "DOUBLE"], "DOUBLE", type="arrow")
    # self-check: character-level (the byte-level built-in gives 0.897 here) and NULL-safe
    assert con.con.execute("select round(cl_jaro_winkler('サトウヒロシ', 'サトウタカシ'), 3), "
                           "cl_levenshtein('サトウ', NULL) is null").fetchall() == [(0.844, True)]
    return con
