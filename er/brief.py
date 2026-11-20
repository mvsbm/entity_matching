"""A command's result for a person: in short, command by command (BRIEF), or every field it declares (text, with
--verbose); rows as tables sized for a terminal, where full-width kana and kanji take two columns."""
from __future__ import annotations
import shlex
import unicodedata
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from er.cli import Command


def nayose(*words: object) -> str:  # a command line, quoted for a shell
    return shlex.join(["nayose", *map(str, words)])


def took(seconds: float) -> str:  # 0.3s, 45s, 1m 12s, 2h 05m
    s = max(seconds, 0)
    return f"{s:.1f}s" if s < 9.95 else f"{s:.0f}s" if s < 59.5 else f"{int(s // 60)}m {int(s % 60):02d}s" if s < 3600 else f"{int(s // 3600)}h {int(s % 3600 // 60):02d}m"


def count(n: float) -> str:  # 4.1M, 118.8M, 12,532
    return f"{n / 1e9:.1f}B" if n >= 1e9 else f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n:,.0f}"


def cell(v: object) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, list):
        return ", ".join(map(cell, v))
    if isinstance(v, dict):
        return " ".join(f"{k.replace('_', ' ')} {cell(x)}" for k, x in v.items())
    return str(v)


def wide(text: str) -> int:  # columns a terminal gives the text: full-width kana and kanji take two
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def table(rows: list[dict], cols: tuple[str, ...] | None, most: int = 20) -> list[str]:
    cols = tuple(c for c in (cols or rows[0].keys()) if c in rows[0])
    return grid(rows, {c: c for c in cols}, most) + ([f"  … {len(rows) - most:,} more (--format json lists every one)"] if len(rows) > most else [])


def text(c: Command, r: dict) -> str:
    """A result for a person: each declared field in order; a summary as aligned lines; rows as a table; next last."""
    if c.name == "check records":
        return check_text(r)
    out = []
    for key in c.result:
        v = r.get(key)
        if v is None or v == [] or v == {} or v == "":
            continue
        label = key.replace("_", " ")
        if (c.show or {}).get(key) == ():  # for programs only
            continue
        if key == "next":
            out += ["next"] + [f"  {x['command']}" + (f"    # {x['why']}" if x.get("why") else "") for x in v]
        elif key == "summary":
            out += [f"{w:<15} {x}" for w, x in v]
        elif isinstance(v, list) and isinstance(v[0], dict):
            out += [label] + table(v, (c.show or {}).get(key))
        elif isinstance(v, dict):
            out.append(f"{label:<15} " + " · ".join(f"{k.replace('_', ' ')} {cell(x)}" for k, x in v.items()))
        elif isinstance(v, list) and len(" · ".join(map(cell, v))) > 80:  # long: one a line
            out += [label] + [f"  {cell(x)}" for x in v]
        elif isinstance(v, list):
            out.append(f"{label:<15} " + " · ".join(map(cell, v)))
        else:
            out.append(f"{label:<15} {cell(v)}")
    return "\n".join(out)


def check_text(r: dict) -> str:
    pct = lambda x: "  —" if x is None else f"{x:>3.0%}"
    out = [f"{r['records']:,} records · filled · looks right, top value: on a sample of 10,000"]
    for f in r["fields"]:
        out.append(f"  {f['field']:<13} " + (f"{f['filled']:>5.0%} filled · looks right {pct(f['looks_right'])} · top value {pct(f['top_value'])}  ← {f['columns']}"
                                             if f["columns"] else "—  no column"))
    out += [f"  turned off: {x}" for x in r["turned_off"]] or ["  nothing turned off"]
    out.append(f"pairs per record, and blocks of {r['oversized_from']}+ records (checked by sampling; a rule doesn't trust their values):")
    for k in r["keys"]:
        out.append(f"  {k['key']:<34} {k['per_record']:>6.2f} / record  largest block {k['largest_block']:>6,}" +
                   (f"  {k['oversized_blocks']:,} oversized ({k['oversized_records']:,} records): checked by sampling" if k["oversized_blocks"] else ""))
    out += [f"  {x}" for x in r["notes"]]
    c, ready = r["capacity"], r["ready"]
    out.append(f"room: {c['memory_limit_gb']} GB of memory, {c['spill_free_gb']} GB to spill in {c['spill_folder']}: "
               f"{c['pairs_fit']:,} pairs fit, the file needs {c['pairs_needed']:,}" + (f" ({c['headroom']}×)" if c["headroom"] else ""))
    out.append("ready: " + ("yes" if ready["ok"] else "no") + (", but look at:" if ready["ok"] and ready["warns"] else ""))
    out += [f"  ✗ {x['what']}: {x['fix']}" for x in ready["stops"]] + [f"  ! {x['what']}: {x['fix']}" for x in ready["warns"]]
    return "\n".join(out + ["next"] + [f"  {x['command']}    # {x['why']}" for x in r["next"]])


WORDS = {"customer_id": "customer ID", "id": "ID", "kind_flag": "person/company flag"}
word = lambda f: WORDS.get(f, f.replace("_", " "))
num = lambda v: f"{v:g}" if isinstance(v, float) else f"{v:,}"


