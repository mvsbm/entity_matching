"""The workspace on disk, and how it is written: one writer at a time (run_lock); every write staged (stage: each
file under a temporary name, then the moves still owed in pending.json, then the moves; finish_writes completes a write
cut short); steps.json written whole, then renamed (log); a new part numbered after the highest (next_part); one
answer people give, written into a sheet (type_in); the record files a run read (inputs). A workspace is made with its
own mapping (create), listed (workspaces), and given records files, each copied into inputs/ (take_in, loaded). What a
run writes there, and what people keep there (decisions/, kind_answers/): docs/architecture.md, the workspace.
"""
import json
import os
import re
import shutil
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from er import intake
from er.config import InputError, lit, toml_of
from er.io import alive, lock, object_store, replace_text
from er.settings import COLUMNS
from er.source import find, globbed
from er.strings import connect

PENDING = "pending.json"  # the renames a write still owes, saved once every new file is complete
STEPS = "steps.json"  # the run's log: one entry per run, increment or set of decisions (log, runs)
SCORED = "scored"  # every pair scored at 0 points or more and every rule pair, each comparison's level with it: what people browse (er.results)
RUN_FILES = ("gold.parquet", STEPS, PENDING, "matches", "rule_kept", "proposed", SCORED, "state", "set_aside",  # what a run writes in its folder
             "qa.md", "report.txt", "review.parquet", "kind_review.parquet")
DECISIONS = "decisions"  # people's decisions: not a run file, so a full run with overwrite keeps and applies them
KIND_ANSWERS = "kind_answers"  # people's person/company answers, a part per sheet as given: kept as decisions are
FULL_TMP = ".full.tmp"  # a full run's new files, until they replace the old run's
METHOD = "method.toml"  # the workspace's changes to the tuned method (config.adjust); none: the method as tuned
ROUNDS = "rounds.json"  # one entry per method a full run used, in order: not a run file, so the history outlasts each run;
# bounded: one entry per change of method people make, each a full run
TRIALS = "trials"  # trials of a method (er.run.trial): the last 5 results, and the clusters of the method they were tried against
PREPARED = "prepared"  # the records as a run loads them, cleaned (er.run.Run.load), a folder per what they were made from:
# not a run file, so a full run reads them again; bounded: the last KEEP_PREPARED used
KEEP_PREPARED = 2  # the method and a trial of another that cleans other columns: neither replaces the other's


class Busy(InputError):
    """Another job is writing to the workspace: no mistake, so nayose exits 75, to be tried again."""


_held = threading.local()  # the folders this thread holds: taking one again (a rerun's full run) is no second lock;
# bounded: the locks held now, each dropped when released


@contextmanager
def run_lock(out: Path):
    """One writer per workspace: an OS lock on <out>/.lock for as long as a run, an increment or a set of decisions
    writes there. The system releases it when the process ends, even if it dies, so it never goes stale. A thread that
    holds it may take it again; another thread or process can't. It holds on a local disk and on a network one (NFS,
    a Windows share); a workspace on object storage mounted as files (io.object_store) is refused: no lock holds there.
    shortcut: one lock per machine's view of a disk; a workspace on object storage itself needs a lease and writes that
    don't rename (folder.stage does), a port of its own."""
    lockable(out)
    out.mkdir(parents=True, exist_ok=True)
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


@contextmanager
def writing(path: Path, wait: float = 10.0):
    """One change of a mapping (a workspace's columns.toml, the project's settings.toml) at a time: each reads the file,
    changes it and replaces it whole, so two at once would lose one. Apart from run_lock: a mapping may change while a
    run runs, for the next. An OS lock on a file beside it; a change takes milliseconds, so another waits up to `wait` s."""
    if not path.parent.is_dir():  # no workspace: what writes says so
        yield
        return
    lockable(path.parent)
    with open(path.with_name(f".{path.name}.lock"), "w") as f:
        until = time.monotonic() + wait
        while not lock(f):
            if time.monotonic() > until:
                raise Busy(f"another change is writing {path}", fix="try again once it is written")
            time.sleep(0.02)
        yield


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


