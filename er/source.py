"""The one door every input goes through: records, increment batches, and people's files (person/company answers,
decisions on pairs), all Parquet. It finds the files (a path, a glob or a folder), checks that each is Parquet, reads
several together by column name, and gives a column its configured name when the two differ only in case, width or
separators. Source.notes says what it did; when it must stop, it raises an InputError that says what to fix. It reads
each file's footer (its schema), never its rows, so its cost doesn't grow with the file. suggest() profiles a
fixed-size sample. People's files are checked here too (answers, decisions), and every ID they give must name a record
(known): one rule for both.
"""
import difflib
import hashlib
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


def suggest(src: Source, con: duckdb.DuckDBPyConnection, fields: Iterable[str], patterns: Mapping[str, str],
            rows: int = 10_000) -> dict[str, tuple[str, float, str]]:
    """For each field, the file's column whose values look most like it, its share and the evidence, from the first `rows`
    records: for `id`, the share filled and unique; for another field, the share of filled values its [locale.detect]
    pattern matches. A field nothing matches is left out. Suggestions only: a wrong guess applied silently would
    corrupt results. O(rows · columns)."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE er_sample AS SELECT * FROM {src.sql} LIMIT {rows}")
    n = con.execute("SELECT count(*) FROM er_sample").fetchall()[0][0]
    if not n:
        return {}
    out = {}
    for f in fields:
        if f == "id":
            stats = [f"count(DISTINCT nullif(trim({q(c)}), '')) / {n}" for c in src.columns]
            what = "filled and unique"
        elif f in patterns:
            p = patterns[f].replace("'", "''")
            stats = [f"coalesce(avg(regexp_matches({q(c)}, '{p}')::INT) FILTER (WHERE nullif(trim({q(c)}), '') IS NOT NULL), 0)" for c in src.columns]
            what = f"of filled values look like {f}"
        else:
            continue
        shares = con.execute(f"SELECT {', '.join(stats)} FROM er_sample").fetchall()[0]
        best = max(range(len(shares)), key=lambda i: shares[i])
        if shares[best] > 0:
            out[f] = (src.columns[best], shares[best], f"{shares[best]:.0%} {what}")
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