def nexts(r: dict, most: int = 3) -> list[str]:  # the commands that usually follow, each with why, aligned
    rows = (r.get("next") or [])[:most]
    if not rows:
        return []
    w = min(max(len(x["command"]) for x in rows), 76)
    return ["next"] + [f"  {x['command']:<{w}}  {x.get('why') or ''}".rstrip() for x in rows]


def grid(rows: list[dict], cols: dict[str, str], most: int = 20) -> list[str]:  # rows as a table: columns by key, headed in words
    if not rows:
        return []
    cells = [[cell(r.get(k)) for k in cols] for r in rows[:most]]
    width = [max(wide(h), *(wide(x[i]) for x in cells)) for i, h in enumerate(cols.values())]
    pad = lambda x, w: x + " " * (w - wide(x))
    return ["  " + "  ".join(pad(h, w) for h, w in zip(cols.values(), width)).rstrip()] + \
           ["  " + "  ".join(pad(x, w) for x, w in zip(row, width)).rstrip() for row in cells]


def merging_words(m: dict) -> str:  # what a run merges, in words
    return f"the rules' pairs, and the model's at {num(m['line'])}+ points, merge without you"


def thin(filled: dict[str, float], one_of, columns: Callable[[str], set[str] | None]) -> list[str]:
    """The fields under 30% filled, said: a group of one_of (a person's or a company's name, each filled only for its
    kind) together, a column both read counted once (columns: a field's columns), each other field alone."""
    either, out = {f for g in one_of for f in g}, []
    for g in [*one_of, *([f] for f in filled if f not in either)]:
        have = [f for f in g if f in filled]
        apart = len(set().union(*(columns(f) or set() for f in have))) == sum(len(columns(f) or ()) for f in have)
        if have and (share := (sum if apart else max)(filled[f] for f in have)) < 0.3:
            out.append(f"{' and '.join(map(word, have))} {'are' if len(have) > 1 else 'is'} {share:.0%} filled" + (" together" if len(have) > 1 else ""))
    return out


def brief_run(r: dict) -> list[str]:  # resolve and add records: what the run found, and what waits
    f = r.get("facts")
    if not f:
        return [f"✓ {x[1]}" for x in r.get("summary") or []] + nexts(r)
    out = [f"✓ {f['records']:,} records → {f['entities']:,} entities in {took(r.get('seconds') or 0)}"]
    out.append(f"  {f['waiting']:,} pairs wait for your review ({num(f['review_from'])}+ points)" if f["waiting"] else "  no pair waits for your review")
    if f.get("merging"):
        out.append(f"  {f['merging']}")
    if f.get("missed") is not None:
        out.append(f"  matches no key listed: about {f['missed']:,} (at most {f['missed_high']:,}), among the pairs the probe checked")
    if f.get("too_big"):
        out.append(f"  ! {f['too_big']:,} groups too big to compare were skipped: see report.txt")
    if f.get("kinds"):
        out.append(f"  person or company: {f['kinds']:,} flagged, matched as the engine says: gold.parquet kind_flagged")
    out.append(f"  details: {f['report']}")
    return out + nexts(r)


def shown_record(x: dict) -> str:  # a record in a line, as a person reads it
    return " · ".join(v for v in (x.get("full_name") or x.get("person_name"), x.get("company_name"), x.get("address"), x.get("phone")) if v)


def brief_match_record(r: dict) -> list[str]:  # the entities it may belong to, best first, each in a line; how long it took
    out = [f"✓ {r['found']:,} possible match{'es' * (r['found'] != 1)}, {r['likely']:,} likely, of {r['candidates']:,} records compared "
           f"in {sum(r['seconds'].values()) * 1000:,.0f} ms"]
    if r.get("read_as"):  # typed one way, read as the records hold it
        out.append(f"  read as {', '.join(r['read_as'].values())}")
    if (c := r.get("closest")):  # none reached --from: the nearest, so a person sees the records are there
        out.append(f"  none reaches {num(r['at_least'])} pts; the closest: {num(c['points'])} pts  {c['entity']}  {shown_record(c['shown'])}")
    out += [f"  {'●' if e['likely'] else '○'} {num(e['points']):>6} pts  {e['entity']}  {shown_record(e['shown'])}" + (f"  (rule {e['rule']})" if e["rule"] else "")
            for e in r["entities"]]
    return out + nexts(r)


BRIEF: dict[str, Callable[[dict], list[str]]] = {
    "resolve records": brief_run, "add records": brief_run,
    "match record": brief_match_record,
    "build index": lambda r: [f"✓ index of {r['records']:,} records built in {took(r['seconds'])}: {r['index']}"] + nexts(r),
    "apply decisions": lambda r: ([f"✓ {r['decisions']:,} decisions applied" + (f": {r['clusters_joined']:,} entities joined" if r.get("clusters_joined") else "")]
                                  if r.get("decisions") else ["✓ nothing new: every decision was applied before"]) + nexts(r),
}


