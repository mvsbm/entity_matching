"""A details file: rows about the records (any number for one record, found by its ID) that people see above it as
they review, and that matching never reads. The workspace keeps all of it in details/: every row and column, sorted by
the ID, in row groups of ROW_GROUP rows, so a card reads only the row groups whose ID range can hold its records."""
import json
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import duckdb

from er import folder, source
from er.config import InputError, lit, q
from er.io import replace_text
from er.settings import norm_name

DETAILS, ABOUT = "details", "details.json"  # details.json names the rows file a reader opens: a load writes a new one, never over one open
KEY, ROW, FILE = "__key", "__row", "__file"  # the ID as one_id makes it; the row's place in the file; its file's, while loading
OWN = (KEY, ROW, FILE, "file_row_number")  # names the copy keeps for itself: a file's own column of one is refused
ROW_GROUP = 32768  # measured at 10 million rows: 10 ms a card, against 24 ms at 8,192 (each group's range is checked)
CAP = 1000  # rows shown for one ID: past it a key is broken (a placeholder ID), not a customer's


def one_id(x: str) -> str:
    """SQL for the ID `x` as one text, the same for both files and the IDs asked: without the spaces around it, a whole
    number's decimals (123.0, 123.00) and the leading zeros of digits alone, so 123, '123', 123.0 and '0000000123' (a
    number column, a text one, one with a missing value, a padded one) name one record."""
    t = f"regexp_replace(regexp_replace(CAST({x} AS VARCHAR), '^\\s+|\\s+$', '', 'g'), '^([0-9]+)\\.0+$', '\\1')"
    return f"nullif(CASE WHEN regexp_full_match({t}, '[0-9]+') THEN coalesce(nullif(ltrim({t}, '0'), ''), '0') ELSE {t} END, '')"


def about(ws: Path) -> dict | None:
    f = ws / DETAILS / ABOUT
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def described(ws: Path, uid: str | None = None, connect: Callable[[], duckdb.DuckDBPyConnection] | None = None) -> dict | None:
    """What describe workspace says of it. Given the records' ID column and a connection, the records that have a row
    are counted again once the file given last is another than the one they were counted in: O(n + m), once."""
    a = about(ws)
    if a and connect and a.get("linked_of") != _counted(ws, uid):
        with folder.writing(ws / DETAILS / ABOUT):
            if (a := about(ws)) and a.get("linked_of") != _counted(ws, uid):  # another counted them meanwhile
                a.update(_linked(connect(), ws, uid, f"read_parquet({lit(ws / DETAILS / a['rows_file'])})"))
                replace_text(ws / DETAILS / ABOUT, json.dumps(a, ensure_ascii=False, indent=1))
    return a and {k: v for k, v in a.items() if k not in ("rows_file", "linked_of")}


