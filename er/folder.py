"""The workspace on disk, and how it is written: one writer at a time (run_lock); every write staged (stage: each
file under a temporary name, then the moves still owed in pending.json, then the moves; finish_writes completes a write
cut short); steps.json written whole, then renamed (log); a new part numbered after the highest (next_part); one
answer people give, written into a sheet (type_in); the record files a run read (inputs). A workspace is made with its
own mapping (create), listed (workspaces), and given records files, each copied into inputs/ (take_in, loaded). What a
run writes there, and what people keep there (decisions/, kind_answers/): docs/architecture.md, the workspace.
"""
import fcntl
import json
import os
import re
import shutil
import threading
import tomllib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from er.config import InputError
from er.settings import COLUMNS
from er.source import find, lit, sha256

PENDING = "pending.json"  # the renames a write still owes, saved once every new file is complete
RUN_FILES = ("gold.parquet", "steps.json", PENDING, "matches", "rule_kept", "proposed", "state", "set_aside",  # what a run writes in its folder
             "qa.md", "report.txt", "review.parquet", "kind_review.parquet")
DECISIONS = "decisions"  # people's decisions: not a run file, so a full run with overwrite keeps and applies them
KIND_ANSWERS = "kind_answers"  # people's person/company answers, a part per sheet as given: kept as decisions are
FULL_TMP = ".full.tmp"  # a full run's new files, until they replace the old run's
OLD_ANSWERS = Path("state") / "kind_labels.parquet"  # where a folder kept people's answers before kind_answers/: read, and moved by the next write
METHOD = "method.toml"  # the workspace's changes to the tuned method (config.adjust); none: the method as tuned
ROUNDS = "rounds.json"  # one entry per method a full run used, in order: not a run file, so the history outlasts each run;
# bounded: one entry per change of method people make, each a full run
TRIALS = "trials"  # trials of a method (er.run.trial): the last 5 results, and the clusters of the method they were tried against


class Busy(InputError):
    """Another job is writing to the workspace: no mistake, so nayose exits 75, to be tried again."""


_held = threading.local()  # the folders this thread holds: taking one again (a rerun's full run) is no second lock;
# bounded: the locks held now, each dropped when released


@contextmanager
def run_lock(out: Path):
    """One writer per workspace: an OS lock on <out>/.lock for as long as a run, an increment or a set of decisions
    writes there. The system releases it when the process ends, even if it dies, so it never goes stale. A thread that
    holds it may take it again; another thread or process can't.
    shortcut: flock holds on a local disk, not on network or object storage; there, run one job per folder at a time."""
    out.mkdir(parents=True, exist_ok=True)
    held, key = _held.__dict__.setdefault("folders", set()), out.resolve()
    if key in held:
        yield
        return
    with open(out / ".lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(f"another job is writing to {out}", fix="wait for it to finish: a workspace takes one writer at a time") from None
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)


def finish_writes(out: Path) -> None:
    """Complete the moves of a write that was interrupted after its new files were complete; nothing otherwise. Each
    move [new, dest] replaces dest, a file or a folder, if new is still there; [None, dest] deletes dest. So done
    twice, they do the same as done once."""
    pending = out / PENDING
    if pending.exists():
        for new, dest in json.loads(pending.read_text(encoding="utf-8")):
            if new is None or os.path.exists(new):
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                elif os.path.exists(dest) and new is None:
                    os.unlink(dest)
                if new is not None:
                    os.replace(new, dest)
        shutil.rmtree(out / FULL_TMP, ignore_errors=True)
        pending.unlink()


def stage(con: duckdb.DuckDBPyConnection, out: Path, tables: list[tuple[str, Path]], texts: list[tuple[str, Path]] = (),
          replace: list[Path] | None = None, frames: list[tuple[pd.DataFrame, Path]] = ()) -> None:
    """Write every file under a temporary name; once all are complete, save the moves still owed (pending.json),
    then do them. An interruption before that leaves the folder as it was; one after it, finish_writes completes.
    With `replace` (a full run), the new run files are written in FULL_TMP, and each of its entries replaces the old
    run's; the old entries the new run doesn't write go. A file outside the run files (people's work) is only added."""
    if replace is not None:
        shutil.rmtree(out / FULL_TMP, ignore_errors=True)  # the files of a full run cut short before its moves
    whole = lambda d: replace is not None and d.relative_to(out).parts[0] in RUN_FILES
    tmp = lambda d: out / FULL_TMP / d.relative_to(out) if whole(d) else d.with_name(d.name + ".tmp")
    for sql, dest in tables:
        tmp(dest).parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY ({sql}) TO {lit(tmp(dest))} (FORMAT parquet)")
    for text, dest in texts:
        tmp(dest).parent.mkdir(parents=True, exist_ok=True)
        tmp(dest).write_text(text, encoding="utf-8")
    for frame, dest in frames:  # sheets for people: pandas keeps their empty answer columns typed
        tmp(dest).parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(tmp(dest))
    dests = [dest for _, dest in (*tables, *texts, *frames)]
    staged = [[str(tmp(d)), str(d)] for d in dests if not whole(d)]
    if replace is not None:
        new = sorted({d.relative_to(out).parts[0] for d in dests if whole(d)})
        staged += [[None, str(x)] for x in replace if x.name not in new] + [[str(out / FULL_TMP / x), str(out / x)] for x in new]
    (out / (PENDING + ".tmp")).write_text(json.dumps(staged), encoding="utf-8")
    os.replace(out / (PENDING + ".tmp"), out / PENDING)  # from here on the write is done, whatever happens next
    finish_writes(out)


