"""Serve an inbox (nayose serve inbox): every file dropped in it (Parquet, CSV or TSV) goes into a run, one at a time,
in the order it arrived.

    inbox/batches/*             new records (Parquet, CSV, TSV): nayose add records, or, into an empty workspace, nayose resolve records
    inbox/decisions/*           people's decisions: nayose apply decisions --file
    inbox/answers/*             people's person/company answers: nayose apply answers --file (a rerun)

Each file runs as its nayose command in a process of its own, so a crash or a memory spike can't take the scheduler
down. What happens to a file, by how its process ends:
    exit 0      done: moved to inbox/done/; a batch already in the run is done too ("nothing new")
    exit 2      a mistake people must fix: moved to inbox/failed/, with its two-line error beside it; the pass goes on
    exit 75     the workspace is busy (another job writes to it): tried again, as below
    otherwise   tried again (retries, waiting 2, 4, 8 … s); if it still fails, the pass stops and the file stays, so
                nothing jumps ahead of it, and the next pass tries again
A file whose content was done before (its SHA-256 in the ledger) is moved to done/ without running. Each file a pass
runs is a line in <run>/jobs.jsonl: its outcome, its attempts, and where a file that ran went, which a rerun reads.
One scheduler serves an inbox at a time (inbox/.schedule.lock); a workspace takes one writer at a time.
"""
import fcntl
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from er import intake
from er.config import InputError
from er.source import sha256

KINDS = ("batches", "decisions", "answers")


def ledger(run: Path) -> list[dict]:
    log = run / "jobs.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line] if log.exists() else []


def record(run: Path, **entry: object) -> None:
    run.mkdir(parents=True, exist_ok=True)
    with (run / "jobs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")


def move(f: Path, folder: Path) -> Path:  # a stamp in front: the same name may arrive again with other content
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{datetime.now():%Y%m%d-%H%M%S}-{f.name}"
    os.replace(f, dest)
    return dest


def command(kind: str, f: Path, run: Path, compute: list[str]) -> list[str]:
    """The nayose command that takes the file in: run as python -m er.cli, so it needs nothing on PATH."""
    limits = ["--compute", *compute] if compute else []
    if kind == "decisions":
        words = ["apply", "decisions", "--workspace", str(run), "--file", str(f), *limits]
    elif kind == "answers":
        words = ["apply", "answers", "--workspace", str(run), "--file", str(f), *limits]
    else:  # into an empty workspace, the first batch is the full run
        words = ["resolve" if not (run / "gold.parquet").exists() else "add", "records", str(f), "--workspace", str(run), *limits]
    return [sys.executable, "-m", "er.cli", *words, "--format", "json"]


def attempt(cmd: Callable[[], list[str]], retries: int, wait: float = 2.0) -> tuple[int, str, str, int]:
    """Run the command cmd() makes; on an unexpected failure (not 0, not 2), make it and run it again, waiting wait,
    2·wait, …: a first batch whose full run was written before it failed goes again as an increment, which finds it
    done. Returns the last exit code, stdout, stderr and the attempts made."""
    for k in range(retries + 1):
        done = subprocess.run(cmd(), capture_output=True, text=True)
        if done.returncode in (0, 2) or k == retries:
            return done.returncode, done.stdout, done.stderr, k + 1
        time.sleep(wait * 2 ** k)


def events(out: str) -> list[dict]:  # the command's JSON events; a line that isn't one (a library's print) is skipped
    found = []
    for line in out.splitlines():
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return [e for e in found if isinstance(e, dict)]


def one_pass(run: Path, inbox: Path, retries: int, compute: list[str], say: Callable[..., None], settle: float = 60.0) -> bool:
    """Every waiting file, oldest first; one changed in the last `settle` seconds may still be being copied in, and
    waits for a later pass. False if the pass stopped on a file that kept failing."""
    done_before = {e["sha256"] for e in ledger(run) if e["outcome"] == "done"}
    now = time.time()
    tasks = sorted(((f.stat().st_mtime, f.name, kind, f) for kind in KINDS if (inbox / kind).is_dir() for f in (inbox / kind).iterdir()
                    if f.suffix.lower() in intake.SUFFIXES and now - f.stat().st_mtime >= settle))
    for _, name, kind, f in tasks:
        digest = sha256(f)
        if digest in done_before:
            record(run, file=name, kind=kind, sha256=digest, outcome="done", note="the same content was done before")
            say(f"{kind}/{name}: done before (the same content), moved to done/", file=name, kind=kind, outcome="done")
            move(f, inbox / "done" / kind)
            continue
        t = time.perf_counter()
        code, out, err, tries = attempt(lambda: command(kind, f, run, compute), retries)
        seconds = round(time.perf_counter() - t, 1)
        said = events(out)
        failure = next((e for e in said if e.get("event") == "error"), None)
        dest = None
        if code == 0:
            outcome = "done"
            dest = move(f, inbox / "done" / kind)
            done_before.add(digest)
        elif code == 2:
            outcome = "failed"
            dest = move(f, inbox / "failed" / kind)
            dest.with_name(dest.name + ".error.txt").write_text(
                f"error: {failure['error']}\nfix: {failure['fix']}\n" if failure else err, encoding="utf-8")
        else:
            outcome = "stopped"
        error = failure["error"] if failure else (err.strip().splitlines()[-1] if err.strip() else None)
        record(run, file=name, kind=kind, sha256=digest, outcome=outcome, exit=code, attempts=tries, seconds=seconds,
               path=str(dest.resolve()) if outcome == "done" else None,  # where a rerun finds the batch again
               error=error if outcome != "done" else None)
        result = next((e for e in said if e.get("event") == "result"), {})
        lines = [f"{w:<12} {v}" for w, v in result.get("summary", [])] if outcome == "done" else [error or ""]
        say(f"{kind}/{name}: {outcome} in {seconds} s" + (f" after {tries} attempts" if tries > 1 else "") + "".join(f"\n  {x}" for x in lines),
            file=name, kind=kind, outcome=outcome, seconds=seconds, attempts=tries, error=error)
        if outcome == "stopped":
            say(f"stopped: {name} kept failing; it stays in the inbox, and the next pass tries it again", file=name, outcome="stopped")
            return False
    return True


def serve(run: Path, inbox: Path, every: float | None, retries: int, compute: list[str], say: Callable[..., None], settle: float = 60.0) -> bool:
    """One pass, or one every `every` seconds until stopped, holding the inbox's lock. True if the last pass ran every
    waiting file."""
    for kind in KINDS:
        (inbox / kind).mkdir(parents=True, exist_ok=True)
    with open(inbox / ".schedule.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released when this process ends, even if it dies
        except BlockingIOError:
            raise InputError(f"another scheduler serves {inbox}", fix="let it run: one scheduler per inbox") from None
        while True:
            ok = one_pass(run, inbox, retries, compute, say, settle)
            if every is None:
                return ok
            time.sleep(every)
