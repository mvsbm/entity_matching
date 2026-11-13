"""Standardize: derived (fallback) columns, each record's kind and the name fields routed by it (er.kind), and the
normalized copies of columns. O(N·L)."""
import re
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from er.config import InputError, Normalizer, Standardization, column_name, legal_pattern

if TYPE_CHECKING:
    from er.kind import Classifier


KATAKANA = str.maketrans({chr(c): chr(c + 0x60) for c in range(0x3041, 0x3097)})  # hiragana as katakana
SEPARATORS = "[\\s\u3000\\-\u2010-\u2015\u2212\u30fc/.()〒]"  # spaces, hyphens and dashes, the long-vowel mark typed for one, / . ( ), 〒
ONE_BYTE = str.maketrans({chr(0x30A0 + i): chr(1 + i) for i in range(96)})  # the katakana block, each character one byte: 0x01–0x60


def _hashed(s: pd.Series) -> pd.Series:  # each value's characters each one ASCII byte, 33 + its code point mod 94: one pass over the column's text
    filled = s.notna().to_numpy()
    values = s[filled].tolist()
    ends = np.cumsum([len(v) for v in values], dtype=np.int64)
    text = (33 + np.frombuffer("".join(values).encode("utf-32-le"), dtype=np.uint32) % 94).astype(np.uint8).tobytes().decode("ascii")
    out = np.full(len(s), None, dtype=object)
    out[filled] = [text[a:b] for a, b in zip(np.concatenate(([0], ends[:-1])), ends)]
    return pd.Series(out, index=s.index, dtype="string")


def normalize(s: pd.Series, steps: tuple[Normalizer, ...], std: Standardization) -> pd.Series:
    """Each step on each value, as `steps` lists them: every step reads one value alone, so each distinct value is
    normalized once and the column made of them. O(N) to factorize, plus O(distinct values · steps · L)."""
    codes, uniques = pd.factorize(s)  # a missing value: code -1
    if len(uniques) > 0.8 * len(s):  # few repeats: mapping back would cost what it saves
        return _normalized(s, steps, std)
    done = _normalized(pd.Series(uniques, dtype=s.dtype), steps, std)
    return pd.Series(done.array.take(codes, allow_fill=True), index=s.index)  # -1: missing


def _normalized(s: pd.Series, steps: tuple[Normalizer, ...], std: Standardization) -> pd.Series:
    for step in steps:
        match step:
            case "nfkc":
                s = s.str.normalize("NFKC")
            case "strip_spaces":  # pandas' Arrow strings use RE2, whose \s is ASCII only: the full-width space is named
                s = s.str.replace("[\\s\u3000]+", "", regex=True)
            case "katakana":  # a name typed in hiragana: the kana the records hold
                s = s.str.translate(KATAKANA)
            case "strip_separators":  # what people write between digits (03-1234-5678, 1993/05/25): one value; letters stay
                s = s.str.replace(SEPARATORS, "", regex=True)
            case "initial":  # blocking keys: the first character
                s = s.str[:1]
            case "first3":  # blocking keys: a postal area
                s = s.str[:3]
            case "reverse":  # a second sort key: names that end alike sort together, so an early typo doesn't split them
                s = s.str[::-1]
            case "one_byte":  # all katakana: each one byte, so DuckDB's similarity (bytes) compares it as characters; else none
                s = s.where(s.str.fullmatch("[\u30a0-\u30ff]+").fillna(False)).str.translate(ONE_BYTE)
            case "one_byte_hash":  # not all ASCII: each character one byte by its code point (two may share one), so DuckDB's edit distance of it is never more than theirs; else none
                s = _hashed(s.where(~s.str.isascii().fillna(True)))
            case "casefold":  # romaji: TANAKA and tanaka are one name
                s = s.str.casefold()
            case "long_vowel":  # keys, after kana_fold: a long vowel written either way (サトウ, サトオ, サトー) is one reading
                s = s.str.replace("([オコソトノホモヨロ])[ウオ]", "\\1ウ", regex=True).str.replace("([エケセテネヘメレ])[イエ]", "\\1イ", regex=True)
            case "last3":  # keys: a name's last three characters, its given name's, kept through a change of family name
                s = s.str[-3:]
            case "kana_fold":
                s = s.str.translate(str.maketrans(dict(std.kana_fold)))
            case "strip_legal_form":
                s = s.str.replace(legal_pattern(std), "", regex=True)
            case "address":
                for _, part in address_parts(std):
                    s = part(s)
    return s.replace("", pd.NA)  # a value normalized away (a legal form alone) is missing, not one huge block of equal values


def address_parts(std: Standardization) -> tuple[tuple[str, Callable[[pd.Series], pd.Series]], ...]:
    """The address normalizer's parts, in order: normalize() applies them all, prepared() shows each."""
    def rules(s: pd.Series) -> pd.Series:
        for pattern, repl in std.address_replacements:
            s = s.str.replace(pattern, repl, regex=True)
        return s
    return (("address:nfkc", lambda s: s.str.normalize("NFKC")), ("address:rules", rules),
            ("address:cut", lambda s: cut(s, std.address_cut_at)),
            ("address:prefecture", lambda s: s.str.replace(f"^(?:{'|'.join(map(re.escape, std.prefectures))})", "", regex=True)))