def stage(con: duckdb.DuckDBPyConnection, out: Path, tables: list[tuple[str, Path]], texts: list[tuple[str | Callable[[], str], Path]] = (),
          replace: list[Path] | None = None, frames: list[tuple[pd.DataFrame, Path]] = ()) -> None:
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
        con.execute(f"COPY ({sql}) TO {lit(tmp(dest))} (FORMAT parquet)")
    for text, dest in texts:
        tmp(dest).parent.mkdir(parents=True, exist_ok=True)
        tmp(dest).write_text(text() if callable(text) else text, encoding="utf-8")
    for frame, dest in frames:  # sheets for people: pandas keeps their empty answer columns typed
        tmp(dest).parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(tmp(dest))
    dests = [dest for _, dest in (*tables, *texts, *frames)]
    staged = [[str(tmp(d)), str(d)] for d in dests if not whole(d)]
    if replace is not None:
        new = sorted({d.relative_to(out).parts[0] for d in dests if whole(d)})
        staged += [[None, str(x)] for x in replace if x.name not in new] + [[str(out / FULL_TMP / x), str(out / x)] for x in new]
    replace_text(out / PENDING, json.dumps(staged))  # from here on the write is done, whatever happens next
    finish_writes(out)


EARLIER = 200  # runs before the current full run kept in steps.json, each in brief: what the workspace's activity lists


def brief(x: dict) -> dict:  # a run of steps.json as the activity lists it: when, what, the record files it read, its seconds
    return dict(at=x["at"], what="decisions" if "decisions" in x else "increment" if x.get("part") else "full run",
                files=[f["file"] for f in x.get("inputs", []) if f.get("role") == "records"], seconds=round(sum(s["seconds"] for s in x["steps"]), 1),
                records=next((s.get("records") for s in x["steps"] if s["step"] == "load"), None),
                steps={k: round(sum(s["seconds"] for s in x["steps"] if s["step"] == k), 1) for k in dict.fromkeys(s["step"] for s in x["steps"])})  # each step's seconds: the next run's estimate, on this machine and file


def history(out: Path) -> list[dict]:  # every run steps.json holds, in brief, the earliest first: the last EARLIER before the current full run, then its own
    old = json.loads((out / STEPS).read_text(encoding="utf-8")) if (out / STEPS).exists() else {}
    return [*old.get("earlier", []), *map(brief, old.get("runs", []))]


def log(out: Path, entry: dict, append: bool, earlier: list[dict] | None = None) -> str:
    """steps.json with this entry: one per run, increment or set of decisions (a full run starts it again, with `earlier`,
    the runs before it in brief: history, read before its write replaced the old log). The text, for stage to write with
    the files it names: a run never lands without its entry, nor an entry without its run."""
    path = out / STEPS
    old = json.loads(path.read_text(encoding="utf-8")) if append and path.exists() else {}
    return json.dumps(dict(earlier=old.get("earlier", []) if append else (earlier or [])[-EARLIER:], runs=[*old.get("runs", []), entry]), indent=1, default=str)


