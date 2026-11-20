"""nayose (名寄せ: gathering each customer's records under one name), the command line, in kubectl's grammar: a verb,
then a noun, then its parameters.

    nayose resolve records customers.parquet --workspace workspaces/customers
    nayose add records new.parquet --workspace workspaces/customers
    nayose build index --workspace workspaces/customers
    nayose match record FULL_NAME_KANA=ヤマダタロウ PHONE_NUM_4=1234 --workspace workspaces/customers

Each command is declared once, in COMMANDS: its verb and noun, what it does, its parameters, the fields of its result,
an example, and the function that runs it. The parser and the reference (docs/commands.md, reference()) are built
from those declarations. A command emits events: each step as it finishes (and, as JSON, how far a file has been
read: progress), then one result, or an error (er.emit). --format text renders them for a person (er.brief);
--format json writes each as one JSON object per line. Every result names the commands that usually come next.
Exit codes: 0; 2, a mistake people fix, in two lines (what is wrong, and how to fix it); 75, the workspace is busy:
try again later.
"""
import argparse
import contextlib
import gc
import json
import math
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import duckdb
import pandas as pd

from er import folder, index
from er.io import read_parquet, replace_text
from er.config import InputError, load_pipeline
from er.brief import merging_words, nayose
from er.emit import BATCH_ORDER, RUN_ORDER, Emit, plain, rows_told
from er.folder import Busy
from er.hints import readable
from er.match import review_floor
from er.results import describe_results
from er.run import Run
from er.settings import (load_settings)


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


# ---------- results in short, for a person (--verbose: every field, as text() writes it) ----------


# ---------- what each command does ----------

def settings_for(a: dict):  # the settings; an earlier nayose's workspace refused
    if (ws := a.get("workspace")) and Path(ws).is_dir():
        folder.current(Path(ws), replacing=bool(a.get("overwrite")))  # a run --overwrite writes the rules' pairs anew
    return load_settings()


def setup(a: dict):
    """The settings, with this run's DuckDB limits, the pipeline, and its file."""
    s = settings_for(a)
    if bad := [kv for kv in a.get("compute") or [] if "=" not in kv]:
        raise InputError(f"--compute {' '.join(bad)}: each limit is KEY=VALUE", fix="for example --compute memory_limit=8GB threads=4")
    s = replace(s, compute={**s.compute, **dict(kv.split("=", 1) for kv in a.get("compute") or [])})
    pipeline = Path(a.get("pipeline") or s.root / "config" / "final.toml")
    return s, load_pipeline(pipeline, s.standardize, s.chains, s.columns), pipeline


def sheet(out: Path, name: str) -> pd.DataFrame | None:
    return read_parquet(out / name) if (out / name).exists() else None


def ids(frame: pd.DataFrame, uid: str) -> pd.DataFrame:  # the file's ID columns under the names every result uses: id, id_l, id_r
    return frame.rename(columns={uid: "id", f"{uid}_l": "id_l", f"{uid}_r": "id_r"})


def rows(frame: pd.DataFrame) -> list[dict]:
    return plain(frame.astype(object).where(frame.notna(), None).to_dict("records"))


def next_after(out: Path, waiting: int | None = None) -> list[dict]:
    """What usually follows a run: people's decisions on the pairs waiting (review.parquet), then the index to look records up in."""
    found = [dict(command=nayose("apply", "decisions", "--file", "DECISIONS", "--workspace", out), why=f"once people decide the {waiting:,} pairs of review.parquet")] if waiting else []
    return found + [dict(command=nayose("build", "index", "--workspace", out), why="look records up")]


def run_facts(run: Run, out: Path) -> dict | None:  # what a person reads first after a run; none if it can't be read (the run stands either way)
    if not any((out / folder.SCORED).glob("part-*.parquet")):  # a run from before the index: building it here would add minutes no one asked for
        return None
    try:
        r = describe_results(run.con, out, run.settings, run.pipeline, review_floor(run.pipeline))
    except (InputError, duckdb.Error, OSError):
        return None
    return dict(records=r["records"], entities=r["entities"], joined=r["joined"], waiting=sum(x["pairs"] for x in r["waiting"]), review_from=r["review_from"],
                merging=merging_words(r["merging"]), too_big=r["too_big"]["skipped"], kinds=r["kinds"]["flagged"],
                report=str(out / "report.txt"))


def after_run(run: Run, out: Path) -> dict:
    wrote = ["gold.parquet", "review.parquet", "qa.md", "report.txt", "matches/", "state/"]
    facts = run_facts(run, out)
    return dict(summary=run.tables["summary"].values.tolist(), seconds=round(sum(x["seconds"] for x in run.steps), 1), facts=facts,
                wrote=[str(out / f) for f in wrote], next=next_after(out, facts and facts["waiting"]))


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
        return str(folder.take_in(ws, a["input"], s.input, progress=told)[0])
    if not (part := folder.last(ws)):
        raise InputError(f"no records file in {ws}", fix=f"name it: nayose resolve records FILE --workspace {ws}")
    return str(folder.fresh(part, s.input, told))


