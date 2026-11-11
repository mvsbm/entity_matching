"""A details file: rows about the records (any number for one record, found by its ID) that people see above it as
they review, and that matching never reads. The workspace keeps where the file is, its key column and the columns
shown (details/details.json), not a copy (a file the page sent, it keeps there): loading reads the file's footer and first rows, and a card reads the file
itself, only the rows of its records. Their IDs are compared as the file holds its key, so no row is changed to be
compared: a number key by its value, a text one as given, without its leading zeros, or padded as the file pads."""
import json
import os
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from er import folder, source
from er.config import InputError, lit, q
from er.io import replace_text
from er.settings import norm_name

DETAILS, ABOUT = "details", "details.json"
CAP = 1000  # rows shown for one ID: past it a key is broken (a placeholder ID), not a customer's
SAMPLE = 2000  # records drawn to count those with a row: the share, for one scan of the key column, at any size
NUMBERS = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL")
INNER = ("paths", "linked_of", "pad", "number")  # what a show needs and describe workspace doesn't say


def about(ws: Path) -> dict | None:
    f = ws / DETAILS / ABOUT
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def described(ws: Path, uid: str | None = None) -> dict | None:
    """What describe workspace says of it. Given the records' ID column, the records with a row are counted again once
    the file given last is another than the one they were counted in."""
    a = about(ws)
    if a and uid and a.get("linked_of") != _counted(ws, uid):
        with folder.writing(ws / DETAILS / ABOUT):
            if (a := about(ws)) and a.get("linked_of") != _counted(ws, uid):  # another counted them meanwhile
                a.update(_linked(duckdb.connect(), ws, uid, a))
                replace_text(ws / DETAILS / ABOUT, json.dumps(a, ensure_ascii=False, indent=1))
    return a and {k: v for k, v in a.items() if k not in INNER}


def load(ws: Path, path: str, key: str | None, shown: list[str] | None, uid: str) -> dict:
    """Where the file is, which column holds the records' IDs (default: the records' own ID column) and which columns
    people see (default: all), from its footer and its first 200 rows: milliseconds at any size; then the records
    with a row, on a sample of SAMPLE, one scan of the key column."""
    if not (ws / "columns.toml").is_file():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    sent = folder.uploaded(ws, path)  # sent by the page: the workspace's own once it loads, in details/; refused, gone
    try:
        return _load(ws, path, key, shown, uid, sent)
    finally:
        if sent:
            folder.remove(sent)