def cut(s: pd.Series, at: str) -> pd.Series:
    """An address up to its street number: the building and room after the first `at` that follows a digit go, then
    any `at` left (between the city and the town, say); an address with no digit before one keeps all but those."""
    c = re.escape(at)
    return s.str.strip().str.replace(rf"^(.*?[0-9][^{c}]*){c}.*$", r"\1", regex=True).str.replace(at, "", regex=False)


def prepared(value: str, steps: tuple[Normalizer, ...], std: Standardization) -> list[tuple[str, str | None]]:
    """One value through each normalizer, the address one part by part: (step, the value after it). The last is what
    normalize() gives; the steps between are for people to see what preparing a value did. O(steps·L)."""
    s, out = pd.Series([value]), []
    for step in steps:
        for name, part in address_parts(std) if step == "address" else ((step, lambda x, one=(step,): normalize(x, one, std)),):
            s = part(s)
            out.append((name, None if pd.isna(s.iloc[0]) or s.iloc[0] == "" else str(s.iloc[0])))
    return out


def prepare(std: Standardization, records: pd.DataFrame, normalized: Iterable[tuple[str, tuple[Normalizer, ...]]],
            used: Iterable[str] = (), kind: "Classifier | None" = None) -> pd.DataFrame:
    """Each field built from its sources, then each record's kind (with `kind`, an er.kind.Classifier: kind_p and kind,
    and a field routed by kind kept only where the record leans its way), then the normalized copies. O(N·L)."""
    df, used, raw = records.copy(), set(used), None
    # a field nothing reads and the file holds none of is absent, as a run treats it (er.settings.fit_to_file)
    derived = [d for d in std.derived if d.name in used or any(c in records.columns for cols in d.sources for c in cols)]
    read = {c for d in derived for cols in d.sources for c in cols}
    if read - set(records.columns):  # the trust boundary: say what is missing, instead of a KeyError deep inside
        raise ValueError(f"input lacks columns that config/settings.toml derives from: {sorted(read - set(records.columns))}")
    for c in read | (used & set(records.columns)):  # a blank value is missing: it must not win a fallback or match
        df[c] = df[c].mask(df[c].str.fullmatch("[\\s\u3000]*").fillna(False))
    for d in derived:
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
        if kind is not None and d.name == kind.spec.name_field:
            raw = out  # the name as written: its legal form still in it
    if kind is not None and raw is not None:
        k = kind.classify(raw, df.get("kind_flag"), df.get("birth_date"), ids=df.get(kind.uid))
        for c in ("kind", "kind_p", "kind_by", "name_p", "kind_flagged", "kind_held", "kind_name"):
            df[c] = k[c].to_numpy()
        kind_, lean = k["kind"].to_numpy(), np.where(k["kind_p"].to_numpy() >= 0.5, "company", "person")
        side = np.where(kind_ == 2, "company", np.where(kind_ == 1, "person", lean))  # its kind; not sure, where it leans
        for d in derived:
            if d.kind:  # a record people can't tell goes to neither side
                df[d.name] = df[d.name].where((side == d.kind) & ~k["kind_held"].to_numpy())
        # one name in a person field and the company field alike (a column holding every record's name, mapped to both):
        # one piece of evidence, kept on its kind's side only, not compared twice
        if "company_name" in df:  # compared folded, as the names are: a converted copy may write small or voiced kana otherwise
            fold = lambda c: normalize(df[c], ("kana_fold",), std)
            company, same = fold("company_name"), {f: None for f in ("full_name", "person_name") if f in df}
            for f in same:
                same[f] = (fold(f) == company).fillna(False).to_numpy()
                df[f] = df[f].mask(same[f] & (side == "company"))
            if same:
                df["company_name"] = df["company_name"].mask(np.logical_or.reduce(list(same.values())) & (side == "person"))
    for col, steps in normalized:
        if column_name(col, steps) not in df:  # a one-byte copy from the column it copies, if made: not the chain again
            done = steps[-1] in ("one_byte", "one_byte_hash") and column_name(col, steps[:-1]) in df
            df[column_name(col, steps)] = normalize(df[column_name(col, steps[:-1])], steps[-1:], std) if done else normalize(df[col], steps, std)
    missing = set(used) - set(df.columns)
    if missing:
        raise ValueError(f"input lacks columns the configuration uses: {sorted(missing)}")
    # DuckDB names ignore case: a source column named like a column made here (BIRTH_DATE → birth_date, KIND → kind) would shadow it there
    made = {x.casefold() for x in df.columns if x not in records.columns}
    return df.drop(columns=[c for c in records.columns if c.casefold() in made])
