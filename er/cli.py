"""nayose (名寄せ: gathering each customer's records under one name), the command line, in kubectl's grammar: a verb,
then a noun, then its parameters.

    nayose check records customers.parquet
    nayose resolve records customers.parquet --workspace workspaces/customers
    nayose list pairs --workspace workspaces/customers --open

Each command is declared once, in COMMANDS: its verb and noun, what it does, its parameters, the fields of its result,
an example, and the function that runs it. The parser, the reference (docs/commands.md, reference()) and the UI's
forms are all built from those declarations. A command emits events: each step as it finishes (and, as JSON, how far a
file has been read: progress), then one result, or an error. --format text renders them for a person; --format json writes each as one JSON object per line. Every result
names the commands that usually come next. Exit codes: 0; 2, a mistake people fix, in two lines (what is wrong, and
how to fix it); 75, the workspace is busy: try again later; 1, a pass of serve inbox stopped on a file.
"""
import argparse
import contextlib
import functools
import gc
import hashlib
import json
import math
import re
import shlex
import shutil
import sys
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import get_args

import duckdb
import numpy as np
import pandas as pd

from er import folder, inbox, index, intake
from er.io import replace_text
from er.config import InputError, Normalizer, adjust, lit, load_pipeline, q, restrict, sources_text, toml_of, widen
from er.folder import Busy
from er.report import (applied, compare_records, describe_entity, describe_key, describe_matching, describe_method, describe_workspace, entity_pairs, explain_pair, fill_rates,
                       key_how, list_patterns, review_workload, rule_how, run_model, trust_state)
from er.source import describe, filled, find, lexicon
from er.kind import sheet_parts
from er.match import review_floor
from er.results import apply_merging, check_merging, describe_merging, describe_results, list_entities, list_scored, merged_links, save_merging, show_records
from er.strings import connect
from er.run import Run, run_config, size_bytes, trial
from er.settings import (COLUMNS, SPECIAL, add_feature, added_of, beside, columns_file, counted_once, features_of, load_settings, names_by_kind, offers,
                         own_columns, placements, present_fields, remove_feature, set_columns, set_features, set_name_kinds, settings_path, slots)
from er.standardize import SEPARATORS


@dataclass(frozen=True)
class Param:
    name: str
    help: str
    kind: str = "text"                        # text, path, flag, choice, many (several values)
    choices: tuple[str, ...] = ()
    positional: bool = False
    required: bool = False
    metavar: str = ""
    optional: bool = False                    # a positional that may be left out

    @property
    def shown(self) -> str:  # how the synopsis writes its value
        return self.metavar or self.name.upper()


@dataclass(frozen=True)
class Command:
    verb: str
    noun: str
    help: str                                 # one line: what it does
    about: str                                # what it reads and writes, and what it costs
    params: tuple[Param, ...]
    result: dict[str, str]                    # the result's fields, in order, and what each holds
    example: str
    run: Callable[[dict, "Emit"], dict]
    quick: bool = False                       # takes seconds and writes no run: the UI runs it in its own process
    show: dict[str, tuple[str, ...]] | None = None  # for text: the columns a list of rows shows

    @property
    def name(self) -> str:
        return f"{self.verb} {self.noun}"


def nayose(*words: object) -> str:  # a command line, quoted for a shell
    return shlex.join(["nayose", *map(str, words)])


def plain(x: object) -> object:
    """A value JSON can carry: numpy and pandas scalars as Python ones, NaN and NA as null."""
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [plain(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if x is pd.NA or x is pd.NaT or (isinstance(x, float) and math.isnan(x)):
        return None
    return x if isinstance(x, str | int | float | bool) or x is None else str(x)


DOING = {"load": "reading the records", "budget": "counting the pairs", "fit": "fitting the model", "rules": "applying the rules",
         "candidates": "listing the pairs to compare", "score": "scoring the pairs", "cluster": "forming entities",
         "probe": "looking for missed matches", "report": "writing the reports", "write": "saving", "decide": "applying the decisions"}
RUN_ORDER = ("load", "budget", "fit", "rules", "candidates", "score", "cluster", "probe", "report", "write")  # a full run's steps
BATCH_ORDER = ("load", "fit", "rules", "candidates", "score", "cluster", "report", "write")  # a batch added: no budget, no probe


def took(seconds: float) -> str:  # 0.3s, 45s, 1m 12s, 2h 05m
    s = max(seconds, 0)
    return f"{s:.1f}s" if s < 9.95 else f"{s:.0f}s" if s < 59.5 else f"{int(s // 60)}m {int(s % 60):02d}s" if s < 3600 else f"{int(s // 3600)}h {int(s % 3600 // 60):02d}m"


def count(n: float) -> str:  # 4.1M, 118.8M, 12,532
    return f"{n / 1e9:.1f}B" if n >= 1e9 else f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n:,.0f}"


def step_facts(x: dict) -> str:  # the one or two facts of a finished step that a person reads; none that are zero
    f = lambda k: x.get(k) or 0
    needs = {"load": "records", "budget": "pairs", "rules": "pairs", "candidates": "candidates", "cluster": "accepted", "decide": "decisions"}
    said = None if needs.get(x["step"]) not in x else {"load": [f"{f('records'):,} records", f"{f('set_aside'):,} set aside" if f("set_aside") else ""],
            "budget": [f"{f('pairs'):,} pairs by the keys", f"{f('oversized_blocks'):,} groups too big: checked by sampling" if f("oversized_blocks") else ""],
            "rules": [f"{f('pairs'):,} pairs matched by rules"],
            "candidates": [f"{f('candidates'):,} pairs to compare", f"{f('oversized_skipped'):,} big groups skipped" if f("oversized_skipped") else ""],
            "cluster": [f"{f('accepted'):,} pairs merged by the model" if f("accepted") else ""],
            "decide": [f"{f('decisions'):,} decisions", f"{f('clusters_joined'):,} entities joined" if f("clusters_joined") else ""]}.get(x["step"])
    if said is None:  # any other step: its counts that aren't zero
        said = [f"{k.replace('_', ' ')} {v:,}" for k, v in x.items() if k not in ("seconds", "peak_memory_gb") and isinstance(v, int) and not isinstance(v, bool) and v]
    return " · ".join(s for s in said if s)


def step_text(x: dict) -> str:  # --verbose: one line per step, every fact
    base = ("event", "step", "big_o", "filled", "seconds", "peak_memory_gb")
    facts = " · ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in x.items() if k not in base and isinstance(v, int | float) and not isinstance(v, bool))
    return f"  {x['step']:<11} {x['seconds']:>6.1f} s  {facts}"


class Live:
    """A long command's steps for a person: a line per finished step, and one line for the step under way (what it
    does, how far, how long is left), redrawn on a terminal and written every 30 seconds elsewhere (a log, a pipe).
    Time left: the step's own pace once it reports how far it is; for the steps after it, the workspace's last run of
    the same kind, scaled to the records; nothing where neither says."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, out, title: str, order: tuple[str, ...], last: dict[str, float] | None, last_records: int | None):
        self.out, self.tty, self.order, self.last, self.last_records = out, out.isatty(), order, last or {}, last_records
        self.records, self.step, self.p, self.lock, self.stop = None, (order[0] if order else None), None, threading.Lock(), threading.Event()
        self.t = self.said = time.monotonic()
        self.frame, self.shown = 0, False
        print(title, file=out, flush=True)
        if self.tty:
            threading.Thread(target=self._tick, daemon=True).start()

    def _tick(self) -> None:
        while not self.stop.wait(0.15):
            with self.lock:
                if self.stop.is_set():
                    return
                self.frame += 1
                self._draw()

    def _clear(self) -> None:
        if self.shown:
            self.out.write("\r\033[K")
            self.shown = False

    def _draw(self) -> None:
        line = self._line(self.FRAMES[self.frame % len(self.FRAMES)])
        width = shutil.get_terminal_size((100, 20)).columns - 1
        self.out.write("\r\033[K" + (line if len(line) <= width else line[:width - 1] + "…"))
        self.out.flush()
        self.shown = True

    def _left(self) -> tuple[float | None, float | None]:  # this step's time left, and all of it, where something measured says
        now, here = time.monotonic(), None
        if self.p and self.p[0] > self.p[3] and now - self.p[4] >= 3:
            done, total, _, first, since = self.p
            here = (total - done) * (now - since) / (done - first)
        if not self.last or self.step not in self.order:
            return here, None
        scale = self.records / self.last_records if self.records and self.last_records else 1.0
        later = sum(self.last.get(s, 0) for s in self.order[self.order.index(self.step) + 1:]) * scale
        mine = here if here is not None else max(self.last.get(self.step, 0) * scale - (now - self.t), 0)
        return here, mine + later

    def _line(self, mark: str) -> str:
        here, everything = self._left()
        parts = [f"  {mark} {self.step or '':<10} {took(time.monotonic() - self.t):>7}  {DOING.get(self.step, 'working')}"]
        if self.p and self.p[1]:
            parts.append(f"{count(self.p[0])} of {count(self.p[1])} {self.p[2]}")
        if here is not None:
            parts.append(f"about {took(here)} left")
        if everything is not None and (here is None or everything > here + 5):
            parts.append(f"about {took(everything)} left in all")
        return " · ".join(parts)

    def done(self, x: dict, verbose: bool) -> None:
        with self.lock:
            self._clear()
            print(step_text(x) if verbose else f"  ✓ {x['step']:<10} {took(x['seconds']):>7}  {step_facts(x)}".rstrip(), file=self.out, flush=True)
            if x["step"] == "load" and x.get("records"):
                self.records = x["records"]
            at = self.order.index(x["step"]) if x["step"] in self.order else None
            self.step = self.order[at + 1] if at is not None and at + 1 < len(self.order) else None
            self.t = self.said = time.monotonic()
            self.p = None

    def progress(self, done: int, total: int, unit: str) -> None:
        with self.lock:
            now = time.monotonic()
            if self.step is None and self.order:  # a count after the last step: the steps again
                self.step, self.t = self.order[0], now
            if self.p is None or self.p[1] != total or self.p[2] != unit:  # a new count: its pace from here
                self.p = (done, total, unit, done, now)
            else:
                self.p = (done, total, unit, self.p[3], self.p[4])
            if not self.tty and now - self.said >= 30:
                print(self._line("…"), file=self.out, flush=True)
                self.said = now

    def say(self, text: str) -> None:
        with self.lock:
            self._clear()
            print(text, file=self.out, flush=True)

    def close(self) -> None:
        self.stop.set()
        with self.lock:
            self._clear()
            self.out.flush()


class Emit:
    """Where a command's events go: text for a person (the steps as they go, then the result in short, or every
    field with verbose; an error on stderr), or JSON, one object per line, all on stdout."""

    def __init__(self, fmt: str = "text", out=None, err=None, verbose: bool = False, title: str = "", order: tuple[str, ...] = RUN_ORDER,
                 last: dict[str, float] | None = None, last_records: int | None = None):
        self.fmt, self.out, self.err, self.verbose = fmt, out or sys.stdout, err or sys.stderr, verbose
        self.title, self.order, self.last, self.last_records, self.live = title, order, last, last_records, None

    def _json(self, event: str, x: dict) -> None:
        print(json.dumps({"event": event, **plain(x)}, ensure_ascii=False), file=self.out, flush=True)

    def _live(self) -> Live:  # made at the first step or count: a quick command shows none
        if self.live is None:
            self.live = Live(self.out, self.title, self.order, self.last, self.last_records)
        return self.live

    def step(self, x: dict) -> None:
        self._json("step", x) if self.fmt == "json" else self._live().done(x, self.verbose)

    def progress(self, done: int, total: int, unit: str, **facts: object) -> None:  # how far a long command has gone
        if self.fmt == "json":
            self._json("progress", {"done": done, "total": total, "unit": unit, **facts})
        else:
            self._live().progress(done, total, unit)

    def line(self, text: str, **data: object) -> None:  # a running note: serve inbox's files, open ui's link
        if self.fmt == "json":
            self._json("line", {"text": text, **data})
        elif self.live:
            self.live.say(text)
        else:
            print(text, file=self.out, flush=True)

    def close(self) -> None:
        if self.live:
            self.live.close()

    def result(self, c: Command, r: dict) -> None:
        self.close()
        if self.fmt == "json":
            self._json("result", {"command": c.name, **r})
        else:
            brief = None if self.verbose else BRIEF.get(c.name)
            said = text(c, r) if brief is None else "\n".join(brief(r))
            if isinstance(ix := r.get("index"), dict) and ix.get("error"):  # the run stands; its index waits for a build
                said += f"\n  ! the index: {ix['error']}\n    fix: {ix['fix']}"
            print(said, file=self.out, flush=True)

    def error(self, e: InputError, code: int) -> None:
        self.close()
        if self.fmt == "json":
            self._json("error", {"error": str(e), "fix": e.fix, "hints": e.hints, "exit": code})
        else:
            print(f"✗ {e}" + (f"\n  fix: {e.fix}" if e.fix else ""), file=self.err, flush=True)


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
    cells = [[cell(r.get(c)) for c in cols] for r in rows[:most]]
    width = [max(wide(c), *(wide(x[i]) for x in cells)) for i, c in enumerate(cols)]
    pad = lambda x, w: x + " " * (w - wide(x))
    out = ["  " + "  ".join(pad(c, w) for c, w in zip(cols, width)).rstrip()]
    out += ["  " + "  ".join(pad(x, w) for x, w in zip(row, width)).rstrip() for row in cells]
    return out + ([f"  … {len(rows) - most:,} more (--format json lists every one)"] if len(rows) > most else [])


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


# ---------- results in short, for a person (--verbose: every field, as text() writes it) ----------

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


def file_lines(r: dict) -> list[str]:  # a file described: the fields found, and what needs a look
    fields = [f for f in r.get("fields") or [] if f["field"] != "id"]
    found = [f for f in fields if f.get("filled") is not None]
    out = [f"  {len(found)} of {len(fields)} fields found"] if fields else []
    needed = r.get("needed") or {}
    lost = lambda f: not any(x["field"] == f and x.get("filled") is not None for x in r.get("fields") or [])
    missing = [word(f) for f in needed.get("every", []) if lost(f)] + [" or ".join(map(word, g)) for g in needed.get("one_of", []) if all(lost(f) for f in g)]
    out += [f"  ✗ needed: {m}" for m in missing]
    filled = {f["field"]: f["filled"] for f in found}
    groups = [g for g in needed.get("one_of", []) if any(f in filled for f in g)]  # a person's or a company's name: together, as check records counts them
    either = {f for g in groups for f in g}
    cols = {f["field"]: {c for a in f.get("alternatives") or [] if a["found"] for c in a["columns"]} for f in found}
    for g in [*groups, *([f] for f in filled if f not in either)]:
        have = [f for f in g if f in filled]
        apart = len(set().union(*(cols[f] for f in have))) == sum(len(cols[f]) for f in have)  # one column for both: counted once, as check records does
        if (share := (sum if apart else max)(filled[f] for f in have)) < 0.3:
            out.append(f"  ! {' and '.join(map(word, have))} {'are' if len(have) > 1 else 'is'} {share:.0%} filled" + (" together" if len(have) > 1 else ""))
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
    "describe records": brief_describe_records,
    "check records": brief_check,
    "resolve records": brief_run, "rerun records": brief_run, "add records": brief_run, "set names": lambda r: [f"✓ names compared {'each on its own side, by kind' if r['names'] == 'by-kind' else 'as mapped'}"] + nexts(r), "apply answers": brief_run, **dict.fromkeys(("adopt method", "reset method", "lower trust", "raise trust", "split entity"), brief_run),
    "describe workspace": brief_workspace,
    "describe results": brief_results,
    "list scored": brief_scored,
    "list entities": brief_entities,
    "show records": brief_show,
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


# ---------- what each command does ----------

def settings_for(a: dict):  # the settings, with the named workspace's own mapping when it keeps one; an earlier nayose's workspace refused
    if (ws := a.get("workspace")) and Path(ws).is_dir():
        folder.current(Path(ws), replacing=bool(a.get("overwrite")))  # a run --overwrite writes the rules' pairs anew
    return load_settings(columns=columns_file(ws))


def setup(a: dict, method: dict | None = None):
    """The settings, with this run's DuckDB limits, the pipeline, and its file; with `method`, that method in place of
    the workspace's method.toml."""
    s = settings_for(a)
    if bad := [kv for kv in a.get("compute") or [] if "=" not in kv]:
        raise InputError(f"--compute {' '.join(bad)}: each limit is KEY=VALUE", fix="for example --compute memory_limit=8GB threads=4")
    s = replace(s, compute={**s.compute, **dict(kv.split("=", 1) for kv in a.get("compute") or [])})
    pipeline = Path(a.get("pipeline") or s.root / "config" / "final.toml")
    ws = a.get("workspace")  # its own features, then its changes to the method
    return s, adjust(widen(load_pipeline(pipeline, s.standardize, s.chains, s.columns), beside(added_of(ws))),
                     folder.method(ws) if method is None else method), pipeline


def sheet(out: Path, name: str) -> pd.DataFrame | None:
    return pd.read_parquet(out / name) if (out / name).exists() else None


def ids(frame: pd.DataFrame, uid: str) -> pd.DataFrame:  # the file's ID columns under the names every result uses: id, id_l, id_r
    return frame.rename(columns={uid: "id", f"{uid}_l": "id_l", f"{uid}_r": "id_r"})


def rows(frame: pd.DataFrame) -> list[dict]:
    return plain(frame.astype(object).where(frame.notna(), None).to_dict("records"))


