"""Serve an inbox: every Parquet file dropped in it goes into a run, one at a time, in the order it arrived.

    .venv/bin/python scripts/schedule.py --run runs/customers --inbox inbox                 # one pass (cron can call it)
    .venv/bin/python scripts/schedule.py --run runs/customers --inbox inbox --every 300     # a pass every 5 minutes

inbox/batches/*.parquet are new records: scripts/resolve.py --increment, or, into an empty run folder, a full run.
inbox/decisions/*.parquet are people's decisions: scripts/resolve.py --decisions. Each file runs in a process of its
own, so a crash or a memory spike can't take the scheduler down.

What happens to a file, by how its process ends:
    exit 0      done: moved to inbox/done/; a batch already in the run is done too ("nothing new")
    exit 2      a mistake people must fix: moved to inbox/failed/, with its two-line error beside it; the pass goes on
    exit 75     the run folder is busy (another job writes to it, scripts/resolve.py by hand): tried again, as below
    otherwise   tried again (--retries, waiting 2, 4, 8 … s); if it still fails, the pass stops and the file stays,
                so nothing jumps ahead of it, and the next pass tries again
A file whose content was done before (its SHA-256 in the ledger) is moved to done/ without running. Each file a pass
runs is a line in <run>/jobs.jsonl, with its outcome and attempts. One scheduler serves an inbox at a time
(inbox/.schedule.lock); a run folder takes one writer at a time.
"""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("batches", "decisions")
RESOLVE = Path(__file__).with_name("resolve.py")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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
    if kind == "decisions":
        return [sys.executable, str(RESOLVE), "--output", str(run), "--decisions", str(f)]
    first = not (run / "gold.parquet").exists()  # into an empty run folder, the first batch is the full run
    return [sys.executable, str(RESOLVE), "--input", str(f), "--output", str(run), *([] if first else ["--increment"]),
            *(["--compute", *compute] if compute else [])]


def attempt(cmd: list[str], retries: int, wait: float = 2.0) -> tuple[int, str, str, int]:
    """Run cmd; on an unexpected failure (not 0, not 2), again, waiting wait, 2·wait, … Returns the last exit code,
    stdout, stderr and the attempts made."""
    for k in range(retries + 1):
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode in (0, 2) or k == retries:
            return done.returncode, done.stdout, done.stderr, k + 1
        time.sleep(wait * 2 ** k)


def one_pass(run: Path, inbox: Path, retries: int, compute: list[str]) -> bool:
    """Every waiting file, oldest first. False if the pass stopped on a file that kept failing."""
    done_before = {e["sha256"] for e in ledger(run) if e["outcome"] == "done"}
    tasks = sorted(((f.stat().st_mtime, f.name, kind, f) for kind in KINDS for f in (inbox / kind).glob("*.parquet")))
    for _, name, kind, f in tasks:
        digest = sha256(f)
        if digest in done_before:
            record(run, file=name, kind=kind, sha256=digest, outcome="done", note="the same content was done before")
            print(f"{kind}/{name}: done before (the same content), moved to done/")
            move(f, inbox / "done" / kind)
            continue
        t = time.perf_counter()
        code, out, err, tries = attempt(command(kind, f, run, compute), retries)
        seconds = round(time.perf_counter() - t, 1)
        if code == 0:
            outcome = "done"
            move(f, inbox / "done" / kind)
            done_before.add(digest)
        elif code == 2:
            outcome = "failed"
            dest = move(f, inbox / "failed" / kind)
            dest.with_name(dest.name + ".error.txt").write_text(err, encoding="utf-8")
        else:
            outcome = "stopped"
        summary = [line for line in out.splitlines() if line and not line.startswith("  ")]  # the summary, not the step lines
        record(run, file=name, kind=kind, sha256=digest, outcome=outcome, exit=code, attempts=tries, seconds=seconds,
               error=err.strip().splitlines()[-1] if err.strip() and outcome != "done" else None)
        print(f"{kind}/{name}: {outcome} in {seconds} s" + (f" after {tries} attempts" if tries > 1 else ""))
        print("\n".join(f"  {line}" for line in (summary if outcome == "done" else err.strip().splitlines()[-2:])))
        if outcome == "stopped":
            print(f"stopped: {name} kept failing; it stays in the inbox, and the next pass tries it again")
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n\n".join(__doc__.split("\n\n")[1:]))
    parser.add_argument("--run", required=True, type=Path, help="the run folder the files go into")
    parser.add_argument("--inbox", required=True, type=Path, help="holds batches/ and decisions/")
    parser.add_argument("--every", type=float, help="seconds between passes; without it, one pass")
    parser.add_argument("--retries", type=int, default=2, help="attempts after an unexpected failure (default 2)")
    parser.add_argument("--compute", nargs="*", default=[], metavar="KEY=VALUE", help="passed on to scripts/resolve.py")
    args = parser.parse_args()
    for kind in KINDS:
        (args.inbox / kind).mkdir(parents=True, exist_ok=True)
    with open(args.inbox / ".schedule.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released when this process ends, even if it dies
        except BlockingIOError:
            print(f"error: another scheduler serves {args.inbox}\nfix: let it run; one scheduler per inbox", file=sys.stderr)
            sys.exit(2)
        while True:
            ok = one_pass(args.run, args.inbox, args.retries, args.compute)
            if args.every is None:
                sys.exit(0 if ok else 1)
            time.sleep(args.every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # Ctrl-C between passes: nothing is half done, every write is staged
        sys.exit(130)
