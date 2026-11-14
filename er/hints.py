"""A file's columns as people map them: a path read as the door reads it (readable), what the reader found
(read_of), and what each slot's sampled values say is off, with what sets it right (hints). A workspace part's
description is kept with it (KEPT), made again when the code it comes from changes (DESCRIBING)."""
from __future__ import annotations
import contextlib
import functools
import hashlib
import re
import tempfile
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pandas as pd

from er import folder, intake
from er.brief import WARN, nayose
from er.config import InputError, q
from er.emit import rows_told
from er.settings import names_by_kind, slots
from er.source import filled, find
from er.standardize import SEPARATORS

if TYPE_CHECKING:
    from er.emit import Emit


FLAG = r"^\s*\S{1,6}\s*$"  # what a person/company flag's values look like, a short code (1, P, 法人, PERSON), padded or not: to warn of a wrong column, never to suggest one
SLOT_FIELD = {"person name": "person_name", "family": "person_name", "given": "given_name", "company name": "company_name"}  # a slot without a field of its own: whose pattern its values should match


@contextlib.contextmanager
def readable(path: str, s, strict: bool = False, emit: "Emit | None" = None):
    """A path as the door reads it: a workspace's part, as its intake read it (read again first if an older reader
    read it: folder.fresh); any other file or files, read for this command alone into a folder that goes once it ends
    (er.intake); people's files strictly: one that needs a repair is refused."""
    p = Path(path).expanduser()
    if p.is_dir() and intake.report(p):
        yield str(folder.fresh(p, s.input, s.paths["reference"], rows_told(emit)))
        return
    files, root = find(path), p if p.is_dir() else None
    with tempfile.TemporaryDirectory(prefix="nayose-", ignore_cleanup_errors=True) as t:  # Windows: a file DuckDB still holds can't go yet
        named = {f: (f.relative_to(root) if root else Path(f.name)).as_posix() for f in files}
        back = [*((str(Path(t) / (x["read"])), str(f)) for f, x in zip(named, intake.take(Path(t), named, s.input, s.paths["reference"], strict=strict)["files"])), (t, str(path))]
        try:
            yield t
        except InputError as e:  # said of the files people gave, not of the folder they were read into
            say = lambda text: functools.reduce(lambda x, pair: x.replace(*pair), back, text)
            raise InputError(say(str(e)), say(e.fix), e.hints) from None


def read_of(part: Path) -> dict | None:  # what the reader found in a part: counts, the repairs waiting with their first examples, rows unread
    if not (r := intake.report(part)):
        return None
    return dict(part=part.name, rows=r["rows"], decoded=r["decoded"], fixed=r["fixed"], proposed=r["proposed"], accepted=r["accepted"],
                waiting={k: n for k, n in r["proposed"].items() if k not in r["accepted"]}, unread=r["unread"], seconds=r["seconds"],
                examples=intake.examples(part))


KEPT = "described.json"  # a part's description, kept with it: one, replaced when what it rests on changes


# the code a description comes from, as it was when this process started, with the libraries it leans on (DuckDB's
# sample, Python's Unicode tables): a description made by other code is made again
DESCRIBING = hashlib.sha256(b"".join([*((Path(__file__).parent / f).read_bytes() for f in ("cli.py", "hints.py", "emit.py", "brief.py", "source.py", "settings.py", "intake.py", "config.py")),
                                      duckdb.__version__.encode(), unicodedata.unidata_version.encode()])).hexdigest()



WRITTEN = (("strip_separators", re.compile(f"{SEPARATORS}|[０-９]"), ("phone", "postal_code", "customer_id"), "with separators or full-width digits"),
           ("katakana", re.compile("[\u3041-\u3096]"), None, "in hiragana"))  # a step, what it prepares as one, the fields it is for (None: names), in words


