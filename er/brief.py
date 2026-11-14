"""A command's result for a person: in short, command by command (BRIEF), or every field it declares (text, with
--verbose); rows as tables sized for a terminal, where full-width kana and kanji take two columns."""
import shlex
import unicodedata
from collections.abc import Callable
from pathlib import Path
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


def merging_words(m: dict | None) -> str:  # what merges without people, as describe results' merging says
    if not m:
        return ""
    if m.get("when"):
        said = []
        for c in m["when"]:
            (k, v), = c.items()
            said.append(f"{num(v)} points or more" if k == "points" else f"found by {', '.join(v)}" if k == "rules"
                        else " and ".join(f"{word(f)} at least {lv}" for f, lv in v.items()))
        return "pairs merge without you when " + f" {m.get('join', 'and')} ".join(said)
    own = m.get("own")
    if not own:
        return "nothing merges without you"
    return (f"the rules' pairs, and the model's at {num(own['line'])}+ points, merge without you" if own.get("rules")
            else f"pairs at {num(own['line'])}+ points merge without you")


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


def file_lines(r: dict) -> list[str]:  # a file described: the fields found, and what needs a look
    fields = [f for f in r.get("fields") or [] if f["field"] != "id"]
    found = [f for f in fields if f.get("filled") is not None]
    out = [f"  {len(found)} of {len(fields)} fields found"] if fields else []
    needed = r.get("needed") or {}
    lost = lambda f: not any(x["field"] == f and x.get("filled") is not None for x in r.get("fields") or [])
    missing = [word(f) for f in needed.get("every", []) if lost(f)] + [" or ".join(map(word, g)) for g in needed.get("one_of", []) if all(lost(f) for f in g)]
    out += [f"  ✗ needed: {m}" for m in missing]
    cols = {f["field"]: {c for a in f.get("alternatives") or [] if a["found"] for c in a["columns"]} for f in found}
    out += [f"  ! {x}" for x in thin({f["field"]: f["filled"] for f in found}, needed.get("one_of", []), cols.get)]  # as check records says it
    for f in found:  # what its values say is off, else how few look right
        if h := f.get("hint"):
            out.append(f"  {'! ' if h['level'] == 'warn' else ''}{word(f['field'])}: {h['says']}" + (f", e.g. {h['example']}" if h.get("example") else ""))
        elif f.get("looks_right") is not None and f["looks_right"] < WARN:
            out.append(f"  ! only {f['looks_right']:.0%} of {word(f['field'])} values look right")
    read = r.get("read") or {}
    if several := (read.get("fixed") or {}).get("first of several"):
        out.append(f"  ! {several:,} values listed several items: the first is read")
    if read.get("waiting"):
        out.append(f"  ! {sum(read['waiting'].values()):,} values wait for a repair you accept: nayose accept repairs")
    if read.get("unread"):
        out.append(f"  ! {read['unread']:,} rows can't be read: kept aside")
    return out


def brief_load(r: dict) -> list[str]:
    name = Path(r["loaded"]).name.split("-", 1)[-1] if r.get("loaded") else "the file"
    return [f"✓ {name}: {r['records']:,} records, {len(r.get('columns') or []):,} columns"] + file_lines(r) + nexts(r)


def brief_describe_records(r: dict) -> list[str]:
    return [f"{r['records']:,} records, {len(r.get('columns') or []):,} columns"] + file_lines(r) + nexts(r)


def brief_check(r: dict) -> list[str]:
    ready, c = r["ready"], r["capacity"]
    out = [f"{'✓ ready' if ready['ok'] else '✗ not ready'}: {r['records']:,} records · {c['pairs_needed']:,} pairs to compare"
           + (f" ({r['records'] and c['pairs_needed'] / r['records']:.1f} per record)" if r["records"] else "")]
    out += [f"  ✗ {x['what']}: {x['fix']}" for x in ready["stops"]] + [f"  ! {x['what']}: {x['fix']}" for x in ready["warns"]]
    big = [k for k in r.get("keys") or [] if k.get("oversized_blocks")]
    out += [f"  {len(big)} keys have groups of {r['oversized_from']}+ records: checked by sampling"] if big else []
    return out + nexts(r)


def brief_run(r: dict) -> list[str]:  # resolve, rerun, add records, apply answers: what the run found, and what waits
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
        out.append(f"  person or company: {f['kinds']:,} flagged, matched as the engine says: nayose list kinds --open")
    out.append(f"  details: {f['report']}")
    return out + nexts(r)


