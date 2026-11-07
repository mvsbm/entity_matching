"""The one door every input goes through: records, increment batches, and people's files (person/company answers,
decisions on pairs), all Parquet. It finds the files (a path, a glob or a folder), checks that each is Parquet, reads
several together by column name, and gives a column its configured name when the two differ only in case, width or
separators. Source.notes says what it did; when it must stop, it raises an InputError that says what to fix. It reads
each file's footer (its schema), never its rows, so its cost doesn't grow with the file. suggest() profiles a
fixed-size sample; describe() says what a file holds, for mapping its columns, in one scan and a sample. People's files are checked here too (answers, decisions), and every ID they give must name a record
(known): one rule for both.
"""
import difflib
import functools
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from er.candidates import q
from er.config import InputError

CONVERT = "records come as Parquet; convert it first, e.g. duckdb -c \"COPY (FROM 'in.csv') TO 'in.parquet'\""
NESTED = ("STRUCT", "MAP", "UNION", "[]")  # DuckDB types a field's column can't hold
NUMBER = re.compile(r"^(U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?|FLOAT|DOUBLE|DECIMAL|REAL)")


def lit(path: str | Path) -> str:  # a path as an SQL string literal
    return "'" + str(path).replace("'", "''") + "'"


def norm(name: str) -> str:  # a column name as people mean it: width, case and separators aside
    return re.sub(r"[\s_\-・.]+", "", unicodedata.normalize("NFKC", name).casefold())


@dataclass
class Source:
    sql: str                                  # the files as one relation: every column text, under its configured name
    columns: list[str]
    notes: list[str] = field(default_factory=list)  # what was detected or fixed, for the run's summary
    files: list[Path] = field(default_factory=list)  # the files read
    ordered: bool = False                     # a list of files in order: sql holds er_file, each row's file by position


def find(path: str | Path) -> list[Path]:
    """The files a path names: one file, a glob, or a folder (its Parquet files, at any depth)."""
    p = Path(path)
    if any(c in str(p) for c in "*?["):
        files = sorted(p.parent.glob(p.name)) if p.parent.exists() else []
    else:
        files = sorted(p.rglob("*.parquet")) if p.is_dir() else [p] if p.is_file() else []
    if files:
        return files
    folder = p.parent
    names = {f.stem: f.name for f in folder.iterdir()} if folder.is_dir() else {}  # stems: every name shares .parquet
    near = [names[s] for s in difflib.get_close_matches(p.stem, names, n=3)]
    raise InputError(f"no file matches {path}", fix=f"did you mean {' or '.join(str(folder / n) for n in near)}?" if near
                     else f"check the path: {folder} {'holds no file like it' if folder.is_dir() else 'does not exist'}")


def check_parquet(f: Path) -> None:
    """A Parquet file starts and ends with PAR1; say what the file looks like instead."""
    with f.open("rb") as h:
        head = h.read(4)
        h.seek(max(0, f.stat().st_size - 4))
        tail = h.read(4)
    if head == tail == b"PAR1":
        return
    if head == b"PAR1":
        raise InputError(f"{f}: a Parquet file cut short (it doesn't end as Parquet does)", fix="copy it again, or write it again from its source")
    kind = "a ZIP or Excel file" if head[:2] == b"PK" else "text, perhaps a CSV" if head and all(b >= 9 for b in head) else "not Parquet"
    raise InputError(f"{f}: not a Parquet file; it looks like {kind}", fix=CONVERT)


