"""Where a command's events go: JSON, one object per line, for programs and the page; for a person, a line per
finished step and one for the step under way, redrawn (Live), then the result as er.brief writes it."""
from __future__ import annotations
import json
import math
import shutil
import sys
import threading
import time
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from er.brief import BRIEF, count, text, took
from er.config import InputError

if TYPE_CHECKING:
    from er.cli import Command


def plain(x: object) -> object:
    """A value JSON can carry: numpy and pandas scalars as Python ones, NaN and NA as null."""
    t = type(x)
    if t is str or t is int or t is bool or x is None:  # most of a result's values, each in one test: a sheet's rows are thousands
        return x
    if t is float:
        return None if math.isnan(x) else x
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [plain(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if x is pd.NA or x is pd.NaT or (isinstance(x, float) and math.isnan(x)):
        return None
    return x if isinstance(x, str | int | float | bool) or x is None else str(x)


DOING = {"load": "reading the records", "budget": "planning the work", "fit": "learning what matches look like", "rules": "applying the match rules", "keys": "checking the keys",
         "candidates": "listing pairs to compare", "score": "scoring the pairs", "cluster": "forming entities",
         "probe": "looking for matches it missed", "gap": "measuring what the keys miss", "report": "writing the report", "write": "saving", "decide": "applying the decisions"}  # the terminal's and the page's



RUN_ORDER = ("load", "budget", "fit", "rules", "keys", "candidates", "score", "cluster", "probe", "gap", "report", "write")  # a full run's steps
BATCH_ORDER = ("load", "fit", "rules", "candidates", "score", "cluster", "report", "write")  # a batch added: no budget, no probe


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



def rows_told(emit: "Emit | None"):  # the rows read so far, for a file being read
    return emit and (lambda n, whole: emit.progress(n, whole, "rows"))
