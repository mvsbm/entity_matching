"""Character-level string metrics: what each comparison function is, its cost, and its character-level scorer.
An engine registers each as cl_<name> (er.engine.duckdb: Python UDFs over rapidfuzz).

DuckDB's built-in jaro_winkler_similarity, jaccard and damerau_levenshtein compare UTF-8 bytes. Katakana is 3 bytes
per character, which inflates similarity between unrelated names (サトウヒロシ / サトウタカシ: 0.897 instead of 0.844). So
er.config.Comparator asks DuckDB's own only of values one byte a character (ASCII, or the one-byte copy), and these
for the rest.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from rapidfuzz.distance import DamerauLevenshtein, Hamming, Jaro, JaroWinkler, Levenshtein

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