def brief_workspace(r: dict) -> list[str]:
    out = [f"{r['workspace']}: " + (f"{r['records']:,} records → {r['entities']:,} entities" if r.get("records") else "no run yet")]
    files = r.get("inputs") or []
    if files:
        out.append("  files: " + ", ".join(f"{x['name'].split('-', 1)[-1]}" for x in files))
    runs = [x for x in r.get("runs") or [] if x.get("what") != "decisions"]
    if runs:
        x = runs[-1]
        out.append(f"  last run: {str(x['at']).replace('T', ' ')[:16]} · {took(x.get('seconds') or 0)}")
    if (r.get("pairs") or {}).get("written_in"):
        out.append(f"  {r['pairs']['written_in']:,} decisions written, not applied: nayose apply decisions")
    if (r.get("kinds") or {}).get("written_in"):
        out.append(f"  {r['kinds']['written_in']:,} person/company answers written, not applied: nayose apply answers")
    if r.get("set_aside"):
        out.append(f"  ! {r['set_aside']:,} records set aside: see set_aside/")
    if r.get("write_owed"):
        out.append("  ! a write was cut short: the next command that writes finishes it")
    return out + nexts(r)


def brief_results(r: dict) -> list[str]:
    waiting = sum(x["pairs"] for x in r.get("waiting") or [])
    out = [f"{r['records']:,} records → {r['entities']:,} entities · " + (f"{r['joined']:,} of two records or more" if r["joined"] else "nothing joined yet"),
           f"  {waiting:,} pairs wait for your review ({num(r['review_from'])}+ points)" if waiting else "  no pair waits for your review"]
    bands = [f"{num(x['down_to'])}+" if x["up_to"] is None else f"{num(x['down_to'])}–{num(x['up_to'])}" for x in r.get("waiting") or []]
    if waiting:
        out.append("    " + " · ".join(f"{b}: {x['pairs']:,}" for b, x in zip(bands, r["waiting"])))
    out.append(f"  {merging_words(r.get('merging'))}")
    if r.get("missed"):
        out.append(f"  matches no key listed: about {sum(x['missed'] for x in r['missed']):,} (at most {sum(x['high'] for x in r['missed']):,}) "
                   f"among pairs sharing {' or '.join(word(f) for x in r['missed'] for f in x['fields'])}")
    if (r.get("too_big") or {}).get("skipped"):
        by = " · ".join(f"{k} {n:,}" for k, n in sorted(r["too_big"].get("by", {}).items(), key=lambda kv: -kv[1])[:3])
        out.append(f"  ! {r['too_big']['skipped']:,} groups too big to compare were skipped" + (f" ({by})" if by else ""))
    if (k := r.get("kinds") or {}).get("flagged"):
        out.append(f"  person or company: {k['flagged']:,} flagged, matched as the engine says" + (f"; the surest {k['to_check']:,} to check" if k["to_check"] < k["flagged"] else ""))
    return out + nexts(r)


def page_line(r: dict, what: str) -> str:  # 1–100 of 1,963 · next: --page 2
    first, last = (r["page"] - 1) * r["count"] + 1, min(r["total"], r["page"] * r["count"])
    return (f"  {first:,}–{last:,} of {r['total']:,} {what}" + (f" · more: --page {r['page'] + 1}" if last < r["total"] else "")) if r["total"] else f"  no {what}"


def brief_scored(r: dict) -> list[str]:
    name = lambda p, k: next((p["fields"][f][k] for f in ("person_name", "company_name", "full_name") if (p.get("fields") or {}).get(f) and p["fields"][f][k]), "")
    rows = [dict(a=p["first"], an=name(p, 0), b=p["second"], bn=name(p, 1), points=f"{p['points']:.1f}", by=p.get("found") or "", status=p["status"]) for p in r["pairs"]]
    return grid(rows, {"a": "record", "an": "name", "b": "record", "bn": "name", "points": "points", "by": "found by", "status": "status"}, most=len(rows)) + [page_line(r, "pairs")]


def brief_entities(r: dict) -> list[str]:
    rows = [dict(e=x["entity"], n=x["records"], by={"you": "you", "model": "the model", "rule": "a rule"}.get(x.get("joined_by"), ""), names=" · ".join(x.get("names") or []))
            for x in r["entities"]]
    return grid(rows, {"e": "entity", "n": "records", "by": "joined by", "names": "names"}, most=len(rows)) + [page_line(r, "entities")]


def brief_show(r: dict) -> list[str]:  # the full rows side by side: the columns that differ first, empty ones left out
    recs = [x for x in r["records"] if x.get("row")]
    out = [f"  {x['id']}: not in the file's copy" for x in r["records"] if not x.get("row")]
    if not recs:
        return out
    rows = []
    for c in r["columns"]:
        vals = [x["row"].get(c["column"]) for x in recs]
        if all(v in (None, "") for v in vals):
            continue
        filled = [v for v in vals if v not in (None, "")]
        differ = len(recs) > 1 and len(set(filled)) > 1 and "id" not in (c.get("fields") or [])  # IDs always differ
        rows.append(dict(column=c["column"], **{f"r{k}": v for k, v in enumerate(vals)}, mark="≠" if differ else ""))
    rows.sort(key=lambda x: x["mark"] != "≠")
    return grid(rows, {"column": "column", **{f"r{k}": x["id"] for k, x in enumerate(recs)}, "mark": ""}, most=len(rows)) + out


