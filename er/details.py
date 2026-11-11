"""A details file: rows about the records (any number for one record, found by its ID) that people see above it as
they review, and that matching never reads. The workspace keeps all of it in details/: every row and column, sorted by
the ID, in row groups of ROW_GROUP rows, so a card reads only the row groups whose ID range can hold its records."""
import json
import re
from pathlib import Path

import duckdb

from er import folder, source
from er.config import InputError, lit, q
from er.io import replace_text
from er.settings import norm_name

DETAILS, ABOUT = "details", "details.json"  # details.json names the rows file a reader opens: a load writes a new one, never over one open
KEY, ROW = "__key", "__row"  # the ID as one_id makes it; the row's place in the file
ROW_GROUP = 32768  # measured at 10 million rows: 10 ms a card, against 24 ms at 8,192 (each group's range is checked)
CAP = 1000  # rows shown for one ID: past it a key is broken (a placeholder ID), not a customer's


def one_id(x: str) -> str:
    """SQL for the ID `x` as one text: trimmed, and digits alone without their leading zeros, so 123, '123' and
    '0000000123' (a number column, a text one, a padded one) name one record. one_id_of is the same in Python."""
    t = f"trim(CAST({x} AS VARCHAR))"
    return f"nullif(CASE WHEN regexp_full_match({t}, '[0-9]+') THEN coalesce(nullif(ltrim({t}, '0'), ''), '0') ELSE {t} END, '')"


def one_id_of(x: str) -> str:
    t = str(x).strip()
    return (t.lstrip("0") or "0") if re.fullmatch(r"[0-9]+", t) else t


def about(ws: Path) -> dict | None:
    f = ws / DETAILS / ABOUT
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def described(ws: Path) -> dict | None:  # what describe workspace says of it
    a = about(ws)
    return a and {k: v for k, v in a.items() if k != "rows_file"}


def load(con: duckdb.DuckDBPyConnection, ws: Path, path: str, key: str | None, shown: list[str] | None, uid: str) -> dict:
    """The file's rows into the workspace, sorted by `key` (default: the records' ID column), and which of its columns
    people see (default: all). O(m log m) for m rows, once; the records linked to them, O(n + m)."""
    files = source.find(path)
    for f in files:
        source.check_parquet(f)
    src = f"read_parquet([{', '.join(lit(str(f)) for f in files)}], union_by_name = true, filename = true, file_row_number = true)"
    columns = [c for c, *_ in con.execute(f"DESCRIBE SELECT * EXCLUDE (filename, file_row_number) FROM {src}").fetchall()]
    name, key = Path(path).name, key or uid
    if key not in columns:
        raise InputError(f"{name} has no column {key}", fix=f"name the one holding the records' IDs: --key COLUMN (one of {', '.join(columns[:12])}{' …' if len(columns) > 12 else ''})")
    shown = _known(columns, shown, name) if shown is not None else [c for c in columns if c != key]
    k = one_id(q(key))
    place = f"list_position([{', '.join(lit(str(f)) for f in files)}], filename) * (1::BIGINT << 40) + file_row_number"
    d = ws / DETAILS
    with folder.run_lock(ws):
        d.mkdir(exist_ok=True)
        rows_file = f"rows-{1 + max((int(f.stem[5:]) for f in d.glob('rows-*.parquet') if f.stem[5:].isdigit()), default=0)}.parquet"
        tmp = d / f".{rows_file}.tmp"
        con.execute(f"COPY (SELECT {k} AS {KEY}, {place} AS {ROW}, * EXCLUDE (filename, file_row_number) FROM {src} WHERE {k} IS NOT NULL "
                    f"ORDER BY {KEY}, {ROW}) TO {lit(tmp)} (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP})")
        tmp.replace(d / rows_file)
        rows = f"read_parquet({lit(d / rows_file)})"
        counts = con.execute(f"SELECT count(*), count(DISTINCT {KEY}), {', '.join(f'count({q(c)}), any_value(CAST({q(c)} AS VARCHAR))' for c in columns)} FROM {rows}").fetchone()
        given = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        a = dict(file=name, rows=counts[0], ids=counts[1], unkeyed=given - counts[0], key=key,
                 columns=[dict(column=c, filled=counts[2 + 2 * i] / counts[0] if counts[0] else 0.0, example=counts[3 + 2 * i]) for i, c in enumerate(columns)],
                 shown=shown, **_linked(con, ws, uid, rows), rows_file=rows_file)
        with folder.writing(d / ABOUT):
            replace_text(d / ABOUT, json.dumps(a, ensure_ascii=False, indent=1))
        for old in d.glob("rows-*.parquet"):  # an older load's, unless a reader still has it open (Windows): the next load tries again
            if old.name != rows_file:
                try:
                    old.unlink()
                except OSError:
                    pass
    return described(ws)