def prepared_one_way(col: str, fld: str | None, prep: dict, sampled: Callable[[str], list[str]], there: list[str]) -> dict | None:
    """The hint that a column's sampled values are written two ways that a step would prepare as one, with the step added
    to every field that reads the column and lacks it (after nfkc), or None. O(sampled values)."""
    for step, pattern, fields, how in WRITTEN:
        ok = (lambda f: f in fields) if fields else (lambda f: f.rstrip("_0123456789").endswith("name"))  # person_name_2, a feature added
        lack = [x for x in prep.values() if ok(x.name) and step not in x.normalize and any(col in alt for alt in x.sources)]
        if not lack or not (fld is None or ok(fld)):
            continue
        values = sampled(col)
        if not 0 < len(odd := [v for v in values if pattern.search(v)]) < len(values):  # written both ways in the file; one way throughout matches itself
            continue
        steps = lambda d: [*(s := list(d.normalize) if "nfkc" in d.normalize else ["nfkc", *d.normalize])[:s.index("nfkc") + 1], step, *s[s.index("nfkc") + 1:]]
        mapping = [f"{x.name}={','.join(steps(x))}" for x in lack]
        return dict(level="warn", says=f"{len(odd):,} of {len(values):,} sampled written {how}: the same value written two ways won't match",
                    example=odd[0], fix="read them as one", act="prepare", prepare=mapping, button="Read as one",
                    command=nayose("set", "preparation", *mapping, *there) if there else None)
    return None