def next_after(out: Path, waiting: int | None = None) -> list[dict]:
    """What usually follows a run: the pairs waiting for people, the person/company answers open, then what it found."""
    found = [dict(command=nayose("open", "ui", "--workspace", out), why=f"review the {waiting:,} pairs in the browser"),
             dict(command=nayose("list", "scored", "--workspace", out, "--status", "waiting"), why="or list them here, best first")] if waiting else []
    if (kinds := sheet(out, "kind_review.parquet")) is not None and (n := int(((sheet_parts(kinds) == "decide") & kinds["kind"].isna()).sum())):
        found.append(dict(command=nayose("list", "kinds", "--workspace", out, "--open"), why=f"{n:,} flagged person or company to check, surest first"))
    return found + [dict(command=nayose("describe", "results", "--workspace", out), why="what the run found")]


def run_facts(run: Run, out: Path) -> dict | None:  # what a person reads first after a run; none if it can't be read (the run stands either way)
    if not any((out / folder.SCORED).glob("part-*.parquet")):  # a run from before the index: building it here would add minutes no one asked for
        return None
    try:
        r = describe_results(run.con, run.db, out, run.settings, run.pipeline, review_floor(run.pipeline))
    except (InputError, duckdb.Error, OSError):
        return None
    return dict(records=r["records"], entities=r["entities"], joined=r["joined"], waiting=sum(x["pairs"] for x in r["waiting"]), review_from=r["review_from"],
                merging=merging_words(r["merging"]), missed=sum(x["missed"] for x in r["missed"]) if r["missed"] else None,
                missed_high=sum(x["high"] for x in r["missed"]) if r["missed"] else None, too_big=r["too_big"]["skipped"], kinds=r["kinds"]["flagged"],
                report=str(out / "report.txt"))


def after_run(run: Run, out: Path) -> dict:
    wrote = ["gold.parquet", "review.parquet", "qa.md", "report.txt", *(["kind_review.parquet"] if (out / "kind_review.parquet").exists() and run.added is None else []),
             "matches/", "state/"]
    facts = run_facts(run, out)
    return dict(summary=run.tables["summary"].values.tolist(), seconds=round(sum(x["seconds"] for x in run.steps), 1), facts=facts,
                wrote=[str(out / f) for f in wrote], next=next_after(out, facts and facts["waiting"]))


def loaded(a: dict, verb: str) -> dict:  # a command's file: the one named, else the workspace's file loaded last
    if a["input"]:
        return a
    if not a.get("workspace") or not (parts := folder.parts(Path(a["workspace"]))):
        raise InputError(f"no file to {verb}", fix=f"name one: nayose {verb} records FILE; or load one into the workspace first")
    return {**a, "input": str(parts[-1])}