def log(out: Path, entry: dict, append: bool) -> None:
    """steps.json: one entry per run, increment or set of decisions (a full run starts it again); written whole, then
    renamed, so a write cut short leaves the old log."""
    path = out / "steps.json"
    runs = json.loads(path.read_text())["runs"] if append and path.exists() else []
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(dict(runs=[*runs, entry]), indent=1, default=str))
    os.replace(tmp, path)


def method(out: Path | str | None) -> dict:  # the workspace's method.toml, {} without one
    f = Path(out) / METHOD if out else None
    return tomllib.loads(f.read_text(encoding="utf-8")) if f and f.exists() else {}


def rounds(out: Path) -> list[dict]:
    return json.loads((out / ROUNDS).read_text(encoding="utf-8")) if (out / ROUNDS).exists() else []


def round_ran(out: Path, entry: dict) -> None:
    """rounds.json after a full run: its entry replaces the last when the method (entry["config"]) is the same, a run
    again on new answers or files; a new method opens the next round. Written whole, then renamed."""
    kept = rounds(out)
    kept = [*kept[:-1], entry] if kept and kept[-1]["config"] == entry["config"] else [*kept, entry]
    tmp = out / (ROUNDS + ".tmp")
    tmp.write_text(json.dumps(kept, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, out / ROUNDS)


def next_part(folder: Path) -> int:  # one past the highest part-n.parquet: a part deleted by hand frees no number to write over
    return max((int(f.stem.removeprefix("part-")) for f in folder.glob("part-*.parquet")), default=-1) + 1


def held(out: Path) -> list[Path]:  # the run files a folder holds: what resolve records --overwrite replaces
    return [out / f for f in RUN_FILES if (out / f).exists()]


def answer_parts(out: Path) -> list[Path]:
    """People's answer sheets the folder keeps, newest first; a folder that keeps them in state/, that one file."""
    return sorted((out / KIND_ANSWERS).glob("part-*.parquet"), reverse=True) or [f for f in [out / OLD_ANSWERS] if f.exists()]


def type_in(out: Path, sheet: str, column: str, value: object, **keys: str) -> None:
    """One answer people give, written into the workspace's sheet (review.parquet's decision, kind_review.parquet's
    kind) on the row whose `keys` columns hold those values, as a person would type it in; None clears it. Nothing is
    applied: the sheet is given back later (Run.decide, a rerun with the answers). Under the lock, and staged as every
    run file is. O(sheet rows)."""
    path = out / sheet
    with run_lock(out):
        finish_writes(out)
        if not path.exists():
            raise InputError(f"{path}: no such sheet", fix="run the records into that folder first: the run writes it")
        frame = pd.read_parquet(path)
        rows = pd.Series(True, index=frame.index)
        for k, v in keys.items():
            rows &= frame[k].astype("string").eq(str(v)).fillna(False)
        if not rows.any():
            raise InputError(f"{path}: no row for {', '.join(f'{k} {v}' for k, v in keys.items())}",
                             fix="answer a row the sheet holds, with the IDs as the run wrote them")
        frame.loc[rows, column] = pd.NA if value is None else value
        stage(duckdb.connect(), out, [], frames=[(frame, path)])


def inputs(out: Path) -> list[Path]:
    """The record files the run in `out` read, in order: the full run's, then each increment's (steps.json). Each
    must still hold what was read, by its SHA-256, where it was read, in the workspace's own inputs/ (wherever the
    workspace now is, and whatever folder nayose starts from), or where the scheduler moved it (jobs.jsonl). O(bytes)."""
    log = out / "steps.json"
    named = [x for run in (json.loads(log.read_text(encoding="utf-8"))["runs"] if log.exists() else [])
             for x in run.get("inputs", []) if x.get("role") == "records"]
    if not named:
        raise InputError(f"{out}: steps.json names no record file", fix="give the files again with a full run that overwrites the folder")
    jobs = out / "jobs.jsonl"
    moved = {e["sha256"]: e["path"] for e in map(json.loads, jobs.read_text(encoding="utf-8").splitlines() if jobs.exists() else [])
             if e.get("path")}
    inside = {sha: part / rel for part in parts(out) for rel, sha in sums(part).items()}
    files = []
    for x in named:
        here = [Path(p) for p in (x["file"], inside.get(x["sha256"]), moved.get(x["sha256"])) if p and Path(p).is_file()]
        if not (found := next((p for p in here if sha256(p) == x["sha256"]), None)):
            raise InputError(f"{x['file']}: {'changed' if here else 'gone'} since the run read it",
                             fix="give the files again with a full run that overwrites the folder")
        files.append(found)
    return files


INPUTS = "inputs"  # the records files a workspace was given, each copied into a part of its own: inputs/NNNN-<name>/
SUMS = ".sha256"  # in each part: each file's SHA-256 and its path in the part, so content given twice is known without reading it
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def create(home: Path, name: str, columns: str) -> Path:
    """The new workspace home/name, with its own mapping (columns.toml, the text given) and its method (method.toml):
    a trust line above every step, so nothing merges before people check (config.TrustRule). O(1)."""
    if not NAME.fullmatch(name):
        raise InputError(f"{name!r}: not a workspace name", fix="letters, digits, '.', '_' and '-', starting with a letter or digit, at most 64")
    ws = home / name
    try:
        ws.mkdir(parents=True)  # at once: two asking for one name, one gets it
    except FileExistsError:
        raise InputError(f"{ws} exists", fix="open it, or choose another name") from None
    try:
        (ws / COLUMNS).write_text(columns, encoding="utf-8")
        (ws / METHOD).write_text('trust = "none"\n', encoding="utf-8")
    except BaseException:
        shutil.rmtree(ws, ignore_errors=True)
        raise
    return ws


def workspaces(home: Path) -> list[dict]:
    """The workspaces in `home` (a folder holding columns.toml or steps.json), the latest active first: each one's name,
    path, files given, whether it holds a run, and when it last changed, from steps.json and the folder; no record is
    read. O(workspaces)."""
    found = []
    for ws in (p for p in home.iterdir() if p.is_dir() and not p.name.startswith(".")) if home.is_dir() else ():
        if not ((ws / COLUMNS).is_file() or (ws / "steps.json").is_file()):
            continue
        log = json.loads((ws / "steps.json").read_text(encoding="utf-8"))["runs"] if (ws / "steps.json").is_file() else []
        found.append(dict(name=ws.name, workspace=str(ws), files=len(parts(ws)), ran=(ws / "gold.parquet").is_file(),
                          last=log[-1]["at"] if log else datetime.fromtimestamp(ws.stat().st_mtime).isoformat(timespec="seconds")))
    return sorted(found, key=lambda w: w["last"], reverse=True)


def parts(ws: Path) -> list[Path]:  # inputs/'s parts, oldest first
    return sorted(p for p in (ws / INPUTS).glob("[0-9]*-*") if p.is_dir())


def sums(part: Path) -> dict[str, str]:  # a part's files: path in the part → SHA-256
    return {rel: sha for sha, rel in (line.split("  ", 1) for line in (part / SUMS).read_text(encoding="utf-8").splitlines())}


def take_in(ws: Path, path: str | Path) -> tuple[Path, bool]:
    """Copy the files `path` names (a file, a glob or a folder: er.source.find) into the next part of the workspace's
    inputs/, under its lock: into a hidden folder first, renamed into place once every file is complete, so a part is
    whole or absent. Content the workspace already holds, file for file by SHA-256, is not copied again. The part, and
    whether it is new. O(bytes)."""
    files = find(path)
    given = sorted(sha256(f) for f in files)
    with run_lock(ws):
        for part in parts(ws):
            if sorted(sums(part).values()) == given:
                return part, False
        p = Path(path)
        root = p if p.is_dir() else None
        stem = p.parent.name if any(c in str(p) for c in "*?[") else p.name if root else p.stem
        n = max((int(x.name.split("-", 1)[0]) for x in parts(ws)), default=0) + 1
        part = ws / INPUTS / f"{n:04d}-{re.sub(r'[^A-Za-z0-9._-]+', '_', stem)[:40] or 'records'}"
        tmp = part.with_name(f".{part.name}.tmp")
        shutil.rmtree(tmp, ignore_errors=True)  # a copy cut short before
        lines = []
        for f in files:
            rel = f.relative_to(root) if root else Path(f.name)
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, tmp / rel)
            lines.append(f"{sha256(tmp / rel)}  {rel.as_posix()}")
        (tmp / SUMS).write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, part)
    return part, True


def loaded(ws: Path) -> list[dict]:
    """inputs/'s parts, oldest first: each one's name, path, files, bytes and rows (from the Parquet footers), and
    whether a run has read all of it (steps.json, by SHA-256). O(parts + files + steps.json)."""
    log = ws / "steps.json"
    read = {x["sha256"] for run in (json.loads(log.read_text(encoding="utf-8"))["runs"] if log.is_file() else [])
            for x in run.get("inputs", []) if x.get("role") == "records"}
    return [dict(name=part.name, path=str(part), files=len(own), bytes=sum((part / rel).stat().st_size for rel in own),
                 rows=sum(pq.ParquetFile(part / rel).metadata.num_rows for rel in own), read=all(sha in read for sha in own.values()))
            for part in parts(ws) for own in [sums(part)]]