def write_method(out: Path, method: dict) -> None:  # method.toml as `method` says, each value in TOML (tables inline)
    from er.config import _toml
    path = out / METHOD
    if method:
        path.write_text("".join(f"{k} = {_toml(v, inline=True)}\n" for k, v in method.items()), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def method(out: Path | str | None) -> dict:  # the workspace's method.toml, {} without one
    f = Path(out) / METHOD if out else None
    return toml_of(f) if f and f.exists() else {}


def runs(out: Path) -> list[dict]:  # steps.json's runs: the current full run's, then each increment and set of decisions; none before a run
    f = Path(out) / STEPS
    return json.loads(f.read_text(encoding="utf-8"))["runs"] if f.is_file() else []


def rounds(out: Path) -> list[dict]:
    return json.loads((out / ROUNDS).read_text(encoding="utf-8")) if (out / ROUNDS).exists() else []


def round_ran(out: Path, entry: dict) -> None:
    """rounds.json after a full run: its entry replaces the last when the method (entry["config"]) is the same, a run
    again on new answers or files; a new method opens the next round. Written whole, then renamed."""
    kept = rounds(out)
    kept = [*kept[:-1], entry] if kept and kept[-1]["config"] == entry["config"] else [*kept, entry]
    replace_text(out / ROUNDS, json.dumps(kept, indent=1, ensure_ascii=False, default=str))


def prepared(ws: Path, key: str) -> Path | None:
    """The records cleaned under `key`, if the workspace keeps them: a folder is there only once complete (keep_prepared
    renames it into place). Marked as the last used."""
    slot = ws / PREPARED / key
    try:
        os.utime(slot)  # a trial in another process may have just let it go
    except FileNotFoundError:
        return None
    return slot / "records.parquet" if (slot / "records.parquet").is_file() else None


def keep_prepared(ws: Path, key: str, write: Callable[[Path], None]) -> None:
    """Keeps records cleaned under `key`: `write` writes them into a folder of its own, renamed into place once complete,
    so a run cut short leaves nothing read for whole; then only the last KEEP_PREPARED used stay. Never fails the run: a
    copy that can't be written (a full disk) is left out. O(the records)."""
    root = ws / PREPARED
    root.mkdir(exist_ok=True)
    for old in root.glob(".*.tmp"):  # a copy a run cut short (killed, out of memory) left half written: its process is gone
        pid = old.name.split(".")[-2]
        if pid.isdigit() and not alive(int(pid)):
            shutil.rmtree(old, ignore_errors=True)
    tmp = root / f".{key}.{os.getpid()}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        tmp.mkdir()
        write(tmp / "records.parquet")
        os.rename(tmp, root / key)
    except (OSError, duckdb.Error):  # no room, or another run kept the same records first
        shutil.rmtree(tmp, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    def used(p: Path) -> float:  # 0: gone, a trial in another process let it go
        try:
            return p.stat().st_mtime
        except FileNotFoundError:
            return 0.0
    kept = sorted((p for p in root.iterdir() if not p.name.startswith(".")), key=used, reverse=True)
    for old in kept[KEEP_PREPARED:]:
        shutil.rmtree(old, ignore_errors=True)


def forget_prepared(ws: Path, key: str) -> None:  # a kept copy that can't be read: made again
    shutil.rmtree(ws / PREPARED / key, ignore_errors=True)


def next_part(folder: Path) -> int:  # one past the highest part-n.parquet: a part deleted by hand frees no number to write over
    return max((int(f.stem.removeprefix("part-")) for f in folder.glob("part-*.parquet")), default=-1) + 1


def held(out: Path) -> list[Path]:  # the run files a folder holds: what resolve records --overwrite replaces
    return [out / f for f in RUN_FILES if (out / f).exists()]


def answer_parts(out: Path) -> list[Path]:  # people's answer sheets the folder keeps, newest first
    return sorted((out / KIND_ANSWERS).glob("part-*.parquet"), reverse=True)


def current(out: Path, replacing: bool = False) -> None:
    """Refuses a workspace an earlier nayose wrote, in a layout this one no longer reads: answers kept in state/, an
    input part the reader never described (no intake.json), or rules' pairs written before they said whether each
    merged, unless a full run is `replacing` them (--overwrite). O(parts) to look."""
    old = ["people's answers in state/" if (out / "state" / "kind_labels.parquet").exists() else None,
           next((f"{p.name} read before the reader described its files" for p in parts(out) if not intake.report(p)), None),
           None if replacing else next(("rules' pairs that don't say whether they merged" for f in (out / "rule_kept").glob("part-*.parquet")
                                        if "merged" not in pq.read_schema(f).names), None)]
    if what := [x for x in old if x]:
        raise InputError(f"{out}: a workspace an earlier nayose wrote ({'; '.join(what)})", fix="create it again: nayose create workspace NAME, then load its files")


def type_in(out: Path, sheet: str, column: str, value: object, append: dict | None = None, **keys: str) -> None:
    """One answer people give, written into the workspace's sheet (review.parquet's decision, kind_review.parquet's
    kind) on the row whose `keys` columns hold those values, as a person would type it in; None clears it. With
    `append`, a row the sheet lacks is added with those values (a stored pair people chose to decide). Nothing is
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
        if not rows.any() and append is not None:
            frame = pd.concat([frame, pd.DataFrame([{**keys, **append}])], ignore_index=True)
            rows = pd.Series(False, index=frame.index)
            rows.iloc[-1] = True
        if not rows.any():
            raise InputError(f"{path}: no row for {', '.join(f'{k} {v}' for k, v in keys.items())}",
                             fix="answer a row the sheet holds, with the IDs as the run wrote them")
        frame.loc[rows, column] = pd.NA if value is None else value
        stage(connect()[0], out, [], frames=[(frame, path)])


def inputs(out: Path, spec: intake.InputSpec | None = None, reference: Path | None = None) -> list[Path]:
    """The record files the run in `out` read, in order: the full run's, then each increment's (steps.json). Each
    must still hold what was read, by its SHA-256, where it was read, in the workspace's own inputs/ (wherever the
    workspace now is, and whatever folder nayose starts from), or where the scheduler moved it (jobs.jsonl). With the
    reader's settings, a part an older reader read is read again first (fresh). O(bytes)."""
    for part in parts(out) if spec else []:
        fresh(part, spec, reference)
    named = [x for run in runs(out) for x in run.get("inputs", []) if x.get("role") == "records"]
    if not named:
        raise InputError(f"{out}: steps.json names no record file", fix="give the files again with a full run that overwrites the folder")
    jobs = out / "jobs.jsonl"
    moved = {e["sha256"]: e["path"] for e in map(json.loads, jobs.read_text(encoding="utf-8").splitlines() if jobs.exists() else [])
             if e.get("path")}
    inside = {sha: part / rel for part in parts(out) for rel, sha in sums(part).items()}
    read = [(part / f["read"], f["versions"]) for part in parts(out) for f in intake.report(part)["files"]]
    inside |= {v: f for f, versions in read for v in versions}
    replaced = {v: versions[-1] for _, versions in read for v in versions[:-1]}  # a read file a repair accepted later replaced
    files = []
    for x in named:
        here = [Path(p) for p in (x["file"], inside.get(x["sha256"]), moved.get(x["sha256"])) if p and Path(p).is_file()]
        if not (found := next((p for p in here if intake.sha256(p) in (x["sha256"], replaced.get(x["sha256"]))), None)):
            raise InputError(f"{x['file']}: {'changed' if here else 'gone'} since the run read it",
                             fix="give the files again with a full run that overwrites the folder")
        files.append(found)
    return files


INPUTS = "inputs"  # the records files a workspace was given, each copied into a part of its own: inputs/NNNN-<name>/
SUMS = ".sha256"  # in each part: each file's SHA-256 and its path in the part, so content given twice is known without reading it
LAST = "last"  # in inputs/: the name of the part given last, held already or new, which a run given no file reads
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
UPLOADS = ".uploads"  # files the page sent (nayose open ui), read once by the command they were sent for: taken in, or kept as the details file
STALE = 3600  # seconds: an upload this old was never read, and goes at the next one


def remove(p: Path) -> None:  # a file or a folder, as far as it goes: one held open elsewhere stays
    try:
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    except OSError:
        pass


def receive(ws: Path, name: str, size: int, read: Callable[[int], bytes], into: str | None = None, first: bool = True) -> Path:
    """The `size` bytes the page sends, read in pieces, written to the workspace's uploads as `name`, in the folder
    `into` when several files are one (the first of them clearing it). A file is whole or absent: written beside, then
    renamed. The file, or its folder. O(bytes)."""
    if not (ws / "columns.toml").is_file():
        raise InputError(f"no workspace at {ws}", fix="create it: nayose create workspace NAME")
    names = [x for x in (into, name) if x is not None]
    if not name or any(x != Path(x).name or x.startswith(".") for x in names):
        raise InputError(f"{name!r}: not a file name", fix="send a file, or give its path")
    up = ws / UPLOADS
    up.mkdir(exist_ok=True)
    for old in up.iterdir():
        try:
            if time.time() - old.stat().st_mtime > STALE:
                remove(old)
        except OSError:  # gone meanwhile: another upload's own sweep
            pass
    if first:
        remove(up / names[0])
    if (free := shutil.disk_usage(up).free) < size:
        raise InputError(f"no room for {name}: {size:,} bytes, {free:,} free", fix="free some disk space, or give the file's path on this computer")
    out = up.joinpath(*names)
    out.parent.mkdir(exist_ok=True)
    part, left = out.with_name(f".{out.name}.part"), size
    try:
        with open(part, "wb") as f:
            while left and (got := read(min(left, 1 << 20))):
                f.write(got)
                left -= len(got)
    except OSError as e:  # the disk filled, or the page went: nothing half written
        part.unlink(missing_ok=True)
        raise InputError(f"{name}: not written ({e.strerror or e})", fix="free some disk space, or send it again") from e
    if left:
        part.unlink(missing_ok=True)
        raise InputError(f"{name}: cut short, {size - left:,} of {size:,} bytes came", fix="send it again")
    os.replace(part, out)
    return up / names[0]


def uploaded(ws: Path, path: str | Path) -> Path | None:  # what the page sent that `path` names: a file or folder in the workspace's uploads
    p = Path(path).expanduser()
    return p.resolve() if p.exists() and p.resolve().parent == (ws / UPLOADS).resolve() else None


def create(home: Path, name: str, columns: str) -> Path:
    """The new workspace home/name, with its own mapping (columns.toml, the text given) and its method (method.toml):
    a trust line above every step, so nothing merges before people check (config.TrustRule). O(1)."""
    if not NAME.fullmatch(name):
        raise InputError(f"{name!r}: not a workspace name", fix="Latin letters (A–Z, a–z), digits, '.', '_' and '-', starting with a letter or digit, at most 64")
    ws = home / name
    lockable(ws)  # refused here, not at the first command that writes to it
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
        if not ((ws / COLUMNS).is_file() or (ws / STEPS).is_file()):
            continue
        log = runs(ws)
        found.append(dict(name=ws.name, workspace=str(ws), files=len(parts(ws)), ran=(ws / "gold.parquet").is_file(),
                          last=log[-1]["at"] if log else datetime.fromtimestamp(ws.stat().st_mtime).isoformat(timespec="seconds")))
    return sorted(found, key=lambda w: w["last"], reverse=True)


def parts(ws: Path) -> list[Path]:  # inputs/'s parts, oldest first
    return sorted(p for p in (ws / INPUTS).glob("[0-9]*-*") if p.is_dir())


def last(ws: Path) -> Path | None:
    """The part given last (inputs/last), whether it was new or held already; a workspace given files before that was
    kept: its newest part. None: no part. O(1) + O(parts)."""
    named = ws / INPUTS / LAST
    if named.is_file() and (part := ws / INPUTS / named.read_text(encoding="utf-8").strip()).is_dir():
        return part
    return next(iter(parts(ws)[-1:]), None)


def sums(part: Path) -> dict[str, str]:  # a part's files: path in the part → SHA-256
    return {rel: sha for sha, rel in (line.split("  ", 1) for line in (part / SUMS).read_text(encoding="utf-8").splitlines())}


def read_by_older(out: Path) -> bool:
    """Whether the run in `out` read a file an earlier version of the reader read (intake.READER): its records were
    prepared otherwise than a batch read now is, so the two wouldn't compare alike until a rerun. O(parts)."""
    older = {sha for part in parts(out) if (r := intake.report(part))
             for sha in [*r.get("older_reader", []), *(x["sha256"] for x in r["files"] if r.get("reader", 1) < intake.READER)]}
    return bool(older) and any(x.get("sha256") in older for run in runs(out) for x in run.get("inputs", []) if x.get("role") == "records")


def fresh(part: Path, spec: intake.InputSpec, reference: Path, progress=None) -> Path:
    """A part as this code and these [input] settings read it: one an older reader read (intake.READER), or under other
    settings, is read again, once, under its workspace's lock, with the repairs people accepted, as accepting one reads
    it; a run that read the old one still finds its file (intake.json versions). A reading cut short in its moves is
    finished first. O(bytes) once; O(1) after."""
    stale = lambda r: r.get("reader", 1) < intake.READER or r.get("input") != intake.read_as(spec)
    if not (part / ".read.tmp" / intake.REPORT).is_file() and ((r := intake.report(part)) is None or not stale(r)):
        return part
    with run_lock(part.parent.parent):
        intake.settle(part)
        if (r := intake.report(part)) is not None and stale(r):  # another job may have read it meanwhile
            intake.take(part, {part / x["given"]: x["given"] for x in r["files"]}, spec, reference, frozenset(r["accepted"]), progress=progress)
    return part


def take_in(ws: Path, path: str | Path, spec: intake.InputSpec, reference: Path, progress=None) -> tuple[Path, bool]:
    """Copy the files `path` names (a file, a glob or a folder: er.source.find) into the next part of the workspace's
    inputs/, and read them (er.intake: read/, what was found, the repairs proposed), under its lock: into a hidden
    folder first, renamed into place once every file is complete and read, so a part is whole or absent. Content the
    workspace already holds, file for file by SHA-256, is not copied again. `progress`: intake.take's. The part, and
    whether it is new. O(bytes)."""
    files = find(path)
    given = sorted(intake.sha256(f) for f in files)
    with run_lock(ws):
        for part in parts(ws):
            if sorted(sums(part).values()) == given:
                replace_text(ws / INPUTS / LAST, part.name)  # given again: the one a run reads, as a new one would be
                return fresh(part, spec, reference, progress), False
        p = Path(path).expanduser()
        root = p if p.is_dir() else None
        stem = p.parent.name if globbed(p) else p.name if root else p.stem
        n = max((int(x.name.split("-", 1)[0]) for x in parts(ws)), default=0) + 1
        part = ws / INPUTS / f"{n:04d}-{re.sub(r'[^A-Za-z0-9._-]+', '_', stem)[:40] or 'records'}"
        tmp = part.with_name(f".{part.name}.tmp")
        shutil.rmtree(tmp, ignore_errors=True)  # a copy cut short before
        lines, copied = [], {}
        for f in files:
            rel = f.relative_to(root) if root else Path(f.name)
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, tmp / rel)
            lines.append(f"{intake.sha256(tmp / rel)}  {rel.as_posix()}")
            copied[tmp / rel] = rel.as_posix()
        (tmp / SUMS).write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            intake.take(tmp, copied, spec, reference, progress=progress)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        os.replace(tmp, part)
        replace_text(ws / INPUTS / LAST, part.name)
    return part, True