def check_records(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    a = loaded(a, "check")
    with readable(a["input"], s, emit=emit) as path:
        return checked(a, s, p, path, emit)


def checked(a: dict, s, p, path: str, emit: "Emit") -> dict:
    parts = folder.parts(Path(a["workspace"])) if a.get("workspace") else []
    own = bool(parts) and Path(a["input"]).resolve() == parts[-1].resolve()  # the file a run given none reads
    run = Run(p, s, echo=emit.step, told=emit.progress)
    run.load(path)
    plan = run.budget(stop=False)
    fill = fill_rates(run).set_index("field")
    shown = plan[(plan["oversized_blocks"] > 0) | plan["name"].isin(plan.nlargest(5, "per_record")["name"])].sort_values("per_record", ascending=False)
    fields = [dict(field=f, filled=fill.loc[f, "filled"], looks_right=fill.loc[f, "looks_right"], top_value=fill.loc[f, "top_value"],
                   columns=sources_text(run.present[f])) if f in fill.index else dict(field=f, filled=None, looks_right=None, top_value=None, columns=None)
              for f in run.fields]
    keys = [dict(key=x.name, per_record=x.per_record, largest_block=x.largest_block, oversized_blocks=x.oversized_blocks,
                 oversized_records=x.oversized_records) for x in shown.itertuples()]
    limit, spill = run.con.execute("SELECT current_setting('memory_limit'), current_setting('temp_directory')").fetchall()[0]
    needed, fit, read = int(plan["normal"].sum()), run.capacity(), read_of(Path(path))
    capacity = dict(memory_limit_gb=round(size_bytes(limit) / 2**30, 2), spill_folder=spill, spill_free_gb=round(run.spill_room() / 2**30, 1),
                    pairs_needed=needed, pairs_fit=fit, headroom=round(fit / needed, 1) if needed else None)
    try:  # what describe records said of the file's fields, kept with a workspace's file: its hints, while nothing they rest on changed
        k = json.loads((Path(path) / KEPT).read_text(encoding="utf-8"))
        kept = {f["field"]: f.get("hint") for f in k["described"]["fields"]} if k["key"] == described_key(a, Path(path)) else {}
    except (OSError, ValueError, KeyError, TypeError):
        kept = {}
    return plain(dict(records=run.n, fields=fields, turned_off=run.disabled, keys=keys, oversized_from=p.fs.budget.min_oversized(), notes=run.notes, read=read,
                      capacity=capacity, ready=ready_for(run, fields, plan, capacity, read, kept),
                      next=[dict(command=nayose("resolve", "records", *([] if own else [a["input"]]), "--workspace", a.get("workspace") or "<workspace>"),
                                 why="find matches")]))


def ready_for(run: Run, fields: list[dict], plan: pd.DataFrame, capacity: dict, read: dict | None, hints: dict | None = None) -> dict:
    """Whether a run of the file checked would go through, and what may hurt it: what would stop it (its pairs over
    the room DuckDB has; a mistake in the file or the mapping stops the check itself, with its fix), and what to
    look at first (a field nearly empty, or whose values don't look like it, said as describe records' hint where it
    gave one; repairs waiting; rows unread; records set aside; little room to spare). Each a sentence, with what to do."""
    stops, warns = [], []
    needed, fit = capacity["pairs_needed"], capacity["pairs_fit"]
    if needed > fit:  # the numbers themselves: the headroom shown is rounded
        most = ", ".join(f"{x.name} {x.normal:,}" for x in plan.nlargest(3, "normal").itertuples())
        stops.append(dict(what=f"the pairs ({capacity['pairs_needed']:,}) are more than fit in memory and the spill disk ({capacity['pairs_fit']:,}); the most: {most}",
                          fix="give DuckDB more room: --compute memory_limit=… temp_directory=<a disk with space>"))
    elif 2 * needed > fit:
        warns.append(dict(what=f"the pairs fill {needed / fit:.0%} of the room DuckDB has", fix="a larger file may not fit: give it more memory or spill disk"))
    filled = {f["field"]: f["filled"] for f in fields if f["filled"] is not None}
    either = {f for group in run.pipeline.fields.one_of for f in group}  # a person's or a company's name: each filled only for its kind, so together
    columns = lambda f: {c for alt in run.present.get(f) or () for c in alt}
    for group in [*run.pipeline.fields.one_of, *([f] for f in filled if f not in either)]:
        have = [f for f in group if f in filled]
        apart = len(set().union(*map(columns, have))) == sum(len(columns(f)) for f in have)  # one column for both: counted once
        if have and (share := (sum if apart else max)(filled[f] for f in have)) < 0.3:
            warns.append(dict(what=f"{' and '.join(map(word, have))} {'are' if len(have) > 1 else 'is'} {share:.0%} filled" + (" together" if len(have) > 1 else ""),
                              fix="map a fuller column, if the file has one"))
    for f in fields:
        if (h := (hints or {}).get(f["field"])) and h["level"] == "warn" and f["filled"]:
            warns.append(dict(what=f"{word(f['field'])}: {h['says']}", fix=h.get("command") or h["fix"]))
        elif f["looks_right"] is not None and f["filled"] and f["looks_right"] < WARN:
            warns.append(dict(what=f"only {f['looks_right']:.0%} of {word(f['field'])} values look right", fix=f"check its column ({f['columns']})"))
    if read and read["waiting"]:
        warns.append(dict(what=f"repairs wait: {', '.join(f'{n:,} {k}' for k, n in read['waiting'].items())}", fix="see them with describe records, then accept repairs KIND"))
    if read and read["unread"]:
        warns.append(dict(what=f"{read['unread']:,} rows couldn't be read", fix="they are in unread.parquet in the file's part: fix the file and load it again"))
    if aside := run._count("set_aside"):
        warns.append(dict(what=f"{aside:,} records are set aside (no ID, or one ID with different content)", fix="the run leaves them out: set_aside/ says why"))
    return dict(ok=not stops, stops=stops, warns=warns)


def list_columns(a: dict, emit: "Emit") -> dict:
    path = columns_file(a.get("workspace")) or settings_path()
    found = []
    for f, spec in toml_of(path)["columns"].items():
        src = spec["sources"] if isinstance(spec, dict) else spec
        alts = [[src]] if isinstance(src, str) else src
        options = " · ".join(f"{k} {v if isinstance(v, str) else ' '.join(v)}" for k, v in spec.items() if k != "sources") if isinstance(spec, dict) else ""
        found.append(dict(field=f, columns=", ".join(" + ".join(x) for x in alts), options=options))
    there = ["--workspace", a["workspace"]] if a.get("workspace") else []
    return dict(settings=str(path), own=path.name == COLUMNS, columns=found, rerun_owed=rerun_owed(a),
                next=[dict(command=nayose("set", "columns", "FIELD=COLUMN", *there), why="map a field to other columns"),
                                                         dict(command=nayose("check", "records", "<file>"), why="check a file with this mapping")])


def set_columns_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    known = {*p.fields.declared(), *SPECIAL, *s.columns}
    mapping = {}
    for item in a["mapping"]:
        f, sep, cols = item.partition("=")
        if not sep or not f:
            raise InputError(f"{item}: write FIELD=COLUMNS", fix="for example phone=TEL4, or person_name=NAME_KANA,SEI+MEI: "
                             "a comma between fallbacks, + between columns joined, nothing after = to remove the field")
        if f not in known:
            raise InputError(f"{f}: no such field", fix=f"the fields: {', '.join(sorted(known))}")
        mapping[f] = tuple(tuple(c.strip() for c in alt.split("+")) for alt in cols.split(",")) if cols else ()
    write_mapping(a.get("workspace"), mapping)
    return {**list_columns(a, emit), "next": [dict(command=nayose("check", "records", "<file>"), why="check a file with the new mapping")]}


def write_mapping(ws: str | None, mapping: dict, update: dict | None = None) -> None:  # the workspace's own mapping (else the project's), rewritten by settings.set_columns
    if ws and not Path(ws).is_dir():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    with folder.writing(Path(ws) / COLUMNS if ws else settings_path()):
        if ws and not columns_file(ws):  # a workspace made before it kept its own mapping starts from the project's
            (Path(ws) / COLUMNS).write_text(own_columns(settings_path()), encoding="utf-8")
        set_columns(columns_file(ws) or settings_path(), mapping, update=update)


def set_preparation(a: dict, emit: "Emit") -> dict:
    s, steps, mapping, update = settings_for(a), [x for x in get_args(Normalizer) if x != "one_byte"], {}, {}  # one_byte: a comparison's own copy
    for item in a["mapping"]:
        f, sep, said = item.partition("=")
        chosen = [x.strip() for x in said.split(",") if x.strip()]
        if not sep or not f:
            raise InputError(f"{item}: write FIELD=STEPS", fix="for example phone=nfkc,strip_separators: the steps in order, nothing after = for none")
        if f not in s.columns or f in SPECIAL:
            raise InputError(f"{f}: no field the mapping prepares", fix=f"its fields: {', '.join(x for x in s.columns if x not in SPECIAL)}")
        if bad := [x for x in chosen if x not in steps]:
            raise InputError(f"{', '.join(bad)}: no such step", fix=f"the steps: {', '.join(steps)}")
        mapping[f], update[f] = s.columns[f], {"normalize": chosen or None}
    ws = a.get("workspace")
    write_mapping(ws, mapping, update)
    return {**list_columns(a, emit), "next": [dict(command=nayose("rerun", "records", "--workspace", ws), why="match again, its values prepared so")] if ws else
            [dict(command=nayose("check", "records", "<file>"), why="check a file with the new preparation")]}


def model_from(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"--model {path}: {e}", fix="give the JSON a run saved (state/model.json), or leave --model out to fit one on the file") from None
    return saved.get("model", saved)


def given(a: dict, emit: "Emit | None" = None) -> str:
    """The records a run reads: the file named, copied into the workspace first; without one, the file loaded last,
    read again first if an older reader read it (folder.fresh)."""
    ws, s, told = Path(a["workspace"]), settings_for(a), rows_told(emit)
    if a["input"]:
        return str(folder.take_in(ws, a["input"], s.input, s.paths["reference"], progress=told)[0])
    if not (parts := folder.parts(ws)):
        raise InputError(f"no records file in {ws}", fix=f"load one: nayose load records FILE --workspace {ws}; or name it here")
    return str(folder.fresh(parts[-1], s.input, s.paths["reference"], told))


def rows_told(emit: "Emit | None"):  # the rows read so far, for a file being read
    return emit and (lambda n, whole: emit.progress(n, whole, "rows"))


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
DESCRIBING = hashlib.sha256(b"".join([*((Path(__file__).parent / f).read_bytes() for f in ("cli.py", "source.py", "settings.py", "intake.py", "config.py")),
                                      duckdb.__version__.encode(), unicodedata.unidata_version.encode()])).hexdigest()


def described_key(a: dict, part: Path) -> str | None:
    """All a workspace part's description rests on, as one hash: the part's files as read (their SHA-256, and the repairs
    accepted), the workspace's mapping and method, the settings and the pipeline, the reference names and places, the
    command's words, the code and its libraries.
    None for anything but a workspace's part: a file read for one command alone is read again anyway."""
    r, ws = intake.report(part), a.get("workspace")
    if not r or not ws or not Path(a["input"]).expanduser().is_dir():
        return None
    s = settings_for(a)
    ref = sorted((f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in Path(s.paths["reference"]).glob("*") if f.is_file())
    words = json.dumps([[x["sha256"], x.get("versions")] for x in r["files"]] + [r["accepted"], str(a["input"]), str(ws), ref, DESCRIBING])
    files = (settings_path(), columns_file(ws), Path(a.get("pipeline") or s.root / "config" / "final.toml"), Path(ws) / folder.METHOD)
    rests = [words.encode(), *(Path(f).read_bytes() if f and Path(f).is_file() else b"" for f in files)]  # each in its place: one missing is never another
    return hashlib.sha256(b"\0".join(rests)).hexdigest()


def describe_records(a: dict, emit: "Emit") -> dict:
    """A workspace part's description is kept with it (KEPT) and given again while nothing it rests on changed
    (described_key): opening step 2 reads no record. Anything else is described as it comes. O(1) kept; else describe's."""
    a = loaded(a, "describe")
    with readable(a["input"], settings_for(a), emit=emit) as path:
        part = Path(path)
        key, kept = described_key(a, part), part / KEPT
        try:  # a copy kept never fails the command: unreadable, it is made again
            old = json.loads(kept.read_text(encoding="utf-8")) if key and kept.is_file() else {}
        except (OSError, ValueError):
            old = {}
        if key and old.get("key") == key:
            d = old["described"]
        else:
            d = plain(described({**a, "given": a["input"], "input": path}))
            if key and described_key(a, part) == key:  # nothing changed while it was read (another client's mapping), and the part is still there
                with contextlib.suppress(OSError):  # another describe writing it, a folder people can only read: kept another time
                    replace_text(kept, json.dumps({"key": key, "described": d}, ensure_ascii=False))
        return {**d, "read": read_of(part)}


def described(a: dict) -> dict:
    (s, p, _), there = setup(a), ["--workspace", a["workspace"]] if a.get("workspace") else []
    feats = features_of(a.get("workspace"))
    script = {path: f.get("script") for g in feats for f in g["features"] for path, _ in slots([dict(g, features=[f])])}
    def field(path: str, x: dict) -> str | None:  # whose pattern a slot's values should match: none in a script the patterns aren't written in
        if script[path] not in (None, "kana"):
            return None
        return (None if x.get("added") else x.get("field")) or SLOT_FIELD.get(x.get("role") or x.get("type"))
    con = connect(s.compute)[0]
    d = describe(a["input"], con, s.columns, s.detect, lex=lexicon(s.paths["reference"], tuple(s.standardize.kana_fold.items())),
                 slots={path: x["columns"] for path, x in slots(feats)},
                 slot_patterns={**{path: s.detect[f] for path, x in slots(feats) if (f := field(path, x)) in s.detect},
                                **{path: FLAG for path, x in slots(feats) if x.get("type") == "flag"}})
    try:  # what a run of this file would turn off, as the run decides it: from the mapping, no record read
        counted_once(p, present := present_fields(s, [c["column"] for c in d["columns"]]))
        off = restrict(p, set(present))[1]
    except InputError as e:
        off = [str(e)]
    said = hints(d, con, s, p, feats, a.get("workspace"), field)
    for x in d["slots"]:
        x["hint"] = said.get(x["feature"])
    by_field = {}
    for path, x in slots(feats):
        if said.get(path) and (f := field(path, x)):
            by_field.setdefault(f, said[path])
    for x in d["fields"]:
        x["hint"] = by_field.get(x["field"])
    d = {**d, "features": feats, "placements": placements(feats, d["profile"], d["fit"]), "offers": offers(feats, d["profile"]),
         "needed": dict(every=list(p.fields.mandatory), one_of=[list(g) for g in p.fields.one_of]), "turned_off": off, "names_by_kind": names_by_kind(s)}
    found = [f"{x['feature']}={x['column']}" for x in d["placements"]]
    waiting = (intake.report(Path(a["input"])) or {}).get("proposed", {}) if there else {}
    fixes = list({h["command"]: h for h in said.values() if h.get("command")}.values())  # one fix a line, the slots' order
    return {**d, "next": [dict(command=h["command"], why=h["fix"]) for h in fixes] +
            [dict(command=nayose("accept", "repairs", k, *there), why=f"{n:,} proposed: see them first, in read.examples") for k, n in waiting.items()] +
            ([dict(command=nayose("set", "feature", *found, *there), why="place what the file's contents suggest")] if found and there else []) +
            [dict(command=nayose("resolve", "records", *there) if there else nayose("check", "records", a["given"]),
                  why="find matches in it" if there else "the full check: every record prepared, every key counted")]}


WARN = 0.5  # under this share of a slot's values that look like it, its column likely holds something else: a hint says what


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


def load_records(a: dict, emit: "Emit") -> dict:
    ws, s = Path(a["workspace"]), settings_for(a)
    part, copied = folder.take_in(ws, a["input"], s.input, s.paths["reference"], progress=lambda n, whole: emit.progress(n, whole, "rows"))
    return {**describe_records({**a, "input": str(part)}, emit), "loaded": str(part), "copied": copied}


def run_pipeline(ws: str | Path | None) -> str | None:  # the pipeline file the workspace's full run used, as its log says (none said: before it did)
    return next((r.get("pipeline") for r in folder.runs(Path(ws)) if not r.get("part")), None) if ws and Path(ws).is_dir() else None


def rerun_owed(a: dict) -> bool:
    """Whether the workspace's run read its records with another mapping or method than these now, under the pipeline
    it ran (its state/config.txt, as an increment checks it): the run reads them so once it runs again. No run, or a
    workspace or method refused where it is read: False."""
    ran_with = Path(a["workspace"]) / "state" / "config.txt" if a.get("workspace") else None
    if ran_with is None or not ran_with.is_file():
        return False
    try:
        s, p, _ = setup({**a, "pipeline": a.get("pipeline") or run_pipeline(a["workspace"])})
    except InputError:
        return False
    return ran_with.read_text(encoding="utf-8") != run_config(p, s)


def list_features(a: dict, emit: "Emit") -> dict:
    feats = features_of(a.get("workspace"))
    return dict(features=feats, slots=[dict(feature=path, columns=sources_text(x["columns"])) for path, x in slots(feats)], rerun_owed=rerun_owed(a),
                next=[dict(command=nayose("set", "feature", "GROUP/FEATURE=COLUMN", *(["--workspace", a["workspace"]] if a.get("workspace") else [])),
                           why="put a column into a feature")])


def set_feature(a: dict, emit: "Emit") -> dict:
    values = {}
    for item in a["mapping"]:
        path, sep, cols = item.partition("=")
        if not sep or not path:
            raise InputError(f"{item}: write GROUP/FEATURE=COLUMNS", fix="for example \"Name/Full name/Family name=SEI\": a comma between "
                             "fallbacks, + between columns joined, nothing after = for no column")
        values[path] = tuple(tuple(c.strip() for c in alt.split("+")) for alt in cols.split(",")) if cols else ()
    with folder.writing(Path(a["workspace"]) / COLUMNS):
        set_features(a["workspace"], values)
    return {**list_features(a, emit), "next": [dict(command=nayose("describe", "records", "<file>", "--workspace", a["workspace"]), why="see how the file fills them")]}


def set_names(a: dict, emit: "Emit") -> dict:
    ws = Path(a["workspace"])
    if not (f := columns_file(ws)):
        raise InputError(f"{ws} keeps no mapping of its own", fix=f"create it as a workspace first: nayose create workspace {ws.name}")
    with folder.writing(f):
        set_name_kinds(f, a["how"] == "by-kind")
    lines = [x for x in f.read_text(encoding="utf-8").splitlines() if x.split("=")[0].strip() in ("full_name", "person_name", "company_name")]
    return dict(names=a["how"], mapping=lines, rerun_owed=rerun_owed(a), next=[dict(command=nayose("describe", "records", "--workspace", ws), why="see the names checked again"),
                                                    dict(command=nayose("resolve", "records", "--workspace", ws), why="match with it")])


def add_feature_(a: dict, emit: "Emit") -> dict:
    with folder.writing(Path(a["workspace"]) / COLUMNS):
        add_feature(a["workspace"], a["path"], a["type"], a["script"], a["column"])
    return {**list_features(a, emit), "next": [dict(command=nayose("describe", "records", "<file>", "--workspace", a["workspace"]), why="see how the file fills it")]}


def remove_feature_(a: dict, emit: "Emit") -> dict:
    with folder.writing(Path(a["workspace"]) / COLUMNS):
        remove_feature(a["workspace"], a["path"])
    return list_features(a, emit)


def accept_repairs(a: dict, emit: "Emit") -> dict:
    s, ws, kind = settings_for(a), Path(a["workspace"]), a["kind"]
    have = [(p, r) for p in folder.parts(ws) if (r := intake.report(p))]
    pick = ([(p, r) for p, r in have if a["part"] in (p.name, p.name.split("-", 1)[0], p.name.split("-", 1)[0].lstrip("0"))] if a["part"]
            else [(p, r) for p, r in have if r["proposed"].get(kind) and kind not in r["accepted"]][-1:])
    if not pick:
        raise InputError(f"{ws}: no loaded file {a['part']}" if a["part"] else f"{ws}: no loaded file has {kind} repairs waiting",
                         fix=f"the files loaded, and what waits in each: {nayose('describe', 'workspace', ws)}")
    part, r = pick[0]
    if kind in r["accepted"] or not r["proposed"].get(kind):
        raise InputError(f"{part.name}: {'its ' + kind + ' repairs are accepted already' if kind in r['accepted'] else 'no ' + kind + ' repair waits'}",
                         fix=f"what waits: {nayose('describe', 'records', part, '--workspace', ws)}")
    with folder.run_lock(ws):
        new = intake.accept(part, kind, s.input, s.paths["reference"])
    again = (ws / "gold.parquet").is_file()
    return dict(part=part.name, kind=kind, repaired=r["proposed"][kind], rows=new["rows"], added=new["rows"] - r["rows"], read=read_of(part),
                next=[dict(command=nayose("rerun", "records", "--workspace", ws), why="a run read the file before: run it again to use them") if again
                      else dict(command=nayose("resolve", "records", "--workspace", ws), why="find matches")])


def create_workspace(a: dict, emit: "Emit") -> dict:
    ws = folder.create(Path(a["home"] or "workspaces"), a["name"], own_columns(settings_path()))
    return dict(workspace=str(ws), next=[dict(command=nayose("load", "records", "<file>", "--workspace", ws), why="give it your records file")])


def list_workspaces(a: dict, emit: "Emit") -> dict:
    home = Path(a["home"] or "workspaces")
    return dict(home=str(home), workspaces=folder.workspaces(home),
                next=[dict(command=nayose("create", "workspace", "<name>", *(["--home", home] if a["home"] else [])), why="start a new one")])


def resolve_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    return after_run(Run(p, s, model=model_from(a["model"]), echo=emit.step, told=emit.progress).full(given(a, emit), out, overwrite=a["overwrite"], pipeline_file=pipeline), out)


def add_records(a: dict, emit: "Emit") -> dict:
    """A batch copied in, then added; a copy that adds nothing, or that is refused before anything is written (a column
    the run reads, missing), is not kept, so the file the run read stays the file loaded last. A file loaded before
    is never removed."""
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    held = [x for x in folder.parts(out) if a["input"] and Path(a["input"]).expanduser().resolve() == x.resolve()]  # a part loaded already: as it is
    part, copied = ((folder.fresh(held[0], s.input, s.paths["reference"], rows_told(emit)), False) if held else
                    folder.take_in(out, a["input"], s.input, s.paths["reference"], progress=rows_told(emit)) if a["input"] else (Path(given(a, emit)), False))
    try:
        run = Run(p, s, echo=emit.step, told=emit.progress).increment(part, out, pipeline_file=pipeline)
    except InputError as e:
        if copied and not isinstance(e, Busy):  # another job may hold it now
            shutil.rmtree(part, ignore_errors=True)
        raise
    if run.added == 0:  # a copy made for this goes; a file loaded before stays, whatever it holds (its values may differ from the run's)
        mine = next((x for x in folder.loaded(out) if Path(x["path"]).resolve() == part.resolve()), {})
        if copied:
            shutil.rmtree(part, ignore_errors=True)
        return dict(summary=[["nothing new", f"every ID of {mine.get('given') or Path(a['input'] or part).name} is in the run already"]],
                    next=next_after(out))
    return after_run(run, out)


def match_records(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    with readable(a["input"], s, emit=emit) as path:
        found = Run(p, s, echo=emit.step, told=emit.progress).match(path, out)
    return dict(counts={k: int(v) for k, v in found["status"].value_counts().items()}, records=rows(ids(found, s.data.unique_id)),
                next=[dict(command=nayose("add", "records", a["input"], "--workspace", out), why="add them to the run")])


def build_index(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws = Path(a["workspace"])
    return {**index.build(ws, s, p), "next": [dict(command=nayose("match", "record", "COLUMN=VALUE", "--workspace", ws), why="look a record up"),
                                              dict(command=nayose("open", "ui", "--workspace", ws), why="or look up in the browser")]}


def typed_values(items: list[str] | None) -> dict[str, str]:  # COLUMN=VALUE words, by the file's column names
    values = {}
    for item in items or []:
        column, sep, value = item.partition("=")
        if not sep or not column:
            raise InputError(f"{item}: write COLUMN=VALUE", fix='for example FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234, by the file\'s column names')
        values[column] = value
    return values


def ranked(a: dict, most: int) -> tuple[float | None, int]:  # --from points, and --count entities
    return number(a["from"], "--from", "points, for example 6") if a["from"] else None, counted(a, "count", most)


def match_record(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws, values = Path(a["workspace"]), typed_values(a["values"])
    if bool(values) == bool(a["record"]):
        raise InputError("give a record's values, or --record ID, one of them", fix="for example: nayose match record PHONE_NUM_4=1234 --workspace W")
    at_least, most = ranked(a, 20)
    found = index.look_up(ws, s, p, values=values or None, record=a["record"], at_least=at_least, most=most)
    return {**found, "next": [dict(command=nayose("show", "records", found["entities"][0]["record"], "--workspace", ws), why="its full row")] if found["entities"] else []}


def search_records(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws, values = Path(a["workspace"]), typed_values(a["values"])
    at_least, most = ranked(a, 10)
    found = index.search(ws, s, p, values, at_least=at_least, most=most)
    return {**found, "next": [dict(command=nayose("match", "record", *(f"{k}={v}" for k, v in values.items()), "--workspace", ws), why="what a run would do with it")]}


def rerun_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    return after_run(Run(p, s, echo=emit.step, told=emit.progress).rerun(out, pipeline_file=pipeline), out)


def try_method(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws, now = Path(a["workspace"]), folder.method(Path(a["workspace"]))
    rules, keys = {r.name for _, _, r in p.rules.each()}, {b.name for b in p.fs.blockers}
    if bad := [x for x in a.get("drop") or [] if x not in rules | keys]:
        raise InputError(f"--drop {' '.join(bad)}: no match rule or pair key of the method has that name", fix="see them: nayose describe method --workspace …")
    method = {**now, **({"line": number(a["line"], "--line")} if a.get("line") else {})}
    declared = p.fields.declared()
    if bad := [x for x in a.get("add") or [] if not all(f.split(":")[0] in declared for f in x.split("+"))]:
        raise InputError(f"--add {' '.join(bad)}: a field the pipeline doesn't declare", fix=f"its fields: {', '.join(sorted(declared))}; join a key's fields with +")
    if a.get("add"):  # each a key's fields joined by +, as describe method proposes it
        method["add_keys"] = [list(k) for k in dict.fromkeys([*map(tuple, now.get("add_keys", [])), *(tuple(x.split("+")) for x in a["add"])])]
    for name, among in (("drop_rules", rules), ("drop_keys", keys)):
        if dropped := sorted({*now.get(name, []), *(x for x in a.get("drop") or [] if x in among)}):
            method[name] = dropped
    if method == now:
        raise InputError("nothing to try: that is the method as it is", fix="give --line, --drop with rules or keys to leave out, or --add with a key to add")
    if not (ws / "gold.parquet").exists():
        raise InputError(f"no run in {ws} to try a method against", fix="find matches first: nayose resolve records --workspace …")
    result = trial(ws, p, setup(a, method)[1], method, s, echo=emit.step)
    return {**result, "next": [dict(command=nayose("adopt", "method", "--workspace", ws, "--trial", result["trial"]), why="adopt it, and find matches with it")]}


def number(text: str, what: str, fix: str = "a weight in bits, for example 9 or 9.5") -> float:
    try:
        return float(text)
    except ValueError:
        raise InputError(f"{what} {text}: not a number", fix=fix) from None


def adopt(a: dict, emit: "Emit", method: dict) -> dict:
    """The workspace's method.toml set to `method` ({}: none, the tuned method), then a run with it; method.toml as it
    was if the run fails, so the method and the run always agree."""
    ws = Path(a["workspace"])
    path, old = ws / folder.METHOD, (ws / folder.METHOD).read_text(encoding="utf-8") if (ws / folder.METHOD).exists() else None
    with folder.run_lock(ws):  # held through the run: no other writer sees the new method before its run
        setup(a, method)  # a method that no longer fits the pipeline is refused before anything changes
        folder.write_method(ws, method)
        try:
            return rerun_records(a, emit)
        except BaseException:
            if old is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(old, encoding="utf-8")
            raise


def adopt_method(a: dict, emit: "Emit") -> dict:
    ws = Path(a["workspace"])
    f = ws / folder.TRIALS / f"{a['trial']}.json"
    if not f.exists():
        raise InputError(f"no trial {a['trial']} in {ws}", fix="try it first: nayose try method --workspace …; the last 5 trials are kept")
    tried, merge = json.loads(f.read_text(encoding="utf-8"))["method"], folder.method(ws).get("merge")  # people's merge conditions as they are now, not as at the trial
    return adopt(a, emit, {**{k: v for k, v in tried.items() if k != "merge"}, **({"merge": merge} if merge else {})})


def reset_method(a: dict, emit: "Emit") -> dict:  # the method as tuned; people's trust line and merge conditions stay, unless they no longer read or fit
    try:
        setup(a, kept := {k: v for k, v in folder.method(Path(a["workspace"])).items() if k in ("trust", "merge")})
    except InputError:  # the way out every refusal of method.toml names: nothing of it kept
        kept = {}
    return adopt(a, emit, kept)


def lower_trust(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws = Path(a["workspace"])
    state = trust_state(connect(s.compute)[0], ws, p, s.data.unique_id) if (ws / "gold.parquet").exists() else None
    if state is None:
        raise InputError(f"{ws} has no trust line: it merges as tuned", fix="start one, and nothing merges before people check: nayose raise trust --workspace …")
    if not state["may_lower"]:
        span = state["next"]
        if span and state["false"]:  # proven false: no count of checks lowers it
            raise InputError(f"people found {state['false']:,} pair{'s' if state['false'] > 1 else ''} of the range below the line different: the line stays",
                             fix="decide its pairs, and those below, one by one: nayose list pairs --workspace … --open")
        raise InputError(f"the range below the line isn't proven yet: {state['checked']:,} of {state['needed']:,} checked"
                         if span else "the trust line is at its last step", fix="check the range's pairs: nayose list pairs --workspace … --open" if span else "")
    return adopt(a, emit, {**folder.method(ws), "trust": state["next"]["down_to"]})


def raise_trust(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws, line = Path(a["workspace"]), p.trust.line
    if line is not None and math.isinf(line):
        raise InputError("the trust line is above every step already: nothing merges before people check", fix="")
    up = [x for x in p.trust.steps if line is not None and x > line]
    return adopt(a, emit, {**folder.method(ws), "trust": min(up) if up else "none"})


def draw_pairs(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out, count = Path(a["workspace"]), int(number(a.get("count") or "50", "--count", "a count of pairs, for example 50"))
    run = Run(p, s, echo=emit.step, told=emit.progress).draw(out, count)
    step = run.steps[-1]
    return dict(drawn=step["drawn"], decide=step["decide"], next=[dict(command=nayose("list", "pairs", "--workspace", out, "--open"), why="the pairs to decide and audit")])


def describe_workspace_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    d = describe_workspace(connect(s.compute)[0], out, s.data.unique_id)
    d["trust"] = trust_state(connect(s.compute)[0], out, p, s.data.unique_id) if d["records"] else None
    files = folder.loaded(out)
    then = ([dict(command=nayose("describe", "results", "--workspace", out), why="what the run found, and what waits for you"),
             dict(command=nayose("open", "ui", "--workspace", out), why="review in the browser")] if d["records"] else
            [dict(command=nayose("resolve", "records", "--workspace", out), why="find matches in the file loaded last")] if files else
            [dict(command=nayose("load", "records", "<file>", "--workspace", out), why="give it your records file")])
    then = [dict(command=nayose("describe", "records", f["path"], "--workspace", out), why=f"{f['waiting']:,} repairs wait in {f['name']}: see them, then accept repairs")
            for f in files if f.get("waiting")] + then
    owed = bool(d["records"]) and rerun_owed(a)
    used = run_pipeline(out)
    again = ["--pipeline", used] if used and Path(used) != Path(s.root / "config" / "final.toml").resolve() else []  # the run's own, not the default
    then = [dict(command=nayose("rerun", "records", "--workspace", out, *again), why="the mapping or the method changed since the run: match again to read the records so")] * owed + then
    told = out / "auto" / "report.md"  # the last auto mode's report, to send
    auto = dict(report=str(told), markdown=told.read_text(encoding="utf-8")) if told.is_file() else None
    return {**d, "inputs": files, "columns": "own" if columns_file(out) else "project", "auto": auto, "index": index.status(out, s), "rerun_owed": owed, "next": then}


def describe_entity_(a: dict, emit: "Emit") -> dict:
    s, out = settings_for(a), Path(a["workspace"])
    uid = s.data.unique_id
    con, db = connect(s.compute)
    d = describe_entity(con, out, uid, a["id"], [f for f in s.columns if f not in SPECIAL])
    if folder.method(out).get("merge"):  # merged by the workspace's conditions since the run: the links its files don't hold
        more, pair = merged_links(con, db, out, s, setup(a)[1], d["records"][uid].tolist()), [f"{uid}_l", f"{uid}_r"]
        more = more[~more.set_index(pair).index.isin(d["links"].set_index(pair).index)]
        d["links"] = pd.concat([d["links"], more], ignore_index=True)
    inside = entity_pairs(out, s, d["records"][uid].tolist(), rows(d["links"]))
    return dict(record=d["record"], entity=d["entity"], size=d["size"], records=rows(ids(d["records"], uid)), links=rows(ids(d["links"], uid)), **inside,
                next=[dict(command=nayose("explain", "pair", "<ID>", "<ID>", "--workspace", out), why="how one pair was scored"),
                      dict(command=nayose("list", "pairs", "--workspace", out), why="the pairs for people")])


def explain_pair_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    d = explain_pair(out, p, s, a["first"], a["second"])
    return {**d, "next": [dict(command=nayose("decide", "pair", d["id_l"], d["id_r"], "match", "--workspace", out), why="decide it, if it is on the sheet"),
                          dict(command=nayose("describe", "entity", d["id_l"], "--workspace", out), why="the customer of the first")]}


def describe_key_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    d = describe_key(out, p, s, a["name"])
    return {**d, "next": [dict(command=nayose("explain", "pair", x[0], x[1], "--workspace", out), why="a link only this key found") for x in d["examples"][:1]]}


def compare_records_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    d = compare_records(out, p, s, a["first"], a["others"])
    return {**d, "next": [dict(command=nayose("explain", "pair", d["first"], x["id"], "--workspace", out), why="how one of them scored")
                          for x in d["candidates"][:1]]}


def list_patterns_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    if not (out / "gold.parquet").exists():
        raise InputError(f"no run in {out}", fix="find matches first: nayose resolve records --workspace …")
    return {**list_patterns(out, p), "next": [dict(command=nayose("explain", "pair", "<ID>", "<ID>", "--workspace", out), why="one of a pattern's pairs")]}


def describe_matching_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"]) if a["workspace"] else None
    return {**describe_matching(connect(s.compute)[0], out, p, s),
            "next": [dict(command=nayose("describe", "workspace", out), why="the workspace at a glance")] if out else
                    [dict(command=nayose("resolve", "records", "<file>", "--workspace", "<workspace>"), why="match records: the graph then holds their numbers")]}


def rehearse_records(a: dict, emit: "Emit") -> dict:
    from er import auto
    s, _, pipeline = setup(a)
    ws = Path(a["workspace"])
    if not ws.is_dir():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    src = a["input"] or next((str(x) for x in folder.parts(ws)[-1:]), None)  # its shape only: never copied in
    if not src:
        raise InputError(f"no records file in {ws}", fix=f"name one, or load it first: nayose load records FILE --workspace {ws}")
    with readable(src, s) as path:
        sh = auto.shape(s, path)
    r = auto.rehearse(ws, sh, s, Path(a["pipeline"]) if a.get("pipeline") else None, emit.step)
    if not r["ok"]:
        raise InputError(f"a file of {r['records']:,} records stopped here: {r['error']}", fix=r["fix"] or "give the run more room: --compute memory_limit=… temp_directory=…")
    return {**r, "next": [dict(command=nayose("resolve", "records", *([a["input"]] if a["input"] else []), "--workspace", ws), why="the real file, now its size is known to fit")]}


def try_everything(a: dict, emit: "Emit") -> dict:
    from er import auto
    trials = int(number(a["trials"], "--trials", "a count, for example 3")) if a.get("trials") else 3
    home = Path(a["home"] or "workspaces")
    r = auto.everything(a["input"], home, max(trials, 0), a["compute"] or [], a.get("pipeline"), emit.step)
    if r["workspace"] is None:
        if r["exit_code"] == 130:  # stopped before its workspace was made: nothing to report
            raise KeyboardInterrupt
        failed = r["facts"]["steps"][-1]
        raise InputError(failed["error"] or "the workspace could not be made", fix=failed.get("fix") or "")
    done = auto.written(r, a["input"], settings_for({"workspace": str(r["workspace"])}))
    steps = [{k: x[k] for k in ("step", "ok", "seconds", "error")} for x in r["facts"]["steps"]]
    return dict(workspace=str(r["workspace"]), ok=r["exit_code"] == 0, steps=steps, report=done["report"], values=done["values"],
                redacted=done["redacted"], markdown=done["markdown"], exit_code=r["exit_code"],
                next=[dict(command=f"cat {shlex.quote(done['report'])}", why="the report to send: it holds no record's value"),
                      dict(command=nayose("describe", "workspace", r["workspace"]), why="the workspace it made")])


def describe_review(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    if not (out / "gold.parquet").exists():
        raise InputError(f"no run in {out}", fix="find matches first: nayose resolve records --workspace …")
    per = number(a["seconds"], "--seconds", "seconds, for example 10") if a.get("seconds") else 10.0
    if not 0 < per < math.inf:
        raise InputError(f"--seconds {a['seconds']}: not a time a pair takes", fix="seconds above 0, for example 10")
    if p.trust.line is None:
        raise InputError(f"{out} has no trust line: it merges as tuned", fix="start one, and nothing merges before people check: nayose raise trust --workspace …")
    return {**review_workload(connect(s.compute)[0], out, p, s.data.unique_id, per),
            "next": [dict(command=nayose("list", "pairs", "--workspace", out, "--pending"), why="the pairs waiting now")]}


def describe_method_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out, tuned = Path(a["workspace"]), setup(a, {})[1]  # the method as tuned: what this one leaves out, in words
    have, keys = {x.name for _, _, x in p.rules.each()}, {b.name for b in p.fs.blockers}
    dropped = dict(rules=[dict(name=x.name, **rule_how(st, x)) for _, st, x in tuned.rules.each() if x.name not in have],
                   keys=[dict(name=b.name, **key_how(b)) for b in tuned.fs.blockers if b.name not in keys])
    return {**describe_method(out, p, s), "dropped": dropped, "next": [dict(command=nayose("list", "pairs", "--workspace", out, "--open"), why="the pairs left to decide")]}


def picked(frame: pd.DataFrame, a: dict) -> pd.DataFrame:  # the sheet's rows --why, --open and --pending ask for
    keep = pd.Series(True, index=frame.index)
    if a["why"]:
        keep &= frame["why"] == a["why"]
    if a["open"]:
        keep &= frame["status"] == "open"
    if a["pending"]:
        keep &= frame["status"] != "applied"
    return frame[keep]


def counts(frame: pd.DataFrame) -> dict[str, int]:  # rows by why and status
    return {f"{why} {status}": int(n) for (why, status), n in frame.groupby(["why", "status"]).size().items()}


def list_pairs(a: dict, emit: "Emit") -> dict:
    uid, out = settings_for(a).data.unique_id, Path(a["workspace"])
    pairs = sheet(out, "review.parquet")
    if pairs is None:
        raise InputError(f"no run in {out}", fix="resolve records into that folder first")
    done = pairs.merge(applied(out, uid), on=[f"{uid}_l", f"{uid}_r"], how="left", suffixes=("", "_applied"))["decision_applied"]
    pairs.insert(1, "status", np.where(done.notna() & (done == pairs["decision"]), "applied", np.where(pairs["decision"].notna(), "written in", "open")))
    return dict(counts=counts(pairs), pairs=rows(ids(picked(pairs, a), uid)), next=[dict(command=nayose("decide", "pair", "<ID>", "<ID>", "match", "--workspace", out), why="decide one"),
                                                    dict(command=nayose("apply", "decisions", "--workspace", out), why="apply the decisions written in")])


def split_entity(a: dict, emit: "Emit") -> dict:
    """An entity split at a link that alone holds it together: that pair decided different (Run.decide stores it with
    people's decisions), then a full run, which never accepts a pair people called different."""
    s, p, _ = setup(a)
    out, uid = Path(a["workspace"]), s.data.unique_id
    if len(a["between"] or []) != 2:
        raise InputError("--between takes the two records of the link", fix="nayose split entity ID --between A B --workspace …")
    first, second = sorted(map(str, a["between"]))
    d = describe_entity(connect(s.compute)[0], out, uid, a["id"], [f for f in s.columns if f not in SPECIAL])
    held = d["records"][uid].tolist()
    inside = entity_pairs(out, s, held, rows(d["links"]))
    if inside["capped"]:
        raise InputError(f"the entity of {a['id']} holds {d['size']:,} records: too many to find where it splits", fix="decide its pairs in Review instead: nayose list scored --record ID, then decide pair")
    if not {first, second} <= set(held):
        raise InputError(f"{first} and {second}: not both records of the entity of {a['id']}", fix="see its records: nayose describe entity ID --workspace …")
    if dict(id_l=first, id_r=second) not in inside["weakest"]:
        raise InputError(f"{first} – {second} doesn't hold the entity together: other links still join them",
                         fix="split it at one of its weakest links: nayose describe entity ID --workspace … lists them")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        f = Path(tmp) / "split.parquet"
        pd.DataFrame({f"{uid}_l": [first], f"{uid}_r": [second], "decision": ["no_match"], "why": ["split"]}).to_parquet(f, index=False)
        Run(p, s, echo=emit.step, told=emit.progress).decide(f, out)
    return rerun_records(a, emit)


def decide_pair(a: dict, emit: "Emit") -> dict:
    uid, out = settings_for(a).data.unique_id, Path(a["workspace"])
    first, second = sorted([a["first"], a["second"]])  # the sheet holds each pair lower ID first
    keys = {f"{uid}_l": first, f"{uid}_r": second}
    sheet, con, stored = out / "review.parquet", duckdb.connect(), None
    on = sheet.exists() and con.execute(f"SELECT count(*) FROM read_parquet({lit(sheet)}) WHERE {q(f'{uid}_l')} = ? AND {q(f'{uid}_r')} = ?", [first, second]).fetchall()[0][0]
    if not on and any((out / folder.SCORED).glob("*.parquet")):  # any pair the run kept may be decided: one the sheet lacks joins it
        stored = con.execute(f"""SELECT match_weight, sources FROM read_parquet({lit(out / folder.SCORED / '*.parquet')}, union_by_name = true)
            WHERE {q(f'{uid}_l')} = ? AND {q(f'{uid}_r')} = ? LIMIT 1""", [first, second]).fetchall()
    append = dict(why="decide", match_weight=stored[0][0], sources=stored[0][1]) if stored else None
    folder.type_in(out, "review.parquet", "decision", None if a["decision"] == "clear" else a["decision"], append, **keys)
    return dict(pair=[first, second], decision=a["decision"], next=[dict(command=nayose("apply", "decisions", "--workspace", out), why="apply them")])


def counted(a: dict, name: str, default: int) -> int:  # a page or a count: a whole number from 1
    v = a.get(name)
    if v in (None, ""):
        return default
    if not str(v).isdigit() or int(v) < 1:
        raise InputError(f"--{name} {v}: a whole number from 1", fix=f"for example --{name} {default}")
    return int(v)


def conditions(a: dict) -> dict | None:  # --conditions as JSON: {"join": "and"|"or", "when": [...]}
    if not a.get("conditions"):
        return None
    try:
        return json.loads(a["conditions"])
    except json.JSONDecodeError as e:
        raise InputError(f"--conditions: not JSON ({e.msg})", fix='for example --conditions \'{"join": "or", "when": [{"points": 12}]}\'') from None


def describe_results_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    con, db = connect(s.compute)
    out = Path(a["workspace"])
    frm = number(a["from"], "--from") if a.get("from") else review_floor(p)
    return {**describe_results(con, db, out, s, p, frm), "next": [dict(command=nayose("list", "scored", "--workspace", out, "--status", "waiting"), why="the pairs waiting for you")]}


def list_scored_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    con, db = connect(s.compute)
    num = lambda k: number(a[k], f"--{k}") if a.get(k) not in (None, "") else None
    r = list_scored(con, db, Path(a["workspace"]), s, p, num("from"), num("to"), a.get("source"), a.get("status"), a.get("record") or None,
                    counted(a, "page", 1), counted(a, "count", 100))
    for x in r["pairs"]:
        x["found"] = found_words(p, x)
    return r


def found_words(p, pair: dict) -> str:  # how a pair was found, in words: its rule's tests, else its first keys
    if pair.get("rule"):
        for _, st, rule in p.rules.each():
            if rule.name == pair["rule"]:
                test = lambda c: {"exact": f"same {word(c)}", "jaro_winkler": f"{word(c)} similar", "hamming": f"{word(c)} 1 digit off"}.get(
                    st.comparators[c].function, f"{word(c)} ≤ {num(st.comparators[c].threshold)} edits")
                return "rule: " + ", ".join([*(f"same {word(c)}" for c in rule.exact), *map(test, rule.fuzzy)])
        return f"rule {pair['rule']}"
    keys = (pair.get("sources") or "").split("+")
    return "keys: " + ", ".join(k.replace("sn_", "sorted ").replace("_", " ") for k in keys[:2]) + (" …" if len(keys) > 2 else "") if keys[0] else ""


def list_entities_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    return list_entities(connect(s.compute)[0], Path(a["workspace"]), s, p, counted(a, "smallest", 2), a.get("record") or None,
                         counted(a, "page", 1), counted(a, "count", 100))


def show_records_(a: dict, emit: "Emit") -> dict:
    s = settings_for(a)
    return show_records(connect(s.compute)[0], Path(a["workspace"]), s, list(dict.fromkeys(a["ids"])))


def describe_merging_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    con, db = connect(s.compute)
    out, m = Path(a["workspace"]), conditions(a)
    return describe_merging(con, db, out, s, p, None if m is None else check_merging(m, p, run_model(out)))


def set_merging(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    m = check_merging(conditions(a) or {}, p, run_model(out))  # the run's own comparisons: a field the file lacks has none
    con, db = connect(s.compute)
    with folder.run_lock(out):
        old = folder.method(out)
        save_merging(out, m)
        try:
            r = apply_merging(con, db, out, s, p)
        except BaseException:  # the method and the entities always agree: the conditions as they were
            folder.write_method(out, old)
            raise
    return {**r, "next": [dict(command=nayose("describe", "results", "--workspace", out), why="what now merges")]}


def apply_decisions(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    with readable(a["file"], s, strict=True) if a["file"] else contextlib.nullcontext(out / "review.parquet") as path:
        run = Run(p, s, echo=emit.step, told=emit.progress).decide(path, out)
    if folder.method(out).get("merge"):  # merged by people's conditions: rebuilt, so a pair said different parts at once
        con, db = connect(s.compute)
        apply_merging(con, db, out, s, p)
    x = run.steps[-1]
    return dict(decisions=x["decisions"], matches=x["matches"], clusters_joined=x["clusters_joined"],
                summary=[["nothing new", "every decision was applied before"]] if not x["decisions"] else [],
                next=[dict(command=nayose("describe", "workspace", out), why="the workspace at a glance")])


KINDS = {"person": 1, "company": 2, "unsure": 0, "clear": None}


def list_kinds(a: dict, emit: "Emit") -> dict:
    uid, out = settings_for(a).data.unique_id, Path(a["workspace"])
    kinds = sheet(out, "kind_review.parquet")
    if kinds is None:
        raise InputError(f"{out}: no kind_review.parquet", fix="a full run that tells persons from companies writes it: nayose resolve records …")
    kinds = kinds.assign(why=sheet_parts(kinds))  # a flagged record drawn at random is to decide, as everywhere
    kinds.insert(2, "status", np.where(kinds["kind"].notna(), "written in", "open"))
    answered = {x for f in folder.answer_parts(out) for x in pd.read_parquet(f, columns=[uid])[uid].astype("string")}  # applied answers leave the sheet a rerun draws
    return dict(counts=counts(kinds), applied=len(answered), kinds=rows(ids(picked(kinds, a), uid)), next=[dict(command=nayose("answer", "kind", "<ID>", "company", "--workspace", out), why="answer one"),
                                                    dict(command=nayose("apply", "answers", "--workspace", out), why="apply the answers written in: a rerun")])


def answer_kind(a: dict, emit: "Emit") -> dict:
    uid, out = settings_for(a).data.unique_id, Path(a["workspace"])
    folder.type_in(out, "kind_review.parquet", "kind", KINDS[a["kind"]], **{uid: a["id"]})
    return dict(record=a["id"], kind=a["kind"], next=[dict(command=nayose("apply", "answers", "--workspace", out), why="apply them: a rerun")])


def apply_answers(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    with readable(a["file"], s, strict=True) if a["file"] else contextlib.nullcontext(out / "kind_review.parquet") as path:
        return after_run(Run(p, s, echo=emit.step, told=emit.progress, kind_labels=find(path)[0]).rerun(out, pipeline_file=pipeline), out)


def serve_inbox(a: dict, emit: "Emit") -> dict:
    seconds = lambda name, default: number(a[name], f"--{name}", "seconds, for example 60") if a[name] else default
    ok = inbox.serve(Path(a["workspace"]), Path(a["inbox"]), seconds("every", None), int(number(a["retries"] or "2", "--retries", "a count, for example 2")),
                     a["compute"] or [], emit.line, seconds("settle", 60.0))
    return dict(stopped=not ok, exit_code=0 if ok else 1, next=[dict(command=nayose("describe", "workspace", a["workspace"]), why="the workspace at a glance")])


def open_ui(a: dict, emit: "Emit") -> dict:
    from er import ui  # the page's server: it reads these declarations
    ui.serve(int(number(a["port"] or "8765", "--port", "a port, for example 8765")), a["workspace"], a["home"] or "workspaces", emit.line, open_browser=not a["link"])
    return dict(next=[])


# ---------- the declarations ----------

INPUT = Param("input", "the records: a CSV, TSV or Parquet file, a quoted glob ('in/*.csv') or a folder of them, read as they come and together by column name",
              "path", positional=True)
WORKSPACE = Param("workspace", "the workspace: the folder that keeps one matching job", "path", required=True)
TRUST = ("the trust line (none: the method as tuned): line (none: above every step), next (the range checked next: down_to, "
         "up_to), its pairs, checked, false, needed, may_lower; above (the pairs above the line: pairs, checked, false); checks")
OWN = Param("workspace", "a workspace, for its own mapping (without it, the project's: config/settings.toml)", "path")
GIVEN = replace(INPUT, help=INPUT.help + "; copied into the workspace first. Without it, the file loaded into it last", optional=True)
HOME = Param("home", "the folder that holds the workspaces (default: workspaces, in the current folder)", "path")
DESCRIBED = {"records": "records", "columns": "each column of the file: column, filled, example",
             "fields": "each field: field, sources, filled, example, looks_right, and each of its alternatives (columns, found, filled, example, looks_right)",
             "fit": "for each field, each column's fit: the share of its values that look like the field (id: filled, each value once)",
             "suggested": "for each field the file holds none of: field, column, why",
             "needed": "the fields a run stops without: every (each of them), one_of (at least one of each group)",
             "turned_off": "rules, keys and levels a run of this file would turn off: a field they read is missing",
             "slots": "each feature and part: feature (its path), sources, filled, example, looks_right, odd (a value that doesn't look right), "
                      "hint (what its values say is off: level warn or info, says, example (a value that doesn't look right), fix, and with a workspace the command and button that fix it), "
                      "and each of its alternatives",
             "names_by_kind": "whether each record's name is compared on the side its kind leans to (set names)",
             "features": "the structure: groups › features › parts, each with type and columns",
             "profile": "each column's script (kanji, kana, romaji) and the shares of its values that are known family names, given names, full names, addresses",
             "placements": "for each feature with no column: feature, column, share, why (the file's contents)",
             "offers": "new features the contents suggest: feature, type, script, column, share, why", "notes": "what the reader detected or fixed",
             "read": "what the reader found (er.intake): rows, values per encoding, fixed (controls, placeholders, numbers, damaged, lists, first of several), proposed and waiting: repairs by kind (realign, garbled, encoding) for accept repairs, with examples; unread rows", "next": "the commands that usually follow"}
CHECKED = {"records": "records read", "fields": "each field: filled, looks_right, top_value (shares), columns",
           "capacity": "the room a run has: memory_limit_gb, spill_folder, spill_free_gb, pairs_needed (this file's, exactly), pairs_fit, headroom (fit ÷ needed)",
           "ready": "ok, and each of stops (what would stop a run) and warns (what to look at first): what, fix",
           "turned_off": "rules, keys and levels a missing field turns off", "keys": "each key's pairs per record and largest block",
           "oversized_from": "the block size checked by sampling", "notes": "what the loader detected or fixed", "read": "what the reader found (er.intake): rows, values per encoding, fixed (controls, placeholders, numbers, damaged, lists, first of several), proposed and waiting: repairs by kind (realign, garbled, encoding) for accept repairs, with examples; unread rows",
           "next": "the commands that usually follow"}
COMPUTE = Param("compute", "DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, "
                "temp_directory=<folder> (past the memory limit DuckDB spills there)", "many", metavar="KEY=VALUE")
PIPELINE = Param("pipeline", "the pipeline file (default: config/final.toml)", "path")
OPEN = Param("open", "only the rows nobody has answered", "flag")
PENDING = Param("pending", "only the rows not yet applied: open, or written in", "flag")
FILE = lambda what: Param("file", f"{what} (default: the workspace's own sheet, with the answers written in)", "path")
RUN_RESULT = {"summary": "the run in words: records, entities, who joined them, the model's links, what is left to people",
              "facts": "what to read first: records, entities, joined, waiting (pairs for people from review_from points), merging, missed and missed_high (the probe), too_big, kinds (flagged person or company), report",
              "seconds": "the run's time", "wrote": "the files written", "index": "the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix", "next": "the commands that usually follow"}
COMMANDS: tuple[Command, ...] = (
    Command("create", "workspace", "Start a workspace: the folder for one matching job",
            "Makes HOME/NAME (HOME: --home, else workspaces/ in the current folder) with its own mapping, columns.toml: "
            "config/settings.toml's [columns] and [kind], which of its files' columns hold each field. Records files given to "
            "it are copied into its inputs/, and its runs, people's decisions and their answers are written beside them, so "
            "opening it again finds all of it. O(1).",
            (Param("name", "letters, digits, '.', '_' and '-', at most 64", positional=True, metavar="NAME"), HOME),
            {"workspace": "the workspace made", "next": "the commands that usually follow"},
            "nayose create workspace acme", create_workspace, quick=True),
    Command("list", "workspaces", "The workspaces, the latest active first",
            "Every folder in HOME that holds a workspace: its name, the files given to it, whether it holds a run, and when it "
            "last changed. Reads steps.json, no record. O(workspaces).",
            (HOME,), {"home": "the folder listed", "workspaces": "each one: name, workspace, files, ran, last",
                      "next": "the commands that usually follow"},
            "nayose list workspaces", list_workspaces, quick=True, show={"workspaces": ("name", "files", "ran", "last")}),
    Command("load", "records", "Copy a file into a workspace, read it as it comes, then describe it",
            "Copies the records into a part of the workspace's own (inputs/0001-customers/), unless it holds the same content "
            "already, and reads it as it comes (er.intake): a CSV, TSV or Parquet, each value in its own encoding; control "
            "bytes, placeholders and spreadsheet numbers fixed; a row whose fields don't line up, a garbled value or another "
            "encoding's reading proposed, for people to see and accept (accept repairs). Then describes it as describe "
            "records does, with the workspace's mapping. Its runs read what was read, so the original can move or go. "
            "O(bytes) for the copy and the reading (about 7 s a million records from Parquet, 15 s from CSV), then the description's.",
            (INPUT, WORKSPACE), {**DESCRIBED, "loaded": "the part the records are in", "copied": "false: the workspace held them already"},
            "nayose load records customers.parquet --workspace workspaces/acme", load_records,
            show={"columns": ("column", "filled", "example"), "fields": ("field", "filled", "looks_right"), "fit": (), "features": (), "profile": (),
                  "slots": ("feature", "filled", "looks_right"), "placements": ("feature", "column", "why"), "offers": ("feature", "column", "why")}),
    Command("accept", "repairs", "Accept one kind of repair the reader proposed for a loaded file",
            "Reads the file again with that kind applied: realign, each row whose fields don't line up re-split where every "
            "value fits its column (unread until then); garbled, each value a wrong decoding garbled upstream decoded back; "
            "encoding, each value another encoding reads far better read in it. Each was proposed only when it read at least "
            "e^margin likelier ([input]). describe records shows them first, in read.examples. When a run read the file "
            "already, run matching again to use them. O(the file).",
            (Param("kind", "realign, garbled or encoding", "choice", intake.KINDS, positional=True),
             Param("part", "the loaded file, by its part (0001, or its name; default: the latest with this kind waiting)", metavar="PART"), WORKSPACE),
            {"part": "the part read again", "kind": "the kind accepted", "repaired": "the repairs applied", "rows": "the rows it now holds",
             "added": "rows that were unread", "read": "what the reader found (er.intake): rows, values per encoding, fixed (controls, placeholders, numbers, damaged, lists, first of several), proposed and waiting: repairs by kind (realign, garbled, encoding) for accept repairs, with examples; unread rows", "next": "the commands that usually follow"},
            "nayose accept repairs realign --workspace workspaces/acme", accept_repairs),
    Command("list", "features", "The features a workspace's columns fill: groups, features, parts",
            "The workspace's structure: each group, its features and their parts (a full name's family and given names), each "
            "with the columns that hold it, read from its mapping. Without --workspace, the project's. O(the file).",
            (OWN,), {"features": "the structure: groups › features › parts, each with type and columns", "slots": "each feature and part: feature (its path), columns", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again",
                     "next": "the commands that usually follow"},
            "nayose list features --workspace workspaces/acme", list_features, quick=True, show={"features": ()}),
    Command("set", "feature", "Put columns into features",
            "Sets each named feature's or part's columns, by its path: GROUP/FEATURE=COLUMN, GROUP/FEATURE/PART=COLUMN, A,B "
            "(B where A is empty), A+B (joined), nothing (no column). Then writes the mapping they mean into the workspace's "
            "columns.toml, checked before it replaces the old: Name/Full name fills full_name and person_name, its Family name "
            "and Given name a joined fallback of person_name and given_name, and every name, any_name. O(the file).",
            (Param("mapping", "one or more GROUP/FEATURE=COLUMNS", "many", positional=True, metavar="PATH=COLUMNS"), WORKSPACE),
            {"features": "the structure, as set", "slots": "each feature and part: feature (its path), columns", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again", "next": "the commands that usually follow"},
            "nayose set feature \"Name/Full name/Family name=SEI\" \"Name/Full name/Given name=MEI\" --workspace workspaces/acme", set_feature, quick=True,
            show={"features": ()}),
    Command("set", "names", "Compare each record's name on its own side, by its kind, or as mapped",
            "by-kind: a person's name is compared only with people's names, a company's only with companies' (kind = person "
            "on full_name and person_name, kind = company on company_name, in the workspace's columns.toml): for a file whose "
            "name columns hold both kinds' names, which a run would otherwise score twice, as a person's name and as a "
            "company's. Each record goes to the side its kind leans to (er.kind); one whose kind is unsure, where the "
            "engine and the flag disagree, compares no name until people answer it (list kinds). as-mapped takes it back. "
            "The next run reads it. O(the file).",
            (Param("how", "by-kind or as-mapped", "choice", ("by-kind", "as-mapped"), positional=True), WORKSPACE),
            {"names": "by-kind or as-mapped", "mapping": "the name lines of columns.toml, as written", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again", "next": "the commands that usually follow"},
            "nayose set names by-kind --workspace workspaces/acme", set_names, quick=True),
    Command("add", "feature", "Add a feature: a name in another script, or another company name",
            "Adds a feature to the Name group (PATH: Name/<its name>): a person's name, with its family and given names, or a "
            "company name, in a script (kana, kanji or romaji: how its values are prepared). Its fields are numbered beside "
            "the ones it stands with (person_name_2, given_name_2; company_name_2) in the workspace's columns.toml. A run then "
            "compares it with them: each step of the name comparison is reached when either name agrees, as one piece of "
            "evidence, and pairs are also found on it; the match rules stay as they are. The steps' thresholds were "
            "tuned on kana; their weights are fitted on each run's file. O(the file).",
            (Param("path", "Name/<its name>", positional=True, metavar="PATH"),
             Param("type", "person name or company name", "choice", ("person name", "company name"), required=True),
             Param("script", "kana, kanji or romaji (default kana)", "choice", ("kana", "kanji", "romaji")),
             Param("column", "the column that holds it, if you know it", metavar="COLUMN"), WORKSPACE),
            {"features": "the structure, with it", "slots": "each feature and part: feature (its path), columns", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again", "next": "the commands that usually follow"},
            "nayose add feature \"Name/Kanji name\" --type \"person name\" --script kanji --column SHIMEI --workspace workspaces/acme", add_feature_,
            quick=True, show={"features": ()}),
    Command("remove", "feature", "Remove a feature added to a workspace",
            "Its fields leave the workspace's columns.toml; the defaults stay (take their columns off instead). O(the file).",
            (Param("path", "GROUP/FEATURE", positional=True, metavar="PATH"), WORKSPACE),
            {"features": "the structure, without it", "slots": "each feature and part: feature (its path), columns", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again", "next": "the commands that usually follow"},
            "nayose remove feature \"Name/Kanji name\" --workspace workspaces/acme", remove_feature_, quick=True, show={"features": ()}),
    Command("describe", "records", "What a file holds, for mapping its columns: nothing prepared",
            "Each column's share filled and an example; each field's columns as the mapping reads them (a later one where the "
            "earlier are empty, a joined one where every part is filled), each with its share filled, an example and the share "
            "of its values that look like the field; how well each column fits each field; and, for a field the file holds "
            "none of, the column its name or values suggest, never applied: set columns applies it; and what a run would turn "
            "off, a field they read missing; and for a feature whose values don't look like it, what they say is off and "
            "what sets it right (hint): a name column holding the other kind's names too (set names by-kind), values that "
            "look like another field (set feature), or a value that doesn't look right. Shares filled cover the "
            "file; the rest a sample of 2,000 records. A file not loaded into a workspace is read as it comes first, for "
            "this command alone (read: what the reader found). O(N·C) in one scan, plus the sample, plus the reading.",
            (replace(INPUT, help=INPUT.help + "; without it, the workspace's file loaded last", optional=True), OWN), DESCRIBED, "nayose describe records customers.parquet --workspace workspaces/acme", describe_records, quick=True,
            show={"columns": ("column", "filled", "example"), "fields": ("field", "filled", "looks_right"), "fit": (), "features": (), "profile": (),
                  "slots": ("feature", "filled", "looks_right"), "placements": ("feature", "column", "why"), "offers": ("feature", "column", "why")}),
    Command("check", "records", "Read, map and check a file, in seconds; resolve nothing",
            "Reads the file through the door every input takes, maps its columns to the logical fields (config/settings.toml "
            "[columns]), and counts each key's pairs before any join. Shows each field's fill rate, the share of values that "
            "look like it and the share of its most common value, what would be turned off, and the blocks the run will check "
            "on a sample. A field the run needs and the file lacks stops it, with the column whose values look most like it. "
            "O(N) for the counts; a sample of 10,000 records for the shares.",
            (replace(INPUT, help=INPUT.help + "; without it, the workspace's file loaded last", optional=True), OWN, COMPUTE, PIPELINE), CHECKED,
            "nayose check records customers.parquet", check_records),
    Command("list", "columns", "Show which of a file's columns hold each field",
            "Reads the workspace's columns.toml, or without one config/settings.toml [columns] (or the ER_SETTINGS file): each "
            "field, its columns (a comma between fallbacks, + between columns joined) and its options. O(the file).",
            (OWN,), {"settings": "the file read", "own": "true: the workspace's own mapping", "columns": "each field: columns, options", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again",
                     "next": "the commands that usually follow"},
            "nayose list columns --workspace workspaces/acme", list_columns, quick=True),
    Command("set", "preparation", "Set how a field's values are prepared",
            "Rewrites the named fields' normalize steps in [columns]: FIELD=STEP,STEP, applied in order (FIELD= for none), the field's "
            "columns as they are. Among the steps: nfkc (full-width as half-width, half-width kana as full), katakana (hiragana as "
            "katakana), strip_separators (03-1234-5678 as 0312345678, letters kept), strip_spaces, kana_fold. With --workspace, the "
            "workspace's columns.toml; else the project's, which new workspaces start from. A run reads the values so once it runs "
            "again. O(the file).",
            (Param("mapping", "one or more FIELD=STEPS", "many", positional=True, metavar="FIELD=STEPS"), OWN),
            {"settings": "the file written", "own": "true: the workspace's own mapping", "columns": "each field: columns, options", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again",
             "next": "the commands that usually follow"},
            "nayose set preparation phone=nfkc,strip_separators --workspace workspaces/acme", set_preparation, quick=True),
    Command("set", "columns", "Map fields to a file's columns",
            "Rewrites the named fields' lines in [columns]: FIELD=COLUMN, FIELD=A,B (B where A is empty), FIELD=A+B (A and B "
            "joined), FIELD= (no column: whatever reads it is turned off). Every other line, each line's comment and a field's options stay; the new file "
            "is checked before it replaces the old. With --workspace, the workspace's columns.toml; else the project's, which "
            "new workspaces start from. O(the file).",
            (Param("mapping", "one or more FIELD=COLUMNS", "many", positional=True, metavar="FIELD=COLUMNS"), OWN),
            {"settings": "the file written", "own": "true: the workspace's own mapping", "columns": "each field: columns, options", "rerun_owed": "the run read its records with another mapping, method or pipeline: it reads them so once it runs again",
             "next": "the commands that usually follow"},
            "nayose set columns phone=TEL4 person_name=NAME_KANA,SEI+MEI --workspace workspaces/acme", set_columns_, quick=True),
    Command("resolve", "records", "Resolve a file: one ID per person or company",
            "A full run, without labels: load, budget, fit, rules, candidates, score, cluster, write, report. Writes the "
            "workspace: gold.parquet, matches/, rule_kept/, proposed/, set_aside/, state/, steps.json, and for people qa.md, "
            "report.txt, review.parquet and kind_review.parquet. With a trust line (method.toml trust), only pairs scoring at "
            "or above it join; the rest wait for people. A folder that holds a run is refused without --overwrite; people's "
            "decisions and answers in it stand. O(N·L + ΣP + C·K·L²).",
            (GIVEN, WORKSPACE, Param("overwrite", "replace the results it holds", "flag"), PIPELINE,
             Param("model", "a fitted model to score with instead of fitting one on the file (its JSON, or the file that holds it under 'model')", "path"),
             COMPUTE),
            RUN_RESULT, "nayose resolve records customers.parquet --workspace workspaces/customers", resolve_records),
    Command("rehearse", "records", "Run a generated file of the same size and shape, and measure what this machine needs",
            "The file's records and each field's share filled (no value kept); a file of that size and shape generated in "
            "parts of 50,000 entities, each field filled at the file's share, a field it lacks left out; that file resolved "
            "in a process of its own, under the same limits and the workspace's method (method.toml; a key on a name feature "
            "added to the workspace left out: the generated file holds none), its spill folder's size read every half second. Says the seconds "
            "of each step, the peak memory, the peak spill, the pairs, and the generated shape beside the file's; if the run "
            "stopped (memory, disk), why, as the real file would. Removes what it made; keeps rehearsal.json in the workspace. "
            "Past 60,000 entities names repeat more than in a real file, so name keys make more pairs: check records counts "
            "the file's own. O(N) to generate, O(a full run) to measure.",
            (replace(INPUT, help=INPUT.help + ", its shape read, not copied in; without it, the file loaded into the workspace last", optional=True),
             WORKSPACE, PIPELINE, COMPUTE),
            {"ok": "whether the run went through", "records": "records generated", "generate_seconds": "seconds to generate and describe them",
             "generate_peak_gb": "the peak memory of generating them, a process apart from the run's",
             "seconds": "the run's seconds", "steps": "seconds of each step", "peak_memory_gb": "the run's peak memory (the process's)",
             "peak_spill_gb": "the most it spilled to disk at once", "pairs": "the pairs its keys and rules listed",
             "shape": "each field: its share filled in the file and in the rehearsal", "error": "why the run stopped, if it did",
             "fix": "what to do then", "limit": "what a generated file can't show", "next": "the commands that usually follow"},
            "nayose rehearse records --workspace workspaces/customers", rehearse_records),
    Command("add", "records", "Add new records to a run",
            "An increment: each new record compared with every stored one, with the run's model; it can join an existing "
            "entity. A record whose ID is already in the run is set aside, so adding the same file twice adds nothing. "
            "O(Δ·(L + Σb) + C_Δ·K·L²) plus narrow O(N) scans.",
            (GIVEN, WORKSPACE, PIPELINE, COMPUTE), RUN_RESULT, "nayose add records new.parquet --workspace workspaces/customers", add_records),
    Command("match", "records", "Which entity each record would join; nothing written",
            "An increment's steps without its write: for each record, the entity it would join or a new one, and the rule or the "
            "model's best weight that links it. The workspace is left as it was. O(an increment).",
            (INPUT, WORKSPACE, PIPELINE, COMPUTE),
            {"counts": "records by status", "records": "each record: id, entity, status, by, weight", "next": "the commands that usually follow"},
            "nayose match records new.parquet --workspace workspaces/customers", match_records,
            show={"records": ("id", "entity", "status", "by", "weight")}),
    Command("build", "index", "The index a record is looked up in, from the run",
            "Every key of every record the run holds and every value a search reads, sorted, in the workspace's index/ (DuckDB "
            "databases), with the person/company classifier and what it was built from. Read once from the run's own files, nothing "
            "standardized again; built beside the last index, which stays until the new one is whole. Once built, it is kept up to "
            "date by the commands that change the run: an increment, decisions or merging conditions write what changed beside it; a "
            "full run builds it again. O(N·(G + R + D·L + F) + N log N): N records, G pair keys, R rules, D deletion keys, L a value's "
            "length, F searched columns.",
            (WORKSPACE, PIPELINE, COMPUTE),
            {"index": "its folder", "records": "the records it holds", "tables": "each table: of (its key or rule), rows, seconds", "seconds": "in all",
             "next": "the commands that usually follow"},
            "nayose build index --workspace workspaces/customers", build_index),
    Command("match", "record", "The entities one record may belong to, from the index; nothing written",
            "One record, by the file's column names (or a stored one's ID, as if it were new), prepared as a run prepares it, "
            "looked up by each of its keys in the index (nayose build index), and scored with the run's model: the entities at "
            "--from points or more, best first, each with its best record, its points, each comparison's level and the rule that "
            "would join it; likely ones at the line or above. The pairs an increment of that record alone would list, scored "
            "alike. O(G·(log N + b) + C·K·L²): N only in log N.",
            (Param("values", "the record's values, by the file's column names", "many", positional=True, metavar="COLUMN=VALUE", optional=True),
             Param("record", "a stored record's ID, looked up as if it were new", metavar="ID"),
             Param("from", "from these points (default: the review floor)", metavar="POINTS"), Param("count", "the most entities (default 20)", metavar="N"),
             WORKSPACE, PIPELINE, COMPUTE),
            {"record": "the record as compared: its fields and kind", "entities": "each: entity, record, points, likely, rule, keys, compared, records, shown",
             "found": "entities at --from or more", "at_least": "the points listed from: --from, else the review floor",
             "closest": "none at --from or more: the nearest record compared (record, entity, points, shown), else null",
             "read_as": "the values as read, when they were typed otherwise than records hold them (a name in hiragana, 03-1234-5678) and so read find more or come closer",
             "candidates": "records compared", "likely": "of them, at the line or joined by a rule",
             "checked": "each key: found, or why not; a block too big: its records and the gate's decision", "seconds": "each part",
             "index": "built_at, records", "next": "the commands that usually follow"},
            'nayose match record FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234 --workspace workspaces/customers', match_record, quick=True),
    Command("search", "records", "The stored records whose values start with those given, any of them; nothing written",
            "Values by the file's column names, any of them (finding nothing as given, read again as people type them: full-width, a "
            "name's hiragana, 100-0001), each prepared as a run prepares it and read by its start in the index "
            "(a name also by its end): the records sharing the most of them, scored with the run's model, a column not given counting "
            "as missing. The entities at --from points or more (default: any), best first, each with its best record, its points and "
            "the fields that agree. A value that starts too many records to list is said, to be given further. "
            "O(F·(log N + 2,000) + 500·K·L²): F the fields given, N only in log N.",
            (Param("values", "the values, by the file's column names", "many", positional=True, metavar="COLUMN=VALUE"),
             Param("from", "from these points (default: any)", metavar="POINTS"), Param("count", "the most entities (default 10)", metavar="N"),
             WORKSPACE, PIPELINE, COMPUTE),
            {"record": "the values as compared: their fields and kind", "entities": "each: entity, record, points, likely, fields (those that agree), compared, records, shown",
             "found": "entities at --from or more", "listed": "records whose values start with those given", "candidates": "of them, scored",
             "typed": "the fields searched", "read_as": "the values as read, when they were typed otherwise than records hold them and so read agree on more", "missing": "the columns given, when every value read as missing: nothing to search by",
             "over": "each value that starts too many records to list them all: field, value, records (how many start with it, counted to 100,000: more true past it), listed (its first by value listed: no other value lists its own)", "seconds": "each part",
             "index": "built_at, records", "next": "the commands that usually follow"},
            "nayose search records FULL_NAME_KANA=ヤマダ PHONE_NUM_4=1234 --workspace workspaces/customers", search_records, quick=True),
    Command("rerun", "records", "A full run again, on the run's own files",
            "Reads the record files the run read, the full run's and each increment's, in order (steps.json; a scheduled batch "
            "found where the scheduler moved it), each checked by its SHA-256, and resolves them again in one full run: every "
            "pair compared again, an ID's records kept as the increments kept them. O(a full run).",
            (WORKSPACE, PIPELINE, COMPUTE), RUN_RESULT, "nayose rerun records --workspace workspaces/customers", rerun_records),
    Command("describe", "workspace", "What a workspace holds",
            "Records and entities, the largest entities, each run so far, the pairs and kinds still open and the answers written "
            "in, records set aside, a write still owed, the last summary, the round with its audits, and the trust line. O(N) in SQL.",
            (Param("workspace", "the workspace", "path", positional=True), PIPELINE),
            {"workspace": "the workspace", "records": "records", "entities": "entities", "largest": "the 10 largest entities",
             "runs": "each run so far: at, what, the record files it read, seconds, records loaded, each step's seconds", "pairs": "open pairs to decide and audit, and decisions written in",
             "kinds": "open records to decide (flagged, drawn or not) and to measure (optional), and answers written in", "set_aside": "records set aside",
             "write_owed": "a write cut short, finished by the next one", "summary": "the last run's summary",
             "round": "the round now: one per method the workspace ran (rounds.json)", "audits": "this round's audits people decided: checked, false",
             "trust": TRUST,
             "inputs": "the records files given to it, each in inputs/: name, path, files, bytes, rows, read (by a run, as it is now), waiting (repairs proposed, for people), unread (rows), given (its file's own name, one file), seconds (its reading took), columns",
             "columns": "own: its columns.toml; project: config/settings.toml's",
             "auto": "the report try everything wrote, to send: report (its path), markdown",
             "rerun_owed": "the mapping, the method or the pipeline changed since the run: it reads the records so once it runs again",
             "index": "the lookup's index: built_at, records, added (of them, since it was built), stale (what changed since, or null; built_at null: none yet), columns (each a lookup reads: column, field, main: in the field's first alternative)",
             "next": "the commands that usually follow"},
            "nayose describe workspace workspaces/customers", describe_workspace_, quick=True,
            show={"largest": ("entity", "records"), "runs": ("at", "what", "seconds"), "inputs": ("name", "files", "bytes", "read"), "auto": (), "index": ()}),
    Command("describe", "entity", "One record's entity, and what joined it",
            "The entity of the record ID: its size, each of its records (the first 200, the ID among them) with its fields and "
            "kind, and every link between them: a rule, the model with its weight in bits, people, or the workspace's merge "
            "conditions (auto). O(N) in SQL.",
            (Param("id", "a record ID, as the run wrote it", positional=True, metavar="ID"), WORKSPACE),
            {"record": "the ID asked for", "entity": "its entity (the cluster_id)", "size": "how many records it holds",
             "records": "each of the entity's records, the first 200",
             "links": "each link between them: id_l, id_r, by, weight",
             "pairs": "of an entity of up to 50 records, every pair inside it scored: id_l, id_r, weight, by (none: joined through others), comparisons (comparison, reached, bits)",
             "weakest": "the links whose loss would split the entity: id_l, id_r", "capped": "true: too many records to score every pair",
             "next": "the commands that usually follow"},
            "nayose describe entity 0000000151 --workspace workspaces/customers", describe_entity_, quick=True,
            show={"records": ("id", "resolved_by", "kind", "person_name", "company_name", "address", "postal_code", "phone", "customer_id", "birth_date"),
                  "links": ("id_l", "id_r", "by", "weight"), "pairs": ("id_l", "id_r", "weight", "by"), "weakest": ("id_l", "id_r")}),
    Command("explain", "pair", "How the model scored one pair, and what found it",
            "Two record IDs of the run, scored again as the run scored: per comparison, each step's tests, the values each "
            "compared after its normalization, the function, its threshold and the score it gave; the step each comparison "
            "reached and its points; the starting points for two records, and the total. What found the pair: a match "
            "rule, the pair keys, people; and whether it merged. When the two are in different customers and one of them holds "
            "more records, both customers and every pair across them (at most 400), scored. O(400·K).",
            (Param("first", "one record ID", positional=True, metavar="ID"), Param("second", "the other", positional=True, metavar="ID"), WORKSPACE, PIPELINE),
            {"id_l": "the lower ID", "id_r": "the other", "weight": "the pair's points (bits)", "probability": "the model's chance they are one",
             "prior": "the points two records start from", "pairs_all": "the pairs of records the run's file holds",
             "pairs_same": "of them, those the model expects are one customer: the start is their ratio",
             "common": "the points term frequencies add (0 without them)",
             "line": "the trust line (none: above every step; null: the method as tuned)", "threshold": "the weight the method accepts at",
             "same_customer": "the two are in one customer", "records": "both records: id and fields",
             "comparisons": "comparison, reached (its step), bits",
             "tests": "each step's tests: comparison, step, field, function, threshold, normalize, raw (the values as written), "
                      "prep (each normalizer step: step, a, b), a, b, score, passed",
             "found": "rule (a match rule's name), keys (the pair keys that listed it), people (a decision), merged",
             "group_a": "the first's customer, when the two are apart and one customer holds more", "group_b": "the second's",
             "across": "each pair across the two customers: id_l, id_r, weight", "next": "the commands that usually follow"},
            "nayose explain pair 0000000151 0000000377 --workspace workspaces/customers", explain_pair_, quick=True,
            show={"records": (), "comparisons": ("comparison", "reached", "bits"),
                  "tests": ("comparison", "step", "field", "function", "threshold", "a", "b", "score", "passed"),
                  "group_a": ("id",), "group_b": ("id",), "across": ("id_l", "id_r", "weight")}),
    Command("describe", "key", "One pair key: what it lists, how big its groups are, and what only it found",
            "A pair key of the run's method lists two records as a pair to compare when they share its value; it matches nothing "
            "itself. This shows the pairs it listed, the links of the run among them and those no other key listed (up to 3, "
            "to explain). For a key of equal values or of one-letter deletions: how many records share each value (1 to 9, "
            "10 or more), its largest values, and one group: the records sharing the value behind one of those links (at most "
            "12). For sorted neighbours: the records around such a link in the key's order. O(N), O(N·L) with deletions.",
            (Param("name", "the pair key, as describe matching names it", positional=True, metavar="KEY"), WORKSPACE, PIPELINE),
            {"name": "the key", "method": "KeyBlocker (equal values), SortedNeighbourhood, DeletionKeys or TfidfNeighbours",
             "keys": "the fields it reads: field, normalize", "pairs": "the pairs it listed", "matched": "links of the run it listed",
             "only": "links no other key listed", "examples": "up to 3 of them: id_l, id_r, weight",
             "sizes": "records per value: records (10: 10 or more), values", "largest": "its 3 largest values: value, records",
             "group": "one value's records: value, pair (the link behind it), records, more",
             "around": "sorted neighbours: window, pair, the records around it in order (sorted_as)", "next": "the commands that usually follow"},
            "nayose describe key person_name --workspace workspaces/customers", describe_key_, quick=True,
            show={"sizes": ("records", "values"), "largest": ("value", "records"), "examples": ()}),
    Command("compare", "records", "One record against others: every comparison's steps, test by test, for each",
            "The first record of the run against each of the others (at most 50), every pair scored again as the run scored: "
            "per other, its points, the step each comparison reached and every step's tests, with the values each compared as "
            "written, after each normalizer and as compared, the first record's side first. For a record's candidates: "
            "another customer's records, or the rest of its own. O(50·K).",
            (Param("first", "the record to compare", positional=True, metavar="ID"), Param("others", "the records to compare it with", "many", positional=True, metavar="ID"),
             WORKSPACE, PIPELINE),
            {"first": "the record compared", "records": "the first, then each other: id and fields",
             "candidates": "each other: id, weight (the pair's points), comparisons (comparison, reached, bits), tests (as explain pair's)",
             "next": "the commands that usually follow"},
            "nayose compare records 0000000151 0000000377 0000000412 --workspace workspaces/customers", compare_records_, quick=True,
            show={"records": (), "candidates": ("id", "weight")}),
    Command("describe", "matching", "How records are matched: every method, on which fields, with its numbers",
            "The pipeline as a graph: records, how each field is made comparable, the rules, the ways pairs are listed, the "
            "comparisons, what each level is worth in bits and the pairs that stopped at it, the line pairs are accepted at, the pairs left to people, and "
            "how linked records become customers. With --workspace, each part also holds that run's numbers and a real example. "
            "O(E + R + N) in SQL over the run's files.",
            (Param("workspace", "a workspace: its numbers and examples (without it, the methods only)", "path"), PIPELINE),
            {"nodes": "each part: id, name, method, its parameters and fields, and with --workspace its numbers and examples",
             "edges": "source, target, count", "next": "the commands that usually follow"},
            "nayose describe matching --workspace workspaces/customers", describe_matching_, quick=True),
    Command("describe", "method", "What the run shows about its method, and the changes worth trying",
            "From the run in the workspace and people's decisions: each round so far (a round per method the workspace "
            "ran: the tuned one, then each change of method.toml), with the links it made and the audits people decided in "
            "it; the line pairs are accepted at, the weight bands, and every pair people decided, scored again with the "
            "run's model; each match rule's pairs, those scoring below the line, and those people said are different; "
            "each pair key's pairs, seconds, links, and links only it found; each comparison step's bits and the pairs that "
            "reached it; and proposals: a line in the band people review that sets right decided pairs without setting any "
            "wrong, a rule people found different pairs in, a key no link needs. Changes nothing. O((D + R)·K) to score the "
            "decided and rule pairs again, + O(E) over the run's files.",
            (WORKSPACE, PIPELINE),
            {"line": "the weight pairs are accepted at", "review_from": "the lowest weight people are asked to decide",
             "method": "the workspace's changes to the tuned method (method.toml)", "round": "the round now (0: no round recorded)",
             "rounds": "round, method, at, matched, expected_false, decided, audited, false_found",
             "audits": "this round's audits: checked, false, at_most (the false rate's 95% upper bound)",
             "dropped": "the rules and pair keys the method leaves out, each as describe matching words it (rules: exact, fuzzy; keys: method, keys)",
             "to_decide": "pairs left to decide", "bands": "weight_from, pairs, accepted",
             "decided": "each pair people decided: id_l, id_r, decision, why, round, weight, named, rule",
             "rules": "name, pairs, below (scored below the line), different (people said)",
             "keys": "name, pairs, seconds, matched, only (links no other key found)",
             "steps": "comparison, level, bits, reached", "proposals": "change (method.toml keys), why",
             "trials": "the trials kept (the last 5), as try method gave them", "trust": TRUST, "next": "the commands that usually follow"},
            "nayose describe method --workspace workspaces/customers", describe_method_, quick=True,
            show={"rounds": ("round", "matched", "audited", "false_found", "expected_false"), "bands": (), "decided": (),
                  "rules": ("name", "pairs", "below", "different"), "keys": ("name", "pairs", "seconds", "matched", "only"),
                  "steps": ("comparison", "level", "bits", "reached"), "proposals": ("change", "why"), "trials": ()}),
    Command("describe", "review", "How much people must check, range by range of the trust line",
            "From the run in the workspace, without labels: for each range of the trust line's steps, its pairs (the rules' "
            "and the model's links), how many people decided and said different, the sample a range needs (checks, or all "
            "of a smaller range), the false links the model expects in it, the chance its sample comes back clean, the false "
            "rate a clean sample bounds, and the reviews left to merge it and every range above; then what waits whatever "
            "the line, the spot-checks a round, the person/company sheet, and the hours they take if each pair takes --seconds (an assumption, "
            "not a measure). A range above the line merges: none left there; a range people found a false pair in, and every "
            "range below it, need all their pairs, since the line never steps past it. A workspace with no trust line merges "
            "as tuned, and is refused. Changes nothing. O(E + D) over the run's files and people's decisions.",
            (WORKSPACE, PIPELINE, Param("seconds", "the seconds one pair takes people to decide, for the hours (default 10)")),
            {"ranges": "each range: down_to, up_to (none: no top), pairs, checked, different, sample, expected_false, chance_clean, "
                       "bound (the false rate a clean sample proves, at 95%), reviews_left, reviews_to_here (cumulative), if_not_clean",
             "below_last_step": "pairs below the last step: they never merge by points", "unnamed": "the model's pairs with no name compared: people decide each",
             "watch": "spot-checks a round of the pairs above the line", "kinds": "the person/company sheet: measure, decide, answered",
             "seconds_per_pair": "the assumption the hours rest on", "hours": "to_each_line (cumulative, range by range), unnamed, kinds",
             "next": "the commands that usually follow"},
            "nayose describe review --workspace workspaces/customers", describe_review, quick=True,
            show={"ranges": ("down_to", "up_to", "pairs", "checked", "different", "sample", "expected_false", "chance_clean", "reviews_left", "reviews_to_here")}),
    Command("try", "method", "Try a change of the method beside the method as it is",
            "Runs the workspace's method and the method with the change (a line; --drop: match rules and pair keys left "
            "out; --add: pair keys added, as describe method proposes them for the matches the probe found no key lists) on the workspace's files, both without people's decisions, so neither is judged on pairs it was told, and at the method's own line with the trust line set aside; both "
            "keep the run's fitted model and people's person/company answers. Says what the change does to the pairs people "
            "decided (those they said are different yet joined: false merges; those they said are the same yet apart) and, "
            "without labels, to the links, the false links the model expects, the entities, and the pairs of records it puts "
            "apart or together. Writes only trials/ in the workspace: each trial's result (the "
            "last 5 kept) and the clusters of the method as it is, kept for the next trial. O(two full runs without the fit); "
            "one when the method and the files are those of the last trial.",
            (WORKSPACE, Param("line", "the weight to accept pairs at, in bits", metavar="BITS"),
             Param("drop", "match rules and pair keys to leave out, by name", "many", metavar="NAME"),
             Param("add", "pair keys to add, each its fields joined by + (field or field:normalizer), as describe method proposes them", "many", metavar="FIELDS"),
             PIPELINE, COMPUTE),
            {"trial": "its number, for adopt method", "at": "when", "method": "the method tried, as method.toml would say it",
             "base": "the method as it is: matched, expected_false, rule_pairs, entities", "variant": "the method tried: the same",
             "different_joined": "pairs people said are different, in one customer (false merges): base, variant",
             "same_apart": "pairs people said are the same, apart: base, variant",
             "fixed": "pairs people decided that it sets right: id_l, id_r, decision (50 at most)", "broken": "those it sets wrong (50 at most)",
             "apart": "pairs of records it puts apart", "together": "pairs of records it puts together",
             "next": "the commands that usually follow"},
            "nayose try method --workspace workspaces/customers --line 9 --drop F3_NAME~_CIF", try_method,
            show={"method": (), "fixed": ("id_l", "id_r", "decision"), "broken": ("id_l", "id_r", "decision")}),
    Command("try", "everything", "Try everything on a file, and write a report to send that holds no record's value",
            "Auto mode: the commands a person would run on the file, in order, each in a process of its own: create workspace "
            "(auto-<month><day>-<time> in HOME, strict: nothing merges before people check), load records, set feature with "
            "what its contents suggest, check records, rehearse records (a stop there stops before the real run), resolve "
            "records, describe method, list patterns, try method for each change it proposes (--trials of them), the names "
            "in another script the file holds in a workspace of their own (auto/offers), and describe review. A step that "
            "fails is kept with its error and fix, and the steps that need it are skipped. Then auto/report.md, to send, and "
            "auto/report.json, its facts: counts, shares, seconds and the names of columns, fields, rules and keys, each taken "
            "field by field; checked against every value of a sample of 20,000 records, every run of six digits or more and "
            "every run of kana or kanji that is no column name, each found redacted and counted. When the file's first line "
            "was a record (the reader says the header may be missing, or two of its names read like values: four digits, an "
            "email, a legal form, a date, a known full name or address), every column name is one of the values. A step that "
            "crashed keeps its own words in auto/<step>.log, never in the report. Never lowers the trust line or adopts a "
            "method. Exit 0 once the run went through, 2 if a step stopped it, 75 if a workspace was busy, 130 if stopped "
            "(Ctrl-C); the report is written each time, once its workspace is made. O(the commands it runs): about 10 "
            "minutes a million records.",
            (INPUT, HOME, Param("trials", "how many of the changes describe method proposes to try (default 3)", metavar="N"),
             PIPELINE, COMPUTE),
            {"workspace": "the workspace it made", "ok": "whether the run went through", "steps": "each step: step, ok, seconds, error",
             "report": "auto/report.md: the report to send", "values": "the values of the sample the report was checked against",
             "redacted": "what the check found and redacted (0: none)", "markdown": "the report itself", "next": "the commands that usually follow"},
            "nayose try everything customers.parquet", try_everything, show={"markdown": ()}),
    Command("adopt", "method", "Adopt a method tried, and find matches with it",
            "Writes the trial's method into the workspace's method.toml, its merge conditions as they are now, then runs the workspace's files again with it, as "
            "rerun records does; method.toml is left as it was if the run fails. Every later command on the workspace runs "
            "this method. O(a full run).",
            (WORKSPACE, Param("trial", "the trial's number (try method gives it)", required=True, metavar="N"), PIPELINE, COMPUTE),
            RUN_RESULT, "nayose adopt method --workspace workspaces/customers --trial 3", adopt_method),
    Command("reset", "method", "Go back to the tuned method, and find matches with it",
            "Takes the workspace's changes to the method out of method.toml (the line, the rules and keys left out or added) "
            "and keeps its trust line, which people earned, and their merge conditions; then runs the workspace's files again, as rerun records does. "
            "method.toml is left as it was if the run fails. O(a full run).",
            (WORKSPACE, PIPELINE, COMPUTE), RUN_RESULT, "nayose reset method --workspace workspaces/customers", reset_method),
    Command("lower", "trust", "Merge the next range of scores without people, once its sample is clean",
            "The trust line (the workspace's method.toml trust): pairs scoring at or above it merge without people. It steps "
            "down one range ([trust] steps) once people answered checks pairs of that range (or all of them), drawn at "
            "random, and found none false: at most 1% false at 95% for 300. Refused before then. Then runs the workspace's "
            "files again with the new line, as rerun records does; method.toml is left as it was if the run fails. O(a full run).",
            (WORKSPACE, PIPELINE, COMPUTE), RUN_RESULT, "nayose lower trust --workspace workspaces/customers", lower_trust),
    Command("raise", "trust", "Take a range of scores back to people",
            "Raises the trust line one step (or starts one, above every step, on a workspace without: nothing then merges "
            "before people check), then runs the workspace's files again; method.toml is left as it was if the run fails. "
            "For when a spot-check above the line finds a false link. O(a full run).",
            (WORKSPACE, PIPELINE, COMPUTE), RUN_RESULT, "nayose raise trust --workspace workspaces/customers", raise_trust),
    Command("split", "entity", "Split an entity at a link that alone holds it together",
            "The two records of the link are decided different, kept with people's decisions, and the workspace's files run "
            "again, which never joins a pair people called different: the entity becomes the two parts that link held together. "
            "Refused for a link other links stand in for, so a split always splits. O(n²·K) to check, then O(a full run).",
            (Param("id", "a record of the entity", positional=True, metavar="ID"), Param("between", "the link's two records", "many", metavar="ID"), WORKSPACE, PIPELINE, COMPUTE),
            RUN_RESULT, "nayose split entity 0000262688 --between 0000262688 0000312261 --workspace workspaces/customers", split_entity),
    Command("draw", "pairs", "More links on the review sheet, to audit; and the pairs of the range people check next",
            "Adds audit rows to review.parquet: links, the model's and the rules', that people have not decided and the sheet "
            "does not hold, spread evenly over 1-bit weight bands, a rule's pairs scored as the model scores them. No false "
            "link in many audits is what says the links are right. With a trust line, first the pairs of the range people "
            "check next that the sheet lacks, from those the run kept for people: no run. O(N + (R + count)·K + E).",
            (WORKSPACE, Param("count", "how many audits (default 50)", metavar="N"), PIPELINE),
            {"drawn": "audit rows added", "decide": "rows of the range people check next added", "next": "the commands that usually follow"},
            "nayose draw pairs --workspace workspaces/customers --count 50", draw_pairs, quick=True),
    Command("list", "pairs", "The pairs for people to decide and to audit",
            "The run's review.parquet: decide rows (the pairs just below the threshold, and those above it with no name "
            "compared) and audit rows (accepted pairs just above it), each with both records' fields, each comparison's level "
            "and bits, and a status: open, written in, or applied. O(sheet rows).",
            (WORKSPACE, Param("why", "decide or audit only", "choice", ("decide", "audit")), OPEN, PENDING),
            {"counts": "rows by why and status", "pairs": "each pair: why, status, decision, id_l, id_r, match_weight, accepted, fields, levels",
             "next": "the commands that usually follow"},
            "nayose list pairs --workspace workspaces/customers --open", list_pairs, quick=True,
            show={"pairs": ("why", "status", "id_l", "id_r", "match_weight", "accepted")}),
    Command("describe", "results", "What the run found, at a glance",
            "How the scores came out (every pair the run scored, the full run's and each increment's, by its points), the pairs waiting for "
            "people from --from points up, by range, what merged and how, entities by size, the merge conditions, whether "
            "matches could be missed (the probe), the groups too big to compare, and the person/company answers to give. "
            "Reads the workspace only: no run. The first read of a run written before runs kept their pairs' levels makes "
            "that index once (scored/), from the pairs it stored. O(N + P + E).",
            (WORKSPACE, Param("from", "review from these points (default: the review floor)", metavar="POINTS"), PIPELINE),
            {"records": "records", "entities": "entities", "joined": "entities of two records or more",
             "sizes": "entities by size: label, entities", "scores": "every scored pair by points: down_to, up_to, pairs",
             "candidates": "pairs compared", "uncounted": "the records added since the full run whose pairs scores leaves out (a run logged before each counted its own)",
             "listed": "the pairs kept at 0 points or more: those list scored lists from 0", "review_from": "the points people review from",
             "waiting": "pairs waiting for people, by range: down_to, up_to, pairs", "pairs": "the pairs kept (0 points or more), by status",
             "merged_by": "records by what joined them: you, model, rule, or none",
             "merging": "the merge conditions: join, when; own: what the method merges by itself when there are none (line, rules), or null",
             "missed": "the probe's strata: stratum, fields, pairs, scored, missed, low, high",
             "too_big": "groups too big to compare: skipped, kept, by (the key that made them → how many skipped)",
             "kinds": "person or company: flagged (the engine sure against the file's flag, matched as the engine says), to_check (those open on the sheet), to_teach (the measuring draw's open rows: optional)",
             "next": "the commands that usually follow"},
            "nayose describe results --workspace workspaces/customers", describe_results_, quick=True),
    Command("list", "scored", "The pairs the run scored, best first, a page at a time",
            "Every pair the run scored at 0 points or more and every rule pair, best first: both IDs, points, how each was "
            "found (keys, rule), its status (waiting, merged, same, different: people's), each comparison's level and "
            "points, and both records' compared fields; filtered by points, by how found, by status or by a record ID; "
            "with the total the filters keep. O(E log E) + O(page·F).",
            (WORKSPACE, Param("from", "from these points", metavar="POINTS"), Param("to", "below these points", metavar="POINTS"),
             Param("source", "found by a rule, or by the model's keys", "choice", ("rules", "model")),
             Param("status", "one status only; open: waiting, or decided and not applied yet", "choice", ("waiting", "merged", "same", "different", "open")),
             Param("record", "pairs of this record ID", metavar="ID"), Param("page", "the page (default 1)", metavar="N"),
             Param("count", "pairs a page (default 100)", metavar="N"), PIPELINE),
            {"total": "pairs the filters keep", "typed": "of them, decided and not applied yet", "page": "this page", "count": "pairs a page",
             "pairs": "each pair: first, second, points, sources, rule, status, said, applied, compared (comparison: level, points), fields (field: [first, second])"},
            "nayose list scored --workspace workspaces/customers --status waiting --from 6", list_scored_, quick=True,
            show={"pairs": ("first", "second", "points", "status", "rule")}),
    Command("list", "entities", "The entities, largest first",
            "Entities of --smallest records or more (default 2), largest first: how many records each holds, what joined "
            "it, and up to three names; the one holding --record. O(N).",
            (WORKSPACE, Param("smallest", "entities of this many records or more (default 2)", metavar="N"),
             Param("record", "the entity of this record ID", metavar="ID"), Param("page", "the page (default 1)", metavar="N"),
             Param("count", "entities a page (default 100)", metavar="N")),
            {"total": "entities the filters keep", "page": "this page", "count": "entities a page",
             "entities": "each entity: entity, records, joined_by (you, model or rule), names"},
            "nayose list entities --workspace workspaces/customers", list_entities_, quick=True,
            show={"entities": ("entity", "records", "joined_by")}),
    Command("show", "records", "Records' full rows, as the file gave them",
            "Each record's full row: every column of the records file, in its order, from the workspace's copy of it "
            "(inputs/…/read/), with the fields each column feeds; a record set aside says why. Side by side for people to "
            "compare. O(N), a scan of the ID column.",
            (Param("ids", "record IDs", "many", positional=True, metavar="ID"), WORKSPACE),
            {"columns": "the file's columns in order: column, fields (those it feeds)", "records": "each record: id, row (column: value), set_aside"},
            "nayose show records 0000102855 0000905311 --workspace workspaces/customers", show_records_, quick=True),
    Command("describe", "merging", "What merge conditions would merge, before they apply",
            "The pairs the conditions merge without people (--conditions, else the workspace's), condition by condition and "
            "together, pairs people said differ left apart, and the entities of two records or more that would then hold; "
            "with none, what the method merges by itself. "
            "Conditions: points (at least), rules (found by one of them), fields (each comparison at least at a level), "
            "joined by and or or. No run. O(E + N).",
            (WORKSPACE, Param("conditions", 'as JSON: {"join": "or", "when": [{"points": 12}, {"rules": ["…"]}, {"fields": {"name": "…"}}]}',
                              metavar="JSON"), PIPELINE),
            {"join": "and or or", "when": "the conditions", "each": "per condition: condition, pairs", "pairs": "pairs merged, all together",
             "entities": "entities of two records or more then"},
            "nayose describe merging --workspace workspaces/customers --conditions '{\"when\": [{\"points\": 12}]}'", describe_merging_, quick=True),
    Command("set", "merging", "Merge pairs without people, by conditions you set",
            "Keeps the conditions in the workspace (method.toml merge) and rebuilds the entities at once from people's "
            "applied answers and the pairs the conditions merge (none: the pairs the method merges by itself, as a run does; "
            "in a new workspace, none); a condition taken off "
            "parts what it joined. No run: the stored pairs. Runs after this one merge by the same conditions. O(E + N).",
            (WORKSPACE, Param("conditions", 'as JSON: {"join": "and", "when": [...]}; {} for none', metavar="JSON", required=True), PIPELINE),
            {"join": "and or or", "when": "the conditions", "entities": "entities of two records or more", "merged": "pairs the conditions merged",
             "index": "the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix", "next": "the commands that usually follow"},
            "nayose set merging --workspace workspaces/customers --conditions '{\"join\": \"or\", \"when\": [{\"points\": 14}]}'", set_merging),
    Command("list", "patterns", "The model's pairs as patterns: what each comparison said, and what became of them",
            "Every pair the model scored, by its pattern (the step each comparison reached): the pairs, their mean points, how "
            "many merged, are on the review sheet for people (wait), were in its band but not asked (held: already one customer, "
            "another pair of the same two customers asked, or outside a trust line's sample) or stayed apart, and three to explain. "
            "From the score steps the full run and its increments logged (steps.json), and the sheet. O(P + S).",
            (WORKSPACE, PIPELINE),
            {"fields": "the comparisons, in pattern order", "pairs": "the pairs scored", "threshold": "the weight the method accepts at",
             "patterns": "key, steps (comparison → step), bits (comparison → its points), pairs, points, merged, wait, held, apart, examples (id_l, id_r)",
             "next": "the commands that usually follow"},
            "nayose list patterns --workspace workspaces/customers", list_patterns_, quick=True,
            show={"patterns": ("key", "pairs", "points", "merged", "wait", "held", "apart")}),
    Command("decide", "pair", "Decide one pair: match or no match",
            "Writes the decision into the workspace's review.parquet; nothing is applied until apply decisions. clear takes "
            "it back. Any pair the run kept (list scored) can be decided: one the sheet lacks joins it. O(sheet rows), and "
            "O(E) over scored/ for a pair the sheet lacks.",
            (Param("first", "one record ID of the pair", positional=True, metavar="ID"), Param("second", "the other", positional=True, metavar="ID"),
             Param("decision", "match, no_match, or clear", "choice", ("match", "no_match", "clear"), positional=True), WORKSPACE),
            {"pair": "the two IDs, lower first", "decision": "what was written", "next": "the commands that usually follow"},
            "nayose decide pair 0000000151 0000000152 match --workspace workspaces/customers", decide_pair, quick=True),
    Command("apply", "decisions", "Apply people's decisions to the run",
            "Each match pair joins its two entities at once, scoring nothing; no_match is kept, and a full run never accepts "
            "the pair. With merge conditions set (set merging), the entities are then rebuilt from the stored pairs, so a "
            "no_match pair the conditions joined parts at once. Decisions are kept in decisions/; one applied before "
            "changes nothing. O(D + touched clusters) + O(N).",
            (WORKSPACE, FILE("a file of decisions: the two ID columns and decision"), PIPELINE, COMPUTE),
            {"decisions": "decisions applied", "matches": "of them, match", "clusters_joined": "entities joined",
             "summary": "said when nothing was new", "index": "the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix", "next": "the commands that usually follow"},
            "nayose apply decisions --workspace workspaces/customers", apply_decisions),
    Command("list", "kinds", "The records for people to answer person or company",
            "The run's kind_review.parquet: decide rows (flagged: the engine sure against the file's flag, surest first, drawn "
            "at random or not) and measure rows (optional: a random draw that places the engine's lines), each with what the "
            "engine, the name and the flag say, and why it is there. O(sheet rows).",
            (WORKSPACE, Param("why", "decide (flagged) or measure (optional) only", "choice", ("decide", "measure")), OPEN, PENDING),
            {"counts": "rows by why and status", "applied": "the records answered in earlier rounds: applied, they leave the sheet", "kinds": "each record: id, why, status, reason, engine_says, name_says, name, kind",
             "next": "the commands that usually follow"},
            "nayose list kinds --workspace workspaces/customers --open", list_kinds, quick=True,
            show={"kinds": ("id", "why", "status", "name", "engine_says", "name_says", "flag")}),
    Command("answer", "kind", "Answer one record: person, company, or unsure",
            "Writes the answer into the workspace's kind_review.parquet (1 person, 2 company, 0 can't tell); nothing is "
            "applied until apply answers. clear takes it back. A sole trader is a person. O(sheet rows).",
            (Param("id", "the record ID", positional=True, metavar="ID"), Param("kind", "person, company, unsure, or clear", "choice", tuple(KINDS), positional=True), WORKSPACE),
            {"record": "the ID", "kind": "what was written", "next": "the commands that usually follow"},
            "nayose answer kind 0000000151 company --workspace workspaces/customers", answer_kind, quick=True),
    Command("apply", "answers", "Apply people's person/company answers: a rerun",
            "The answers stand for their records, teach the engine, and the draw to measure places its lines; they are kept in "
            "kind_answers/. They change how each name is matched, so they are applied by a full run on the run's own files "
            "(rerun records). O(a full run).",
            (WORKSPACE, FILE("a file of answers: the ID column and kind"), PIPELINE, COMPUTE), RUN_RESULT,
            "nayose apply answers --workspace workspaces/customers", apply_answers),
    Command("serve", "inbox", "Take in every file dropped in an inbox, one at a time",
            "inbox/batches/ (new records: add records; into an empty workspace, resolve records), inbox/decisions/ (apply "
            "decisions), inbox/answers/ (apply answers), oldest first, each as its nayose command in a process of its own. "
            "Done files go to inbox/done/, ones people must fix to inbox/failed/ with their error; any other failure is tried "
            "again, then stops the pass with the file left in place. A file changed in the last --settle seconds waits for a "
            "later pass: write a file elsewhere and move it in. One pass, or one every --every seconds. Each file is a "
            "line in <run>/jobs.jsonl.",
            (Param("inbox", "the inbox folder", "path", positional=True, metavar="INBOX"), WORKSPACE,
             Param("every", "seconds between passes; without it, one pass", "text", metavar="SECONDS"),
             Param("retries", "attempts after an unexpected failure (default 2)", "text", metavar="N"),
             Param("settle", "seconds a file must be left unchanged before it is taken, so one still being copied in waits (default 60)", "text", metavar="SECONDS"),
             COMPUTE),
            {"stopped": "the pass stopped on a file that kept failing", "next": "the commands that usually follow"},
            "nayose serve inbox inbox --workspace workspaces/customers --every 300", serve_inbox),
    Command("open", "ui", "The commands in a browser, on this machine only",
            "Serves a page on 127.0.0.1, reachable only from this machine and only with the link it prints, and opens it. Its "
            "screens follow the work: records, columns, check and run, results, pairs (keys M, N, S), kinds (keys 1, 2, 0). Each "
            "button runs one of these commands, shown as the command line it is; lists, describes and single answers run in "
            "the page's own process, the others each in a process of their own, one at a time. Nothing is loaded from the "
            "network. Ctrl-C stops it.",
            (Param("workspace", "the workspace the page starts with", "path"), HOME, Param("port", "the port (default 8765; 0: any free one)", metavar="PORT"),
             Param("link", "print the link only; open no browser", "flag")),
            {"next": "the commands that usually follow"}, "nayose open ui --workspace workspaces/customers", open_ui),
)


# ---------- the parser and the reference, from the declarations ----------

GROUPS = (  # the top-level help's commands, by task
    ("Set up", ("create workspace", "list workspaces", "load records", "accept repairs", "check records", "describe records", "list columns",
                "set columns", "set preparation", "list features", "set feature", "set names", "add feature", "remove feature")),
    ("Run", ("resolve records", "add records", "match records", "rerun records", "rehearse records", "try everything", "serve inbox")),
    ("Review", ("open ui", "describe results", "list scored", "show records", "decide pair", "apply decisions", "list kinds", "answer kind",
                "apply answers", "describe merging", "set merging", "list entities", "describe entity", "split entity")),
    ("Look up", ("build index", "match record", "search records")),
    ("Look inside", ("describe workspace", "describe matching", "describe key", "list patterns", "explain pair", "compare records")),
    ("Method", ("describe method", "try method", "adopt method", "reset method", "describe review", "lower trust", "raise trust", "draw pairs", "list pairs")),
)


def parser(kind: type[argparse.ArgumentParser] = argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The parser, from the declarations; `kind` its class, which every subcommand's parser takes too."""
    raw = argparse.RawDescriptionHelpFormatter
    by = {c.name: c for c in COMMANDS}
    assert set(by) == {n for _, names in GROUPS for n in names}, "every command in one group of the help, and no other name"
    listed = "\n".join(f"\n{group}\n" + "\n".join(f"  {n:<20} {by[n].help}" for n in names) for group, names in GROUPS)
    top = kind(prog="nayose", usage="nayose VERB NOUN [options]", description="nayose: gather each customer's records under one ID.", formatter_class=raw,
               epilog=listed.lstrip("\n") + "\n\nnayose VERB NOUN --help for one command; docs/commands.md for all.")
    verbs = top.add_subparsers(dest="verb", required=True, metavar="VERB", help=argparse.SUPPRESS)
    for verb in dict.fromkeys(c.verb for c in COMMANDS):
        mine = [c for c in COMMANDS if c.verb == verb]
        vp = verbs.add_parser(verb, help=", ".join(c.noun for c in mine), formatter_class=raw,
                              description="\n".join(f"{c.name}: {c.help}" for c in mine))
        nouns = vp.add_subparsers(dest="noun", required=True, metavar="NOUN")
        for c in mine:
            cp = nouns.add_parser(c.noun, help=c.help, description=f"{c.help}.", epilog=f"example:\n  {c.example}\n\nmore: docs/commands.md", formatter_class=raw)
            for p in c.params:
                kw = dict(help=p.help)
                if p.kind == "flag":
                    cp.add_argument(f"--{p.name}", action="store_true", **kw)
                    continue
                if p.choices:
                    kw["choices"] = p.choices
                if p.kind == "many":
                    kw["nargs"] = "+" if p.positional and not p.optional else "*"
                    if not p.positional:  # --between A B, or --between=A --between=B (a value like -h): one list
                        kw["action"] = "extend"
                if p.metavar and not p.choices:
                    kw["metavar"] = p.metavar
                if p.positional:
                    cp.add_argument(p.name, **kw, **({"nargs": "?"} if p.optional and p.kind != "many" else {}))
                else:
                    cp.add_argument(f"--{p.name}", required=p.required, **kw)
            cp.add_argument("--format", choices=("text", "json"), default="text", help="text for people (the default); json: one object per line")
            cp.add_argument("--verbose", "-v", action="store_true", help="every field of the result, and every fact of each step")
            cp.set_defaults(command=c)
    return top


def synopsis(c: Command) -> str:
    words = ["nayose", c.verb, c.noun]
    for p in c.params:
        value = "|".join(p.choices) if p.choices else p.shown + (" …" if p.kind == "many" else "")
        word = value if p.positional else f"--{p.name}" if p.kind == "flag" else f"--{p.name} {value}"
        words.append(word if (p.positional and not p.optional) or p.required else f"[{word}]")
    return " ".join(words + ["[--format text|json]"])


def reference() -> str:
    """docs/commands.md: every command, from its declaration."""
    out = ["[← README](../README.md) · [Usage](usage.md)", "", "# Commands", "",
           "Written by `scripts/document_commands.py` from the declarations in `er/cli.py`; `tests/test_design.py` fails when "
           "the two differ.", "", "`nayose` (名寄せ: gathering each customer's records under one name) reads as a sentence: a "
           "verb, a noun, then the parameters. Every command takes `--help` and `--format`.", "",
           "- **`--format text`**, the default, for a person: a long command shows each step as it ends and, on a terminal, one line for "
           "the step under way (what it does, how far, how long is left, measured on the step's own pace and on the workspace's last "
           "run of the same kind); elsewhere that line every 30 seconds. Then the result in short: what it found first, then what to "
           "look at, then the commands that usually follow. `--verbose` writes every field of the result, and every fact of each step.",
           "- **`--format json`**: one JSON object per line: `{\"event\": \"step\", …}` per step (a file being read: `{\"event\": \"progress\", \"done\": …, \"total\": …, \"unit\": \"rows\"}` as it goes, the total about; a run's long steps, each its own count: `\"records\"` loaded, `\"rules\"` applied, `\"keys\"` joined (weighed by the pairs each lists, with `\"more\"` when oversized blocks wait for the gate), `\"sampled pairs\"` the gate scored, and `\"pairs\"` scored with `\"likely\"`, the pairs at the model's line so far), then `{\"event\": \"result\", "
           "\"command\": …, …}` with the fields listed below, or `{\"event\": \"error\", \"error\": …, \"fix\": …, \"hints\": …, "
           "\"exit\": …}`. IDs are `id`, `id_l`, `id_r`, whatever the file calls them.",
           "- **Exit codes:** 0; 2, a mistake people fix (two lines: what is wrong, and the fix); 75, the workspace is busy: "
           "try again later; 1, a pass of `serve inbox` stopped on a file; 130, stopped with Ctrl-C.",
           "- **`next`**, in every result: the commands that usually follow, each with why.", "",
           "| Command | Does |", "|---|---|", *(f"| [`{c.name}`](#nayose-{c.verb}-{c.noun}) | {c.help} |" for c in COMMANDS), ""]
    for c in COMMANDS:
        out += [f"## nayose {c.name}", "", f"{c.help}.", "", "```", synopsis(c), "```", "", c.about, ""]
        if c.params:
            out += ["| Parameter | |", "|---|---|"]
            for p in c.params:
                value = "|".join(p.choices) if p.choices else p.shown
                name = value if p.positional else f"--{p.name}" if p.kind == "flag" else f"--{p.name} {value}"
                out.append(f"| `{name}` | {p.help}{' (required)' if p.required else ''} |")
            out.append("")
        out += ["| Result | |", "|---|---|", *(f"| `{k}` | {v} |" for k, v in c.result.items()), "",
                "```bash", c.example, "```", ""]
    return "\n".join(out)


def out_of_memory(e: BaseException) -> InputError | None:  # DuckDB's, raised as it is or by Splink: a limit people set, which they can raise
    oom = next((x for x in (e, e.__cause__) if isinstance(x, duckdb.OutOfMemoryException)), None)
    return oom and InputError(f"out of memory: {str(oom).splitlines()[0]}", fix="raise --compute memory_limit, or give --compute temp_directory "
                              "a folder with more free disk (config/settings.toml [compute] for every run)")


def perform(c: Command, a: dict, emit: Emit) -> dict:
    """A command run on its parameters; a field the file lacks, in a workspace, is mapped in the workspace's own
    columns.toml, so its fix says so (set columns --workspace), with the columns the file's values suggest."""
    try:
        r = c.run(a, emit)
    except InputError as e:
        if isinstance(e, Busy) or not (a.get("workspace") and e.hints):
            raise
        if c.name in ("add records", "match records"):  # a batch for a run: its columns take the run's names, the mapping stays
            s = settings_for(a)
            named = dict.fromkeys(f"{col} as {' + '.join(s.columns[f][0])}" for f, col in e.hints.items() if s.columns.get(f) and s.columns[f][0])
            if named:
                raise InputError(str(e), fix=f"a batch has the run's columns: write {', '.join(named)} in it (check them first), then try again", hints=e.hints) from None
        raise InputError(str(e), fix=f"map it in the workspace, once the values look right: "
                         f"{nayose('set', 'columns', *(f'{f}={c}' for f, c in e.hints.items()), '--workspace', a['workspace'])}", hints=e.hints) from None
    if c.name in INDEXED and a.get("workspace") and (Path(a["workspace"]) / index.INDEX / "manifest.json").exists():  # a run changed: its index, built once, kept up to date
        r["index"] = indexed(a)
    return r


def indexed(a: dict) -> dict:  # the workspace's index brought up to date with its run, or why not: the run is written either way
    gc.collect()  # the run's DuckDB, if a cycle holds it: gone before the index may be built again beside it
    try:
        s, p, _ = setup(a)
        return index.update(Path(a["workspace"]), s, p)
    except Exception as e:
        said = e if isinstance(e, InputError) else out_of_memory(e) or InputError(f"{type(e).__name__}: {e}", fix=f"build it: {nayose('build', 'index', '--workspace', a['workspace'])}")
        return dict(error=str(said), fix=said.fix)


STEPS_OF = {"check records": ("load", "budget"), "apply decisions": ("decide",), "load records": ("load",),
            "try method": RUN_ORDER[:8]}  # the steps of a command that isn't a run: try method's two runs write nothing
FULL_RUNS = ("resolve records", "rerun records", "apply answers", "adopt method", "reset method", "lower trust", "raise trust", "split entity")
INDEXED = (*FULL_RUNS, "add records", "apply decisions", "set merging")  # the commands that change a run: its index is kept up to date after them


def last_run(ws: str | None, name: str) -> dict:
    """The steps a command runs and, for a run, the workspace's last run of the same kind (a full run, or a batch
    added): its seconds per step and its records, which the time left is measured against. No steps known: none."""
    batch = name in ("add records", "match records")
    if name not in FULL_RUNS and not batch:
        return dict(order=STEPS_OF.get(name, ()))
    try:
        runs = [r for r in folder.runs(Path(ws)) if bool(r.get("part")) == batch and r.get("steps") and r["steps"][0]["step"] == "load"] if ws else []
        steps = runs[-1]["steps"] if runs else []
        last, records = {s["step"]: float(s["seconds"]) for s in steps}, steps[0].get("records") if steps else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):  # an odd steps.json: no estimate, the command still runs
        steps, last, records = [], {}, None
    order = tuple(last) or (BATCH_ORDER if batch else RUN_ORDER)
    if name == "match records":  # a batch's steps, up to its entities: it writes nothing
        order = tuple(s for s in order if s not in ("report", "write"))
    if name == "split entity":  # the split decided, then a full run
        order = ("decide", *order)
    return dict(order=order, last=last or None, last_records=records)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # UTF-8 wherever it goes: a pipe or a file on Windows would take the locale's code page
        if hasattr(stream, "reconfigure") and stream.encoding.replace("-", "").lower() != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    a = parser().parse_args(argv)
    c = a.command
    emit = Emit(a.format, verbose=a.verbose, title=f"{c.name} · {getattr(a, 'workspace', None) or getattr(a, 'input', None) or ''}".rstrip(" ·"),
                **({} if a.format == "json" or c.quick else last_run(getattr(a, "workspace", None), c.name)))
    try:
        result = perform(c, {p.name: getattr(a, p.name) for p in c.params}, emit)
    except InputError as e:
        code = 75 if isinstance(e, Busy) else 2
        emit.error(e, code)
        return code
    except Exception as e:
        if not (oom := out_of_memory(e)):
            emit.close()
            raise
        emit.error(oom, 2)
        return 2
    except KeyboardInterrupt:  # Ctrl-C: nothing is half done, every write is staged
        emit.close()
        return 130
    code = result.pop("exit_code", 0)
    emit.result(c, result)
    return code


if __name__ == "__main__":
    sys.exit(main())
