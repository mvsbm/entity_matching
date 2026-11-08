"""Any records file as it comes, read into one clean Parquet before the door (er.source): the intake.

A CSV or TSV is split on its own bytes (Python's csv over a latin-1 view, which keeps every byte as one character), so
each value, in whatever encoding, survives to be decoded on its own: in the one of [input] encodings it decodes in
strictly, else in its column's. What loses nothing is fixed at once: control bytes, zero-width characters and BOMs
removed, placeholder nulls ([input] nulls) and numbers a spreadsheet cut short (1.23E+11) made missing, 12345.0 read
as 12345. What would be a guess is proposed, and applies once people accept its kind (`nayose accept repairs`):
- realign: a row whose fields don't line up, re-split where every value fits its column;
- garbled: a value a wrong decoding upstream garbled (mojibake), decoded back;
- encoding: a value that several encodings read, read in another than its column's.
Until then a row that doesn't line up is unread, never dropped. A Parquet file's text gets the same fixes.

A part holds what was given, `read/` (what runs read), intake.json (counts only: no value), proposals.parquet and
unread.parquet (the values, which stay in the workspace). The intake is a function of the files given, [input] and
the kinds accepted, so accepting one reads them again. O(bytes) in one pass, in chunks of 200,000 rows.
"""
import csv
import functools
import hashlib
import itertools
import json
import math
import mmap
import os
import re
import shutil
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from er.config import InputError

REPORT, READ, PROPOSALS, UNREAD = "intake.json", "read", "proposals.parquet", "unread.parquet"
SUFFIXES = (".parquet", ".csv", ".tsv", ".txt")  # the records files a folder or an inbox holds
KINDS = ("realign", "garbled", "encoding")
KEEP = 1000  # proposals of each kind kept to show
ODD = 0.1  # past this share of records that don't line up, the file is refused: its delimiter or header is wrong
CHUNK = 200_000  # shortcut: one Python pass, about 15 s a million records; past ~20M rows on one machine, split the file or decode per column in DuckDB
CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‍⁠﻿]")
BREAKS = re.compile("[\t\r\n]+")
WHOLE = re.compile(r"^(-?\d+)\.0+$")  # a whole number a spreadsheet wrote as a float
CUT = re.compile(r"^-?\d(\.\d+)?[eE]\+\d+$")  # a number a spreadsheet wrote in E notation (1.23457E+11, 1E+11): its digits are gone
DELIMITERS = (",", "\t", "|", ";")
HALF, KANJI = re.compile("[\uff61-\uff9f]"), re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# what text of these files is written in: UTF-8 that decodes into anything else may be other bytes it happens to read
JAPANESE = re.compile("[\x00-\x7f\u2000-\u206f\ufeff\u2190-\u23ff\u2460-\u27bf\u3000-\u30ff\u3190-\u33ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]*")
REVERSALS = (("cp932", "utf-8"), ("latin-1", "utf-8"), ("cp1252", "utf-8"), ("latin-1", "cp932"), ("cp1252", "cp932"))


@dataclass(frozen=True)
class InputSpec:  # [input]: how a file is read, before anything else
    encodings: tuple[str, ...] = ("utf-8", "cp932", "euc-jp")
    nulls: tuple[str, ...] = ("NULL", "null", "Null", "\\N", "NaN", "nan", "None", "none", "N/A", "n/a", "#N/A", "-", "－")
    margin_text: float = 0.75  # a value's guess reads at least e^margin likelier per character than what it replaces
    margin_row: float = 4.6    # a row's re-split reads at least e^margin likelier than the next one (100 to 1)
    max_extra: int = 3         # fields a row may hold too many and still be re-split


# ---------- what Japanese text looks like: a character bigram model of the reference names and addresses ----------

@dataclass(frozen=True)
class Model:
    pairs: dict[tuple[str, str], int]
    chars: dict[str, int]
    total: int
    garbled: frozenset[str]   # characters a wrong decoding makes of the reference's own, which it never holds