def loaded(ws: Path) -> list[dict]:
    """inputs/'s parts, oldest first: each one's name, path, files, bytes and rows (as the intake read them), the name
    of its file as given (one file), the repairs waiting for people and the rows unread, whether a run has read all of it as it is now (steps.json, by
    SHA-256), the seconds its reading took and its columns (this machine's pace: the page's estimate of a run), and
    whether it was given last (last: the one a run given no file reads). O(parts + files + steps.json)."""
    read, given_last = {x["sha256"] for run in runs(ws) for x in run.get("inputs", []) if x.get("role") == "records"}, last(ws)
    def facts(part: Path) -> dict:  # a part's rows and whether a run read it, as the intake read it
        r = intake.report(part)
        waiting = sum(n for k, n in r["proposed"].items() if k not in r["accepted"])
        return dict(rows=r["rows"], read=all(f["versions"][-1] in read for f in r["files"]), waiting=waiting, unread=r["unread"], seconds=r.get("seconds"), columns=max((x["columns"] for x in r["files"]), default=0),
                    given=Path(r["files"][0]["given"]).name if len(r["files"]) == 1 else None)  # its file's own name, kana and kanji kept
    return [dict(name=part.name, path=str(part), files=len(own), bytes=sum((part / rel).stat().st_size for rel in own), **facts(part), last=part == given_last)
            for part in parts(ws) for own in [sums(part)]]
