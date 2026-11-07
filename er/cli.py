"""nayose (名寄せ: gathering each customer's records under one name), the command line, in kubectl's grammar: a verb,
then a noun, then its parameters.

    nayose check records customers.parquet
    nayose resolve records customers.parquet --run runs/customers
    nayose list pairs --run runs/customers --open

Each command is declared once, in COMMANDS: its verb and noun, what it does, its parameters, the fields of its result,
an example, and the function that runs it. The parser, the reference (docs/commands.md, reference()) and the UI's
forms are all built from those declarations. A command emits events: each step as it finishes, then one result, or an
error. --format text renders them for a person; --format json writes each as one JSON object per line. Every result
names the commands that usually come next. Exit codes: 0; 2, a mistake people fix, in two lines (what is wrong, and
how to fix it); 75, the run folder is busy: try again later; 1, a pass of serve inbox stopped on a file.
"""
import argparse
import json
import math
import shlex
import sys
import tomllib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from er import folder, inbox
from er.config import InputError, load_pipeline, sources_text
from er.folder import Busy
from er.report import applied, describe_entity, describe_matching, describe_run, fill_rates
from er.run import Run
from er.settings import SPECIAL, load_settings, set_columns, settings_path


@dataclass(frozen=True)
class Param:
    name: str
    help: str
    kind: str = "text"                        # text, path, flag, choice, many (several values)
    choices: tuple[str, ...] = ()
    positional: bool = False
    required: bool = False
    metavar: str = ""

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


def step_text(x: dict) -> str:  # one line per step, as it finishes: what it did, and how long it took
    base = ("event", "step", "big_o", "filled", "seconds", "peak_memory_gb")
    facts = " · ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in x.items() if k not in base and isinstance(v, int | float) and not isinstance(v, bool))
    return f"  {x['step']:<11} {x['seconds']:>6.1f} s  {facts}"


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


class Emit:
    """Where a command's events go: text for a person (steps and the result on stdout, an error on stderr), or JSON,
    one object per line, all on stdout."""

    def __init__(self, fmt: str = "text", out=None, err=None):
        self.fmt, self.out, self.err = fmt, out or sys.stdout, err or sys.stderr

    def _json(self, event: str, x: dict) -> None:
        print(json.dumps({"event": event, **plain(x)}, ensure_ascii=False), file=self.out, flush=True)

    def step(self, x: dict) -> None:
        self._json("step", x) if self.fmt == "json" else print(step_text(x), file=self.out, flush=True)

    def line(self, text: str, **data: object) -> None:  # a running note: serve inbox's files
        self._json("line", {"text": text, **data}) if self.fmt == "json" else print(text, file=self.out, flush=True)

    def result(self, c: Command, r: dict) -> None:
        self._json("result", {"command": c.name, **r}) if self.fmt == "json" else print(text(c, r), file=self.out, flush=True)

    def error(self, e: InputError, code: int) -> None:
        if self.fmt == "json":
            self._json("error", {"error": str(e), "fix": e.fix, "hints": e.hints, "exit": code})
        else:
            print(f"error: {e}" + (f"\nfix: {e.fix}" if e.fix else ""), file=self.err, flush=True)


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
    return "\n".join(out + ["next"] + [f"  {x['command']}    # {x['why']}" for x in r["next"]])


# ---------- what each command does ----------

def setup(a: dict):
    """The settings, with this run's DuckDB limits, the pipeline, and its file."""
    s = load_settings()
    if bad := [kv for kv in a.get("compute") or [] if "=" not in kv]:
        raise InputError(f"--compute {' '.join(bad)}: each limit is KEY=VALUE", fix="for example --compute memory_limit=8GB threads=4")
    s = replace(s, compute={**s.compute, **dict(kv.split("=", 1) for kv in a.get("compute") or [])})
    pipeline = Path(a.get("pipeline") or s.root / "config" / "final.toml")
    return s, load_pipeline(pipeline, s.standardize, s.chains, s.columns), pipeline


def sheet(out: Path, name: str) -> pd.DataFrame | None:
    return pd.read_parquet(out / name) if (out / name).exists() else None


