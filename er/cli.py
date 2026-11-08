"""nayose (名寄せ: gathering each customer's records under one name), the command line, in kubectl's grammar: a verb,
then a noun, then its parameters.

    nayose check records customers.parquet
    nayose resolve records customers.parquet --workspace workspaces/customers
    nayose list pairs --workspace workspaces/customers --open

Each command is declared once, in COMMANDS: its verb and noun, what it does, its parameters, the fields of its result,
an example, and the function that runs it. The parser, the reference (docs/commands.md, reference()) and the UI's
forms are all built from those declarations. A command emits events: each step as it finishes, then one result, or an
error. --format text renders them for a person; --format json writes each as one JSON object per line. Every result
names the commands that usually come next. Exit codes: 0; 2, a mistake people fix, in two lines (what is wrong, and
how to fix it); 75, the workspace is busy: try again later; 1, a pass of serve inbox stopped on a file.
"""
import argparse
import contextlib
import functools
import json
import math
import shlex
import sys
import tempfile
import tomllib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from er import folder, inbox, intake
from er.config import InputError, adjust, load_pipeline, restrict, sources_text, widen
from er.folder import Busy
from er.report import (applied, compare_records, describe_entity, describe_key, describe_matching, describe_method, describe_workspace, entity_pairs, explain_pair, fill_rates,
                       list_patterns, trust_state)
from er.source import describe, find, lexicon
from er.run import Run, trial
from er.settings import (COLUMNS, SPECIAL, add_feature, added_of, beside, columns_file, features_of, load_settings, offers, own_columns,
                         placements, present_fields, remove_feature, set_columns, set_features, settings_path, slots)


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
    return "\n".join(out + ["next"] + [f"  {x['command']}    # {x['why']}" for x in r["next"]])


# ---------- what each command does ----------

def settings_for(a: dict):  # the settings, with the named workspace's own mapping when it keeps one
    return load_settings(columns=columns_file(a.get("workspace")))


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


def next_after(out: Path, uid: str) -> list[dict]:
    """What usually follows a run: the pairs and the kinds still open, then the folder at a glance."""
    found = []
    if (pairs := sheet(out, "review.parquet")) is not None and (n := int(((pairs["why"] == "decide") & pairs["decision"].isna()).sum())):
        found.append(dict(command=nayose("list", "pairs", "--workspace", out, "--open"), why=f"{n:,} pairs for people to decide"))
    if (kinds := sheet(out, "kind_review.parquet")) is not None and (n := int(kinds["kind"].isna().sum())):
        found.append(dict(command=nayose("list", "kinds", "--workspace", out, "--open"), why=f"{n:,} records to answer person or company"))
    return found + [dict(command=nayose("describe", "workspace", out), why="the workspace at a glance")]


def after_run(run: Run, out: Path) -> dict:
    wrote = ["gold.parquet", "review.parquet", "qa.md", "report.txt", *(["kind_review.parquet"] if (out / "kind_review.parquet").exists() and run.added is None else []),
             "matches/", "state/"]
    return dict(summary=run.tables["summary"].values.tolist(), seconds=round(sum(x["seconds"] for x in run.steps), 1),
                wrote=[str(out / f) for f in wrote], next=next_after(out, run.uid))


