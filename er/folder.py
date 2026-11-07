"""The run folder on disk, and how it is written: one writer at a time (run_lock); every write staged (stage: each
file under a temporary name, then the moves still owed in pending.json, then the moves; finish_writes completes a write
cut short); steps.json written whole, then renamed (log); a new part numbered after the highest (next_part); one
answer people give, written into a sheet (type_in); the record files a run read (inputs). What a run writes there, and
what people keep there (decisions/, kind_answers/): docs/architecture.md, the run folder.
"""
import fcntl
import json
import os
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pandas as pd

from er.config import InputError
from er.source import lit, sha256

PENDING = "pending.json"  # the renames a write still owes, saved once every new file is complete
RUN_FILES = ("gold.parquet", "steps.json", PENDING, "matches", "rule_kept", "state", "set_aside",  # what a run writes in its folder
             "qa.md", "report.txt", "review.parquet", "kind_review.parquet")
DECISIONS = "decisions"  # people's decisions: not a run file, so a full run with overwrite keeps and applies them
KIND_ANSWERS = "kind_answers"  # people's person/company answers, a part per sheet as given: kept as decisions are
FULL_TMP = ".full.tmp"  # a full run's new files, until they replace the old run's
OLD_ANSWERS = Path("state") / "kind_labels.parquet"  # where a folder kept people's answers before kind_answers/: read, and moved by the next write


class Busy(InputError):
    """Another job is writing to the run folder: no mistake, so scripts/resolve.py exits 75, to be tried again."""


_held = threading.local()  # the folders this thread holds: taking one again (a rerun's full run) is no second lock


@contextmanager
def run_lock(out: Path):
    """One writer per run folder: an OS lock on <out>/.lock for as long as a run, an increment or a set of decisions
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
            raise Busy(f"another job is writing to {out}", fix="wait for it to finish: a run folder takes one writer at a time") from None
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


def next_part(folder: Path) -> int:  # one past the highest part-n.parquet: a part deleted by hand frees no number to write over
    return max((int(f.stem.removeprefix("part-")) for f in folder.glob("part-*.parquet")), default=-1) + 1


def held(out: Path) -> list[Path]:  # the run files a folder holds: what a full run with --overwrite replaces
    return [out / f for f in RUN_FILES if (out / f).exists()]


def answer_parts(out: Path) -> list[Path]:
    """People's answer sheets the folder keeps, newest first; a folder that keeps them in state/, that one file."""
    return sorted((out / KIND_ANSWERS).glob("part-*.parquet"), reverse=True) or [f for f in [out / OLD_ANSWERS] if f.exists()]


def type_in(out: Path, sheet: str, column: str, value: object, **keys: str) -> None:
    """One answer people give, written into the run folder's sheet (review.parquet's decision, kind_review.parquet's
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
    must still hold what was read, by its SHA-256, where it was read or where the scheduler moved it (jobs.jsonl).
    O(bytes)."""
    log = out / "steps.json"
    named = [x for run in (json.loads(log.read_text(encoding="utf-8"))["runs"] if log.exists() else [])
             for x in run.get("inputs", []) if x.get("role") == "records"]
    if not named:
        raise InputError(f"{out}: steps.json names no record file", fix="give the files again with a full run that overwrites the folder")
    jobs = out / "jobs.jsonl"
    moved = {e["sha256"]: e["path"] for e in map(json.loads, jobs.read_text(encoding="utf-8").splitlines() if jobs.exists() else [])
             if e.get("path")}
    files = []
    for x in named:
        here = [Path(p) for p in (x["file"], moved.get(x["sha256"])) if p and Path(p).is_file()]
        if not (found := next((p for p in here if sha256(p) == x["sha256"]), None)):
            raise InputError(f"{x['file']}: {'changed' if here else 'gone'} since the run read it",
                             fix="give the files again with a full run that overwrites the folder")
        files.append(found)
    return files