@functools.lru_cache(maxsize=2)
def model(folder: Path) -> Model:
    texts = []
    for name, keys in (("individual.json", ("surname", "given", "surname_kana", "given_kana")), ("companies.json", ("name", "name_kana")),
                       ("addresses.json", ("pref", "city", "town", "pref_kana", "city_kana", "town_kana")), ("registry.json", ("reading",))):
        if (folder / name).is_file():
            texts += [str(r[k]) for r in json.loads((folder / name).read_text(encoding="utf-8")) for k in keys if r.get(k)]
    texts = list(dict.fromkeys(texts))
    chars = Counter(ch for t in texts for ch in t)
    pairs = Counter((a, b) for t in texts for a, b in zip("^" + t, t + "$"))
    garbled = set()
    for t in texts[::7]:  # a sample of the texts, as a wrong decoding would see them
        raw = t.encode("utf-8")
        garbled |= set(raw.decode("cp932", "ignore")) | set(raw.decode("latin-1"))
    real = lambda c: c in chars or c.isascii() or "\u3000" <= c <= "\u303f" or "\uff00" <= c <= "\uffef"  # width forms and CJK punctuation: real files hold them
    return Model(dict(pairs), dict(chars), sum(chars.values()), frozenset(c for c in garbled if not real(c)))


def plausible(text: str, m: Model) -> float:
    """Mean log-probability per character, the next given the one before, of the text as its width forms fold
    (half-width ｱｲｳ as アイウ); a text that mixes half-width kana with kanji stays as it is, since only a wrong decoding
    writes that."""
    if not (HALF.search(text) and KANJI.search(text)):
        text = unicodedata.normalize("NFKC", text)
    v = len(m.chars) + 1
    score = 0.0
    for a, b in zip("^" + text, text + "$"):
        uni = (m.chars.get(b, 0) + 1) / (m.total + v)
        bi = (m.pairs.get((a, b), 0) + 1) / (m.chars.get(a, m.total if a == "^" else 0) + v)
        score += math.log(0.95 * bi + 0.05 * uni)  # a pair the reference never holds counts heavily against
    return score / (len(text) + 1)


def ungarbled(text: str, m: Model, margin: float) -> str | None:  # a garbled value decoded back, when one reversal reads far likelier
    base, best = plausible(text, m), None
    for wrong, right in REVERSALS:
        try:
            back = text.encode(wrong).decode(right)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if back != text and not any(ch in m.garbled for ch in back) and (s := plausible(back, m)) - base >= margin and (best is None or s > best[0]):
            best = (s, back)
    return best[1] if best else None


# ---------- one value: its decodings, and what loses nothing ----------

def decodings(v: str, order: tuple[str, ...]) -> list[tuple[str, str]]:  # each encoding a value's bytes decode in strictly
    if v.isascii():
        return [("ascii", v)]
    raw, found = v.encode("latin-1"), []
    for e in order:
        try:
            found.append((e, raw.decode(e)))
        except UnicodeDecodeError:
            pass
    return found


def tidy(v: str | None, nulls: frozenset[str], numeric: bool) -> tuple[str | None, str | None]:  # the value, and what was fixed
    if v is None:
        return None, None
    fixed = None
    if not v.isprintable():
        w = BREAKS.sub(" ", CONTROL.sub("", v))
        fixed, v = ("controls" if w != v else None), w
    s = v.strip(" 　")
    if s in nulls:
        return None, "placeholders"
    if numeric and ("." in s or "e" in s or "E" in s):
        if m := WHOLE.match(s):
            return m.group(1), "numbers"
        if CUT.match(s):
            return None, "numbers"
    return v, fixed