def check_records(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    with readable(a["input"], s) as path:
        return checked(a, s, p, path, emit)


def checked(a: dict, s, p, path: str, emit: "Emit") -> dict:
    run = Run(p, s, echo=emit.step)
    try:
        run.load(path)
    except InputError as e:
        if not (a.get("workspace") and e.hints):
            raise
        raise InputError(str(e), fix=f"map it in the workspace, once the values look right: "
                         f"{nayose('set', 'columns', *(f'{f}={c}' for f, c in e.hints.items()), '--workspace', a['workspace'])}", hints=e.hints) from None
    plan = run.budget()
    fill = fill_rates(run).set_index("field")
    shown = plan[(plan["oversized_blocks"] > 0) | plan["name"].isin(plan.nlargest(5, "per_record")["name"])].sort_values("per_record", ascending=False)
    fields = [dict(field=f, filled=fill.loc[f, "filled"], looks_right=fill.loc[f, "looks_right"], top_value=fill.loc[f, "top_value"],
                   columns=sources_text(run.present[f])) if f in fill.index else dict(field=f, filled=None, looks_right=None, top_value=None, columns=None)
              for f in run.fields]
    keys = [dict(key=x.name, per_record=x.per_record, largest_block=x.largest_block, oversized_blocks=x.oversized_blocks,
                 oversized_records=x.oversized_records) for x in shown.itertuples()]
    return plain(dict(records=run.n, fields=fields, turned_off=run.disabled, keys=keys, oversized_from=p.fs.budget.min_oversized(), notes=run.notes, read=read_of(Path(path)),
                      next=[dict(command=nayose("resolve", "records", a["input"], "--workspace", "<workspace>"), why="ready: resolve them")]))


def list_columns(a: dict, emit: "Emit") -> dict:
    path = columns_file(a.get("workspace")) or settings_path()
    found = []
    for f, spec in tomllib.loads(path.read_text(encoding="utf-8"))["columns"].items():
        src = spec["sources"] if isinstance(spec, dict) else spec
        alts = [[src]] if isinstance(src, str) else src
        options = " · ".join(f"{k} {v if isinstance(v, str) else ' '.join(v)}" for k, v in spec.items() if k != "sources") if isinstance(spec, dict) else ""
        found.append(dict(field=f, columns=", ".join(" + ".join(x) for x in alts), options=options))
    there = ["--workspace", a["workspace"]] if a.get("workspace") else []
    return dict(settings=str(path), own=path.name == COLUMNS, columns=found,
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
    ws = a.get("workspace")
    if ws and not Path(ws).is_dir():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    if ws and not columns_file(ws):  # a workspace made before it kept its own mapping starts from the project's
        (Path(ws) / COLUMNS).write_text(own_columns(settings_path()), encoding="utf-8")
    set_columns(columns_file(ws) or settings_path(), mapping)
    return {**list_columns(a, emit), "next": [dict(command=nayose("check", "records", "<file>"), why="check a file with the new mapping")]}


def model_from(path: str | None) -> dict | None:
    if not path:
        return None
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    return saved.get("model", saved)


def given(a: dict) -> str:
    """The records a run reads: the file named, copied into the workspace first; without one, the file loaded last."""
    ws, s = Path(a["workspace"]), settings_for(a)
    if a["input"]:
        return str(folder.take_in(ws, a["input"], s.input, s.paths["reference"])[0])
    if not (parts := folder.parts(ws)):
        raise InputError(f"no records file in {ws}", fix=f"load one: nayose load records FILE --workspace {ws}; or name it here")
    return str(parts[-1])


SLOT_FIELD = {"person name": "person_name", "family": "person_name", "given": "given_name", "company name": "company_name"}  # a slot without a field of its own: whose pattern its values should match


@contextlib.contextmanager
def readable(path: str, s, strict: bool = False):
    """A path as the door reads it: a workspace's part, as its intake read it; any other file or files, read for this
    command alone into a folder that goes once it ends (er.intake); people's files strictly: one that needs a repair is
    refused."""
    p = Path(path)
    if p.is_dir() and intake.report(p):
        yield str(p)
        return
    files, root = find(path), p if p.is_dir() else None
    with tempfile.TemporaryDirectory(prefix="nayose-") as t:
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


def describe_records(a: dict, emit: "Emit") -> dict:
    with readable(a["input"], settings_for(a)) as path:
        d = described({**a, "given": a["input"], "input": path})
        return {**d, "read": read_of(Path(path))}


def described(a: dict) -> dict:
    (s, p, _), there = setup(a), ["--workspace", a["workspace"]] if a.get("workspace") else []
    feats = features_of(a.get("workspace"))
    script = {path: f.get("script") for g in feats for f in g["features"] for path, _ in slots([dict(g, features=[f])])}
    def field(path: str, x: dict) -> str | None:  # whose pattern a slot's values should match: none in a script the patterns aren't written in
        if script[path] not in (None, "kana"):
            return None
        return (None if x.get("added") else x.get("field")) or SLOT_FIELD.get(x.get("role") or x.get("type"))
    d = describe(a["input"], duckdb.connect(), s.columns, s.detect, lex=lexicon(s.paths["reference"], tuple(s.standardize.kana_fold.items())),
                 slots={path: x["columns"] for path, x in slots(feats)},
                 slot_patterns={path: s.detect[f] for path, x in slots(feats) if (f := field(path, x)) in s.detect})
    try:  # what a run of this file would turn off, as the run decides it: from the mapping, no record read
        off = restrict(p, set(present_fields(s, [c["column"] for c in d["columns"]])))[1]
    except InputError as e:
        off = [str(e)]
    d = {**d, "features": feats, "placements": placements(feats, d["profile"], d["fit"]), "offers": offers(feats, d["profile"]),
         "needed": dict(every=list(p.fields.mandatory), one_of=[list(g) for g in p.fields.one_of]), "turned_off": off}
    found = [f"{x['feature']}={x['column']}" for x in d["placements"]]
    waiting = (intake.report(Path(a["input"])) or {}).get("proposed", {}) if there else {}
    return {**d, "next": [dict(command=nayose("accept", "repairs", k, *there), why=f"{n:,} proposed: see them first, in read.examples") for k, n in waiting.items()] +
            ([dict(command=nayose("set", "feature", *found, *there), why="place what the file's contents suggest")] if found and there else []) +
            [dict(command=nayose("resolve", "records", *there) if there else nayose("check", "records", a["given"]),
                  why="find matches in it" if there else "the full check: every record prepared, every key counted")]}


def load_records(a: dict, emit: "Emit") -> dict:
    ws, s = Path(a["workspace"]), settings_for(a)
    part, copied = folder.take_in(ws, a["input"], s.input, s.paths["reference"])
    return {**describe_records({**a, "input": str(part)}, emit), "loaded": str(part), "copied": copied}


def list_features(a: dict, emit: "Emit") -> dict:
    feats = features_of(a.get("workspace"))
    return dict(features=feats, slots=[dict(feature=path, columns=sources_text(x["columns"])) for path, x in slots(feats)],
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
    set_features(a["workspace"], values)
    return {**list_features(a, emit), "next": [dict(command=nayose("describe", "records", "<file>", "--workspace", a["workspace"]), why="see how the file fills them")]}


def add_feature_(a: dict, emit: "Emit") -> dict:
    add_feature(a["workspace"], a["path"], a["type"], a["script"], a["column"])
    return {**list_features(a, emit), "next": [dict(command=nayose("describe", "records", "<file>", "--workspace", a["workspace"]), why="see how the file fills it")]}


def remove_feature_(a: dict, emit: "Emit") -> dict:
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
    return after_run(Run(p, s, model=model_from(a["model"]), echo=emit.step).full(given(a), out, overwrite=a["overwrite"], pipeline_file=pipeline), out)


def add_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    run = Run(p, s, echo=emit.step).increment(path := given(a), out, pipeline_file=pipeline)
    if run.added == 0:
        return dict(summary=[["nothing new", f"every record of {path} is already in the run"]], next=next_after(out, run.uid))
    return after_run(run, out)


def match_records(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    with readable(a["input"], s) as path:
        found = Run(p, s, echo=emit.step).match(path, out)
    return dict(counts={k: int(v) for k, v in found["status"].value_counts().items()}, records=rows(ids(found, s.data.unique_id)),
                next=[dict(command=nayose("add", "records", a["input"], "--workspace", out), why="add them to the run")])


def rerun_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    return after_run(Run(p, s, echo=emit.step).rerun(out, pipeline_file=pipeline), out)


def try_method(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws, now = Path(a["workspace"]), folder.method(Path(a["workspace"]))
    rules, keys = {r.name for _, _, r in p.rules.each()}, {b.name for b in p.fs.blockers}
    if bad := [x for x in a.get("drop") or [] if x not in rules | keys]:
        raise InputError(f"--drop {' '.join(bad)}: no match rule or pair key of the method has that name", fix="see them: nayose describe method --workspace …")
    method = {**now, **({"line": number(a["line"], "--line")} if a.get("line") else {})}
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


def number(text: str, what: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise InputError(f"{what} {text}: not a number", fix="a weight in bits, for example 9 or 9.5") from None


def adopt(a: dict, emit: "Emit", method: dict) -> dict:
    """The workspace's method.toml set to `method` ({}: none, the tuned method), then a run with it; method.toml as it
    was if the run fails, so the method and the run always agree."""
    ws = Path(a["workspace"])
    path, old = ws / folder.METHOD, (ws / folder.METHOD).read_text(encoding="utf-8") if (ws / folder.METHOD).exists() else None
    with folder.run_lock(ws):  # held through the run: no other writer sees the new method before its run
        setup(a, method)  # a method that no longer fits the pipeline is refused before anything changes
        if method:
            path.write_text("".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in method.items()), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
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
    return adopt(a, emit, json.loads(f.read_text(encoding="utf-8"))["method"])


def reset_method(a: dict, emit: "Emit") -> dict:
    return adopt(a, emit, {})


def lower_trust(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    ws = Path(a["workspace"])
    state = trust_state(duckdb.connect(), ws, p, s.data.unique_id) if (ws / "gold.parquet").exists() else None
    if state is None:
        raise InputError(f"{ws} has no trust line: it merges as tuned", fix="start one, and nothing merges before people check: nayose raise trust --workspace …")
    if not state["may_lower"]:
        span = state["next"]
        raise InputError(f"the range below the line isn't proven yet: {state['checked']:,} of {state['needed']:,} checked, {state['false']:,} found false"
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
    out, count = Path(a["workspace"]), int(number(a.get("count") or "50", "--count"))
    run = Run(p, s, echo=emit.step).draw(out, count)
    return dict(drawn=run.steps[-1]["drawn"], next=[dict(command=nayose("list", "pairs", "--workspace", out, "--why", "audit", "--open"), why="the audits to decide")])


def describe_workspace_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    d = describe_workspace(duckdb.connect(), out, s.data.unique_id)
    d["trust"] = trust_state(duckdb.connect(), out, p, s.data.unique_id) if d["records"] else None
    files = folder.loaded(out)
    then = (next_after(out, s.data.unique_id)[:-1] + [dict(command=nayose("describe", "entity", "<record ID>", "--workspace", out),
                                                           why="one record's entity, and what joined it")] if d["records"] else
            [dict(command=nayose("resolve", "records", "--workspace", out), why="find matches in the file loaded last")] if files else
            [dict(command=nayose("load", "records", "<file>", "--workspace", out), why="give it your records file")])
    then = [dict(command=nayose("describe", "records", f["path"], "--workspace", out), why=f"{f['waiting']:,} repairs wait in {f['name']}: see them, then accept repairs")
            for f in files if f.get("waiting")] + then
    return {**d, "inputs": files, "columns": "own" if columns_file(out) else "project", "next": then}


def describe_entity_(a: dict, emit: "Emit") -> dict:
    s, out = settings_for(a), Path(a["workspace"])
    uid = s.data.unique_id
    d = describe_entity(duckdb.connect(), out, uid, a["id"], [f for f in s.columns if f not in SPECIAL])
    rename = lambda xs: [{{uid: "id", f"{uid}_l": "id_l", f"{uid}_r": "id_r"}.get(k, k): v for k, v in x.items()} for x in xs]
    inside = entity_pairs(out, s, [x[uid] for x in d["records"]], d["links"])
    return dict(record=d["record"], entity=d["entity"], records=rename(d["records"]), links=rename(d["links"]), **inside,
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
    return {**describe_matching(duckdb.connect(), out, p, s),
            "next": [dict(command=nayose("describe", "workspace", out), why="the workspace at a glance")] if out else
                    [dict(command=nayose("resolve", "records", "<file>", "--workspace", "<workspace>"), why="match records: the graph then holds their numbers")]}


def describe_method_(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    return {**describe_method(out, p, s), "next": [dict(command=nayose("list", "pairs", "--workspace", out, "--open"), why="the pairs left to decide")]}


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
    uid, out = settings_for(a).data.unique_id, Path(a["workspace"])
    pairs = sheet(out, "review.parquet")
    if pairs is None:
        raise InputError(f"no run in {out}", fix="resolve records into that folder first")
    done = pairs.merge(applied(out, uid), on=[f"{uid}_l", f"{uid}_r"], how="left", suffixes=("", "_applied"))["decision_applied"]
    pairs.insert(1, "status", np.where(done.notna() & (done == pairs["decision"]), "applied", np.where(pairs["decision"].notna(), "written in", "open")))
    return dict(counts=counts(pairs), pairs=rows(ids(picked(pairs, a["why"], a["open"]), uid)), next=[dict(command=nayose("decide", "pair", "<ID>", "<ID>", "match", "--workspace", out), why="decide one"),
                                                    dict(command=nayose("apply", "decisions", "--workspace", out), why="apply the decisions written in")])


def split_entity(a: dict, emit: "Emit") -> dict:
    """An entity split at a link that alone holds it together: that pair decided different (Run.decide stores it with
    people's decisions), then a full run, which never accepts a pair people called different."""
    import tempfile
    s, p, _ = setup(a)
    out, uid = Path(a["workspace"]), s.data.unique_id
    if len(a["between"] or []) != 2:
        raise InputError("--between takes the two records of the link", fix="nayose split entity ID --between A B --workspace …")
    first, second = sorted(map(str, a["between"]))
    d = describe_entity(duckdb.connect(), out, uid, a["id"], [f for f in s.columns if f not in SPECIAL])
    ids = [x[uid] for x in d["records"]]
    if not {first, second} <= set(ids):
        raise InputError(f"{first} and {second}: not both records of the entity of {a['id']}", fix="see its records: nayose describe entity ID --workspace …")
    inside = entity_pairs(out, s, ids, d["links"])
    if inside["capped"]:
        raise InputError(f"the entity of {a['id']} holds {len(ids):,} records: too many to find where it splits", fix="decide its pairs in step 4 instead")
    if dict(id_l=first, id_r=second) not in inside["weakest"]:
        raise InputError(f"{first} – {second} doesn't hold the entity together: other links still join them",
                         fix="split it at one of its weakest links: nayose describe entity ID --workspace … lists them")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "split.parquet"
        pd.DataFrame({f"{uid}_l": [first], f"{uid}_r": [second], "decision": ["no_match"], "why": ["split"]}).to_parquet(f, index=False)
        Run(p, s, echo=emit.step).decide(f, out)
    return rerun_records(a, emit)


def decide_pair(a: dict, emit: "Emit") -> dict:
    uid, out = settings_for(a).data.unique_id, Path(a["workspace"])
    first, second = sorted([a["first"], a["second"]])  # the sheet holds each pair lower ID first
    folder.type_in(out, "review.parquet", "decision", None if a["decision"] == "clear" else a["decision"], **{f"{uid}_l": first, f"{uid}_r": second})
    return dict(pair=[first, second], decision=a["decision"], next=[dict(command=nayose("apply", "decisions", "--workspace", out), why="apply them")])


def apply_decisions(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    with readable(a["file"], s, strict=True) if a["file"] else contextlib.nullcontext(out / "review.parquet") as path:
        run = Run(p, s, echo=emit.step).decide(path, out)
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
    kinds.insert(2, "status", np.where(kinds["kind"].notna(), "written in", "open"))
    return dict(counts=counts(kinds), kinds=rows(ids(picked(kinds, a["why"], a["open"]), uid)), next=[dict(command=nayose("answer", "kind", "<ID>", "company", "--workspace", out), why="answer one"),
                                                    dict(command=nayose("apply", "answers", "--workspace", out), why="apply the answers written in: a rerun")])


def answer_kind(a: dict, emit: "Emit") -> dict:
    uid, out = settings_for(a).data.unique_id, Path(a["workspace"])
    folder.type_in(out, "kind_review.parquet", "kind", KINDS[a["kind"]], **{uid: a["id"]})
    return dict(record=a["id"], kind=a["kind"], next=[dict(command=nayose("apply", "answers", "--workspace", out), why="apply them: a rerun")])


def apply_answers(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    with readable(a["file"], s, strict=True) if a["file"] else contextlib.nullcontext(out / "kind_review.parquet") as path:
        return after_run(Run(p, s, echo=emit.step, kind_labels=find(path)[0]).rerun(out, pipeline_file=pipeline), out)


def serve_inbox(a: dict, emit: "Emit") -> dict:
    every = float(a["every"]) if a["every"] else None
    ok = inbox.serve(Path(a["workspace"]), Path(a["inbox"]), every, int(a["retries"] or 2), a["compute"] or [], emit.line)
    return dict(stopped=not ok, exit_code=0 if ok else 1, next=[dict(command=nayose("describe", "workspace", a["workspace"]), why="the workspace at a glance")])


def open_ui(a: dict, emit: "Emit") -> dict:
    from er import ui  # the page's server: it reads these declarations
    ui.serve(int(a["port"] or 8765), a["workspace"], a["home"] or "workspaces", emit.line, open_browser=not a["link"])
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
             "slots": "each feature and part: feature (its path), sources, filled, example, looks_right, and each of its alternatives",
             "features": "the structure: groups › features › parts, each with type and columns",
             "profile": "each column's script (kanji, kana, romaji) and the shares of its values that are known family names, given names, full names, addresses",
             "placements": "for each feature with no column: feature, column, share, why (the file's contents)",
             "offers": "new features the contents suggest: feature, type, script, column, share, why", "notes": "what the reader detected or fixed",
             "read": "what the reader found (er.intake): rows, values per encoding, fixed (controls, placeholders, numbers, damaged), proposed and waiting: repairs by kind (realign, garbled, encoding) for accept repairs, with examples; unread rows", "next": "the commands that usually follow"}
CHECKED = {"records": "records read", "fields": "each field: filled, looks_right, top_value (shares), columns",
           "turned_off": "rules, keys and levels a missing field turns off", "keys": "each key's pairs per record and largest block",
           "oversized_from": "the block size checked by sampling", "notes": "what the loader detected or fixed", "read": "what the reader found (er.intake): rows, values per encoding, fixed (controls, placeholders, numbers, damaged), proposed and waiting: repairs by kind (realign, garbled, encoding) for accept repairs, with examples; unread rows",
           "next": "the commands that usually follow"}
COMPUTE = Param("compute", "DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, "
                "temp_directory=<folder> (past the memory limit DuckDB spills there)", "many", metavar="KEY=VALUE")
PIPELINE = Param("pipeline", "the pipeline file (default: config/final.toml)", "path")
OPEN = Param("open", "only the rows nobody has answered", "flag")
FILE = lambda what: Param("file", f"{what} (default: the workspace's own sheet, with the answers written in)", "path")
RUN_RESULT = {"summary": "the run in words: records, entities, who joined them, the model's links, what is left to people",
              "seconds": "the run's time", "wrote": "the files written", "next": "the commands that usually follow"}
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
            "O(bytes) for the copy and the reading (about 15 s a million records), then the description's.",
            (INPUT, WORKSPACE), {**DESCRIBED, "loaded": "the part the records are in", "copied": "false: the workspace held them already"},
            "nayose load records customers.parquet --workspace workspaces/acme", load_records, quick=True,
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
             "added": "rows that were unread", "read": "what the reader found (er.intake): rows, values per encoding, fixed (controls, placeholders, numbers, damaged), proposed and waiting: repairs by kind (realign, garbled, encoding) for accept repairs, with examples; unread rows", "next": "the commands that usually follow"},
            "nayose accept repairs realign --workspace workspaces/acme", accept_repairs, quick=True),
    Command("list", "features", "The features a workspace's columns fill: groups, features, parts",
            "The workspace's structure: each group, its features and their parts (a full name's family and given names), each "
            "with the columns that hold it, read from its mapping. Without --workspace, the project's. O(the file).",
            (OWN,), {"features": "the structure: groups › features › parts, each with type and columns", "slots": "each feature and part: feature (its path), columns",
                     "next": "the commands that usually follow"},
            "nayose list features --workspace workspaces/acme", list_features, quick=True, show={"features": ()}),
    Command("set", "feature", "Put columns into features",
            "Sets each named feature's or part's columns, by its path: GROUP/FEATURE=COLUMN, GROUP/FEATURE/PART=COLUMN, A,B "
            "(B where A is empty), A+B (joined), nothing (no column). Then writes the mapping they mean into the workspace's "
            "columns.toml, checked before it replaces the old: Name/Full name fills full_name and person_name, its Family name "
            "and Given name a joined fallback of person_name and given_name, and every name, any_name. O(the file).",
            (Param("mapping", "one or more GROUP/FEATURE=COLUMNS", "many", positional=True, metavar="PATH=COLUMNS"), WORKSPACE),
            {"features": "the structure, as set", "slots": "each feature and part: feature (its path), columns", "next": "the commands that usually follow"},
            "nayose set feature \"Name/Full name/Family name=SEI\" \"Name/Full name/Given name=MEI\" --workspace workspaces/acme", set_feature, quick=True,
            show={"features": ()}),
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
            {"features": "the structure, with it", "slots": "each feature and part: feature (its path), columns", "next": "the commands that usually follow"},
            "nayose add feature \"Name/Kanji name\" --type \"person name\" --script kanji --column SHIMEI --workspace workspaces/acme", add_feature_,
            quick=True, show={"features": ()}),
    Command("remove", "feature", "Remove a feature added to a workspace",
            "Its fields leave the workspace's columns.toml; the defaults stay (take their columns off instead). O(the file).",
            (Param("path", "GROUP/FEATURE", positional=True, metavar="PATH"), WORKSPACE),
            {"features": "the structure, without it", "slots": "each feature and part: feature (its path), columns", "next": "the commands that usually follow"},
            "nayose remove feature \"Name/Kanji name\" --workspace workspaces/acme", remove_feature_, quick=True, show={"features": ()}),
    Command("describe", "records", "What a file holds, for mapping its columns: nothing prepared",
            "Each column's share filled and an example; each field's columns as the mapping reads them (a later one where the "
            "earlier are empty, a joined one where every part is filled), each with its share filled, an example and the share "
            "of its values that look like the field; how well each column fits each field; and, for a field the file holds "
            "none of, the column its name or values suggest, never applied: set columns applies it; and what a run would turn "
            "off, a field they read missing. Shares filled cover the "
            "file; the rest a sample of 2,000 records. A file not loaded into a workspace is read as it comes first, for "
            "this command alone (read: what the reader found). O(N·C) in one scan, plus the sample, plus the reading.",
            (INPUT, OWN), DESCRIBED, "nayose describe records customers.parquet --workspace workspaces/acme", describe_records, quick=True,
            show={"columns": ("column", "filled", "example"), "fields": ("field", "filled", "looks_right"), "fit": (), "features": (), "profile": (),
                  "slots": ("feature", "filled", "looks_right"), "placements": ("feature", "column", "why"), "offers": ("feature", "column", "why")}),
    Command("check", "records", "Read, map and check a file, in seconds; resolve nothing",
            "Reads the file through the door every input takes, maps its columns to the logical fields (config/settings.toml "
            "[columns]), and counts each key's pairs before any join. Shows each field's fill rate, the share of values that "
            "look like it and the share of its most common value, what would be turned off, and the blocks the run will check "
            "on a sample. A field the run needs and the file lacks stops it, with the column whose values look most like it. "
            "O(N) for the counts; a sample of 10,000 records for the shares.",
            (INPUT, OWN, COMPUTE, PIPELINE), CHECKED, "nayose check records customers.parquet", check_records),
    Command("list", "columns", "Show which of a file's columns hold each field",
            "Reads the workspace's columns.toml, or without one config/settings.toml [columns] (or the ER_SETTINGS file): each "
            "field, its columns (a comma between fallbacks, + between columns joined) and its options. O(the file).",
            (OWN,), {"settings": "the file read", "own": "true: the workspace's own mapping", "columns": "each field: columns, options",
                     "next": "the commands that usually follow"},
            "nayose list columns --workspace workspaces/acme", list_columns, quick=True),
    Command("set", "columns", "Map fields to a file's columns",
            "Rewrites the named fields' lines in [columns]: FIELD=COLUMN, FIELD=A,B (B where A is empty), FIELD=A+B (A and B "
            "joined), FIELD= (no column: whatever reads it is turned off). Every other line, each line's comment and a field's options stay; the new file "
            "is checked before it replaces the old. With --workspace, the workspace's columns.toml; else the project's, which "
            "new workspaces start from. O(the file).",
            (Param("mapping", "one or more FIELD=COLUMNS", "many", positional=True, metavar="FIELD=COLUMNS"), OWN),
            {"settings": "the file written", "own": "true: the workspace's own mapping", "columns": "each field: columns, options",
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
             "runs": "each run so far: at, what, files, seconds", "pairs": "open pairs to decide and audit, and decisions written in",
             "kinds": "open records to decide and to measure, and answers written in", "set_aside": "records set aside",
             "write_owed": "a write cut short, finished by the next one", "summary": "the last run's summary",
             "round": "the round now: one per method the workspace ran (rounds.json)", "audits": "this round's audits people decided: checked, false",
             "trust": TRUST,
             "inputs": "the records files given to it, each in inputs/: name, path, files, bytes, rows, read (by a run, as it is now), waiting (repairs proposed, for people), unread (rows)",
             "columns": "own: its columns.toml; project: config/settings.toml's", "next": "the commands that usually follow"},
            "nayose describe workspace workspaces/customers", describe_workspace_, quick=True,
            show={"largest": ("entity", "records"), "runs": ("at", "what", "seconds"), "inputs": ("name", "files", "bytes", "read")}),
    Command("describe", "entity", "One record's entity, and what joined it",
            "The entity of the record ID: each of its records with its fields and kind, and every link between them: a rule, "
            "the model with its weight in bits, or people. O(N) in SQL.",
            (Param("id", "a record ID, as the run wrote it", positional=True, metavar="ID"), WORKSPACE),
            {"record": "the ID asked for", "entity": "its entity (the cluster_id)", "records": "each of the entity's records",
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
    Command("try", "method", "Try a change of the method beside the method as it is",
            "Runs the workspace's method and the method with the change (a line; --drop: match rules and pair keys left "
            "out; --add: pair keys added, as describe method proposes them for the matches the probe found no key lists) on the workspace's files, both without people's decisions, so neither is judged on pairs it was told; both "
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
    Command("adopt", "method", "Adopt a method tried, and find matches with it",
            "Writes the trial's method into the workspace's method.toml, then runs the workspace's files again with it, as "
            "rerun records does; method.toml is left as it was if the run fails. Every later command on the workspace runs "
            "this method. O(a full run).",
            (WORKSPACE, Param("trial", "the trial's number (try method gives it)", required=True, metavar="N"), PIPELINE, COMPUTE),
            RUN_RESULT, "nayose adopt method --workspace workspaces/customers --trial 3", adopt_method),
    Command("reset", "method", "Go back to the tuned method, and find matches with it",
            "Removes the workspace's method.toml, then runs the workspace's files again, as rerun records does; method.toml "
            "is left as it was if the run fails. O(a full run).",
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
    Command("draw", "pairs", "More links on the review sheet, to audit",
            "Adds audit rows to review.parquet: links, the model's and the rules', that people have not decided and the sheet "
            "does not hold, spread evenly over 1-bit weight bands, a rule's pairs scored as the model scores them. No false "
            "link in many audits is what says the links are right. O(N + (R + count)·K + E).",
            (WORKSPACE, Param("count", "how many (default 50)", metavar="N"), PIPELINE),
            {"drawn": "rows added", "next": "the commands that usually follow"},
            "nayose draw pairs --workspace workspaces/customers --count 50", draw_pairs, quick=True),
    Command("list", "pairs", "The pairs for people to decide and to audit",
            "The run's review.parquet: decide rows (the pairs just below the threshold, and those above it with no name "
            "compared) and audit rows (accepted pairs just above it), each with both records' fields, each comparison's level "
            "and bits, and a status: open, written in, or applied. O(sheet rows).",
            (WORKSPACE, Param("why", "decide or audit only", "choice", ("decide", "audit")), OPEN),
            {"counts": "rows by why and status", "pairs": "each pair: why, status, decision, id_l, id_r, match_weight, accepted, fields, levels",
             "next": "the commands that usually follow"},
            "nayose list pairs --workspace workspaces/customers --open", list_pairs, quick=True,
            show={"pairs": ("why", "status", "id_l", "id_r", "match_weight", "accepted")}),
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
            "it back. O(sheet rows).",
            (Param("first", "one record ID of the pair", positional=True, metavar="ID"), Param("second", "the other", positional=True, metavar="ID"),
             Param("decision", "match, no_match, or clear", "choice", ("match", "no_match", "clear"), positional=True), WORKSPACE),
            {"pair": "the two IDs, lower first", "decision": "what was written", "next": "the commands that usually follow"},
            "nayose decide pair 0000000151 0000000152 match --workspace workspaces/customers", decide_pair, quick=True),
    Command("apply", "decisions", "Apply people's decisions to the run",
            "Each match pair joins its two entities at once, scoring nothing; no_match is kept, and a full run never accepts "
            "the pair. Decisions are kept in decisions/; one applied before changes nothing. O(D + touched clusters) + O(N).",
            (WORKSPACE, FILE("a file of decisions: the two ID columns and decision"), PIPELINE),
            {"decisions": "decisions applied", "matches": "of them, match", "clusters_joined": "entities joined",
             "summary": "said when nothing was new", "next": "the commands that usually follow"},
            "nayose apply decisions --workspace workspaces/customers", apply_decisions),
    Command("list", "kinds", "The records for people to answer person or company",
            "The run's kind_review.parquet: decide rows (where the engine and the file's flag disagree, and the flag's likely "
            "errors) and measure rows (a random draw that places the engine's lines), each with what the engine, the name and "
            "the flag say, and why it is there. O(sheet rows).",
            (WORKSPACE, Param("why", "decide or measure only", "choice", ("decide", "measure")), OPEN),
            {"counts": "rows by why and status", "kinds": "each record: id, why, status, reason, engine_says, name_says, name, kind",
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
            "again, then stops the pass with the file left in place. One pass, or one every --every seconds. Each file is a "
            "line in <run>/jobs.jsonl.",
            (Param("inbox", "the inbox folder", "path", positional=True, metavar="INBOX"), WORKSPACE,
             Param("every", "seconds between passes; without it, one pass", "text", metavar="SECONDS"),
             Param("retries", "attempts after an unexpected failure (default 2)", "text", metavar="N"), COMPUTE),
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
                    cp.add_argument(p.name, **kw, **({"nargs": "?"} if p.optional else {}))
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
        words.append(word if (p.positional and not p.optional) or p.required else f"[{word}]")
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
           "- **Exit codes:** 0; 2, a mistake people fix (two lines: what is wrong, and the fix); 75, the workspace is busy: "
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
