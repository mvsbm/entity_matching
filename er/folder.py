"""The workspace on disk, and how it is written: one writer at a time (run_lock); every write staged (stage: each
file under a temporary name, then the moves still owed in pending.json, then the moves; finish_writes completes a write
cut short); steps.json written whole, then renamed (log); a new part numbered after the highest (next_part). What a run
writes there, and what people keep there (decisions/): docs/architecture.md, the workspace."""
import json
import os
import shutil
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path


from er.engine.engine import Engine
from er.config import InputError, q
from er.io import lock, object_store, patiently, replace_text

PENDING = "pending.json"  # the renames a write still owes, saved once every new file is complete
STEPS = "steps.json"  # the run's log: one entry per run, increment or set of decisions (log)
SCORED = "scored"  # every pair scored at 0 points or more and every rule pair, each comparison's level with it: what a match run reads
MATCHED = "matched"  # each match run's table (er.jobs.match): read from the run, so a full run clears them with it
RUN_FILES = ("gold.parquet", STEPS, PENDING, "rule_kept", SCORED, MATCHED, "state", "set_aside", "report.txt",  # what a run writes in its folder
             "matches", "review.parquet", "qa.md")  # and, where one lies, what an earlier version wrote: cleared by a full run
DECISIONS = "decisions"  # people's decisions: not a run file, so a full run with overwrite keeps and applies them
FULL_TMP = ".full.tmp"  # a full run's new files, until they replace the old run's


class Busy(InputError):
    """Another job is writing to the workspace: no mistake, so a job exits 75, to be tried again."""


_held = threading.local()  # the folders this thread holds: taking one again (a rerun's full run) is no second lock;
# bounded: the locks held now, each dropped when released


@contextmanager
def run_lock(out: Path, make: bool = False):
    """One writer per workspace: an OS lock on <out>/.lock for as long as a run, an increment or a set of decisions
    writes there. A folder that isn't there is refused, unless the job makes a workspace (`make`: a full run, a file
    loaded), so a mistyped one is said, never made. The system releases it when the process ends, even if it dies, so it never goes stale. A thread that
    holds it may take it again; another thread or process can't. It holds on a local disk and on a network one (NFS,
    a Windows share); a workspace on object storage mounted as files (io.object_store) is refused: no lock holds there.
    shortcut: one lock per machine's view of a disk; a workspace on object storage itself needs a lease and writes that
    don't rename (folder.stage does), a port of its own."""
    lockable(out)
    if make:
        out.mkdir(parents=True, exist_ok=True)
    elif not out.is_dir():
        raise InputError(f"no workspace at {out}", fix="check the path, or make it with a full run: python -m er build FILE --out PATH")
    held, key = _held.__dict__.setdefault("folders", set()), out.resolve()
    if key in held:
        yield
        return
    with open(out / ".lock", "w") as f:
        if not lock(f):
            raise Busy(f"another job is writing to {out}", fix="wait for it to finish: a workspace takes one writer at a time")
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)


def lockable(path: Path) -> None:  # refused where no lock holds, before anything is written there
    if kind := object_store(path):
        raise InputError(f"{path} is on object storage ({kind}): no lock holds there, so two jobs could write it at once",
                         fix="put the workspace on a local or network disk: a persistent disk, Filestore, NFS")


def finish_writes(out: Path) -> None:
    """Complete the moves of a write that was interrupted after its new files were complete; nothing otherwise. Each
    move [new, dest] replaces dest, a file or a folder, if new is still there; [None, dest] deletes dest. So done
    twice, they do the same as done once."""
    pending = out / PENDING
    if pending.exists():
        for new, dest in json.loads(pending.read_text(encoding="utf-8")):
            if new is None or os.path.exists(new):
                if os.path.isdir(dest):
                    patiently(shutil.rmtree, dest)
                elif os.path.exists(dest) and new is None:
                    patiently(os.unlink, dest)
                if new is not None:
                    patiently(os.replace, new, dest)
        shutil.rmtree(out / FULL_TMP, ignore_errors=True)
        pending.unlink()


def stage(engine: Engine, out: Path, tables: list[tuple[str, Path]], texts: list[tuple[str | Callable[[], str], Path]] = (),
          replace: list[Path] | None = None) -> None:
    """Write every file under a temporary name; once all are complete, save the moves still owed (pending.json),
    then do them. An interruption before that leaves the folder as it was; one after it, finish_writes completes.
    With `replace` (a full run), the new run files are written in FULL_TMP, and each of its entries replaces the old
    run's; the old entries the new run doesn't write go. A file outside the run files (people's work) is only added.
    A text may be a function, called once the tables are written: the log, with the time they took."""
    if replace is not None:
        shutil.rmtree(out / FULL_TMP, ignore_errors=True)  # the files of a full run cut short before its moves
    whole = lambda d: replace is not None and d.relative_to(out).parts[0] in RUN_FILES
    tmp = lambda d: out / FULL_TMP / d.relative_to(out) if whole(d) else d.with_name(d.name + ".tmp")
    for sql, dest in tables:
        tmp(dest).parent.mkdir(parents=True, exist_ok=True)
        engine.write(sql, tmp(dest))
    for text, dest in texts:
        tmp(dest).parent.mkdir(parents=True, exist_ok=True)
        tmp(dest).write_text(text() if callable(text) else text, encoding="utf-8")
    dests = [dest for _, dest in (*tables, *texts)]
    staged = [[str(tmp(d)), str(d)] for d in dests if not whole(d)]
    if replace is not None:
        new = sorted({d.relative_to(out).parts[0] for d in dests if whole(d)})
        staged += [[None, str(x)] for x in replace if x.name not in new] + [[str(out / FULL_TMP / x), str(out / x)] for x in new]
    replace_text(out / PENDING, json.dumps(staged))  # from here on the write is done, whatever happens next
    finish_writes(out)


def log(out: Path, entry: dict, append: bool) -> str:
    """steps.json with this entry: one per run, increment or set of decisions (a full run starts it again). The text,
    for stage to write with the files it names: a run never lands without its entry, nor an entry without its run."""
    path = out / STEPS
    old = json.loads(path.read_text(encoding="utf-8")) if append and path.exists() else {}
    return json.dumps(dict(runs=[*old.get("runs", []), entry]), indent=1, default=str)


def latest_decisions(engine: Engine, out: Path, uid: str, cols: tuple[str, ...] = ("decision",)) -> str | None:
    """SQL: each pair's latest decision the folder holds (the last part's: one decided again counts once, as last
    said), with `cols` as that part gave them; None before any."""
    parts, l, r = Path(out) / DECISIONS, q(f"{uid}_l"), q(f"{uid}_r")
    if not any(parts.glob("part-*.parquet")):
        return None
    return (f"(SELECT {l}, {r}, {', '.join(f'arg_max({c}, filename) AS {c}' for c in cols)} "
            f"FROM {engine.read(parts / 'part-*.parquet', by_name=True, filename=True)} GROUP BY {l}, {r})")


def next_part(folder: Path) -> int:  # one past the highest part-n.parquet: a part deleted by hand frees no number to write over
    return max((int(f.stem.removeprefix("part-")) for f in folder.glob("part-*.parquet")), default=-1) + 1


def held(out: Path) -> list[Path]:  # the run files a folder holds: what a full run with overwrite replaces
    return [out / f for f in RUN_FILES if (out / f).exists()]