def ids(frame: pd.DataFrame, uid: str) -> pd.DataFrame:  # the file's ID columns under the names every result uses: id, id_l, id_r
    return frame.rename(columns={uid: "id", f"{uid}_l": "id_l", f"{uid}_r": "id_r"})


def rows(frame: pd.DataFrame) -> list[dict]:
    return plain(frame.astype(object).where(frame.notna(), None).to_dict("records"))


def next_after(out: Path, uid: str) -> list[dict]:
    """What usually follows a run: the pairs and the kinds still open, then the folder at a glance."""
    found = []
    if (pairs := sheet(out, "review.parquet")) is not None and (n := int(((pairs["why"] == "decide") & pairs["decision"].isna()).sum())):
        found.append(dict(command=nayose("list", "pairs", "--run", out, "--open"), why=f"{n:,} pairs for people to decide"))
    if (kinds := sheet(out, "kind_review.parquet")) is not None and (n := int(kinds["kind"].isna().sum())):
        found.append(dict(command=nayose("list", "kinds", "--run", out, "--open"), why=f"{n:,} records to answer person or company"))
    return found + [dict(command=nayose("describe", "run", out), why="the run folder at a glance")]


def after_run(run: Run, out: Path) -> dict:
    wrote = ["gold.parquet", "review.parquet", "qa.md", "report.txt", *(["kind_review.parquet"] if (out / "kind_review.parquet").exists() and run.added is None else []),
             "matches/", "state/"]
    return dict(summary=run.tables["summary"].values.tolist(), seconds=round(sum(x["seconds"] for x in run.steps), 1),
                wrote=[str(out / f) for f in wrote], next=next_after(out, run.uid))


def check_records(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    run = Run(p, s, echo=emit.step)
    run.load(a["input"])
    plan = run.budget()
    fill = fill_rates(run).set_index("field")
    shown = plan[(plan["oversized_blocks"] > 0) | plan["name"].isin(plan.nlargest(5, "per_record")["name"])].sort_values("per_record", ascending=False)
    fields = [dict(field=f, filled=fill.loc[f, "filled"], looks_right=fill.loc[f, "looks_right"], top_value=fill.loc[f, "top_value"],
                   columns=sources_text(run.present[f])) if f in fill.index else dict(field=f, filled=None, looks_right=None, top_value=None, columns=None)
              for f in run.fields]
    keys = [dict(key=x.name, per_record=x.per_record, largest_block=x.largest_block, oversized_blocks=x.oversized_blocks,
                 oversized_records=x.oversized_records) for x in shown.itertuples()]
    return plain(dict(records=run.n, fields=fields, turned_off=run.disabled, keys=keys, oversized_from=p.fs.budget.min_oversized(), notes=run.notes,
                      next=[dict(command=nayose("resolve", "records", a["input"], "--run", "<run folder>"), why="ready: resolve them")]))


def list_columns(a: dict, emit: "Emit") -> dict:
    path = settings_path()
    found = []
    for f, spec in tomllib.loads(path.read_text(encoding="utf-8"))["columns"].items():
        src = spec["sources"] if isinstance(spec, dict) else spec
        alts = [[src]] if isinstance(src, str) else src
        options = " · ".join(f"{k} {v if isinstance(v, str) else ' '.join(v)}" for k, v in spec.items() if k != "sources") if isinstance(spec, dict) else ""
        found.append(dict(field=f, columns=", ".join(" + ".join(x) for x in alts), options=options))
    return dict(settings=str(path), columns=found, next=[dict(command=nayose("set", "columns", "FIELD=COLUMN"), why="map a field to other columns"),
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
    set_columns(settings_path(), mapping)
    return {**list_columns(a, emit), "next": [dict(command=nayose("check", "records", "<file>"), why="check a file with the new mapping")]}


def model_from(path: str | None) -> dict | None:
    if not path:
        return None
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    return saved.get("model", saved)


def resolve_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["run"])
    return after_run(Run(p, s, model=model_from(a["model"]), echo=emit.step).full(a["input"], out, overwrite=a["overwrite"], pipeline_file=pipeline), out)


def add_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["run"])
    run = Run(p, s, echo=emit.step).increment(a["input"], out, pipeline_file=pipeline)
    if run.added == 0:
        return dict(summary=[["nothing new", f"every record of {a['input']} is already in the run"]], next=next_after(out, run.uid))
    return after_run(run, out)


def match_records(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["run"])
    found = Run(p, s, echo=emit.step).match(a["input"], out)
    return dict(counts={k: int(v) for k, v in found["status"].value_counts().items()}, records=rows(ids(found, s.data.unique_id)),
                next=[dict(command=nayose("add", "records", a["input"], "--run", out), why="add them to the run")])


def rerun_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["run"])
    return after_run(Run(p, s, echo=emit.step).rerun(out, pipeline_file=pipeline), out)