def resolve_records(a: dict, emit: "Emit") -> dict:
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    return after_run(Run(p, s, model=model_from(a["model"]), echo=emit.step, told=emit.progress).full(given(a, emit), out, overwrite=a["overwrite"], pipeline_file=pipeline), out)


def add_records(a: dict, emit: "Emit") -> dict:
    """A batch copied in, then added; a copy that adds nothing, or that is refused before anything is written (a column
    the run reads, missing), is not kept, and the file given before it is again the one a run given none reads. A file
    loaded before is never removed."""
    s, p, pipeline = setup(a)
    out = Path(a["workspace"])
    before = folder.last(out)

    def drop() -> None:  # the copy made for this, gone; the file given before it, given last again
        shutil.rmtree(part, ignore_errors=True)
        (replace_text(out / folder.INPUTS / folder.LAST, before.name) if before else (out / folder.INPUTS / folder.LAST).unlink(missing_ok=True))
    held = [x for x in folder.parts(out) if a["input"] and Path(a["input"]).expanduser().resolve() == x.resolve()]  # a part loaded already: as it is
    part, copied = ((folder.fresh(held[0], s.input, rows_told(emit)), False) if held else
                    folder.take_in(out, a["input"], s.input, progress=rows_told(emit)) if a["input"] else (Path(given(a, emit)), False))
    try:
        run = Run(p, s, echo=emit.step, told=emit.progress).increment(part, out, pipeline_file=pipeline)
    except InputError as e:
        if copied and not isinstance(e, Busy):  # another job may hold it now
            drop()
        raise
    if run.added == 0:  # a copy made for this goes; a file loaded before stays, whatever it holds (its values may differ from the run's)
        mine = next((x for x in folder.loaded(out) if Path(x["path"]).resolve() == part.resolve()), {})
        if copied:
            drop()
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
    return {**index.build(ws, s, p), "next": [dict(command=nayose("match", "record", "COLUMN=VALUE", "--workspace", ws), why="look a record up")]}


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
    return {**found, "next": []}


def number(text: str, what: str, fix: str = "a weight in bits, for example 9 or 9.5") -> float:
    try:
        if math.isfinite(x := float(text)):
            return x
    except ValueError:
        pass
    raise InputError(f"{what} {text}: not a number", fix=fix)  # nan and inf too: no line, count or bound


def counted(a: dict, name: str, default: int) -> int:  # a page or a count: a whole number from 1
    v = a.get(name)
    if v in (None, ""):
        return default
    if not str(v).isdecimal() or int(v) < 1:  # ² is a digit, not a number int() reads
        raise InputError(f"--{name} {v}: a whole number from 1", fix=f"for example --{name} {default}")
    return int(v)


def apply_decisions(a: dict, emit: "Emit") -> dict:
    s, p, _ = setup(a)
    out = Path(a["workspace"])
    with folder.run_lock(out), readable(a["file"], s) if a["file"] else contextlib.nullcontext(out / "review.parquet") as path:
        run = Run(p, s, echo=emit.step, told=emit.progress).decide(path, out)
    x = run.steps[-1]
    return dict(decisions=x["decisions"], matches=x["matches"], clusters_joined=x["clusters_joined"],
                summary=[["nothing new", "every decision was applied before"]] if not x["decisions"] else [],
                next=[dict(command=nayose("build", "index", "--workspace", out), why="look records up, with these decisions")])


# ---------- the declarations ----------

INPUT = Param("input", "the records: a Parquet file, a quoted glob ('in/*.parquet') or a folder of them, read together by column name",
              "path", positional=True)
WORKSPACE = Param("workspace", "the workspace: the folder that keeps one matching job", "path", required=True)
GIVEN = replace(INPUT, help=INPUT.help + "; copied into the workspace first. Without it, the file loaded into it last", optional=True)
COMPUTE = Param("compute", "DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, "
                "temp_directory=<folder> (past the memory limit DuckDB spills there)", "many", metavar="KEY=VALUE")
PIPELINE = Param("pipeline", "the pipeline file (default: config/final.toml)", "path")
FILE = lambda what: Param("file", f"{what} (default: the workspace's own sheet, with the answers written in)", "path")
RUN_RESULT = {"summary": "the run in words: records, entities, who joined them, the model's links, what is left to people",
              "facts": "what to read first: records, entities, joined, waiting (pairs for people from review_from points), merging, too_big, kinds (flagged person or company), report",
              "seconds": "the run's time", "wrote": "the files written", "index": "the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix", "next": "the commands that usually follow"}