def brief_details(r: dict) -> list[str]:
    linked = f"; {r['linked']:,} of {r['drawn']:,} records drawn have some" if r.get("drawn") else ""
    return [f"✓ {r['file']}: {r['rows']:,} rows, by {r['key']}{linked}", f"  shown: {', '.join(r['shown']) or 'none'}"]


def brief_merging(r: dict) -> list[str]:
    m = {"join": r.get("join"), "when": r.get("when")}
    if not r.get("when"):
        return [f"{r.get('pairs', 0):,} pairs merge without you → {r['entities']:,} entities of two records or more"]
    out = [f"{r['pairs']:,} pairs would merge → {r['entities']:,} entities of two records or more", f"  {merging_words(m)}"]
    if len(r.get("each") or []) > 1:
        out += [f"    {merging_words({'when': [x['condition']]}).removeprefix('pairs merge without you when ')}: {x['pairs']:,}" for x in r["each"]]
    return out


def brief_set_merging(r: dict) -> list[str]:
    said = merging_words({"join": r.get("join"), "when": r.get("when"), "own": None}) if r.get("when") else "conditions off"
    return [f"✓ {said}", f"  {r['entities']:,} entities of two records or more"] + nexts(r)


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


def brief_search_records(r: dict) -> list[str]:  # the entities best first, each in a line with the fields that agree; a value too common to list
    out = [f"✓ {r['found']:,} entit{'ies' if r['found'] != 1 else 'y'} of {r['listed']:,} records listed in {sum(r['seconds'].values()) * 1000:,.0f} ms"]
    out += [f"  ! {x['field']} {x['value']}: {x['records']:,}{'+' if x['more'] else ''} records start with it: the first by value below; give more of it, or another value beside it, to narrow"
            for x in r["over"] if x["listed"]]
    out += [f"  nothing to search by: {', '.join(r['missing'])} read as missing"] if r.get("missing") else []
    out += [f"  read as {', '.join(r['read_as'].values())}"] if r.get("read_as") else []
    out += [f"  {'●' if e['likely'] else '○'} {num(e['points']):>6} pts  {e['entity']}  {shown_record(e['shown'])}  ({', '.join(e['fields'])})" for e in r["entities"]]
    return out + nexts(r)


BRIEF: dict[str, Callable[[dict], list[str]]] = {
    "create workspace": lambda r: [f"✓ created {r['workspace']}"] + nexts(r),
    "list workspaces": lambda r: (grid([dict(n=x["name"], f=x.get("files"), ran="yes" if x.get("ran") else "", last=str(x.get("last") or "")[:10]) for x in r["workspaces"]],
                                       {"n": "workspace", "f": "files", "ran": "matched", "last": "last"}) or [f"  no workspace in {r['home']}"]) + nexts(r),
    "load records": brief_load,
    "generate records": brief_load,
    "describe records": brief_describe_records,
    "check records": brief_check,
    "resolve records": brief_run, "rerun records": brief_run, "add records": brief_run, "set names": lambda r: [f"✓ names compared {'each on its own side, by kind' if r['names'] == 'by-kind' else 'as mapped'}"] + nexts(r), "apply answers": brief_run, **dict.fromkeys(("adopt method", "reset method", "lower trust", "raise trust", "split entity"), brief_run),
    "describe workspace": brief_workspace,
    "describe results": brief_results,
    "list scored": brief_scored,
    "list entities": brief_entities,
    "show records": brief_show,
    "load details": brief_details, "set details": brief_details,
    "show details": lambda r: [line for x in r["records"] for line in [f"  {x['id']}: {x['total']:,} row{'s' * (x['total'] != 1)} in {r['file']}"] + grid([dict(zip(r["columns"], v)) for v in x["rows"]], {c: c for c in r["columns"]}, most=len(x["rows"]))]
                              if r["file"] else ["  no details file: nayose load details FILE --workspace …"],
    "match record": brief_match_record,
    "search records": brief_search_records,
    "build index": lambda r: [f"✓ index of {r['records']:,} records built in {took(r['seconds'])}: {r['index']}"] + nexts(r),
    "describe merging": brief_merging,
    "set merging": brief_set_merging,
    "decide pair": lambda r: [f"✓ {' · '.join(r['pair'])}: {r['decision'].replace('no_match', 'different').replace('match', 'same')} (written; applied by apply decisions)"] + nexts(r),
    "apply decisions": lambda r: ([f"✓ {r['decisions']:,} decisions applied" + (f": {r['clusters_joined']:,} entities joined" if r.get("clusters_joined") else "")]
                                  if r.get("decisions") else ["✓ nothing new: every decision was applied before"]) + nexts(r),
    "answer kind": lambda r: [f"✓ {r['record']}: {r['kind'] or 'cleared'} (written; applied by apply answers)"] + nexts(r),
    "open ui": lambda r: [],
}



WARN = 0.5  # under this share of a slot's values that look like it, its column likely holds something else: a hint says what
