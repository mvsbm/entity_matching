"""Standardize: derived (fallback) columns and normalized copies of columns. O(N·L)."""
import re
from collections.abc import Iterable

import pandas as pd

from er.config import Normalizer, Standardization, column_name


def normalize(s: pd.Series, steps: tuple[Normalizer, ...], std: Standardization) -> pd.Series:
    for step in steps:
        match step:
            case "nfkc":
                s = s.str.normalize("NFKC")
            case "strip_spaces":
                s = s.str.replace(r"\s+", "", regex=True)
            case "kana_fold":
                s = s.str.translate(str.maketrans(dict(std.kana_fold)))
            case "strip_legal_form":
                s = s.str.replace("|".join(map(re.escape, std.legal_forms)), "", regex=True)
            case "address":
                s = s.str.normalize("NFKC")
                for pattern, repl in std.address_replacements:
                    s = s.str.replace(pattern, repl, regex=True)
                s = s.str.split(std.address_cut_at).str[0]
                s = s.str.replace(f"^(?:{'|'.join(map(re.escape, std.prefectures))})", "", regex=True)
    return s


def prepare(std: Standardization, records: pd.DataFrame, normalized: Iterable[tuple[str, tuple[Normalizer, ...]]],
            used: Iterable[str] = ()) -> pd.DataFrame:
    df = records.copy()
    for d in std.derived:
        assert d.name not in records.columns, f"derived column {d.name} shadows an input column"
        out = pd.Series(pd.NA, index=df.index, dtype="string")
        for cols in d.sources:
            joined = df[cols[0]]
            for c in cols[1:]:
                joined = joined + df[c]  # NA if any part is missing
            out = out.fillna(joined)
        df[d.name] = normalize(out, d.normalize, std)
    for col, steps in normalized:
        if column_name(col, steps) not in df:
            df[column_name(col, steps)] = normalize(df[col], steps, std)
    missing = set(used) - set(df.columns)
    assert not missing, f"unknown columns: {sorted(missing)}"
    return df