def describe_run_(a: dict, emit: "Emit") -> dict:
    s, out = load_settings(), Path(a["run"])
    d = describe_run(duckdb.connect(), out, s.data.unique_id)
    return {**d, "next": next_after(out, s.data.unique_id)[:-1] + [dict(command=nayose("describe", "entity", "<record ID>", "--run", out),
                                                                       why="one record's entity, and what joined it")]}


def describe_entity_(a: dict, emit: "Emit") -> dict:
    s, out = load_settings(), Path(a["run"])
    uid = s.data.unique_id
    d = describe_entity(duckdb.connect(), out, uid, a["id"], [f for f in s.columns if f not in SPECIAL])
    rename = lambda xs: [{{uid: "id", f"{uid}_l": "id_l", f"{uid}_r": "id_r"}.get(k, k): v for k, v in x.items()} for x in xs]
    return dict(record=d["record"], entity=d["entity"], records=rename(d["records"]), links=rename(d["links"]),
                next=[dict(command=nayose("list", "pairs", "--run", out), why="the pairs for people")])


def describe_matching_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["run"]) if a["run"] else None
    return {**describe_matching(duckdb.connect(), out, p, s),
            "next": [dict(command=nayose("describe", "run", out), why="the run folder at a glance")] if out else
                    [dict(command=nayose("resolve", "records", "<file>", "--run", "<run folder>"), why="match records: the graph then holds their numbers")]}


def picked(frame: pd.DataFrame, why: str | None, only_open: bool) -> pd.DataFrame:
    keep = pd.Series(True, index=frame.index)
    if why:
        keep &= frame["why"] == why
    if only_open:
        keep &= frame["status"] == "open"
    return frame[keep]


def counts(frame: pd.DataFrame) -> dict[str, int]:  # rows by why and status
    return {f"{why} {status}": int(n) for (why, status), n in frame.groupby(["why", "status"]).size().items()}


def list_pairs(a: dict, emit: "Emit") -> dict:
    uid, out = load_settings().data.unique_id, Path(a["run"])
    pairs = sheet(out, "review.parquet")
    if pairs is None:
        raise InputError(f"no run in {out}", fix="resolve records into that folder first")
    done = pairs.merge(applied(out, uid), on=[f"{uid}_l", f"{uid}_r"], how="left", suffixes=("", "_applied"))["decision_applied"]
    pairs.insert(1, "status", np.where(done.notna() & (done == pairs["decision"]), "applied", np.where(pairs["decision"].notna(), "written in", "open")))
    return dict(counts=counts(pairs), pairs=rows(ids(picked(pairs, a["why"], a["open"]), uid)), next=[dict(command=nayose("decide", "pair", "<ID>", "<ID>", "match", "--run", out), why="decide one"),
                                                    dict(command=nayose("apply", "decisions", "--run", out), why="apply the decisions written in")])


def decide_pair(a: dict, emit: "Emit") -> dict:
    uid, out = load_settings().data.unique_id, Path(a["run"])
    first, second = sorted([a["first"], a["second"]])  # the sheet holds each pair lower ID first
    folder.type_in(out, "review.parquet", "decision", None if a["decision"] == "clear" else a["decision"], **{f"{uid}_l": first, f"{uid}_r": second})
    return dict(pair=[first, second], decision=a["decision"], next=[dict(command=nayose("apply", "decisions", "--run", out), why="apply them")])