def open_source(path: str | Path | list[Path], con: duckdb.DuckDBPyConnection, expected: Iterable[str]) -> Source:
    """The files `path` names as one relation of text columns; a list of files is read in order, and each row keeps
    its file's position (er_file). A column whose name matches an `expected` one but for case, width or separators is
    given the expected name; one stored as a number is read as text, with a note."""
    ordered = isinstance(path, list)
    files = [x for p in path for x in find(p)] if ordered else find(path)
    for f in files:
        check_parquet(f)
    schemas = {}
    for f in files:
        try:
            schemas[f] = [(row[0], row[1]) for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet({lit(f)})").fetchall()]
        except duckdb.Error as e:
            raise InputError(f"{f}: can't be read as Parquet ({str(e).splitlines()[0]})", fix="copy it again, or write it again from its source") from None
    types: dict[str, str] = {}
    for cols in schemas.values():
        for name, kind in cols:
            types.setdefault(name, kind)
    notes = []
    if len(files) > 1:
        lacking = {f.name: sorted(set(types) - {n for n, _ in cols}) for f, cols in schemas.items()}
        notes.append(f"{len(files)} files read together by column name" +
                     "".join(f"; {name} lacks {', '.join(cols)}" for name, cols in lacking.items() if cols))
    expected = list(dict.fromkeys(expected))
    by_norm: dict[str, list[str]] = {}
    for c in types:
        by_norm.setdefault(norm(c), []).append(c)
    rename = {}
    for e in expected:
        found = by_norm.get(norm(e), [])
        if e in types or not found:
            continue
        if len(found) > 1:
            raise InputError(f"columns {', '.join(found)} could each be {e}", fix="rename all but one, or map the field to one of them in config/settings.toml [columns]")
        rename[found[0]] = e
        notes.append(f"column {found[0]} read as {e}")
    cols = []
    for c, kind in types.items():
        name = rename.get(c, c)
        if name in expected and any(x in kind for x in NESTED):
            raise InputError(f"column {c} holds {kind}, not one value per record", fix="flatten it upstream to one text value per record")
        if name in expected and NUMBER.match(kind):
            notes.append(f"column {c} is stored as a number ({kind}): read as text, but leading zeros (0599) may already be lost upstream")
        # a whole number stored as a float reads 599, not 599.0
        value = (f"CASE WHEN abs({q(c)}) < 9e18 AND {q(c)} = trunc({q(c)}) THEN CAST(CAST({q(c)} AS BIGINT) AS VARCHAR) ELSE CAST({q(c)} AS VARCHAR) END"
                 if kind in ("FLOAT", "DOUBLE", "REAL") else f"CAST({q(c)} AS VARCHAR)")
        cols.append(f"{value} AS {q(name)}")
    paths = ", ".join(lit(f) for f in files)
    if ordered:
        cols.append(f"list_position([{paths}], er_path) AS er_file")
    return Source(sql=f"(SELECT {', '.join(cols)} FROM read_parquet([{paths}], union_by_name = true{", filename = 'er_path'" if ordered else ''}))",
                  columns=[rename.get(c, c) for c in types], notes=notes, files=files, ordered=ordered)


FILLED = " \t\n\r\u3000"  # what a blank value is made of: blank is missing, as the run reads it (er.standardize.prepare)


def filled(c: str) -> str:  # SQL: the column holds a value; trimmed only when its first byte is blank (CASE: a sixth of the cost)
    starts = " OR ".join(f"prefix({q(c)}, '{ch}')" for ch in FILLED)
    return f"({q(c)} <> '' AND CASE WHEN {starts} THEN trim({q(c)}, '{FILLED}') <> '' ELSE true END)"


def fit(con: duckdb.DuckDBPyConnection, table: str, columns: list[str], fields: Iterable[str], patterns: Mapping[str, str]) -> dict[str, dict[str, float]]:
    """For each field and each column of `table`, how well the column's values fit the field: for `id`, the share of
    rows filled with a value no other row holds; for another field, the share of filled values its [locale.detect]
    pattern matches. A field with neither is left out. O(rows · columns · fields)."""
    asked = [f for f in fields if f == "id" or f in patterns]
    if not asked or not columns:
        return {}
    n = max(1, con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0])
    def share(f: str, c: str) -> str:
        if f == "id":
            return f"count(DISTINCT {q(c)}) FILTER (WHERE {filled(c)}) / {n}"
        p = patterns[f].replace("'", "''")
        return f"coalesce(avg(regexp_matches({q(c)}, '{p}')::INT) FILTER (WHERE {filled(c)}), 0)"
    got = con.execute(f"SELECT {', '.join(share(f, c) for f in asked for c in columns)} FROM {table}").fetchall()[0]
    return {f: dict(zip(columns, got[i * len(columns):(i + 1) * len(columns)])) for i, f in enumerate(asked)}