def _known(columns: list[str], shown: list[str], name: str) -> list[str]:  # the file's columns named, in its order
    if unknown := [c for c in shown if c not in columns]:
        raise InputError(f"{name} has no column {', '.join(unknown)}", fix=f"one of {', '.join(columns)}")
    return [c for c in columns if c in shown]


def _linked(con: duckdb.DuckDBPyConnection, ws: Path, uid: str, rows: str) -> dict:  # the records, in the file given last, that have a row
    part = folder.last(ws)
    if part is None:
        return dict(linked=None, records=None)
    got = f"read_parquet([{', '.join(lit(str(f)) for f in source.find(part))}], union_by_name = true)"
    have = [c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {got}").fetchall()]
    col = next((c for c in have if c == uid), None) or next((c for c in have if norm_name(c) == norm_name(uid)), None)
    if col is None:
        return dict(linked=None, records=None)
    n, linked = con.execute(f"SELECT count(*), count(d.{KEY}) FROM {got} r LEFT JOIN (SELECT DISTINCT {KEY} FROM {rows}) d ON {one_id(f"r.{q(col)}")} = d.{KEY}").fetchone()
    return dict(linked=linked, records=n)


def choose(ws: Path, shown: list[str]) -> dict:
    """The columns people see, in the file's order. O(columns): matching reads none of it, so nothing runs again."""
    with folder.writing(ws / DETAILS / ABOUT):
        a = about(ws)
        if a is None:
            raise InputError(f"{ws} holds no details file", fix=f"load one: nayose load details FILE --workspace {ws}")
        a["shown"] = _known([c["column"] for c in a["columns"]], shown, a["file"])
        replace_text(ws / DETAILS / ABOUT, json.dumps(a, ensure_ascii=False, indent=1))
    return described(ws)


def show(con: duckdb.DuckDBPyConnection, ws: Path, ids: list[str]) -> dict:
    """Each record's rows, the columns shown, in the file's order: the first CAP of each, and how many it has. The row
    groups whose ID range holds none of `ids` are skipped, so a call reads O(len(ids) · ROW_GROUP) rows, and the ranges of the m / ROW_GROUP groups."""
    a = about(ws)
    if a is None:
        return dict(file=None, key=None, columns=[], records=[])
    cols, given = a["shown"], list(dict.fromkeys(str(i) for i in ids))
    wanted = list(dict.fromkeys(map(one_id_of, given)))
    got = con.execute(f"SELECT {KEY}, count(*) OVER (PARTITION BY {KEY}), {', '.join([f'CAST({q(c)} AS VARCHAR)' for c in cols] or ['NULL'])} "
                      f"FROM read_parquet({lit(ws / DETAILS / a['rows_file'])}) WHERE {KEY} IN ({', '.join(map(lit, wanted)) or 'NULL'}) "
                      f"QUALIFY row_number() OVER (PARTITION BY {KEY} ORDER BY {ROW}) <= {CAP} ORDER BY {KEY}, {ROW}").fetchall() if wanted else []
    by: dict[str, dict] = {}
    for k, total, *values in got:
        by.setdefault(k, dict(rows=[], total=total))["rows"].append(values[:len(cols)])
    return dict(file=a["file"], key=a["key"], columns=cols, records=[dict(id=i, **by.get(one_id_of(i), dict(rows=[], total=0))) for i in given])