def apply_decisions(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["run"])
    run = Run(p, s, echo=emit.step).decide(a["file"] or out / "review.parquet", out)
    x = run.steps[-1]
    return dict(decisions=x["decisions"], matches=x["matches"], clusters_joined=x["clusters_joined"],
                summary=[["nothing new", "every decision was applied before"]] if not x["decisions"] else [],
                next=[dict(command=nayose("describe", "run", out), why="the run folder at a glance")])


KINDS = {"person": 1, "company": 2, "unsure": 0, "clear": None}


def list_kinds(a: dict, emit: "Emit") -> dict:
    uid, out = load_settings().data.unique_id, Path(a["run"])
    kinds = sheet(out, "kind_review.parquet")
    if kinds is None:
        raise InputError(f"{out}: no kind_review.parquet", fix="a full run that tells persons from companies writes it: nayose resolve records …")
    kinds.insert(2, "status", np.where(kinds["kind"].notna(), "written in", "open"))
    return dict(counts=counts(kinds), kinds=rows(ids(picked(kinds, a["why"], a["open"]), uid)), next=[dict(command=nayose("answer", "kind", "<ID>", "company", "--run", out), why="answer one"),
                                                    dict(command=nayose("apply", "answers", "--run", out), why="apply the answers written in: a rerun")])


def answer_kind(a: dict, emit: "Emit") -> dict:
    uid, out = load_settings().data.unique_id, Path(a["run"])
    folder.type_in(out, "kind_review.parquet", "kind", KINDS[a["kind"]], **{uid: a["id"]})
    return dict(record=a["id"], kind=a["kind"], next=[dict(command=nayose("apply", "answers", "--run", out), why="apply them: a rerun")])


def apply_answers(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["run"])
    return after_run(Run(p, s, echo=emit.step, kind_labels=Path(a["file"] or out / "kind_review.parquet")).rerun(out, pipeline_file=pipeline), out)


def serve_inbox(a: dict, emit: "Emit") -> dict:
    every = float(a["every"]) if a["every"] else None
    ok = inbox.serve(Path(a["run"]), Path(a["inbox"]), every, int(a["retries"] or 2), a["compute"] or [], emit.line)
    return dict(stopped=not ok, exit_code=0 if ok else 1, next=[dict(command=nayose("describe", "run", a["run"]), why="the run folder at a glance")])


def open_ui(a: dict, emit: "Emit") -> dict:
    from er import ui  # the page's server: it reads these declarations
    ui.serve(int(a["port"] or 8765), a["run"], emit.line, open_browser=not a["link"])
    return dict(next=[])


# ---------- the declarations ----------

INPUT = Param("input", "the records: a Parquet file, a quoted glob ('in/*.parquet') or a folder of them, read together by column name",
              "path", positional=True)
RUN = Param("run", "the run folder", "path", required=True)
COMPUTE = Param("compute", "DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, "
                "temp_directory=<folder> (past the memory limit DuckDB spills there)", "many", metavar="KEY=VALUE")
PIPELINE = Param("pipeline", "the pipeline file (default: config/final.toml)", "path")
OPEN = Param("open", "only the rows nobody has answered", "flag")
FILE = lambda what: Param("file", f"{what} (default: the run folder's own sheet, with the answers written in)", "path")
RUN_RESULT = {"summary": "the run in words: records, entities, who joined them, the model's links, what is left to people",
              "seconds": "the run's time", "wrote": "the files written", "next": "the commands that usually follow"}