COMMANDS: tuple[Command, ...] = (
    Command("resolve", "records", "Resolve a file: one ID per person or company",
            "A full run, without labels: load, budget, fit, rules, candidates, score, cluster, write, report. Writes the "
            "workspace: gold.parquet, matches/, rule_kept/, set_aside/, state/, steps.json, and for people qa.md, "
            "report.txt and review.parquet. A folder that holds a run is refused without --overwrite; people's "
            "decisions in it stand. O(N·L + ΣP + C·K·L²).",
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
    Command("build", "index", "The index a record is looked up in, from the run",
            "Every key of every record the run holds, sorted, in the workspace's index/ (DuckDB "
            "databases), with what it was built from. Read once from the run's own files, nothing "
            "standardized again; built beside the last index, which stays until the new one is whole. Once built, it is kept up to "
            "date by the commands that change the run: an increment or decisions write what changed beside it; a "
            "full run builds it again. O(N·(G + R + D·L) + N log N): N records, G pair keys, R rules, D deletion keys, L a value's "
            "length.",
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
    Command("apply", "decisions", "Apply people's decisions to the run",
            "Each match pair joins its two entities at once, scoring nothing; no_match is kept, and a full run never accepts "
            "the pair. Decisions are kept in decisions/; one applied before "
            "changes nothing. O(D + touched clusters) + O(N).",
            (WORKSPACE, FILE("a file of decisions: the two ID columns and decision"), PIPELINE, COMPUTE),
            {"decisions": "decisions applied", "matches": "of them, match", "clusters_joined": "entities joined",
             "summary": "said when nothing was new", "index": "the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix", "next": "the commands that usually follow"},
            "nayose apply decisions --workspace workspaces/customers", apply_decisions),
)


# ---------- the parser and the reference, from the declarations ----------

GROUPS = (  # the top-level help's commands, by task
    ("Run", ("resolve records", "add records", "match records", "apply decisions")),
    ("Look up", ("build index", "match record")),
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
           "try again later; 130, stopped with Ctrl-C.",
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
    """A command run on its parameters. A batch for a run that lacks a field says to name its column as the run does.
    A workspace named that isn't there is refused, unless the command makes one (MAKES): a mistyped path is said,
    never made."""
    if (ws := a.get("workspace")) and c.name not in MAKES and not Path(ws).is_dir():
        raise InputError(f"no workspace at {ws}", fix="check the path, or make it with a full run: nayose resolve records FILE --workspace PATH")
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
        raise
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


STEPS_OF = {"apply decisions": ("decide",)}  # the steps of a command that isn't a run
MAKES = ("resolve records",)  # the commands a folder not there yet may be given as a workspace: they make it
FULL_RUNS = ("resolve records",)
INDEXED = (*FULL_RUNS, "add records", "apply decisions")  # the commands that change a run: its index is kept up to date after them


def last_run(ws: str | None, name: str) -> dict:
    """The steps a command runs and, for a run, the workspace's last run of the same kind (a full run, or a batch
    added): its seconds per step and its records, which the time left is measured against. No steps known: none."""
    batch, order = name in ("add records", "match records"), steps_of(name)
    if name not in FULL_RUNS and not batch:
        return dict(order=order)
    try:
        runs = [r for r in folder.runs(Path(ws)) if bool(r.get("part")) == batch and r.get("steps") and r["steps"][0]["step"] == "load"] if ws else []
        steps = runs[-1]["steps"] if runs else []
        last, records = {s["step"]: float(s["seconds"]) for s in steps}, steps[0].get("records") if steps else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):  # an odd steps.json: no estimate, the command still runs
        steps, last, records = [], {}, None
    return dict(order=order, last=last or None, last_records=records)  # this version's steps: the last run's, from an older one, may lack some; its seconds still count


def steps_of(name: str) -> tuple[str, ...]:  # the steps a command runs, in the order they end: the terminal's progress and the page's
    if name in ("add records", "match records"):  # a batch's; a preview's up to its entities: it writes nothing
        return BATCH_ORDER if name == "add records" else tuple(s for s in BATCH_ORDER if s not in ("report", "write"))
    if name in FULL_RUNS:
        return RUN_ORDER
    return STEPS_OF.get(name, ())


def execute(a: argparse.Namespace, emit: Emit) -> int:
    """The command parsed in `a` run, its result or error said through `emit`; the exit code: the command's own, 2 a
    mistake people fix or memory short, 75 another command holds the workspace. A bug raises. The CLI's and the page's."""
    c = a.command
    try:
        result = perform(c, {p.name: getattr(a, p.name) for p in c.params}, emit)
    except InputError as e:
        code = 75 if isinstance(e, Busy) else 2
        emit.error(e, code)
        return code
    except Exception as e:
        if not (oom := out_of_memory(e)):
            raise
        emit.error(oom, 2)
        return 2
    code = result.pop("exit_code", 0)
    emit.result(c, result)
    return code


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # UTF-8 wherever it goes: a pipe or a file on Windows would take the locale's code page
        if hasattr(stream, "reconfigure") and stream.encoding.replace("-", "").lower() != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    a = parser().parse_args(argv)
    c = a.command
    emit = Emit(a.format, verbose=a.verbose, title=f"{c.name} · {getattr(a, 'workspace', None) or getattr(a, 'input', None) or ''}".rstrip(" ·"),
                **({} if a.format == "json" or c.quick else last_run(getattr(a, "workspace", None), c.name)))
    try:
        return execute(a, emit)
    except KeyboardInterrupt:  # Ctrl-C: nothing is half done, every write is staged
        emit.close()
        return 130
    except Exception:
        emit.close()
        raise


if __name__ == "__main__":
    sys.exit(main())
