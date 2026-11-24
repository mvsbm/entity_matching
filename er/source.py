"""The one door every input goes through: records, increment batches, and people's decisions on pairs, all Parquet. It finds the files (a path, a glob or a folder), checks that each is Parquet, reads
several together by column name, and gives a column its configured name when the two differ only in case, width or
separators. Source.notes says what it did; when it must stop, it raises an InputError that says what to fix. It reads
each file's footer (its schema), never its rows, so its cost doesn't grow with the file. suggest() profiles a
fixed-size sample. People's decisions are checked here too, and every ID they give must name a record
(known).
"""
import contextlib
import difflib
import functools
import re
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from er.engine.engine import Engine
from er import intake
from er.config import InputError, lit, q, unpivoted
from er.settings import norm_name

NESTED = ("STRUCT", "MAP", "UNION", "[]")  # DuckDB types a field's column can't hold
NUMBER = re.compile(r"^(U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?|FLOAT|DOUBLE|DECIMAL|REAL)")


@dataclass
class Source:
    sql: str                                  # the files as one relation: every column text, under its configured name
    columns: list[str]
    notes: list[str] = field(default_factory=list)  # what was detected or fixed, for the run's summary
    files: list[Path] = field(default_factory=list)  # the files read
    given: dict[str, str] = field(default_factory=dict)  # a column read under another name (KIND_2) → its name in the file


def globbed(p: Path) -> bool:  # a pattern of names (*.parquet, part-?.parquet); a file or folder that exists is itself, [ in its name or not
    return not p.exists() and any(c in p.name for c in "*?[")


def find(path: str | Path) -> list[Path]:
    """The files a path names: one file, a glob, or a folder (its Parquet files, at any depth: intake.SUFFIXES); a
    workspace's part, the files its intake read (er.intake). ~ is the home folder."""
    p = Path(path).expanduser()
    if p.is_dir() and (r := intake.report(p)):
        return [p / x["read"] for x in r["files"]]
    if p.is_file() and p.suffix.lower() not in intake.SUFFIXES:  # a CSV, a picture, a document refused, saying how to write it as Parquet
        intake.check(p)
        return [p]  # Parquet saved without its ending: read as it is
    if globbed(p):  # its files, as a folder's: no folder, no hidden file, a records file's ending
        files = sorted(f for f in p.parent.glob(p.name) if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in intake.SUFFIXES) if p.parent.exists() else []
    else:
        files = sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in intake.SUFFIXES  # a hidden file or folder (.DS_Store, __MACOSX) holds no records
                       and not any(x.startswith(".") or x == "__MACOSX" for x in f.relative_to(p).parts)) if p.is_dir() else [p] if p.is_file() else []
    if files:
        return files
    if p.is_dir():
        raise InputError(f"{path} holds no Parquet file", fix=f"name a Parquet file, or a folder that holds some; a CSV: {intake.CONVERT}")
    folder = p.parent
    names = {f.stem: f.name for f in folder.iterdir() if f != p} if folder.is_dir() else {}  # by stem: a close name, whatever its suffix
    near = [names[s] for s in difflib.get_close_matches(p.stem, names, n=3)]
    raise InputError(f"no file matches {path}", fix=f"did you mean {' or '.join(str(folder / n) for n in near)}?" if near
                     else f"check the path: {folder} {'holds no file like it' if folder.is_dir() else 'does not exist'}")


@contextlib.contextmanager
def readable(path: str | Path, spec: "intake.InputSpec", told=None):
    """The records `path` names (a Parquet file, a quoted glob or a folder of them) as a job reads them: read by the
    intake (er.intake: placeholders and blanks as missing, a number's text as written, control characters out) into a
    folder of the job's own, which goes once it ends. An error names the files given, not that folder. O(bytes)."""
    p = Path(path).expanduser()
    files, root = find(path), p if p.is_dir() else None
    progress = (lambda done, total: told(done, total, "rows")) if told else None
    with tempfile.TemporaryDirectory(prefix="er-", ignore_cleanup_errors=True) as t:  # Windows: a file DuckDB still holds can't go yet
        named = {f: (f.relative_to(root) if root else Path(f.name)).as_posix() for f in files}
        back = [*((str(Path(t) / x["read"]), str(f)) for f, x in zip(named, intake.take(Path(t), named, spec, progress=progress)["files"])), (t, str(path))]
        try:
            yield t
        except InputError as e:  # said of the files people gave, not of the folder they were read into
            say = lambda text: functools.reduce(lambda x, pair: x.replace(*pair), back, text)
            raise InputError(say(str(e)), say(e.fix), e.hints) from None