COMMANDS: tuple[Command, ...] = (
    Command("check", "records", "Read, map and check a file, in seconds; resolve nothing",
            "Reads the file through the door every input takes, maps its columns to the logical fields (config/settings.toml "
            "[columns]), and counts each key's pairs before any join. Shows each field's fill rate, the share of values that "
            "look like it and the share of its most common value, what would be turned off, and the blocks the run will check "
            "on a sample. A field the run needs and the file lacks stops it, with the column whose values look most like it. "
            "O(N) for the counts; a sample of 10,000 records for the shares.",
            (INPUT, COMPUTE, PIPELINE),
            {"records": "records read", "fields": "each field: filled, looks_right, top_value (shares), columns",
             "turned_off": "rules, keys and levels a missing field turns off", "keys": "each key's pairs per record and largest block",
             "oversized_from": "the block size checked by sampling", "notes": "what the loader detected or fixed", "next": "the commands that usually follow"},
            "nayose check records customers.parquet", check_records),
    Command("list", "columns", "Show which of a file's columns hold each field",
            "Reads config/settings.toml [columns] (or the ER_SETTINGS file): each field, its columns (a comma between fallbacks, "
            "+ between columns joined) and its options. O(the file).",
            (), {"settings": "the settings file", "columns": "each field: columns, options", "next": "the commands that usually follow"},
            "nayose list columns", list_columns, quick=True),
    Command("set", "columns", "Map fields to a file's columns",
            "Rewrites the named fields' lines in [columns]: FIELD=COLUMN, FIELD=A,B (B where A is empty), FIELD=A+B (A and B "
            "joined), FIELD= (the field goes). Every other line, each line's comment and a field's options stay; the new file "
            "is checked before it replaces the old. O(the file).",
            (Param("mapping", "one or more FIELD=COLUMNS", "many", positional=True, metavar="FIELD=COLUMNS"),),
            {"settings": "the settings file", "columns": "each field: columns, options", "next": "the commands that usually follow"},
            "nayose set columns phone=TEL4 person_name=NAME_KANA,SEI+MEI", set_columns_, quick=True),
    Command("resolve", "records", "Resolve a file: one ID per person or company",
            "A full run, without labels: load, budget, fit, rules, candidates, score, cluster, write, report. Writes the run "
            "folder: gold.parquet, matches/, rule_kept/, set_aside/, state/, steps.json, and for people qa.md, report.txt, "
            "review.parquet and kind_review.parquet. A folder that holds a run is refused without --overwrite; people's "
            "decisions and answers in it stand. O(N·L + ΣP + C·K·L²).",
            (INPUT, RUN, Param("overwrite", "replace the run the folder holds", "flag"), PIPELINE,
             Param("model", "a fitted model to score with instead of fitting one on the file (its JSON, or the file that holds it under 'model')", "path"),
             COMPUTE),
            RUN_RESULT, "nayose resolve records customers.parquet --run runs/customers", resolve_records),
    Command("add", "records", "Add new records to a run",
            "An increment: each new record compared with every stored one, with the run's model; it can join an existing "
            "entity. A record whose ID is already in the run is set aside, so adding the same file twice adds nothing. "
            "O(Δ·(L + Σb) + C_Δ·K·L²) plus narrow O(N) scans.",
            (INPUT, RUN, PIPELINE, COMPUTE), RUN_RESULT, "nayose add records new.parquet --run runs/customers", add_records),
    Command("match", "records", "Which entity each record would join; nothing written",
            "An increment's steps without its write: for each record, the entity it would join or a new one, and the rule or the "
            "model's best weight that links it. The run folder is left as it was. O(an increment).",
            (INPUT, RUN, PIPELINE, COMPUTE),
            {"counts": "records by status", "records": "each record: id, entity, status, by, weight", "next": "the commands that usually follow"},
            "nayose match records new.parquet --run runs/customers", match_records,
            show={"records": ("id", "entity", "status", "by", "weight")}),
    Command("rerun", "records", "A full run again, on the run's own files",
            "Reads the record files the run read, the full run's and each increment's, in order (steps.json; a scheduled batch "
            "found where the scheduler moved it), each checked by its SHA-256, and resolves them again in one full run: every "
            "pair compared again, an ID's records kept as the increments kept them. O(a full run).",
            (RUN, PIPELINE, COMPUTE), RUN_RESULT, "nayose rerun records --run runs/customers", rerun_records),
    Command("describe", "run", "What a run folder holds",
            "Records and entities, the largest entities, each run so far, the pairs and kinds still open and the answers written "
            "in, records set aside, a write still owed, and the last summary. O(N) in SQL.",
            (Param("run", "the run folder", "path", positional=True),),
            {"run": "the run folder", "records": "records", "entities": "entities", "largest": "the 10 largest entities",
             "runs": "each run so far: at, what, files, seconds", "pairs": "open pairs to decide and audit, and decisions written in",
             "kinds": "open records to decide and to measure, and answers written in", "set_aside": "records set aside",
             "write_owed": "a write cut short, finished by the next one", "summary": "the last run's summary", "next": "the commands that usually follow"},
            "nayose describe run runs/customers", describe_run_, quick=True,
            show={"largest": ("entity", "records"), "runs": ("at", "what", "seconds")}),
    Command("describe", "entity", "One record's entity, and what joined it",
            "The entity of the record ID: each of its records with its fields and kind, and every link between them: a rule, "
            "the model with its weight in bits, or people. O(N) in SQL.",
            (Param("id", "a record ID, as the run wrote it", positional=True, metavar="ID"), RUN),
            {"record": "the ID asked for", "entity": "its entity (the cluster_id)", "records": "each of the entity's records",
             "links": "each link between them: id_l, id_r, by, weight", "next": "the commands that usually follow"},
            "nayose describe entity 0000000151 --run runs/customers", describe_entity_, quick=True,
            show={"records": ("id", "resolved_by", "kind", "person_name", "company_name", "address", "postal_code", "phone", "customer_id", "birth_date"),
                  "links": ("id_l", "id_r", "by", "weight")}),
    Command("describe", "matching", "How records are matched: every method, on which fields, with its numbers",
            "The pipeline as a graph: records, how each field is made comparable, the rules, the ways pairs are listed, the "
            "comparisons and what each level is worth in bits, the line pairs are accepted at, the pairs left to people, and "
            "how linked records become customers. With --run, each part also holds that run's numbers and a real example. "
            "O(E + R + N) in SQL over the run's files.",
            (Param("run", "a run folder: its numbers and examples (without it, the methods only)", "path"), PIPELINE),
            {"nodes": "each part: id, name, method, its parameters and fields, and with --run its numbers and examples",
             "edges": "source, target, count", "next": "the commands that usually follow"},
            "nayose describe matching --run runs/customers", describe_matching_, quick=True),
    Command("list", "pairs", "The pairs for people to decide and to audit",
            "The run's review.parquet: decide rows (the pairs just below the threshold, and those above it with no name "
            "compared) and audit rows (accepted pairs just above it), each with both records' fields, each comparison's level "
            "and bits, and a status: open, written in, or applied. O(sheet rows).",
            (RUN, Param("why", "decide or audit only", "choice", ("decide", "audit")), OPEN),
            {"counts": "rows by why and status", "pairs": "each pair: why, status, decision, id_l, id_r, match_weight, accepted, fields, levels",
             "next": "the commands that usually follow"},
            "nayose list pairs --run runs/customers --open", list_pairs, quick=True,
            show={"pairs": ("why", "status", "id_l", "id_r", "match_weight", "accepted")}),
    Command("decide", "pair", "Decide one pair: match or no match",
            "Writes the decision into the run folder's review.parquet; nothing is applied until apply decisions. clear takes "
            "it back. O(sheet rows).",
            (Param("first", "one record ID of the pair", positional=True, metavar="ID"), Param("second", "the other", positional=True, metavar="ID"),
             Param("decision", "match, no_match, or clear", "choice", ("match", "no_match", "clear"), positional=True), RUN),
            {"pair": "the two IDs, lower first", "decision": "what was written", "next": "the commands that usually follow"},
            "nayose decide pair 0000000151 0000000152 match --run runs/customers", decide_pair, quick=True),
    Command("apply", "decisions", "Apply people's decisions to the run",
            "Each match pair joins its two entities at once, scoring nothing; no_match is kept, and a full run never accepts "
            "the pair. Decisions are kept in decisions/; one applied before changes nothing. O(D + touched clusters) + O(N).",
            (RUN, FILE("a file of decisions: the two ID columns and decision"), PIPELINE),
            {"decisions": "decisions applied", "matches": "of them, match", "clusters_joined": "entities joined",
             "summary": "said when nothing was new", "next": "the commands that usually follow"},
            "nayose apply decisions --run runs/customers", apply_decisions),
    Command("list", "kinds", "The records for people to answer person or company",
            "The run's kind_review.parquet: decide rows (where the engine and the file's flag disagree, and the flag's likely "
            "errors) and measure rows (a random draw that places the engine's lines), each with what the engine, the name and "
            "the flag say, and why it is there. O(sheet rows).",
            (RUN, Param("why", "decide or measure only", "choice", ("decide", "measure")), OPEN),
            {"counts": "rows by why and status", "kinds": "each record: id, why, status, reason, engine_says, name_says, name, kind",
             "next": "the commands that usually follow"},
            "nayose list kinds --run runs/customers --open", list_kinds, quick=True,
            show={"kinds": ("id", "why", "status", "name", "engine_says", "name_says", "flag")}),
    Command("answer", "kind", "Answer one record: person, company, or unsure",
            "Writes the answer into the run folder's kind_review.parquet (1 person, 2 company, 0 can't tell); nothing is "
            "applied until apply answers. clear takes it back. A sole trader is a person. O(sheet rows).",
            (Param("id", "the record ID", positional=True, metavar="ID"), Param("kind", "person, company, unsure, or clear", "choice", tuple(KINDS), positional=True), RUN),
            {"record": "the ID", "kind": "what was written", "next": "the commands that usually follow"},
            "nayose answer kind 0000000151 company --run runs/customers", answer_kind, quick=True),
    Command("apply", "answers", "Apply people's person/company answers: a rerun",
            "The answers stand for their records, teach the engine, and the draw to measure places its lines; they are kept in "
            "kind_answers/. They change how each name is matched, so they are applied by a full run on the run's own files "
            "(rerun records). O(a full run).",
            (RUN, FILE("a file of answers: the ID column and kind"), PIPELINE, COMPUTE), RUN_RESULT,
            "nayose apply answers --run runs/customers", apply_answers),
    Command("serve", "inbox", "Take in every file dropped in an inbox, one at a time",
            "inbox/batches/ (new records: add records; into an empty run folder, resolve records), inbox/decisions/ (apply "
            "decisions), inbox/answers/ (apply answers), oldest first, each as its nayose command in a process of its own. "
            "Done files go to inbox/done/, ones people must fix to inbox/failed/ with their error; any other failure is tried "
            "again, then stops the pass with the file left in place. One pass, or one every --every seconds. Each file is a "
            "line in <run>/jobs.jsonl.",
            (Param("inbox", "the inbox folder", "path", positional=True, metavar="INBOX"), RUN,
             Param("every", "seconds between passes; without it, one pass", "text", metavar="SECONDS"),
             Param("retries", "attempts after an unexpected failure (default 2)", "text", metavar="N"), COMPUTE),
            {"stopped": "the pass stopped on a file that kept failing", "next": "the commands that usually follow"},
            "nayose serve inbox inbox --run runs/customers --every 300", serve_inbox),
    Command("open", "ui", "The commands in a browser, on this machine only",
            "Serves a page on 127.0.0.1, reachable only from this machine and only with the link it prints, and opens it. Its "
            "screens follow the work: records, columns, check and run, results, pairs (keys M, N, S), kinds (keys 1, 2, 0). Each "
            "button runs one of these commands, shown as the command line it is; lists, describes and single answers run in "
            "the page's own process, the others each in a process of their own, one at a time. Nothing is loaded from the "
            "network. Ctrl-C stops it.",
            (Param("run", "the run folder the page starts with", "path"), Param("port", "the port (default 8765; 0: any free one)", metavar="PORT"),
             Param("link", "print the link only; open no browser", "flag")),
            {"next": "the commands that usually follow"}, "nayose open ui --run runs/customers", open_ui),
)