def _load(ws: Path, path: str, key: str | None, shown: list[str] | None, uid: str, sent: Path | None) -> dict:
    files, given = source.find(path), Path(path).expanduser()
    for f in files:
        source.check_parquet(f)
    name, key = given.parent.name if source.globbed(given) else given.name, key or uid
    con = duckdb.connect()
    types = dict(con.execute(f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM {_read(files)})").fetchall())
    columns = list(types)
    if "file_row_number" in types:
        raise InputError(f"{name} has a column named file_row_number: the name a file's own row order is read by", fix="rename it in the file, then load it again")
    if key not in types:
        raise InputError(f"{name} has no column {key}", fix=f"name the one holding the records' IDs: --key COLUMN (one of {', '.join(columns[:12])}{' …' if len(columns) > 12 else ''})")
    shown = _known(columns, shown, name) if shown is not None else [c for c in columns if c != key]
    rows, nulls = 0, dict.fromkeys(columns, 0)
    for f in files:  # the footer's counts: no row read
        m = pq.ParquetFile(f).metadata
        rows += m.num_rows
        for g in range(m.num_row_groups):
            for k in range(m.num_columns):
                c = m.row_group(g).column(k)
                if c.path_in_schema in nulls and c.statistics is not None and c.statistics.has_null_count:
                    nulls[c.path_in_schema] += c.statistics.null_count
    first = con.execute(f"SELECT {', '.join(f'CAST({q(c)} AS VARCHAR)' for c in columns)} FROM {_read(files)} LIMIT 200").fetchall()
    example = {c: next((r[i] for r in first if r[i] not in (None, "")), None) for i, c in enumerate(columns)}
    keys = [r[columns.index(key)].strip() for r in first if r[columns.index(key)] is not None]
    widths = {len(k) for k in keys if k.isascii() and k.isdigit()}
    a = dict(file=name, rows=rows, key=key, columns=[dict(column=c, filled=1 - nulls[c] / rows if rows else 0.0, example=example[c]) for c in columns],
             shown=shown, paths=[str(f.resolve()) for f in files], number=types[key].split("(")[0] in NUMBERS,
             pad=widths.pop() if len(widths) == 1 and all(k.isascii() and k.isdigit() for k in keys) else None)  # every ID digits of one width: the file pads them
    (ws / DETAILS).mkdir(exist_ok=True)
    if sent:  # moved, not copied: one rename on the workspace's disk
        kept, inside = ws / DETAILS / sent.name, [f.resolve().relative_to(sent) for f in files] if sent.is_dir() else []
        folder.remove(kept)
        os.replace(sent, kept)
        a["paths"] = [str((kept / f).resolve()) for f in inside] or [str(kept.resolve())]
    a.update(_linked(con, ws, uid, a))
    with folder.writing(ws / DETAILS / ABOUT):
        replace_text(ws / DETAILS / ABOUT, json.dumps(a, ensure_ascii=False, indent=1))
    for x in (ws / DETAILS).iterdir():  # a file the page sent that this one replaces
        if x.name != ABOUT and not x.name.startswith(".") and not any(Path(p).resolve().is_relative_to(x.resolve()) for p in a["paths"]):
            folder.remove(x)
    return described(ws)


def _read(files: list[Path], keep: str = "") -> str:  # the files as one table; with `keep`, those columns and each row's place in the files (__place)
    if not keep:
        return f"read_parquet([{', '.join(lit(str(f)) for f in files)}], union_by_name = true)"
    return "(" + " UNION ALL BY NAME ".join(f"SELECT {keep}, ({i}::BIGINT << 40) + file_row_number AS __place FROM read_parquet({lit(str(f))}, file_row_number = true)"
                                            for i, f in enumerate(files)) + ")"


def _forms(ids: list[str], a: dict) -> dict[str, str]:
    """The forms the file may hold each ID's key in, as SQL literals, each → its ID: a number key, the number; a text
    one, the ID as given, without its leading zeros, and padded to the file's width."""
    out = {}
    for i in ids:
        t = str(i).strip()
        digits = t.isascii() and t.isdigit()
        if a["number"]:
            if digits:
                out[str(int(t))] = i
            continue
        bare = (t.lstrip("0") or "0") if digits else t
        for x in (t, bare, bare.zfill(a["pad"]) if digits and a.get("pad") else t):
            out.setdefault(lit(x), i)
    return out


def _owner(v: object, forms: dict[str, str], number: bool) -> str | None:  # the ID a value of the file's key is a form of
    if number:
        return forms.get(str(int(v))) if v is not None and float(v).is_integer() else None
    return forms.get(lit(str(v).strip()))


def _counted(ws: Path, uid: str) -> str | None:  # what the records with a row were counted in: the file given last, by its ID column
    part = folder.last(ws)
    return part and f"{part.name} {uid}"


def _known(columns: list[str], shown: list[str], name: str) -> list[str]:  # the file's columns named, in the order given: the first names each row on its chip
    if unknown := [c for c in shown if c not in columns]:
        raise InputError(f"{name} has no column {', '.join(unknown)}", fix=f"one of {', '.join(columns)}")
    return list(dict.fromkeys(shown))


def _here(a: dict) -> bool:
    return all(os.path.isfile(p) for p in a["paths"])


def _linked(con: duckdb.DuckDBPyConnection, ws: Path, uid: str, a: dict) -> dict:
    """Of SAMPLE records drawn from the file given last (every one, if it holds fewer), those with a row."""
    part, none = folder.last(ws), dict(linked=None, drawn=None, linked_of=_counted(ws, uid))
    if part is None or not _here(a):
        return none
    got = f"read_parquet([{', '.join(lit(str(f)) for f in source.find(part))}], union_by_name = true)"
    have = [c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {got}").fetchall()]
    col = next((c for c in have if c == uid), None) or next((c for c in have if norm_name(c) == norm_name(uid)), None)
    if col is None:
        return none
    ids = [r[0] for r in con.execute(f"SELECT {q(col)} FROM {got} WHERE {q(col)} IS NOT NULL USING SAMPLE reservoir({SAMPLE} ROWS) REPEATABLE (0)").fetchall()]
    forms = _forms(ids, a)
    found = {_owner(v, forms, a["number"]) for (v,) in con.execute(
        f"SELECT DISTINCT {q(a['key'])} FROM {_read([Path(p) for p in a['paths']])} WHERE {q(a['key'])} IN ({', '.join(forms)})").fetchall()} if forms else set()
    return {**none, "drawn": len(ids), "linked": len(found - {None})}


def choose(ws: Path, shown: list[str]) -> dict:
    """The columns people see, in the order given. O(columns): matching reads none of it, so nothing runs again."""
    with folder.writing(ws / DETAILS / ABOUT):
        a = about(ws)
        if a is None:
            raise InputError(f"{ws} holds no details file", fix=f"load one: nayose load details FILE --workspace {ws}")
        a["shown"] = _known([c["column"] for c in a["columns"]], shown, a["file"])
        replace_text(ws / DETAILS / ABOUT, json.dumps(a, ensure_ascii=False, indent=1))
    return described(ws)


def show(ws: Path, ids: list[str]) -> dict:
    """Each record's rows in the file, the columns shown, in the file's order: the first CAP of each, and how many it
    has. The key is compared as the file holds it, so the file's own statistics skip what can't hold the IDs: at most
    one scan of the key column, and the shown columns of the rows found."""
    a = about(ws)
    if a is None:
        return dict(file=None, key=None, columns=[], records=[])
    if not _here(a):
        raise InputError(f"{a['file']} is no longer where it was loaded from ({a['paths'][0]})", fix=f"load it again: nayose load details FILE --workspace {ws}")
    given = list(dict.fromkeys(str(i) for i in ids))
    forms, cols, key = _forms(given, a), a["shown"], q(a["key"])
    got = duckdb.connect().execute(
        f"SELECT {key}, count(*) OVER (PARTITION BY {key}), {', '.join([f'CAST({q(c)} AS VARCHAR)' for c in cols] or ['NULL'])} "
        f"FROM {_read([Path(p) for p in a['paths']], ', '.join(dict.fromkeys([key, *map(q, cols)])))} WHERE {key} IN ({', '.join(forms)}) "
        f"QUALIFY row_number() OVER (PARTITION BY {key} ORDER BY __place) <= {CAP} ORDER BY __place").fetchall() if forms else []
    by: dict[str, dict] = {}
    for k, total, *values in got:  # in the file's order; one ID held in two forms (123 and 0123): both counted
        if (i := _owner(k, forms, a["number"])) is None:
            continue
        x = by.setdefault(i, dict(rows=[], total=0, seen=set()))
        if k not in x["seen"]:
            x["seen"].add(k)
            x["total"] += total
        if len(x["rows"]) < CAP:
            x["rows"].append(values[:len(cols)])
    return dict(file=a["file"], key=a["key"], columns=cols,
                records=[dict(id=i, rows=by[i]["rows"] if i in by else [], total=by[i]["total"] if i in by else 0) for i in given])