def open_source(path: str | Path, engine: Engine, expected: Iterable[str], reserved: Iterable[str] = ()) -> Source:
    """The files `path` names as one relation of text columns. A column whose name matches an `expected` one but for case, width or separators is
    given the expected name; one stored as a number is read as text, with a note. One no field reads whose name, in
    any case, is a `reserved` one (a column the run writes itself: a field, kind) or begins with one and __, is read
    under another (KIND_2), with a note: SQL names don't tell case apart."""
    files = find(path)
    for f in files:
        intake.check(f)
    schemas = {}
    for f in files:
        try:
            schemas[f] = engine.columns(engine.read(f))
        except duckdb.Error as e:
            raise InputError(f"{f}: can't be read as Parquet ({str(e).splitlines()[0]})", fix="copy it again, or write it again from its source") from None
    types: dict[str, str] = {}
    for cols in schemas.values():
        for name, kind in cols:
            types.setdefault(name, kind)
    notes = intake.notes(files)
    if len(files) > 1:
        lacking = {f.name: sorted(set(types) - {n for n, _ in cols}) for f, cols in schemas.items()}
        notes.append(f"{len(files)} files read together by column name" +
                     "".join(f"; {name} lacks {', '.join(cols)}" for name, cols in lacking.items() if cols))
    expected = list(dict.fromkeys(expected))
    by_norm: dict[str, list[str]] = {}
    for c in types:
        by_norm.setdefault(norm_name(c), []).append(c)
    rename = {}
    for e in expected:
        found = by_norm.get(norm_name(e), [])
        if e in types or not found:
            continue
        found += [c for c in types if c not in found and re.fullmatch(re.escape(e) + r"_\d+", c, re.I)]  # e itself, renamed by intake past a case-only twin
        if len(found) > 1:
            raise InputError(f"columns {', '.join(found)} could each be {e}", fix="rename all but one, or map the field to one of them in config/settings.toml [columns]")
        rename[found[0]] = e
        notes.append(f"column {found[0]} read as {e}")
    taken, own = {rename.get(c, c).casefold() for c in types}, {x.casefold() for x in reserved}
    for c in types:
        if c in rename or c in expected or not (c.casefold() in own or c.casefold().split("__")[0] in own and "__" in c):
            continue
        k = 2
        while f"{c}_{k}".casefold() in taken | own:
            k += 1
        rename[c] = f"{c}_{k}"
        taken.add(rename[c].casefold())
        notes.append(f"column {c} read as {rename[c]}: the run writes a {c.casefold()} of its own")
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
    return Source(sql=f"(SELECT {', '.join(cols)} FROM {engine.read(files, by_name=True)})",
                  columns=[rename.get(c, c) for c in types], notes=notes, files=files,
                  given={rename[c]: c for c in rename if rename[c] not in expected})


FILLED = "".join(ch for ch in map(chr, range(0x3001)) if ch.isspace())  # what a blank value is made of, as Python's \s: blank is missing, as the run reads it (er.standardize.prepare)


def filled(c: str) -> str:  # SQL: the column holds a value, never NULL itself; trimmed only when its first character is blank (CASE: a sixth of the cost)
    return (f"coalesce({q(c)} <> '' AND CASE WHEN unicode({q(c)}) IN ({', '.join(str(ord(ch)) for ch in FILLED)}) THEN trim({q(c)}, {lit(FILLED)}) <> '' "
            f"ELSE true END, false)")


def fit(engine: Engine, table: str, columns: list[str], fields: Iterable[str], patterns: Mapping[str, str]) -> dict[str, dict[str, float]]:
    """For each field and each column of `table`, how well the column's values fit the field: for `id`, the share of
    rows filled with a value no other row holds; for another field, the share of filled values its [locale.detect]
    pattern matches. A field with neither is left out. O(rows · columns · fields) time; memory for the fields alone."""
    asked = [f for f in fields if f == "id" or f in patterns]
    if not asked or not columns:
        return {}
    n = max(1, engine.value(f"SELECT count(*) FROM {table}"))
    share = lambda f: (f"count(DISTINCT v) FILTER (WHERE {filled('v')}) / {n}" if f == "id"
                       else f"coalesce(avg(regexp_matches(v, {lit(patterns[f])})::INT) FILTER (WHERE {filled('v')}), 0)")
    # the sample long (one row per column and value), each pattern once over it: memory grows with the patterns, not columns × patterns
    got = {c: x for c, *x in engine.rows(f"SELECT c, {', '.join(map(share, asked))} FROM {unpivoted(table, columns, 'c', 'v')} GROUP BY c")}
    return {f: {c: got[c][i] if c in got else 0 for c in columns} for i, f in enumerate(asked)}