# ---------- the parser and the reference, from the declarations ----------

def parser(kind: type[argparse.ArgumentParser] = argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The parser, from the declarations; `kind` its class, which every subcommand's parser takes too."""
    raw = argparse.RawDescriptionHelpFormatter
    top = kind(prog="nayose", description=__doc__.split("\n\n")[0], formatter_class=raw,
                                  epilog="commands:\n" + "\n".join(f"  {c.name:<18} {c.help}" for c in COMMANDS) +
                                         "\n\nnayose VERB NOUN --help says what one does; docs/commands.md has them all.")
    verbs = top.add_subparsers(dest="verb", required=True, metavar="VERB")
    for verb in dict.fromkeys(c.verb for c in COMMANDS):
        mine = [c for c in COMMANDS if c.verb == verb]
        vp = verbs.add_parser(verb, help=", ".join(c.noun for c in mine), formatter_class=raw,
                              description="\n".join(f"{c.name}: {c.help}" for c in mine))
        nouns = vp.add_subparsers(dest="noun", required=True, metavar="NOUN")
        for c in mine:
            cp = nouns.add_parser(c.noun, help=c.help, description=f"{c.help}.\n\n{c.about}", epilog=f"example:\n  {c.example}", formatter_class=raw)
            for p in c.params:
                kw = dict(help=p.help)
                if p.kind == "flag":
                    cp.add_argument(f"--{p.name}", action="store_true", **kw)
                    continue
                if p.choices:
                    kw["choices"] = p.choices
                if p.kind == "many":
                    kw["nargs"] = "+" if p.positional else "*"
                if p.metavar and not p.choices:
                    kw["metavar"] = p.metavar
                if p.positional:
                    cp.add_argument(p.name, **kw)
                else:
                    cp.add_argument(f"--{p.name}", required=p.required, **kw)
            cp.add_argument("--format", choices=("text", "json"), default="text", help="text for people (the default); json: one object per line")
            cp.set_defaults(command=c)
    return top


def synopsis(c: Command) -> str:
    words = ["nayose", c.verb, c.noun]
    for p in c.params:
        value = "|".join(p.choices) if p.choices else p.shown + (" …" if p.kind == "many" else "")
        word = value if p.positional else f"--{p.name}" if p.kind == "flag" else f"--{p.name} {value}"
        words.append(word if p.positional or p.required else f"[{word}]")
    return " ".join(words + ["[--format text|json]"])


def reference() -> str:
    """docs/commands.md: every command, from its declaration."""
    out = ["[← README](../README.md) · [Usage](usage.md)", "", "# Commands", "",
           "Written by `scripts/document_commands.py` from the declarations in `er/cli.py`; `tests/test_design.py` fails when "
           "the two differ.", "", "`nayose` (名寄せ: gathering each customer's records under one name) reads as a sentence: a "
           "verb, a noun, then the parameters. Every command takes `--help` and `--format`.", "",
           "- **`--format text`**, the default: each step on a line as it finishes, then the result, for a person.",
           "- **`--format json`**: one JSON object per line: `{\"event\": \"step\", …}` per step, then `{\"event\": \"result\", "
           "\"command\": …, …}` with the fields listed below, or `{\"event\": \"error\", \"error\": …, \"fix\": …, \"hints\": …, "
           "\"exit\": …}`. IDs are `id`, `id_l`, `id_r`, whatever the file calls them.",
           "- **Exit codes:** 0; 2, a mistake people fix (two lines: what is wrong, and the fix); 75, the run folder is busy: "
           "try again later; 1, a pass of `serve inbox` stopped on a file.",
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


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    c, emit = a.command, Emit(a.format)
    try:
        result = c.run({p.name: getattr(a, p.name) for p in c.params}, emit)
    except InputError as e:
        code = 75 if isinstance(e, Busy) else 2
        emit.error(e, code)
        return code
    except KeyboardInterrupt:  # Ctrl-C: nothing is half done, every write is staged
        return 130
    code = result.pop("exit_code", 0)
    emit.result(c, result)
    return code


if __name__ == "__main__":
    sys.exit(main())