def suggest(src: Source, con: duckdb.DuckDBPyConnection, fields: Iterable[str], patterns: Mapping[str, str],
            rows: int = 10_000) -> dict[str, tuple[str, float, str]]:
    """For each field, the file's column whose values look most like it, its share and the evidence, from the first `rows`
    records (fit). A field nothing matches is left out. Suggestions only: a wrong guess applied silently would
    corrupt results. O(rows · columns)."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE er_sample AS SELECT * FROM {src.sql} LIMIT {rows}")
    out = {}
    for f, shares in fit(con, "er_sample", src.columns, fields, patterns).items():
        best = max(shares, key=shares.get)
        if shares[best] > 0:
            out[f] = (best, shares[best], f"{shares[best]:.0%} {'filled and unique' if f == 'id' else f'of filled values look like {f}'}")
    return out


def describe(path: str | Path, con: duckdb.DuckDBPyConnection, columns: Mapping[str, tuple[tuple[str, ...], ...]],
             patterns: Mapping[str, str], rows: int = 2_000, lex: "Lexicon | None" = None,
             slots: Mapping[str, tuple[tuple[str, ...], ...]] | None = None, slot_patterns: Mapping[str, str] | None = None) -> dict:
    """What a records file holds, for mapping its columns, without preparing a record. Its records; each column's share
    filled and an example; each field's sources (`columns`: its alternatives, each one column or several joined, as a
    run reads them: a later one where the earlier are empty, a joined one only where every part is filled), with each
    one's share filled, an example, and the share of its values that look like the field, and the same for the field
    as a whole; for each field and column, how well the column fits (`fit`: the order to offer them in); and for a
    field the file holds none of, the column whose name or values suggest it. Shares filled cover the file; examples
    and fits come from a sample of `rows` records. Suggestions only: a wrong guess applied silently would corrupt
    results. With `slots` (a workspace's features, by path, er.settings.slots), the same numbers for each, in the same
    scan, and their values matched against `slot_patterns`; with `lex`, each column's profile (profiled). O(N · (C +
    alternatives)) in one scan, plus O(rows · C · F)."""
    every = {**columns, **{f"slot:{k}": v for k, v in (slots or {}).items()}}  # a slot by its path, apart from the fields
    src = open_source(path, con, {c for alts in every.values() for alt in alts for c in alt})
    cols, fields = src.columns, {f: alts for f, alts in columns.items() if f != "entity"}
    here = {f: [alt for alt in alts if set(alt) <= set(cols)] for f, alts in {**fields, **{k: v for k, v in every.items() if k.startswith("slot:")}}.items()}
    value = lambda alt: (f"CASE WHEN {' AND '.join(filled(c) for c in alt)} THEN {' || '.join(q(c) for c in alt)} END"
                         if len(alt) > 1 else f"CASE WHEN {filled(alt[0])} THEN {q(alt[0])} END")
    whole = lambda alts: f"coalesce({', '.join(value(a) for a in alts)})"
    shown = {**{("column", c): value((c,)) for c in cols},
             **{("alt", f, i): value(a) for f, alts in here.items() for i, a in enumerate(alts)},
             **{("field", f): whole(alts) for f, alts in here.items() if alts}}
    keys = list(shown)
    b = {c: f"er_b{i}" for i, c in enumerate(cols)}  # each column's filled test once per row, every share counted from them
    held = lambda alt: " AND ".join(b[c] for c in alt)
    test = {k: b[k[1]] if k[0] == "column" else held(here[k[1]][k[2]]) if k[0] == "alt" else " OR ".join(f"({held(a)})" for a in here[k[1]])
            for k in keys}
    counts = con.execute(f"SELECT count(*), {', '.join(f'coalesce(count_if({test[k]}), 0)' for k in keys)} "  # none true: NULL, not 0
                         f"FROM (SELECT {', '.join(f'{filled(c)} AS {b[c]}' for c in cols)} FROM {src.sql})").fetchall()[0]
    n, share = counts[0], dict(zip(keys, (x / max(1, counts[0]) for x in counts[1:])))
    con.execute(f"CREATE OR REPLACE TEMP TABLE er_described AS SELECT * FROM {src.sql} USING SAMPLE reservoir({rows} ROWS) REPEATABLE (0)")
    pattern = {f: x.replace("'", "''") for f, x in {**patterns, **{f"slot:{k}": v for k, v in (slot_patterns or {}).items()}}.items() if f in here}
    looks = lambda f, v: f"coalesce(avg(regexp_matches({v}, '{pattern[f]}')::INT) FILTER (WHERE {v} IS NOT NULL), 0)" if f in pattern else "NULL"
    seen = con.execute(f"SELECT {', '.join(f'first({shown[k]}) FILTER (WHERE {shown[k]} IS NOT NULL), ' + (looks(k[1], shown[k]) if k[0] != 'column' else 'NULL') for k in keys)} "
                       f"FROM er_described").fetchall()[0]
    example, looks_right = dict(zip(keys, seen[0::2])), dict(zip(keys, seen[1::2]))
    fits = fit(con, "er_described", cols, fields, patterns)
    sample = con.execute(f"SELECT {', '.join(q(c) for c in cols)} FROM er_described").fetchall()
    profile = profiled({c: [r[i] for r in sample if r[i] is not None] for i, c in enumerate(cols)}, lex) if lex else {}
    norms, suggested = {norm(c): c for c in cols}, []
    unique = lambda c: con.execute(f"SELECT count(DISTINCT {q(c)}) = count(*) FROM {src.sql} WHERE {filled(c)}").fetchall()[0][0]
    for f in fields:
        if here[f]:
            continue
        if (c := norms.get(norm(f))) is not None:
            suggested.append(dict(field=f, column=c, why="its name"))
        elif f in fits and (c := max(fits[f], key=fits[f].get, default=None)) and fits[f][c] >= (0.99 if f == "id" else 0.5) and (f != "id" or unique(c)):
            suggested.append(dict(field=f, column=c, why=f"{fits[f][c]:.0%} " + ("filled, each value once" if f == "id" else f"look like {f.replace('_', ' ')}")))
    def entry(f: str, alts: tuple[tuple[str, ...], ...]) -> dict:  # a field's or a slot's numbers, and each of its alternatives'
        return dict(sources=[list(a) for a in alts], filled=share.get(("field", f)), example=example.get(("field", f)), looks_right=looks_right.get(("field", f)),
                    alternatives=[dict(columns=list(a), found=set(a) <= set(cols),
                                       **({k: v for k, v in zip(("filled", "example", "looks_right"), (share[key], example[key], looks_right[key]))}
                                          if (key := ("alt", f, here[f].index(a)) if a in here[f] else None) else
                                          dict(filled=None, example=None, looks_right=None))) for a in alts])
    return dict(
        records=n,
        columns=[dict(column=c, filled=share[("column", c)], example=example[("column", c)]) for c in cols],
        fields=[dict(field=f, **entry(f, alts)) for f, alts in fields.items()],
        slots=[dict(feature=k, **entry(f"slot:{k}", alts)) for k, alts in (slots or {}).items()],
        fit=fits, suggested=suggested, profile=profile, notes=src.notes)


@dataclass(frozen=True)
class Lexicon:
    """What names and places look like, from data/reference/ (individual.json, addresses.json): family and given names
    and prefectures and cities, each in kanji and in kana, kana folded as the run folds it."""
    family: frozenset[str]
    given: frozenset[str]
    places: frozenset[str]
    fold: dict[int, str]


@functools.lru_cache(maxsize=1)  # bounded: the one reference folder a process reads
def lexicon(folder: Path, kana_fold: tuple[tuple[str, str], ...]) -> Lexicon:
    """The reference lists as sets, read once per process. O(reference rows)."""
    fold = str.maketrans(dict(kana_fold))
    people = json.loads((folder / "individual.json").read_text(encoding="utf-8"))
    places = json.loads((folder / "addresses.json").read_text(encoding="utf-8"))
    keep = lambda values: frozenset(v for x in values if x and (v := plain(x, fold)))
    return Lexicon(family=keep(x for r in people for x in (r["surname"], r["surname_kana"])),
                   given=keep(x for r in people for x in (r["given"], r["given_kana"])),
                   places=keep(x for r in places for x in (r["pref"], r["pref_kana"], r["city"], r["city_kana"])), fold=fold)


def plain(value: str, fold: dict[int, str]) -> str:  # a value as names are looked up: same width, no spaces, katakana, kana folded
    v = re.sub(r"[\s\u3000・]+", "", unicodedata.normalize("NFKC", value))
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in v).translate(fold)


SCRIPTS = {"kanji": re.compile(r"[\u4e00-\u9fff々]"), "kana": re.compile(r"[\u30a0-\u30ff\u3040-\u309f]"), "romaji": re.compile(r"[A-Za-z]")}


def profiled(values: Mapping[str, list[str]], lex: Lexicon) -> dict[str, dict]:
    """For each column, from its sampled filled values: its script (kanji, kana, romaji, or none: the letters most of its
    values are written in), and the share of values that are a known family name, a known given name, a known family name
    followed by a known given name (a full name), and that start with a known prefecture or city and go on (an address).
    O(values · length)."""
    out = {}
    for c, vs in values.items():
        vs = [plain(v, lex.fold) for v in vs if v and v.strip()]
        n = max(1, len(vs))
        written = {k: sum(bool(rx.search(v)) for v in vs) / n for k, rx in SCRIPTS.items()}
        script = max(written, key=written.get) if vs and max(written.values()) >= 0.5 else None
        full = lambda v: any(v[:i] in lex.family and v[i:] in lex.given for i in range(1, len(v)))
        address = lambda v: any(v[:i] in lex.places for i in range(2, min(len(v) - 1, 12) + 1))  # a place, then more
        out[c] = dict(script=script, family=sum(v in lex.family for v in vs) / n, given=sum(v in lex.given for v in vs) / n,
                      full=sum(full(v) for v in vs) / n, address=sum(address(v) for v in vs) / n)
    return out


def sha256(f: Path) -> str:
    with open(f, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def file_facts(files: list[Path], role: str) -> list[dict]:
    """Each file read: its path, what it is (records, decisions, answers, the name model), size and SHA-256, so a run
    says exactly what went in, and a rerun finds its records again. O(bytes)."""
    return [dict(file=str(Path(f).resolve()), role=role, bytes=Path(f).stat().st_size, sha256=sha256(Path(f))) for f in files]


def answers(path: str | Path, con: duckdb.DuckDBPyConnection, uid: str) -> pd.DataFrame:
    """A sheet of person/company answers (kind_review.parquet, filled in): its answered rows (kind 1 person, 2 company,
    0 can't tell), every column as text, as every input is read. Refuses a file without the ID and kind columns, a kind
    that is none of those, a sheet with no answer, and an answered row without an ID. O(rows)."""
    src = open_source(path, con, [uid, "kind"])
    if {uid, "kind"} - set(src.columns):
        raise InputError(f"{path}: needs the columns {uid} and kind; it has {sorted(src.columns)}",
                         fix="give back kind_review.parquet with kind filled in: 1 person, 2 company, 0 can't tell")
    rows = con.sql(f"SELECT * FROM {src.sql}").df().astype("string")
    given, kind = rows["kind"].str.strip().replace("", pd.NA), pd.to_numeric(rows["kind"], errors="coerce")
    if len(bad := sorted(set(given[given.notna() & ~kind.isin([0, 1, 2])]))):
        raise InputError(f"{path}: a kind is 1, 2 or 0, not {bad[:5]}", fix="write 1 person, 2 company or 0 can't tell, or leave it empty")
    rows = rows[kind.isin([0, 1, 2]).to_numpy()].reset_index(drop=True)
    if rows.empty:
        raise InputError(f"{path}: no row is answered", fix="answer records first (nayose answer kind ID company), or write 1 person, 2 company or 0 can't tell in the sheet's kind column")
    if (blank := int(rows[uid].str.strip().fillna("").eq("").sum())):
        raise InputError(f"{path}: {blank:,} answered rows have no {uid}", fix="fill in each answered row's ID, or clear its answer")
    return rows


def decisions(path: str | Path, con: duckdb.DuckDBPyConnection, l: str, r: str, into: str) -> list[Path]:
    """People's decisions on pairs (review.parquet with decision filled in, or any file with the two IDs and decision)
    as the table `into`, and the files read: each pair once, the lower ID first, decision match or no_match; rows
    without a decision skipped. Refuses a file without those columns, a decided row without both IDs, a file with no
    decision, another decision, and a pair decided both ways. O(rows)."""
    src = open_source(path, con, [l, r, "decision"])
    if {l, r, "decision"} - set(src.columns):  # say what is wrong, row by row where it can
        raise InputError(f"{path}: needs the columns {l}, {r} and decision; it has {sorted(src.columns)}",
                         fix="give back review.parquet with decision filled in, or a file with those three columns")
    decided = f"FROM {src.sql} WHERE nullif(trim(decision), '') IS NOT NULL"
    if (blank := con.execute(f"SELECT count(*) {decided} AND (nullif(trim({q(l)}), '') IS NULL OR nullif(trim({q(r)}), '') IS NULL)").fetchall()[0][0]):
        raise InputError(f"{path}: {blank:,} decided rows lack an ID", fix="fill in both IDs of each decided row, or clear its decision")
    con.execute(f"""CREATE OR REPLACE TABLE {q(into)} AS SELECT DISTINCT least({q(l)}, {q(r)}) AS {q(l)}, greatest({q(l)}, {q(r)}) AS {q(r)},
        lower(trim(decision)) AS decision {decided}""")
    if not con.execute(f"SELECT count(*) FROM {q(into)}").fetchall()[0][0]:
        raise InputError(f"{path}: no row has a decision", fix="decide pairs first (nayose decide pair ID ID match), or write match or no_match in the sheet's decision column")
    if (bad := con.execute(f"SELECT DISTINCT decision FROM {q(into)} WHERE decision NOT IN ('match', 'no_match')").fetchall()):
        raise InputError(f"{path}: a decision is match or no_match, not {sorted(x for x, in bad)}", fix="correct those rows, or leave them empty")
    if (both := con.execute(f"SELECT {q(l)}, {q(r)} FROM {q(into)} GROUP BY ALL HAVING count(*) > 1 LIMIT 5").fetchall()):
        raise InputError(f"{path}: pairs decided both ways: {both}", fix="keep one decision per pair")
    return src.files


def known(con: duckdb.DuckDBPyConnection, ids: str, records: str, uid: str, path: str | Path, where: str) -> None:
    """Every ID people gave (`ids`: SQL with one column, id) names a record of `records`; the first five that don't are
    refused. A spreadsheet reads 0000000151 as the number 151: such a file would stand for no record. O(IDs + N)."""
    unknown = [x for x, in con.execute(f"SELECT id FROM ({ids}) WHERE id NOT IN (SELECT {q(uid)} FROM {records}) ORDER BY 1 LIMIT 5").fetchall()]
    if unknown:
        raise InputError(f"{path}: IDs that name no record of {where}: {unknown}",
                         fix="check the IDs as the run wrote them: a spreadsheet may read 0000000151 as the number 151")