def classes(v: str) -> tuple[frozenset[str], int]:  # the character classes a value holds, and its length class
    held = set()
    for ch in v[:60]:
        held.add("d" if "0" <= ch <= "9" else "D" if ch.isdigit() else "a" if ch.isascii() and ch.isalpha() else "k" if "ァ" <= ch <= "ヺ" or ch == "ー"
                 else "h" if "ぁ" <= ch <= "ゖ" else "n" if "ｦ" <= ch <= "ﾟ" else "c" if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" else "s" if ch.isspace() else "p")
    return frozenset(held), min(len(v).bit_length(), 7)


CLASSES = "dDakhncsp"


def learn(profile: Counter, v: str | None) -> None:  # one value of a column, counted: empty or not, each class it holds, its length class
    profile["rows"] += 1
    if not v:
        profile["empty"] += 1
        return
    held, length = classes(v)
    profile.update(held)
    profile[("len", length)] += 1


def fits(profile: Counter, v: str | None) -> float:  # how likely a column holds the value: each class held or not, and its length (log)
    n, empty = profile["rows"], profile["empty"]
    if not v:
        return math.log((empty + 1) / (n + 2))
    filled, (held, length) = n - empty, classes(v)
    score = math.log((filled + 1) / (n + 2)) + math.log((profile[("len", length)] + 1) / (filled + 8))
    for c in CLASSES:
        p = (profile[c] + 1) / (filled + 2)
        score += math.log(p if c in held else 1 - p)
    return score


# ---------- a file as rows of text ----------

def parquet(f: Path, head: bytes, tail: bytes) -> bool:  # whether the file is Parquet, by its first and last bytes; one cut short is refused
    if head[:4] != b"PAR1":
        return False
    if tail != b"PAR1":
        raise InputError(f"{f}: a Parquet file cut short (it doesn't end as Parquet does)", fix="copy it again, or write it again from its source")
    return True


def sniff(f: Path) -> tuple[str, str | None, bool]:  # (format, its delimiter, whether it quotes): by the bytes, never the name
    with f.open("rb") as h:
        head = h.read(1 << 20)
        h.seek(max(0, f.stat().st_size - 4))
        tail = h.read(4)
    if parquet(f, head, tail):
        return "parquet", None, False
    if head[:2] == b"PK":
        raise InputError(f"{f}: a ZIP or Excel file, not records", fix="save it as CSV (UTF-8 or Shift-JIS) or Parquet, and give that")
    if head[:2] == b"\x1f\x8b":
        raise InputError(f"{f}: a gzip file", fix=f"decompress it first (gunzip {f.name}), then give the file inside")
    wide = (("utf-16" if head[:2] in (b"\xff\xfe", b"\xfe\xff") else  # UTF-16: by its BOM, or without one by where its NULs fall
             "utf-16-le" if head[1:4096:2].count(0) > 0.3 * len(head[1:4096:2]) > 0 and head[0:4096:2].count(0) < 0.05 * len(head[0:4096:2]) else
             "utf-16-be" if head[0:4096:2].count(0) > 0.3 * len(head[0:4096:2]) > 0 and head[1:4096:2].count(0) < 0.05 * len(head[1:4096:2]) else
             "iso2022_jp" if re.search(rb"\x1b\$[@B]", head) else None))  # JIS: Japanese in seven bits, a comma among them, so decoded whole first
    text = head.decode(wide, "ignore") if wide else head.decode("latin-1")
    lines = [x for x in text.splitlines()[:50] if x.strip()]
    if not lines:
        raise InputError(f"{f}: empty", fix="give a file with a header line and records")
    def steady(d: str) -> tuple[float, int]:  # how many lines share the most common count of d, and that count
        counts = Counter(x.count(d) for x in lines)
        n, share = counts.most_common(1)[0]
        return (share / len(lines) if n else 0.0, n)
    d = max(DELIMITERS, key=steady)
    d = d if steady(d)[1] else ","
    lines = head.splitlines()[:-1] if len(head) == 1 << 20 else head.splitlines()  # whole lines, however they end: the last cut off when the head was
    foreign = [x for x in lines if not x.isascii()]
    not_utf8 = [x for x in foreign if _fails(x, "utf-8")]
    cp932 = sum(not _fails(x, "cp932") and _fails(x, "euc-jp") for x in not_utf8)  # UTF-8 and EUC-JP read as CP932 too; CP932's kana and kanji leads are no EUC-JP's
    if not wide and d == "|" and len(not_utf8) > len(foreign) / 2 and cp932 >= 0.9 * len(not_utf8):
        wide = "cp932"  # | is the second byte of some CP932 characters (ポ is 83 7C): a file mostly in CP932 is decoded first; any other is read by value
    return (wide or "csv"), d, quoted(f, d, wide)


def _fails(raw: bytes, enc: str) -> bool:
    try:
        raw.decode(enc)
        return False
    except UnicodeDecodeError:
        return True


def quoted(f: Path, d: str, wide: str | None) -> bool:
    """Whether the file quotes its values: a value anywhere in it opens and closes with a quote, the quotes inside
    doubled. A file that never does reads a quote as text, so a stray one (\"Beppu) splits nothing. O(bytes), in C."""
    e = re.escape(d)
    pattern = f'(?:^|(?<=\r)|{e})"(?:[^"]|"")*"(?={e}|\r|$)'  # a line ends in \n, \r\n or \r alone
    if wide:  # decoded as it will be read, in blocks of whole lines: a quoted value may hold a line break
        found, rest = re.compile(pattern, re.M), ""
        with f.open(encoding=wide, errors="replace", newline="") as h:
            while block := h.read(1 << 22):
                text = rest + block
                end = max(text.rfind("\n"), text.rfind("\r")) + 1
                if found.search(text[:end]):
                    return True
                rest = text[end:]
        return bool(found.search(rest))
    if f.stat().st_size == 0:
        return False
    with f.open("rb") as h, mmap.mmap(h.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        return bool(re.search(pattern.encode(), mm, re.M))


def view(x: str | None) -> str | None:  # real text as the latin-1 view of its UTF-8 bytes, as a CSV's fields come
    return x if x is None or x.isascii() else x.encode("utf-8").decode("latin-1")


def text_rows(f: Path, fmt: str, delimiter: str, quotes: bool):  # (line, fields) of a text file; fields hold bytes as latin-1 characters
    csv.field_size_limit(sys.maxsize)
    if fmt != "csv":  # an encoding of the whole file (UTF-16, JIS): decoded first
        h = f.open(encoding=fmt, errors="replace", newline="")
    else:
        h = f.open(encoding="latin-1", newline="")
        if h.read(3) != "ï»¿":  # a UTF-8 BOM
            h.seek(0)
    with h:
        reader = csv.reader(h, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL if quotes else csv.QUOTE_NONE, strict=False)
        for fields in reader:
            if fields:  # a file decoded whole: as the bytes of its UTF-8, so every file reads alike from here
                yield reader.line_num, [view(x) for x in fields] if fmt != "csv" else fields


def parquet_rows(f: Path):  # (line, fields) of a Parquet file: text as its bytes (latin-1 characters), the rest as text
    try:
        pf = pq.ParquetFile(f)
        yield 0, [view(n) for n in pf.schema_arrow.names]
        line = 0
        for batch in pf.iter_batches(batch_size=CHUNK):
            cols = []
            for a in batch.columns:
                if pa.types.is_dictionary(a.type):
                    a = a.dictionary_decode()
                t = a.type
                if pa.types.is_string(t) or pa.types.is_large_string(t) or pa.types.is_binary(t) or pa.types.is_large_binary(t):
                    cols.append([None if b is None else b.decode("latin-1") for b in a.cast(pa.large_binary()).to_pylist()])
                elif pa.types.is_nested(t):
                    cols.append([None if x is None else view(json.dumps(x, ensure_ascii=False, default=str)) for x in a.to_pylist()])
                else:
                    cols.append([view(x) for x in a.cast(pa.string()).to_pylist()])
            for row in zip(*cols):
                line += 1
                yield line, list(row)
    except (OSError, pa.ArrowException) as e:
        raise InputError(f"{f}: can't be read as Parquet ({str(e).splitlines()[0]})", fix="copy it again, or write it again from its source") from None


# ---------- one file read ----------

def read_one(f: Path, out: Path, spec: InputSpec, m: Model, accepted: frozenset[str], strict: bool) -> tuple[dict, list[dict], list[dict]]:
    """One file into `out` (Parquet, every column text): its facts (counts only), its proposals, its unread rows."""
    fmt, delimiter, quotes = sniff(f)
    rows = parquet_rows(f) if fmt == "parquet" else text_rows(f, fmt, delimiter, quotes)
    try:
        lines = [next(rows), *(itertools.islice(rows, 20) if fmt != "parquet" else ())]
        wide = Counter(len(x) for _, x in lines[1:]).most_common(1)[0][0] if len(lines) > 1 else len(lines[0][1])
        k = next((i for i, (_, x) in enumerate(lines[:10]) if len(x) > wide / 2), 0)  # a title line above the header, far narrower, is skipped, and said
        above, header = lines[:k], lines[k][1]
        trailing = sum(len(x) == len(header) + 1 and not x[-1] for _, x in lines[k + 1:]) > len(lines[k + 1:]) / 2  # a writer that ends every record with a delimiter
        rows = itertools.chain(lines[k + 1:], rows)
    except StopIteration:
        raise InputError(f"{f}: empty", fix="give a file with a header line and records") from None
    given = [CONTROL.sub("", (decodings(h, spec.encodings) or [("", "")])[0][1]).strip() or f"column_{i + 1}" for i, h in enumerate(header)]
    names: list[str] = []
    for base in given:  # each column a name of its own: a blank one numbered, a repeat suffixed past every name the header gives
        name, k = base, 1
        while name in names or (k > 1 and name in given):
            k += 1
            name = f"{base}_{k}"
        names.append(name)
    width, nulls = len(names), frozenset(spec.nulls)
    facts = dict(file=f.name, format=fmt, delimiter=delimiter, quotes=quotes, columns=width, rows=0, decoded={}, fixed={}, proposed={}, unread=0, notes=[])
    if above:
        facts["notes"].append(f"{f.name}: {len(above)} line{'s' if len(above) > 1 else ''} above the header skipped")
    if any(h.strip().isdigit() for h in header):  # a column named by a number: more likely a record than names
        facts["notes"].append(f"{f.name}: its first line holds numbers, not names: a header may be missing")
    if fmt == "parquet":
        facts["notes"] += [f"column {x.name} is stored as a number ({x.type}): read as text, but leading zeros (0599) may already be lost upstream"
                          for x in pq.read_schema(f) if pa.types.is_integer(x.type) or pa.types.is_floating(x.type) or pa.types.is_decimal(x.type)]
    proposals, unread, odd = [], [], []
    majority: list[str | None] = [None] * width
    numeric = [False] * width
    profile: list[Counter] = [Counter() for _ in range(width)]
    count = lambda key, what, n=1: facts[key].__setitem__(what, facts[key].get(what, 0) + n)
    def propose(p: dict) -> None:  # every proposal counted; the first KEEP of each kind kept, to see (accepting reads the file again)
        count("proposed", p["kind"])
        if facts["proposed"][p["kind"]] <= KEEP:
            proposals.append(p)
    def lined_up(seen: int) -> None:  # past 1,000 and a tenth of the records read, the delimiter or the header is wrong
        if len(odd) > 1000 and len(odd) > ODD * seen:
            raise InputError(f"{f}: {len(odd):,} of its first {seen:,} records don't line up with its header ({width} columns)",
                             fix="check its delimiter and its header line, then give it again")
    writer = None
    def value(j: int, v: str | None, line: int) -> str | None:  # one field: decoded, then what loses nothing
        if not v:
            return None
        if "\xef\xbf\xbd" in v:  # U+FFFD: bytes the file's encoding can't decode (a file decoded whole), or damage upstream
            count("fixed", "damaged")
            return None
        if not v.isascii() and spec.encodings[0] == "utf-8":  # most text: UTF-8, with nothing a wrong decoding makes
            try:
                text = v.encode("latin-1").decode("utf-8")
                if JAPANESE.fullmatch(text) and m.garbled.isdisjoint(text):
                    count("decoded", "utf-8")
                    text, fixed = tidy(text, nulls, numeric[j])
                    if fixed:
                        count("fixed", fixed)
                    return text
            except UnicodeDecodeError:
                pass
        found = decodings(v, spec.encodings)
        if not found:
            count("fixed", "damaged")
            return None
        # UTF-8 that decodes strictly into Japanese text is UTF-8: other bytes almost never do, though UTF-8 is often
        # valid CP932 too. Among the rest, the column's own encoding, and another that reads far likelier is proposed.
        sure = found[0][0] == "ascii" or (found[0][0] == "utf-8" and bool(JAPANESE.fullmatch(found[0][1])) and m.garbled.isdisjoint(found[0][1]))
        enc, text = found[0] if sure or len(found) == 1 else next(((e, t) for e, t in found if e == majority[j]), found[0])
        if not sure and len(found) > 1:  # each reading judged as text, and by what its column holds (its profile)
            judge = lambda t: plausible(t, m) * (len(t) + 1) + fits(profile[j], t)
            best = max(found, key=lambda x: judge(x[1]))
            if best[0] != enc and (judge(best[1]) - judge(text)) / (len(text) + 1) >= spec.margin_text:
                propose(dict(kind="encoding", line=line, column=names[j], before=text, after=best[1]))
                if "encoding" in accepted:
                    enc, text = best
        if enc != "ascii":
            count("decoded", enc)
        if not text.isascii() and not m.garbled.isdisjoint(text) and (back := ungarbled(text, m, spec.margin_text)):
            propose(dict(kind="garbled", line=line, column=names[j], before=text, after=back))
            if "garbled" in accepted:
                text = back
        text, fixed = tidy(text, nulls, numeric[j])
        if fixed:
            count("fixed", fixed)
        return text
    def write(cols: list[list[str | None]]) -> None:
        nonlocal writer
        table = pa.table({n: pa.array(c, pa.string()) for n, c in zip(names, cols)})
        if writer is None:
            out.parent.mkdir(parents=True, exist_ok=True)
            writer = pq.ParquetWriter(out, table.schema)
        writer.write_table(table)
    block: list[tuple[int, list]] = []
    def flush(first: bool) -> None:
        lines = [line for line, _ in block]
        cols = list(zip(*(r for _, r in block))) if block else [()] * width
        done = []
        encs = [Counter() for _ in cols]
        for j, col in enumerate(cols if first else ()):  # the first chunk learns each column from the values it reads for sure: what they look like, their encoding, whether they are numbers
            for k, v in enumerate(col):
                found = [("ascii", v)] if not v or v.isascii() else decodings(v, spec.encodings)
                if len(found) == 1 and found[0][0] not in ("ascii", "utf-8"):
                    encs[j][found[0][0]] += 1
                if k < 50_000 and found and (len(found) == 1 or (found[0][0] == "utf-8" and JAPANESE.fullmatch(found[0][1]))):
                    learn(profile[j], found[0][1] or None)
            vals = [x for v in col[:50_000] if v and (x := v.strip())]
            numeric[j] = bool(vals) and sum(x.replace(".", "", 1).replace("E+", "").replace("e+", "").lstrip("-").isdigit() for x in vals) >= 0.5 * len(vals)
        if first:  # a column's own encoding, else the file's: a column whose values no other encoding rules out reads as the rest of the file
            whole = sum(encs, Counter())
            for j, e in enumerate(encs):
                majority[j] = (e or whole).most_common(1)[0][0] if (e or whole) else None
        for j, col in enumerate(cols):
            num = numeric[j]
            done.append([None if not v else v if v.isascii() and v.isprintable() and v[0] != " " and v[-1] != " " and v not in nulls
                         and not (num and ("." in v or "e" in v or "E" in v)) else value(j, v, line) for v, line in zip(col, lines)])  # most values: as they are
        write(done)
        facts["rows"] += len(lines)
    for line, fields in rows:
        if trailing and len(fields) == width + 1 and not fields[-1]:  # the delimiter its writer ends records with: an empty field, nothing lost
            fields = fields[:-1]
        if len(fields) == width:
            block.append((line, fields))
            if len(block) == CHUNK:
                flush(writer is None)
                block = []
        else:
            odd.append((line, fields))
            if len(odd) > 1000 and (seen := facts["rows"] + len(block) + len(odd)) >= CHUNK:  # judged on a chunk at least: a few bad rows at the top refuse nothing
                lined_up(seen)
    lined_up(facts["rows"] + len(block) + len(odd))
    if block or writer is None:
        flush(writer is None)
    realigned = realign(odd, width, profile, delimiter or ",", spec)
    taken = []  # rows people's accepted realignment reads
    shown = lambda x: (decodings(x, spec.encodings) or [("", x)])[0][1]  # a field as people read it, in a proposal
    for (line, fields), fit in zip(odd, realigned):
        if not fields:  # joined into the row before it
            continue
        raw = (delimiter or ",").join(x or "" for x in fields)
        if fit is None:
            unread.append(dict(line=line, raw=raw.encode("latin-1", "replace"),
                               reason=f"{len(fields)} fields where the header has {width}"))
            facts["unread"] += 1
            continue
        joined, row = fit
        propose(dict(kind="realign", line=line, column=", ".join(names[j] for j in joined), before=shown(raw),
                              after=" | ".join(shown(row[j] or "") for j in joined)))
        if "realign" in accepted:
            taken.append([value(j, v, line) for j, v in enumerate(row)])
        else:
            unread.append(dict(line=line, raw=raw.encode("latin-1", "replace"),
                               reason="its fields don't line up: a repair waits (accept repairs realign)"))
            facts["unread"] += 1
    if taken:
        write([list(c) for c in zip(*taken)])
        facts["rows"] += len(taken)
    writer.close()
    if strict and (proposals or unread):
        first = (proposals or unread)[0]
        raise InputError(f"{f}: line {first['line']}: {'its fields do not line up' if first in unread else 'a value needs a repair'}",
                         fix="write the file again, one value per column, in one encoding")
    return facts, [dict(p, file=f.name) for p in proposals], [dict(u, file=f.name) for u in unread]


def realign(odd: list[tuple[int, list]], width: int, profile: list[Counter], delimiter: str, spec: InputSpec) -> list[tuple[list[int], list] | None]:
    """Each row that doesn't line up, re-split if one reading fits its columns far better than any other: too many
    fields, adjacent ones joined back (the delimiter was in a value); too few, joined with the next short row when the
    two make one (a line break was in a value). (the columns joined, the row) or None. O(rows · width · C(width + extra − 1, extra)):
    every way of joining the extra fields is tried, which [input] max_extra keeps small."""
    decode = lambda x: (decodings(x, spec.encodings) or [("", x)])[0][1] if x else x
    out: list = [None] * len(odd)
    i = 0
    while i < len(odd):
        line, fields = odd[i]
        extra = len(fields) - width
        if 0 < extra <= spec.max_extra:
            text = [decode(x) for x in fields]
            span = {}  # (column, first field, fields): the column's score for those fields joined
            for j in range(width):
                for s in range(j, j + extra + 1):
                    for t in range(1, extra + 2):
                        if s + t <= len(fields):
                            span[j, s, t] = fits(profile[j], delimiter.join(text[s:s + t]))
            readings = []
            for gaps in itertools.combinations(range(len(fields) - 1), extra):  # which gaps were the delimiter inside a value
                starts = [0] + [g + 1 for g in range(len(fields) - 1) if g not in gaps]
                bounds = list(zip(starts, starts[1:] + [len(fields)]))
                readings.append((sum(span[j, s, e - s] for j, (s, e) in enumerate(bounds)), bounds))
            readings.sort(key=lambda x: -x[0])
            if len(readings) == 1 or readings[0][0] - readings[1][0] >= spec.margin_row:
                bounds = readings[0][1]
                out[i] = ([j for j, (s, e) in enumerate(bounds) if e - s > 1], [delimiter.join(fields[s:e]) for s, e in bounds])
        elif extra < 0 and i + 1 < len(odd) and odd[i + 1][0] == line + 1 and len(fields) + len(odd[i + 1][1]) - 1 == width:
            nxt = odd[i + 1][1]
            row = fields[:-1] + [fields[-1] + " " + nxt[0]] + nxt[1:]
            out[i] = ([len(fields) - 1], row)
            odd[i + 1] = (odd[i + 1][0], [])  # its fields went into the row before
            i += 1
        i += 1
    return out


# ---------- a part: every file given, read ----------

def sha256(f: Path) -> str:
    with open(f, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def take(part: Path, given: dict[Path, str], spec: InputSpec, reference: Path, accepted: frozenset[str] = frozenset(), strict: bool = False) -> dict:
    """Read every file given (file → its name in the part) into part/read/, and write what was found: intake.json,
    proposals.parquet, unread.parquet. Read again (with more kinds accepted), each read file keeps the SHA-256 of what
    it replaced, so a run that read the earlier one still finds its file (er.folder.inputs). The report. O(bytes)."""
    t, m = time.time(), model(reference)
    old = json.loads((part / REPORT).read_text(encoding="utf-8")) if (part / REPORT).is_file() else {}
    before = {x["read"]: x.get("versions", []) for x in old.get("files", [])}
    tmp = part / ".read.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    files, proposals, unread = [], [], []
    for f, name in given.items():
        rel = Path(name)
        rel = rel if rel.suffix == ".parquet" else rel.with_name(rel.name + ".parquet")
        facts, p, u = read_one(f, tmp / READ / rel, spec, m, accepted, strict)
        sha = sha256(tmp / READ / rel)
        files.append(dict(facts, given=name, read=(Path(READ) / rel).as_posix(), sha256=sha,
                          versions=list(dict.fromkeys([*before.get((Path(READ) / rel).as_posix(), []), sha]))))
        proposals += p
        unread += u
    pq.write_table(pa.Table.from_pylist(proposals, pa.schema([("kind", pa.string()), ("file", pa.string()), ("line", pa.int64()), ("column", pa.string()),
                                                               ("before", pa.string()), ("after", pa.string())])), tmp / PROPOSALS)
    pq.write_table(pa.Table.from_pylist(unread, pa.schema([("file", pa.string()), ("line", pa.int64()), ("raw", pa.binary()), ("reason", pa.string())])), tmp / UNREAD)
    total = lambda key: dict(sum((Counter(x[key]) for x in files), Counter()))
    report = dict(files=files, rows=sum(x["rows"] for x in files), decoded=total("decoded"), fixed=total("fixed"), proposed=total("proposed"),
                  unread=sum(x["unread"] for x in files), accepted=sorted(accepted), notes=[n for x in files for n in x["notes"]],
                  seconds=round(time.time() - t, 2))
    (tmp / REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    gone = part / ".read.old"
    shutil.rmtree(gone, ignore_errors=True)
    if (part / READ).exists():
        os.replace(part / READ, gone)
    os.replace(tmp / READ, part / READ)
    shutil.rmtree(gone, ignore_errors=True)
    for name in (PROPOSALS, UNREAD, REPORT):  # the report last: a part with a report is whole
        os.replace(tmp / name, part / name)
    shutil.rmtree(tmp, ignore_errors=True)
    return report


def report(part: Path) -> dict | None:  # what the intake found in a part, or None for a path that is no part
    return json.loads((part / REPORT).read_text(encoding="utf-8")) if (part / REPORT).is_file() else None


def accept(part: Path, kind: str, spec: InputSpec, reference: Path) -> dict:  # the part read again, one more kind of repair accepted
    r = report(part)
    return take(part, {part / x["given"]: x["given"] for x in r["files"]}, spec, reference, frozenset(r["accepted"]) | {kind})


def part_of(f: Path) -> Path | None:  # the part a read file belongs to
    return next((p for p in f.parents[:4] if (p / REPORT).is_file()), None)


def notes(files: list[Path]) -> list[str]:  # what the intake found in the parts these files were read into: counts only, never a value
    out = []
    for part in dict.fromkeys(filter(None, map(part_of, files))):
        r = report(part)
        fixed = ", ".join(f"{n:,} {k}" for k, n in sorted(r["fixed"].items()))
        waiting = ", ".join(f"{n:,} {k}" for k, n in sorted(r["proposed"].items()) if k not in r["accepted"])
        out += [*r["notes"], *([f"{part.name}: fixed as read: {fixed}"] if fixed else []),
                *([f"{part.name}: repairs waiting (accept repairs): {waiting}"] if waiting else []),
                *([f"{part.name}: {r['unread']:,} rows unread (unread.parquet)"] if r["unread"] else [])]
    return out


def examples(part: Path, most: int = 20) -> dict[str, list[dict]]:  # each kind's proposals, the first `most`, and the unread rows
    p = pq.read_table(part / PROPOSALS).to_pylist() if (part / PROPOSALS).is_file() else []
    u = pq.read_table(part / UNREAD).to_pylist() if (part / UNREAD).is_file() else []
    out = {k: [x for x in p if x["kind"] == k][:most] for k in KINDS}
    out["unread"] = [dict(file=x["file"], line=x["line"], reason=x["reason"], raw=(decodings(x["raw"].decode("latin-1"), InputSpec().encodings) or [("", x["raw"].decode("utf-8", "replace"))])[0][1])
                     for x in u[:most]]  # its bytes read as a value is
    return {k: v for k, v in out.items() if v}
