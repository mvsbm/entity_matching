"""Character-level string metrics, registered in DuckDB as cl_<name>.

DuckDB's built-in jaro_winkler_similarity, jaccard and damerau_levenshtein compare UTF-8 bytes. Katakana is 3 bytes
per character, which inflates similarity between unrelated names (サトウヒロシ / サトウタカシ: 0.897 instead of 0.844). So
er.config.Comparator asks DuckDB's own only of values one byte a character (ASCII, or the one-byte copy), and these
for the rest.
"""
import getpass
import os
import tempfile
import threading
import time
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

Function = Literal["exact", "jaro_winkler", "jaro", "jaccard", "levenshtein", "levenshtein_similarity", "damerau_levenshtein", "hamming"]


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
    "levenshtein_similarity": FunctionInfo(True, "m·n", lambda L: L * L, Levenshtein.normalized_similarity),  # 1 − edits / the longer length
    "damerau_levenshtein": FunctionInfo(False, "m·n", lambda L: L * L, DamerauLevenshtein.distance),
    "hamming": FunctionInfo(False, "n", lambda L: L, Hamming.distance),
}


SPENT: dict[str, list[float]] = {}  # per function and "all", in this process: its CPU seconds (each calling thread's own, not its wait for
# Python's lock), values, calls, and the wall seconds while any call ran; er.run.Run._done reads each step's; bounded: one entry per function
_spent = threading.Lock()  # DuckDB calls a function on several threads at once
_running: dict[str, list[float]] = {}  # per function and "all": calls running now, and since when one has; bounded: one entry per function


def spent() -> dict[str, tuple[float, ...]]:  # SPENT as it stands, read whole
    with _spent:
        return {k: tuple(v) for k, v in SPENT.items()}


def _enter(names: tuple[str, ...], now: float) -> None:
    with _spent:
        for k in names:
            r = _running.setdefault(k, [0, 0.0])
            if not r[0]:
                r[1] = now
            r[0] += 1


def _leave(names: tuple[str, ...], cpu: float, now: float, values: int) -> None:
    with _spent:
        for k in names:
            s, r = SPENT.setdefault(k, [0.0, 0, 0, 0.0]), _running[k]
            s[0] += cpu
            s[1] += values
            s[2] += 1
            r[0] -= 1
            if not r[0]:
                s[3] += now - r[1]


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
        _enter((function, "all"), time.perf_counter())
        start = time.thread_time()  # this thread's own: not its wait for Python's lock
        try:
            return run(a, b, threshold)
        finally:
            _leave((function, "all"), time.thread_time() - start, time.perf_counter(), len(a))

    def run(a: pa.Array, b: pa.Array, threshold: pa.Array | None) -> pa.Array:
        null = pc.or_(a.is_null(), b.is_null())
        x, y = pc.fill_null(a, "").to_pylist(), pc.fill_null(b, "").to_pylist()
        # a similarity's cut a hair below its threshold: the scores are float32, which round a value just under it up to it
        # kept in rapidfuzz's range: no similarity is past 0 to 1, no distance under 0, so a threshold outside passes or fails as before
        t = None if threshold is None or not len(threshold) else threshold[0].as_py()
        early = {} if t is None else {"score_cutoff": min(max(t - 1e-6, 0.0), 1.0) if info.similarity else max(int(t), 0)}
        if scorer is char_jaccard:
            scores = np.array([char_jaccard(p, q) if p or q else 0.0 for p, q in zip(x, y)])
        else:
            scores = process.cpdist(x, y, scorer=scorer, **early)
        return pa.array(np.asarray(scores, dtype=float), mask=null.to_numpy(zero_copy_only=False))  # NULL never satisfies a condition
    return (lambda a, b, threshold: f(a, b, threshold)) if cut else (lambda a, b: f(a, b, None))  # DuckDB counts the parameters


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
        try:
            who = getpass.getuser()
        except (KeyError, OSError):  # a uid with no name, as in a container
            who = str(os.getuid()) if hasattr(os, "getuid") else "user"
        (spill := Path(tempfile.gettempdir()) / f"nayose-spill-{who}").mkdir(mode=0o700, exist_ok=True)
        if hasattr(os, "getuid") and ((st := spill.lstat()).st_uid != os.getuid() or st.st_mode & 0o077):  # made before, by someone else, open to them, or a link
            raise InputError(f"{spill}: the spill folder isn't yours alone, so spilled records could be read by others",
                             fix="give --compute temp_directory=<a folder of your own> (or [compute] temp_directory), or remove that folder")
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
            con.create_function(f"cl_{name}_cut", udf(name, cut=True), ["VARCHAR", "VARCHAR", "DOUBLE"], "DOUBLE", type="arrow")
    # self-check: character-level (the byte-level built-in gives 0.897 here) and NULL-safe
    assert con.sql("select round(cl_jaro_winkler('サトウヒロシ', 'サトウタカシ'), 3), "
                   "cl_levenshtein('サトウ', NULL) is null").fetchall() == [(0.844, True)]
    return con, DuckDBAPI(connection=con)
