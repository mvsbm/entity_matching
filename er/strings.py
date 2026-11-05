"""Character-level string metrics, registered in DuckDB as cl_<name>.

DuckDB's built-in jaro_winkler_similarity, jaccard and damerau_levenshtein compare UTF-8 bytes. Katakana is 3 bytes
per character, which inflates similarity between unrelated names (サトウヒロシ / サトウタカシ: 0.897 instead of 0.844).
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import duckdb
import numpy as np
import pyarrow as pa
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

    def f(a: pa.Array, b: pa.Array) -> pa.Array:
        x, y = a.to_pylist(), b.to_pylist()
        null = np.array([p is None or q is None for p, q in zip(x, y)], dtype=bool)
        x, y = ["" if n else p for p, n in zip(x, null)], ["" if n else q for q, n in zip(y, null)]
        if scorer is char_jaccard:
            scores = np.array([char_jaccard(p, q) if p or q else 0.0 for p, q in zip(x, y)])
        else:
            scores = process.cpdist(x, y, scorer=scorer, workers=-1)
        return pa.array(np.asarray(scores, dtype=float), mask=null)  # NULL never satisfies a condition
    return f


def connect(compute: dict | None = None) -> tuple[duckdb.DuckDBPyConnection, DuckDBAPI]:
    """A DuckDB connection with every cl_<function> registered, wrapped for Splink. `compute` (config/settings.toml
    [compute]) sets threads, memory_limit and temp_directory: past the memory limit, DuckDB spills to that folder."""
    con = duckdb.connect()
    for key, value in (compute or {}).items():
        if value not in ("", None):
            con.execute(f"SET {key} = '{value}'")
    for name, info in FUNCTIONS.items():
        if info.scorer:
            con.create_function(f"cl_{name}", udf(name), ["VARCHAR", "VARCHAR"], "DOUBLE", type="arrow")
    # self-check: character-level (the byte-level built-in gives 0.897 here) and NULL-safe
    assert con.sql("select round(cl_jaro_winkler('サトウヒロシ', 'サトウタカシ'), 3), "
                   "cl_levenshtein('サトウ', NULL) is null").fetchall() == [(0.844, True)]
    return con, DuckDBAPI(connection=con)
