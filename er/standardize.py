"""Standardize: derived (fallback) columns and normalized copies of columns. O(N·L)."""
import re
from collections.abc import Iterable

import pandas as pd

from er.config import InputError, Normalizer, Standardization, column_name


SMALL_KANA = str.maketrans("ァィゥェォッャュョヮ", "アイウエオツヤユヨワ")  # banks write no small kana


def legal_pattern(std: Standardization) -> str:
    """A legal form anywhere (its reading, also with small kana written large), or a bank abbreviation where it may
    stand: first, カ)〇〇, or last, 〇〇(カ. Longest first, so 医療法人社団 isn't cut to 医療法人. On NFKC text."""
    forms = sorted({f for x in std.legal_forms for f in (x, x.translate(SMALL_KANA))}, key=len, reverse=True)
    parts = [re.escape(f) for f in forms]
    if std.legal_front:
        parts.append(f"^(?:{'|'.join(map(re.escape, sorted(std.legal_front, key=len, reverse=True)))})\\)")
    if std.legal_end:
        parts.append(f"\\((?:{'|'.join(map(re.escape, sorted(std.legal_end, key=len, reverse=True)))})$")
    return "|".join(parts)


def normalize(s: pd.Series, steps: tuple[Normalizer, ...], std: Standardization) -> pd.Series:
    for step in steps:
        match step:
            case "nfkc":
                s = s.str.normalize("NFKC")
            case "strip_spaces":  # pandas' Arrow strings use RE2, whose \s is ASCII only: the full-width space is named
                s = s.str.replace("[\\s\u3000]+", "", regex=True)
            case "initial":  # blocking keys: the first character
                s = s.str[:1]
            case "first3":  # blocking keys: a postal area
                s = s.str[:3]
            case "reverse":  # a second sort key: names that end alike sort together, so an early typo doesn't split them
                s = s.str[::-1]
            case "kana_fold":
                s = s.str.translate(str.maketrans(dict(std.kana_fold)))
            case "strip_legal_form":
                s = s.str.replace(legal_pattern(std), "", regex=True)
            case "address":
                s = s.str.normalize("NFKC")
                for pattern, repl in std.address_replacements:
                    s = s.str.replace(pattern, repl, regex=True)
                s = s.str.split(std.address_cut_at).str[0]
                s = s.str.replace(f"^(?:{'|'.join(map(re.escape, std.prefectures))})", "", regex=True)
    return s.replace("", pd.NA)  # a value normalized away (a legal form alone) is missing, not one huge block of equal values


def prepare(std: Standardization, records: pd.DataFrame, normalized: Iterable[tuple[str, tuple[Normalizer, ...]]],
            used: Iterable[str] = ()) -> pd.DataFrame:
    df = records.copy()
    read = {c for d in std.derived for cols in d.sources for c in cols}
    if read - set(records.columns):  # the trust boundary: say what is missing, instead of a KeyError deep inside
        raise ValueError(f"input lacks columns that config/settings.toml derives from: {sorted(read - set(records.columns))}")
    for c in read | (set(used) & set(records.columns)):  # a blank value is missing: it must not win a fallback or match
        df[c] = df[c].mask(df[c].str.fullmatch("[\\s\u3000]*").fillna(False))
    for d in std.derived:
        if d.name in records.columns:
            raise InputError(f"the file has a column named {d.name}, which is also the name of a field",
                             fix=f"rename the column, or map field {d.name} to it in config/settings.toml [columns]")
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
    # DuckDB names ignore case: a source column named like its field (BIRTH_DATE → birth_date) would shadow the field there
    return df.drop(columns=[c for c in records.columns for d in std.derived if c != d.name and c.casefold() == d.name.casefold()])
