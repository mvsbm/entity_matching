"""A records file as it comes, read into one clean Parquet before the door (er.source): the intake.

Records come as Parquet: anything else is refused, with how to write it as Parquet. A file is read a chunk of CHUNK
rows at a time, by column, every column as text. What loses nothing is fixed at once and counted, never a value:
control bytes, zero-width characters and BOMs removed; placeholder nulls ([input] nulls) and values of spaces alone
made missing; numbers a spreadsheet cut short (1.23E+11) made missing, and 12345.0 read as 12345; a value written as a
list (a Parquet list column, or text like ["8700848"]) read as its item: the first, when it lists several, counted
apart. Text is UTF-8: a value stored as bytes that aren't, or holding U+FFFD (bytes decoded wrong upstream), is made
missing and counted as damaged. A blank column name is numbered, and one that repeats another but for case suffixed.

A part (a job's own temporary folder, er.source.readable) holds `read/` (what the job reads) and intake.json (counts
only: no value). O(bytes) in one pass: what reading keeps as it is settled in Arrow, the rest one value at a time.
"""
import ast
import functools
import hashlib
import json
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from er.config import InputError

REPORT, READ = "intake.json", "read"
SUFFIXES = (".parquet",)  # the records files a folder holds
CHUNK = 200_000  # shortcut: about 9 s a million records of 25 columns; past ~20M rows on one machine, split the file
CONVERT = ("write it as Parquet, every column as text: in Python, pandas.read_csv(path, dtype=str).to_parquet(new); "
           "in DuckDB, COPY (FROM read_csv(path, all_varchar = true)) TO new")
CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‍⁠﻿]")
BREAKS = re.compile("[\t\r\n]+")
WHOLE = re.compile(r"^(-?\d+)\.0+$")  # a whole number a spreadsheet wrote as a float
CUT = re.compile(r"^-?\d(\.\d+)?[eE]\+\d+$")  # a number a spreadsheet wrote in E notation (1.23457E+11, 1E+11): its digits are gone
# the text reading keeps as it is, without a look at each value: what a Japanese records file holds, controls and breaks aside
JAPANESE = re.compile("[\x00-\x7f -⁯﻿←-⏿①-➿　-ヿ㆐-㏿㐀-䶿一-鿿豈-﫿︰-﹏＀-￯]*")
SPACES = "  -     　"  # JAPANESE's spaces, controls and breaks aside


@dataclass(frozen=True)
class InputSpec:  # [input]: how a file is read, before anything else
    nulls: tuple[str, ...] = ("NULL", "null", "Null", "\\N", "NaN", "nan", "None", "none", "N/A", "n/a", "#N/A", "-", "－")


# ---------- a value as read: what loses nothing, fixed ----------

class _Number(str):  # a number as a list wrote it, its own text kept: the number rules read it as they read a bare one
    pass


def _refuse(_: str) -> None:  # NaN, Infinity: no list of plain items
    raise ValueError


def unlisted(v: str) -> tuple[str | None, str] | None:
    """A value written as a list of plain items (["8700848"], ['大分県'], [8700848], [0708612], [], ["a", "b"]): its
    first filled item, and the fix (lists: nothing lost; first of several: the rest dropped). Items are strings, or
    numbers kept as written (a whole one written 12345.0 read as 12345, one cut short like 1.23E+11 made missing, as a
    bare one is). None for anything else in brackets ([株], [true], a list of lists), which stays as it is."""
    if digits := re.fullmatch(r"\[\s*(\d+)\s*\]", v):  # a code with leading zeros, unquoted: no parser keeps them
        return digits.group(1), "lists"
    try:
        items = json.loads(v, parse_int=_Number, parse_float=_Number, parse_constant=_refuse, strict=False)  # a line break inside: the controls fix takes it
    except ValueError:
        try:  # quoted with ' (a Python list written out): strings only
            items = ast.literal_eval(v)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):  # TypeError: an unhashable item, [{[]}]
            return None
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            return None
    if not isinstance(items, list) or not all(x is None or isinstance(x, str) for x in items):  # true, false, nested: not plain items
        return None
    items = [x for x in items if x is not None and x.strip()]
    if not items:
        return None, "lists"
    first, several = items[0], len(items) > 1
    if isinstance(first, _Number):
        first = None if CUT.match(first) else (m.group(1) if (m := WHOLE.match(first)) else str(first))
    return first, "first of several" if several else "lists"