def hints(d: dict, con, s, p, feats: list[dict], ws: str | None, field_of: Callable[[str, dict], str | None]) -> dict[str, dict]:
    """What each slot's sampled values say is off, and what sets it right (a note to act on, never applied by itself),
    the first that holds, by slot path:
    - a name slot holding the other kind's names (the name model, and legal forms, on the sample): compare each
      record's name on its own side (set names by-kind); so set already, said as info;
    - a birth date written more than one way (its shapes, digits as 9; once separators go, when the field drops them):
      the same date won't match;
    - values that look right, written two ways that a step would prepare as one (WRITTEN: 03-1234-5678 beside
      0312345678, a name in hiragana) where the fields reading the column lack it: set preparation, the step added to each;
    - values that look like one other field: read the column there, the target's own columns kept after it, or take
      it off when that field reads it already (set feature);
    - else how few look right, with one that doesn't.
    A slot read from columns joined is judged whole: no one column of it is moved or named. Each: level (warn, info),
    says (no record's value: check records' warnings reach reports), fix; a value that doesn't look right (example);
    with a fix to apply, act (names; move, to and column; off and column), the page's button, and with a workspace the
    command. O(slots + the sample's names)."""
    from er.kind import legal, name_model, text as name_text
    slot, paths, there, by_kind = {x["feature"]: x for x in d["slots"]}, list(slots(feats)), (["--workspace", ws] if ws else []), names_by_kind(s)
    try:
        model = name_model(s, p.kind) if p.kind else None
    except InputError:  # no name model here: the other notes still hold
        model = None
    found = lambda e: [alt["columns"] for alt in e.get("alternatives") or [] if alt.get("found")]
    prep = {d.name: d for d in s.standardize.derived}
    sampled = lambda col: [v for (v,) in con.execute(f"SELECT {q(col)} FROM er_described WHERE {filled(col)}").fetchall()]
    alts = lambda e, col: ",".join("+".join(alt) for alt in e["sources"] if alt != [col])  # a slot's other alternatives, as set feature writes them
    out = {}
    for path, x in paths:
        e, fld = slot[path], field_of(path, x)
        if not e.get("filled") or not (first := next(iter(found(e)), None)):
            continue
        col, side = first[0] if len(first) == 1 else None, "company" if fld == "company_name" else "person" if x.get("type") == "person name" and fld else None
        if side and model and col:
            names = pd.Series(sampled(col), dtype="string")
            company = (model.logit(name_text(names, s.standardize)) >= 0) | legal(names, s.standardize)
            other = float((~company if side == "company" else company).mean()) if len(names) else 0.0
            if other >= 0.2:
                whose = "people's names" if side == "company" else "company names"
                out[path] = (dict(level="info", says=f"{whose} too ({other:.0%}): each compared on its own side", fix=None) if by_kind else
                             dict(level="warn", says=f"mostly {whose} ({other:.0%})" if other >= 0.5 else f"{whose} too ({other:.0%})",
                                  fix="compare each record's name on its own side, by its kind", act="names", button="Compare by kind",
                                  command=nayose("set", "names", "by-kind", *there) if ws else None))
                continue
        if fld == "birth_date" and col:  # 1993-05-25 beside 93-05-25: equal dates, unequal strings
            gone = "strip_separators" in (prep[fld].normalize if fld in prep else ())  # prepared without them: they make no other way
            shape = lambda v: re.sub(r"\d", "9", re.sub(SEPARATORS, "", v) if gone else v)
            written = pd.DataFrame({"as": [re.sub(r"\d", "9", v.strip()) for v in sampled(col)], "is": [shape(v.strip()) for v in sampled(col)]})
            shapes = written["is"].value_counts(normalize=True)
            if len(ways := shapes[shapes >= 0.05]) > 1:
                shown = [written.loc[written["is"] == w, "as"].mode()[0] for w in ways.index[:3]]  # each way as it is written
                out[path] = dict(level="warn", says=f"written {len(ways)} ways ({', '.join(shown)}): the same date written two ways won't match",
                                 fix="write every date one way in the file")
                continue
        looks = e.get("looks_right")
        if col and (looks is None or looks >= WARN) and (said := prepared_one_way(col, fld, prep, sampled, there)):  # values of the field: a step reads them as one
            out[path] = said
            continue
        if looks is None or looks >= WARN:
            continue
        fits = sorted(((share, g) for g, cols in d["fit"].items() if g not in ("id", fld) and (share := cols.get(col) or 0) >= WARN), reverse=True) if col else []
        target_of = lambda g: next((tp for tp, tx in paths if tp.count("/") == 1 and field_of(tp, tx) == g), None)
        close = [(share, g, tp) for share, g in fits if share >= fits[0][0] - 0.2 and (tp := target_of(g))]  # 7 digits fit a postal code and an address code alike
        pick = (next((c for c in close if [col] in slot[c[2]]["sources"]), None)  # the feature that reads this column already
                or (close[0] if len(close) == 1 else None)
                or (empty[0] if len(empty := [c for c in close if not found(slot[c[2]])]) == 1 else None))  # else the one feature with no column
        if pick:
            share, g, target = pick
            name, says = target.split("/")[-1], f"values look like {target.split('/')[-1].lower()} ({share:.0%})"
            fam = path.removesuffix("/Given name") + "/Family name"  # a family name is read joined to the given name: it goes with the last of it
            also = [f"{fam}="] if path.endswith("/Given name") and not alts(e, col) and any(slot.get(fam, {}).get("sources") or []) else []
            out[path] = (dict(level="warn", says=f"{says}, which reads this column already", fix=f"take it off {x['name']}", act="off", column=col,
                              button="Take it off", command=nayose("set", "feature", f"{path}={alts(e, col)}", *also, *there) if ws else None)
                         if [col] in slot[target]["sources"] else
                         dict(level="warn", says=says, fix=f"read this column as {name}", act="move", to=target, column=col, button=f"Move to {name}",
                              command=nayose("set", "feature", f"{target}={','.join(filter(None, (col, alts(slot[target], col))))}", f"{path}={alts(e, col)}", *also, *there)
                              if ws else None)
                         if not found(slot[target]) or (slot[target].get("looks_right") or 0) < WARN else
                         dict(level="warn", says=says, fix=f"check the column ({col})"))
            continue
        out[path] = dict(level="warn", says=f"only {looks:.0%} look right", example=e.get("odd"), fix=f"check the column ({'+'.join(first)})")  # a value: shown here, never in a report
    return out
