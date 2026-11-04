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
            case "initial":  # blocking keys: the first character (an empty value must not become one huge block)
                s = s.str[:1].replace("", pd.NA)
            case "first3":  # blocking keys: a postal area
                s = s.str[:3].replace("", pd.NA)
            case "reverse":  # a second sort key: names that end alike sort together, so an early typo doesn't split them
                s = s.str[::-1]
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
    sources = {c for d in std.derived for cols in d.sources for c in cols} - set(records.columns)
    if sources:  # the trust boundary: say what is missing, instead of a KeyError deep inside
        raise ValueError(f"input lacks columns that config/settings.toml derives from: {sorted(sources)}")
    for d in std.derived:
        if d.name in records.columns:
            raise ValueError(f"derived column {d.name} shadows an input column")
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
    if missing:
        raise ValueError(f"input lacks columns the configuration uses: {sorted(missing)}")
    return df