def tidy(v: str | None, nulls: frozenset[str], numeric: bool) -> tuple[str | None, str | None]:  # the value, and what was fixed
    if v is None:
        return None, None
    fixed = None
    if (s := v.strip())[:1] == "[" and s[-1:] == "]" and (listed := unlisted(s)):  # first: its item gets every fix below
        v, fixed = listed
        if v is None:
            return None, fixed
    if not v.isprintable():
        w = BREAKS.sub(" ", CONTROL.sub("", v))
        fixed, v = ("controls" if w != v else fixed), w
    s = v.strip(" 　")
    if s in nulls or not v.strip():  # spaces alone (any width, tabs) say nothing: two such records would agree on nothing
        return None, "placeholders"
    if numeric and ("." in s or "e" in s or "E" in s):
        if m := WHOLE.match(s):
            return m.group(1), "numbers"
        if CUT.match(s):
            return None, "numbers"
    return v, fixed


def numeric(values: list[str | None]) -> bool:  # a column of numbers: half its filled values (of the first 50,000) digits, a point or an exponent aside
    vals = [x for v in values[:50_000] if v and (x := v.strip())]
    return bool(vals) and sum(x.isascii() and x.replace(".", "", 1).replace("E+", "").replace("e+", "").lstrip("-").isdigit() for x in vals) >= 0.5 * len(vals)


# ---------- what reading keeps as it is, settled in Arrow ----------

def members(chars: str) -> set[int]:  # a character class's members (ranges kept), by code point
    out, i = set(), 0
    while i < len(chars):
        if i + 2 < len(chars) and chars[i + 1] == "-":
            out.update(range(ord(chars[i]), ord(chars[i + 2]) + 1))
            i += 3
        else:
            out.add(ord(chars[i]))
            i += 1
    return out


def re2_class(points: set[int]) -> str:  # code points as an RE2 character class's members, each run a range
    xs, out, i = sorted(points), [], 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1:
            j += 1
        out.append(f"\\x{{{xs[i]:x}}}" + (f"-\\x{{{xs[j]:x}}}" if j > i else ""))
        i = j + 1
    return "".join(out)


@functools.cache
def text_re2() -> str:
    """Text reading keeps as it is, as one RE2 pattern: every character JAPANESE's and none a control or a break, and
    one at least not a space. One pass where three would read each value."""
    ok = members(JAPANESE.pattern[1:-2]) - members(CONTROL.pattern[1:-1]) - members(BREAKS.pattern[1:-2])
    return f"^[{re2_class(ok)}]*[{re2_class(ok - members(SPACES))}][{re2_class(ok)}]*$"


def plain_ascii(x: pa.Array) -> pa.Array:  # ASCII text printable, not empty, no space at either end: what reading keeps as it is; a byte loop, not a regex
    return pc.and_(pc.and_(pc.ascii_is_printable(x), pc.greater(pc.binary_length(x), 0)), pc.invert(pc.or_(pc.starts_with(x, " "), pc.ends_with(x, " "))))


def settled(a: pa.Array, numeric: bool, nulls: pa.Array) -> np.ndarray:
    """Which values of a text column reading keeps as they are, decided in Arrow: plain ASCII (printable, no space at
    either end, not a placeholder, not a number to fix), and text in JAPANESE with nothing to fix (no control character
    or line break, not spaces alone, not a placeholder, not a number to fix, not a list). Only what value() would return
    unchanged: every other value is read one by one. O(values · length) in Arrow."""
    def on(mask: np.ndarray, test) -> np.ndarray:  # a test run on the values `mask` picks alone, False elsewhere: each value is tested only as what it can be
        out = np.zeros(len(a), bool)
        if (where := np.flatnonzero(mask)).size:
            picked = a if where.size == len(a) else a.take(pa.array(where, pa.int64()))  # every value: no copy
            out[where] = pc.fill_null(test(picked), False).to_numpy(zero_copy_only=False)
        return out
    has = lambda pattern: lambda x: pc.match_substring_regex(x, pattern)
    ascii_ = pc.fill_null(pc.string_is_ascii(a), True).to_numpy(zero_copy_only=False)
    number = on(np.ones(len(a), bool), has("[.eE]")) if numeric else np.zeros(len(a), bool)
    number |= on(pc.fill_null(pc.match_substring_regex(a, r"\["), False).to_numpy(zero_copy_only=False), has(r"\[.*\]"))  # perhaps written as a list, spaces around it or not: read one by one, as tidy() decides; RE2 finds a literal far faster than match_substring
    plain = on(ascii_, lambda x: pc.and_(plain_ascii(x), pc.invert(pc.is_in(x, value_set=nulls)))) & ~number
    if ascii_.all():
        return plain
    text = on(~ascii_ & ~number, lambda x: pc.and_(pc.match_substring_regex(x, text_re2()), pc.invert(pc.is_in(pc.utf8_trim(x, " 　"), value_set=nulls))))
    return plain | text


# ---------- one file read ----------