def load(con: duckdb.DuckDBPyConnection, ws: Path, path: str, key: str | None, shown: list[str] | None, uid: str) -> dict:
    """The file's rows into the workspace, sorted by `key` (default: the records' ID column), and which of its columns
    people see (default: all). O(m log m) for m rows, once; the records linked to them, O(n + m)."""
    if not (ws / "columns.toml").is_file():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    files, given = source.find(path), Path(path).expanduser()
    for f in files:
        source.check_parquet(f)
    name, key = given.parent.name if source.globbed(given) else given.name, key or uid
    plain = f"read_parquet([{', '.join(lit(str(f)) for f in files)}], union_by_name = true)"
    columns = [c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {plain}").fetchall()]
    if taken := [c for c in columns if c in OWN]:
        raise InputError(f"{name} has a column named {', '.join(taken)}: a name nayose keeps for its copy", fix="rename it in the file, then load it again")
    if key not in columns:
        raise InputError(f"{name} has no column {key}", fix=f"name the one holding the records' IDs: --key COLUMN (one of {', '.join(columns[:12])}{' …' if len(columns) > 12 else ''})")
    shown = _known(columns, shown, name) if shown is not None else [c for c in columns if c != key]
    k = one_id(q(key))
    src = " UNION ALL BY NAME ".join(f"SELECT {i}::BIGINT AS {FILE}, * FROM read_parquet({lit(str(f))}, file_row_number = true)" for i, f in enumerate(files))  # each file's place, as given
    d = ws / DETAILS
    d.mkdir(exist_ok=True)
    with _loading(d):
        rows_file = f"rows-{1 + max((int(f.stem[5:]) for f in d.glob('rows-*.parquet') if f.stem[5:].isdigit()), default=0)}.parquet"
        tmp = d / f".{rows_file}.tmp"
        con.execute(f"COPY (SELECT {k} AS {KEY}, ({FILE} << 40) + file_row_number AS {ROW}, * EXCLUDE ({FILE}, file_row_number) FROM ({src}) WHERE {k} IS NOT NULL "
                    f"ORDER BY {KEY}, {ROW}) TO {lit(tmp)} (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP})")
        tmp.replace(d / rows_file)
        rows = f"read_parquet({lit(d / rows_file)})"
        counts = con.execute(f"SELECT count(*), count(DISTINCT {KEY}), {', '.join(f'count({q(c)}), any_value(CAST({q(c)} AS VARCHAR))' for c in columns)} FROM {rows}").fetchone()
        total = con.execute(f"SELECT count(*) FROM {plain}").fetchone()[0]
        a = dict(file=name, rows=counts[0], ids=counts[1], unkeyed=total - counts[0], key=key,
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


@contextmanager
def _loading(d: Path):  # one load at a time; not the workspace's lock, so a run, a decision or an answer goes on meanwhile
    try:
        with folder.writing(d / "rows", wait=0):
            yield
    except folder.Busy:
        raise folder.Busy(f"another details file is loading into {d.parent}", fix="wait for it to finish") from None


def _counted(ws: Path, uid: str) -> str | None:  # what the records with a row were counted in: the file given last, by its ID column
    part = folder.last(ws)
    return part and f"{part.name} {uid}"


def _known(columns: list[str], shown: list[str], name: str) -> list[str]:  # the file's columns named, in its order
    if unknown := [c for c in shown if c not in columns]:
        raise InputError(f"{name} has no column {', '.join(unknown)}", fix=f"one of {', '.join(columns)}")
    return [c for c in columns if c in shown]


def _linked(con: duckdb.DuckDBPyConnection, ws: Path, uid: str, rows: str) -> dict:  # the records, in the file given last, that have a row
    part, none = folder.last(ws), dict(linked=None, records=None, linked_of=_counted(ws, uid))
    if part is None:
        return none
    got = f"read_parquet([{', '.join(lit(str(f)) for f in source.find(part))}], union_by_name = true)"
    have = [c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {got}").fetchall()]
    col = next((c for c in have if c == uid), None) or next((c for c in have if norm_name(c) == norm_name(uid)), None)
    if col is None:
        return none
    n, linked = con.execute(f"SELECT count(*), count(d.{KEY}) FROM {got} r LEFT JOIN (SELECT DISTINCT {KEY} FROM {rows}) d ON {one_id(f"r.{q(col)}")} = d.{KEY}").fetchone()
    return {**none, "linked": linked, "records": n}


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
    as_one = dict(con.execute(f"SELECT x, {one_id('x')} FROM unnest([{', '.join(map(lit, given))}]::VARCHAR[]) t(x)").fetchall()) if given else {}  # as the copy holds them
    wanted = list(dict.fromkeys(x for x in as_one.values() if x is not None))
    got = con.execute(f"SELECT {KEY}, count(*) OVER (PARTITION BY {KEY}), {', '.join([f'CAST({q(c)} AS VARCHAR)' for c in cols] or ['NULL'])} "
                      f"FROM read_parquet({lit(ws / DETAILS / a['rows_file'])}) WHERE {KEY} IN ({', '.join(map(lit, wanted)) or 'NULL'}) "
                      f"QUALIFY row_number() OVER (PARTITION BY {KEY} ORDER BY {ROW}) <= {CAP} ORDER BY {KEY}, {ROW}").fetchall() if wanted else []
    by: dict[str, dict] = {}
    for k, total, *values in got:
        by.setdefault(k, dict(rows=[], total=total))["rows"].append(values[:len(cols)])
    return dict(file=a["file"], key=a["key"], columns=cols, records=[dict(id=i, **by.get(as_one.get(i), dict(rows=[], total=0))) for i in given])