def suggest(src: Source, engine: Engine, fields: Iterable[str], patterns: Mapping[str, str],
            rows: int = 10_000) -> dict[str, tuple[str, float, str]]:
    """For each field, the file's column whose values look most like it, its share and the evidence, from the first `rows`
    records (fit). A field nothing matches is left out. Suggestions only: a wrong guess applied silently would
    corrupt results. O(rows · columns)."""
    engine.run(f"CREATE OR REPLACE TEMP TABLE er_sample AS SELECT * FROM {src.sql} LIMIT {rows}")
    out = {}
    for f, shares in fit(engine, "er_sample", src.columns, fields, patterns).items():
        best = max(shares, key=shares.get)
        if shares[best] > 0:
            out[f] = (best, shares[best], f"{shares[best]:.0%} {'filled and unique' if f == 'id' else f'of filled values look like {f}'}")
    return out




def plain(value: str, fold: dict[int, str]) -> str:  # a value as names are looked up: same width, no spaces, katakana, kana folded
    v = re.sub(r"[\s\u3000・]+", "", unicodedata.normalize("NFKC", value))
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in v).translate(fold)


def file_facts(files: list[Path], role: str) -> list[dict]:
    """Each file read: its path, what it is (records, decisions, the name model), size and SHA-256, so a run
    says exactly what went in, and a rerun finds its records again. O(bytes)."""
    return [dict(file=str(Path(f).resolve()), role=role, bytes=Path(f).stat().st_size, sha256=intake.sha256(Path(f))) for f in files]


def decisions(path: str | Path, engine: Engine, l: str, r: str, into: str) -> list[Path]:
    """People's decisions on pairs (a match table with decision filled in, or any file with the two IDs and decision)
    as the table `into`, and the files read: each pair once, the lower ID first, decision match or no_match, and the
    file's why where it has one; rows without a decision skipped. Refuses a file without those
    columns, a decided row without both IDs, a file with no decision, another decision, and a pair decided both ways.
    O(rows)."""
    src = open_source(path, engine, [l, r, "decision"])
    if {l, r, "decision"} - set(src.columns):  # say what is wrong, row by row where it can
        raise InputError(f"{path}: needs the columns {l}, {r} and decision; it has {sorted(src.columns)}",
                         fix="give back a match table with decision filled in, or a file with those three columns")
    decided = f"FROM {src.sql} WHERE {filled('decision')}"
    if (blank := engine.value(f"SELECT count(*) {decided} AND NOT ({filled(l)} AND {filled(r)})")):
        raise InputError(f"{path}: {blank:,} decided rows lack an ID", fix="fill in both IDs of each decided row, or clear its decision")
    blank = lit(FILLED)  # spaces of any width, as filled() reads them: "match　" is match
    why = f"nullif(trim(why, {blank}), '')" if "why" in src.columns else "NULL::VARCHAR"  # the file's own why, kept with the decision
    engine.run(f"""CREATE OR REPLACE TABLE {q(into)} AS SELECT least({q(l)}, {q(r)}) AS {q(l)}, greatest({q(l)}, {q(r)}) AS {q(r)},
        lower(trim(decision, {blank})) AS decision, any_value({why}) AS why {decided} GROUP BY 1, 2, 3""")
    if not engine.value(f"SELECT count(*) FROM {q(into)}"):
        raise InputError(f"{path}: no row has a decision", fix="write match or no_match in the table's decision column")
    if (bad := engine.rows(f"SELECT DISTINCT decision FROM {q(into)} WHERE decision NOT IN ('match', 'no_match')")):
        raise InputError(f"{path}: a decision is match or no_match, not {sorted(x for x, in bad)}", fix="correct those rows, or leave them empty")
    if (both := engine.rows(f"SELECT {q(l)}, {q(r)} FROM {q(into)} GROUP BY ALL HAVING count(*) > 1 LIMIT 5")):
        raise InputError(f"{path}: pairs decided both ways: {both}", fix="keep one decision per pair")
    return src.files


def known(engine: Engine, ids: str, records: str, uid: str, path: str | Path, where: str) -> None:
    """Every ID people gave (`ids`: SQL with one column, id) names a record of `records`; the first five that don't are
    refused. A spreadsheet reads 0000000151 as the number 151: such a file would stand for no record. O(IDs + N)."""
    unknown = [x for x, in engine.rows(f"SELECT id FROM ({ids}) WHERE id NOT IN (SELECT {q(uid)} FROM {records}) ORDER BY 1 LIMIT 5")]
    if unknown:
        raise InputError(f"{path}: IDs that name no record of {where}: {unknown}",
                         fix="check the IDs as the run wrote them: a spreadsheet may read 0000000151 as the number 151")