def parquet(f: Path, head: bytes, tail: bytes) -> bool:  # whether the file is Parquet, by its first and last bytes; one cut short is refused
    if head[:4] != b"PAR1":
        return False
    if tail != b"PAR1":
        raise InputError(f"{f}: a Parquet file cut short (it doesn't end as Parquet does)", fix="copy it again, or write it again from its source")
    return True


def check(f: Path, fix: str = CONVERT) -> None:
    """A Parquet file starts and ends with PAR1; one that doesn't is refused, saying what it looks like instead."""
    with f.open("rb") as h:
        head = h.read(4)
        h.seek(max(0, f.stat().st_size - 4))
        tail = h.read(4)
    if parquet(f, head, tail):
        return
    kind = "a ZIP or Excel file" if head[:2] == b"PK" else "empty" if not head else "text, perhaps a CSV" if all(b >= 9 for b in head) else "not Parquet"
    raise InputError(f"{f}: not a Parquet file; it looks like {kind}", fix=fix)


def texts(batch: pa.RecordBatch) -> list[pa.Array]:  # a chunk's columns: text as Arrow text (pa.string), bytes (and text a writer stored that isn't UTF-8) and nested values as they are, the rest cast to text
    arrays = []
    for a in batch.columns:
        a = a.dictionary_decode() if pa.types.is_dictionary(a.type) else a
        if not (pa.types.is_binary(a.type) or pa.types.is_large_binary(a.type) or pa.types.is_nested(a.type)):
            if pa.types.is_floating(a.type):  # a whole number as its digits: Arrow writes 9e+10, which reads as one cut short
                a = a.cast(pa.float64()) if a.type == pa.float16() else a  # Arrow has no floor of a half float
                whole = pc.and_(pc.equal(pc.floor(a), a), pc.less(pc.abs(a), 9e18))
                a = pc.if_else(whole, a.cast(pa.int64(), safe=False).cast(pa.string()), a.cast(pa.string()))
            a = a if pa.types.is_string(a.type) else a.cast(pa.string())  # Parquet's own text as it comes: no copy
            try:
                a.validate(full=True)
            except pa.ArrowInvalid:  # bytes stored as text that aren't UTF-8: read one by one, as bytes
                a = a.cast(pa.binary())
        arrays.append(a)
    return arrays


def one_by_one(a: pa.Array) -> list[str | None]:  # a column of bytes or nested values, each as text: nested values as JSON, bytes that aren't UTF-8 as U+FFFD (damaged)
    if pa.types.is_nested(a.type):
        return [None if x is None else json.dumps(x, ensure_ascii=False, default=str) for x in a.to_pylist()]
    return [None if b is None else b.decode("utf-8", "replace") for b in a.cast(pa.large_binary()).to_pylist()]


def chunks(f: Path):  # a Parquet file's columns' names, then its records a chunk of CHUNK rows at a time, by column (texts)
    try:
        pf = pq.ParquetFile(f)
        yield list(pf.schema_arrow.names)
        held, n = [], 0  # a dictionary column's batches end where its row groups do: gathered back into chunks of CHUNK rows
        for batch in pf.iter_batches(batch_size=CHUNK):
            held, n = [*held, batch], n + len(batch)
            while n >= CHUNK:
                whole = held[0] if len(held) == 1 else pa.concat_batches(held)  # one batch of a chunk, as most files come: no copy
                held, n = ([whole.slice(CHUNK)] if n > CHUNK else []), n - CHUNK  # nothing left: nothing held, so the next batch isn't copied
                yield texts(whole.slice(0, CHUNK))
        if n:
            yield texts(pa.concat_batches(held))
    except (OSError, pa.ArrowException) as e:
        raise InputError(f"{f}: can't be read as Parquet ({str(e).splitlines()[0]})", fix="copy it again, or write it again from its source") from None


def names_of(header: list[str]) -> list[str]:  # each column a name of its own: a blank one numbered, a repeat suffixed past every name the header gives, case aside as DuckDB reads names
    given = [CONTROL.sub("", h).strip() or f"column_{i + 1}" for i, h in enumerate(header)]
    names, seen, low = [], set(), {g.casefold() for g in given}
    for base in given:
        name, k = base, 1
        while name.casefold() in seen or (k > 1 and name.casefold() in low):
            k += 1
            name = f"{base}_{k}"
        names.append(name)
        seen.add(name.casefold())
    return names


