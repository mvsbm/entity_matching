"""Character-level string metrics, registered in DuckDB as cl_<name>.

DuckDB's built-in jaro_winkler_similarity, jaccard and damerau_levenshtein compare UTF-8 bytes. Katakana is 3 bytes
per character, which inflates similarity between unrelated names (サトウヒロシ / サトウタカシ: 0.897 instead of 0.844).
"""
import getpass
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein, Hamming, Jaro, JaroWinkler, Levenshtein
from splink import DuckDBAPI

Function = Literal["exact", "jaro_winkler", "jaro", "jaccard", "levenshtein", "damerau_levenshtein", "hamming"]


def char_jaccard(a: str, b: str, **_: object) -> float:  # character-set Jaccard
    return len(set(a) & set(b)) / len(set(a) | set(b))


@dataclass(frozen=True)
class FunctionInfo:
    similarity: bool                          # True: passes at >= threshold; False (a distance): passes at <=
    big_o: str                                # per-pair cost; m, n = string lengths
    ops: Callable[[float], float]             # per-pair operation count at average length L
    scorer: Callable[..., float] | None       # character-level implementation; None for exact (a hash join)


FUNCTIONS: dict[str, FunctionInfo] = {
    "exact": FunctionInfo(True, "1", lambda L: 1, None),
    "jaro_winkler": FunctionInfo(True, "m·n", lambda L: L * L, JaroWinkler.similarity),
    "jaro": FunctionInfo(True, "m·n", lambda L: L * L, Jaro.similarity),
    "jaccard": FunctionInfo(True, "m+n", lambda L: 2 * L, char_jaccard),
    "levenshtein": FunctionInfo(False, "m·n", lambda L: L * L, Levenshtein.distance),
    "damerau_levenshtein": FunctionInfo(False, "m·n", lambda L: L * L, DamerauLevenshtein.distance),
    "hamming": FunctionInfo(False, "n", lambda L: L, Hamming.distance),
}


def udf(function: str) -> Callable[[pa.Array, pa.Array], pa.Array]:  # vectorized, character-level, NULL-safe
    scorer = FUNCTIONS[function].scorer
    # DuckDB already calls this on its threads, a vector of ~2,000 rows at a time: a thread pool per call costs more than
    # it saves, except for Damerau–Levenshtein on long values (a customer ID), where the work per pair dominates
    workers = -1 if function == "damerau_levenshtein" else 1

    def f(a: pa.Array, b: pa.Array) -> pa.Array:
        null = pc.or_(a.is_null(), b.is_null())
        x, y = pc.fill_null(a, "").to_pylist(), pc.fill_null(b, "").to_pylist()
        if scorer is char_jaccard:
            scores = np.array([char_jaccard(p, q) if p or q else 0.0 for p, q in zip(x, y)])
        else:
            scores = process.cpdist(x, y, scorer=scorer, workers=workers)
        return pa.array(np.asarray(scores, dtype=float), mask=null.to_numpy(zero_copy_only=False))  # NULL never satisfies a condition
    return f


COMPUTE = ("threads", "memory_limit", "temp_directory", "max_temp_directory_size")  # the limits [compute] and --compute may set


def connect(compute: dict | None = None) -> tuple[duckdb.DuckDBPyConnection, DuckDBAPI]:
    """A DuckDB connection with every cl_<function> registered, wrapped for Splink. `compute` (config/settings.toml
    [compute]) sets threads, memory_limit, temp_directory and max_temp_directory_size: past the memory limit, DuckDB
    spills to that folder (none set: one of the person's own in the system's temporary folder, never the folder nayose starts from). A limit
    nayose doesn't set, or one DuckDB refuses, is an InputError."""
    from er.config import InputError, lit  # here, not above: er.config reads this module's functions
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")  # a long query's bar would land in stdout, between the JSON lines
    limits = {k: v for k, v in (compute or {}).items() if v not in ("", None)}
    if "temp_directory" not in limits:  # a folder of each person's, only theirs: spilled records stay private, and no one else's blocks it
        (spill := Path(tempfile.gettempdir()) / f"nayose-spill-{getpass.getuser()}").mkdir(mode=0o700, exist_ok=True)
        limits["temp_directory"] = str(spill)
    where = "--compute, or config/settings.toml [compute]"
    for key, value in limits.items():
        if key not in COMPUTE:
            raise InputError(f"{key}: not a limit nayose sets ({where})", fix=f"one of {', '.join(COMPUTE)}, as KEY=VALUE")
        try:
            con.execute(f"SET {key} = {lit(value)}")
        except duckdb.Error as e:
            raise InputError(f"{key}={value} ({where}): {str(e).splitlines()[0]}", fix="e.g. memory_limit=8GB threads=4 temp_directory=/a/folder/with/room") from None
    for name, info in FUNCTIONS.items():
        if info.scorer:
            con.create_function(f"cl_{name}", udf(name), ["VARCHAR", "VARCHAR"], "DOUBLE", type="arrow")
    # self-check: character-level (the byte-level built-in gives 0.897 here) and NULL-safe
    assert con.sql("select round(cl_jaro_winkler('サトウヒロシ', 'サトウタカシ'), 3), "
                   "cl_levenshtein('サトウ', NULL) is null").fetchall() == [(0.844, True)]
    return con, DuckDBAPI(connection=con)
