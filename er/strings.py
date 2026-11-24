"""Character-level string metrics: what each comparison function is, and its character-level scorer.
An engine registers each as cl_<name> (er.engine.duckdb: Python UDFs over rapidfuzz).

DuckDB's built-in jaro_winkler_similarity and damerau_levenshtein compare UTF-8 bytes. Katakana is 3 bytes
per character, which inflates similarity between unrelated names (サトウヒロシ / サトウタカシ: 0.897 instead of 0.844). So
er.config.Comparator asks DuckDB's own only of values one byte a character (ASCII, or the one-byte copy), and these
for the rest.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from rapidfuzz.distance import DamerauLevenshtein, Hamming, Jaro, JaroWinkler, Levenshtein

Function = Literal["exact", "jaro_winkler", "jaro", "levenshtein", "damerau_levenshtein", "hamming"]


@dataclass(frozen=True)
class FunctionInfo:
    similarity: bool                          # True: passes at >= threshold; False (a distance): passes at <=
    scorer: Callable[..., float] | None       # character-level implementation; None for exact (a hash join)


FUNCTIONS: dict[str, FunctionInfo] = {
    "exact": FunctionInfo(True, None),
    "jaro_winkler": FunctionInfo(True, JaroWinkler.similarity),
    "jaro": FunctionInfo(True, Jaro.similarity),
    "levenshtein": FunctionInfo(False, Levenshtein.distance),
    "damerau_levenshtein": FunctionInfo(False, DamerauLevenshtein.distance),
    "hamming": FunctionInfo(False, Hamming.distance),
}