def read_one(f: Path, out: Path, spec: InputSpec) -> dict:
    """One Parquet file into `out` (Parquet, every column text), and its facts: counts only. O(bytes)."""
    check(f)
    parts = chunks(f)
    header = next(parts)
    names, nulls = names_of(header), frozenset(spec.nulls)
    null_set = pa.array(sorted(nulls), pa.string())
    facts = dict(file=f.name, columns=len(names), rows=0, fixed={}, notes=[])
    if any(h.strip().isdigit() for h in header):  # a column named by a number: more likely a record than names
        facts["notes"].append(f"{f.name}: a column is named by a number, not a name: its header may be missing")
    facts["notes"] += [f"column {x.name} is stored as a number ({x.type}): read as text, but leading zeros (0599) may already be lost upstream"
                       for x in pq.read_schema(f) if pa.types.is_integer(x.type) or pa.types.is_floating(x.type) or pa.types.is_decimal(x.type)]
    count = lambda what, n=1: facts["fixed"].__setitem__(what, facts["fixed"].get(what, 0) + n)
    numbers: list[bool] | None = None  # which columns hold numbers: learned from the first chunk

    def value(v: str | None, j: int) -> str | None:  # one value, with what loses nothing fixed
        if not v:
            return None
        if "�" in v:  # bytes that aren't UTF-8, here or upstream: what they said is gone
            count("damaged")
            return None
        text, fixed = tidy(v, nulls, numbers[j])
        if fixed:
            count(fixed)
        return text

    writer = None
    for arrays in parts:
        if numbers is None:
            numbers = [numeric(a.slice(0, 50_000).to_pylist() if pa.types.is_string(a.type) else one_by_one(a.slice(0, 50_000))) for a in arrays]
        done = []
        for j, a in enumerate(arrays):
            if not pa.types.is_string(a.type):  # bytes, or nested values: one by one
                done.append(pa.array([value(v, j) for v in one_by_one(a)], pa.string()))
                continue
            keep = settled(a, numbers[j], null_set)
            filled = pc.fill_null(pc.greater(pc.binary_length(a), 0), False).to_numpy(zero_copy_only=False)
            slow = np.flatnonzero(filled & ~keep)
            col = pc.if_else(pa.array(keep), a, pa.scalar(None, pa.string()))
            if len(slow):
                got = [value(v, j) for v in a.take(pa.array(slow, pa.int64())).to_pylist()]
                col = pc.replace_with_mask(col, pa.array(filled & ~keep), pa.array(got, pa.string()))
            done.append(col)
        table = pa.table({n: c.cast(pa.string()) for n, c in zip(names, done)})
        if writer is None:
            out.parent.mkdir(parents=True, exist_ok=True)
            writer = pq.ParquetWriter(out, table.schema)
        writer.write_table(table)
        facts["rows"] += table.num_rows
    if writer is None:  # no record: the header alone
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({n: pa.array([], pa.string()) for n in names}), out)
    else:
        writer.close()
    return facts


# ---------- a part: the files given, read ----------

def sha256(f: Path) -> str:
    with open(f, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def take(part: Path, given: dict[Path, str], spec: InputSpec) -> dict:
    """Read every file given (file → its name in the part) into part/read/, and write what was found: intake.json,
    counts only. The report. O(bytes)."""
    t = time.time()
    files = []
    for f, name in given.items():
        rel = Path(name)
        rel = rel if rel.suffix == ".parquet" else rel.with_name(rel.name + ".parquet")
        same = lambda x: x["read"].casefold() == (Path(READ) / rel).as_posix().casefold()  # X.parquet and x.parquet, on a disk that ignores case
        if any(map(same, files)):
            raise InputError(f"{name} and {next(x['given'] for x in files if same(x))} would be read into one file",
                             fix="rename one of them, then give them again")
        files.append(dict(read_one(f, part / READ / rel, spec), given=name, read=(Path(READ) / rel).as_posix()))
    report = dict(files=files, rows=sum(x["rows"] for x in files), fixed=dict(sum((Counter(x["fixed"]) for x in files), Counter())),
                  notes=[n for x in files for n in x["notes"]], seconds=round(time.time() - t, 2))
    part.mkdir(parents=True, exist_ok=True)
    (part / REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def report(part: Path) -> dict | None:  # what the intake found in a part, or None for a path that is no part
    return json.loads((part / REPORT).read_text(encoding="utf-8")) if (part / REPORT).is_file() else None


def part_of(f: Path) -> Path | None:  # the part a read file belongs to
    return next((p for p in f.parents[:4] if (p / REPORT).is_file()), None)


def notes(files: Iterable[Path]) -> list[str]:  # what the intake found in the parts these files were read into: counts only, never a value
    out = []
    for part in dict.fromkeys(filter(None, map(part_of, files))):
        r = report(part)
        fixed = ", ".join(f"{n:,} {k}" for k, n in sorted(r["fixed"].items()))
        out += [*r["notes"], *([f"{part.name}: fixed as read: {fixed}"] if fixed else [])]
    return out
