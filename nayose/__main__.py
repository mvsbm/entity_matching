"""The jobs, as a machine runs them locally, on DuckDB. On BigQuery, the same SQL runs as the dataset's procedures
(deploy/).

    python -m nayose build records.parquet --out runs/main          a run's first batch: records, model, scores
    python -m nayose update batch.parquet --out runs/main           a batch added to the run
    python -m nayose match --out runs/main --threshold 8            the pairs at 8 points or more, as a table for people
    python -m nayose decide decided.parquet --out runs/main         people's decisions applied (a match table filled in)
    python -m nayose lookup --out runs/main --record 1234           a stored record looked up, as if it were new
    python -m nayose lookup --out runs/main FULL_NAME_KANA=ヤマダタロウ PHONE_NUM_4=1234
    python -m nayose lookup --out runs/main --file people.parquet  each record of a file looked up

A run is a folder: run.duckdb (its tables), report.txt and matched/. A job that writes takes the folder's lock, works
on a copy of run.duckdb, and puts the copy in place whole when it is done. So a run is never half written, and readers
never wait: a match works on a copy of its own, and a lookup reads the run itself, read-only (on Windows, a copy).

Each job prints one JSON object on stdout, and each stage, as it ends, one JSON line on stderr. Exit codes: 0; 2 for a
mistake people fix, where the JSON says what is wrong and the fix; 75 when another job is writing the run, to try
again later. The method is nayose/sql/, its values nayose/config.toml, and the input's columns mapping.sql.
"""
import argparse
import contextlib
import functools
import glob
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

import nayose
from nayose import InputError
from nayose.engines import DuckDB

RUN = "run.duckdb"


class Busy(InputError):
    """Another job is writing the run. It is no mistake, so the job exits 75, to be tried again."""


class NothingNew(Exception):
    """The batch holds nothing new: the run stays as it was, and the job says so (`result`)."""

    def __init__(self, result: dict) -> None:
        self.result = result


def files(given: str) -> list[Path]:
    """Return the Parquet files `given` names, in order: a file, a folder of them, or a quoted glob."""
    path = Path(given)
    if path.is_dir():
        found = sorted(path.glob("*.parquet"))
    else:
        found = [path] if path.is_file() else sorted(map(Path, glob.glob(given)))
    if not found:
        raise InputError(f"{given}: no Parquet file there",
                         fix="give a Parquet file, a folder of them, or a quoted glob")
    return found


@contextlib.contextmanager
def writing(out: Path, make: bool = False, compute: dict | None = None):
    """Give the run in `out` to write, on a copy that is put in place whole when the job is done.

    The job holds the folder's lock, which the system releases when the process ends, even if it dies. With `make`,
    the copy is a new, empty run.
    """
    if not make and not (out / RUN).is_file():
        raise InputError(f"no run at {out}",
                         fix=f"check the path, or build one: python -m nayose build FILE --out {out}")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / ".lock", "w") as lock:
        if not locked(lock):
            raise Busy(f"another job is writing the run in {out}",
                       fix="wait for it to finish: a run takes one writer at a time")
        new = out / f"{RUN}.new"
        new.unlink(missing_ok=True)
        if not make:
            shutil.copyfile(out / RUN, new)
        engine = DuckDB(new, compute)
        try:
            yield engine
            engine.close()  # before the rename: Windows can't replace an open file
            os.replace(new, out / RUN)
        finally:
            engine.close()  # a job that failed too; a second close does nothing
            new.unlink(missing_ok=True)


@contextlib.contextmanager
def reading(out: Path, copy: bool = True):
    """Give the run in `out` to read: on a copy of its own (a match's statements write), or in place with `copy` False.

    A lookup's statements write temporary tables alone, so it reads the run itself, read-only: a writer's os.replace
    leaves a file that is open as it was. Windows can't do that, so a lookup there works on a copy too.
    """
    if not (out / RUN).is_file():
        raise InputError(f"no run at {out}",
                         fix=f"check the path, or build one: python -m nayose build FILE --out {out}")
    in_place = not copy and os.name != "nt"
    with contextlib.nullcontext() if in_place else tempfile.TemporaryDirectory(prefix="nayose-") as tmp:
        if not in_place:
            shutil.copyfile(out / RUN, Path(tmp) / RUN)
        engine = DuckDB(out / RUN if in_place else Path(tmp) / RUN, read_only=in_place)
        try:
            yield engine
        finally:
            engine.close()


def locked(f) -> bool:
    """Take an exclusive lock on the open file `f` until it closes, and return whether it was free.

    The lock is flock on POSIX, and a byte's lock on Windows.
    """
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def timed(steps: dict, name: str, do, *args) -> None:
    """Run a stage, keep its seconds in `steps`, and say them on stderr."""
    t = time.perf_counter()
    do(*args)
    steps[name] = round(time.perf_counter() - t, 2)
    print(json.dumps(dict(severity="INFO", stage=name, seconds=steps[name])), file=sys.stderr, flush=True)


def build(a: argparse.Namespace) -> dict:
    """Run the build job: make a run from its first batch, keeping people's decisions where it replaces one."""
    out, given, steps = a.out, files(a.given), {}
    if (out / RUN).is_file() and not a.overwrite:
        raise InputError(f"{out} already holds a run",
                         fix="choose another folder, or replace the run: "
                             f"python -m nayose build {a.given} --out {out} --overwrite")
    with writing(out, make=True, compute=limits(a)) as engine:
        if (out / RUN).is_file() and (decisions_file := saved_decisions(out)):  # they stay with the run replacing it
            engine.con.execute(f"CREATE TABLE decisions AS SELECT * FROM read_parquet('{decisions_file}')")
            Path(decisions_file).unlink()
        nayose.build(engine, given, timed=functools.partial(timed, steps))
        n = engine.value("SELECT COUNT(*) FROM records")
        report(engine, out, steps, "build")
    return dict(records=n, seconds=round(sum(steps.values()), 1), steps=steps)


def saved_decisions(out: Path) -> str | None:
    """Write the run's decisions to a Parquet file beside it, for the run that replaces it, and return its path.

    A run built before the column round was named holds it as batch: the file names it round.
    """
    con = duckdb.connect(str(out / RUN), read_only=True)
    try:
        columns = {c for (c,) in con.execute("SELECT column_name FROM information_schema.columns "
                                             "WHERE table_name = 'decisions'").fetchall()}
        if not columns:
            return None
        path = out / "decisions.parquet"
        round_ = "batch AS round" if "batch" in columns else "round"
        con.execute(f"COPY (SELECT id_l, id_r, decision, why, {round_}, latest FROM decisions) "
                    f"TO '{path}' (FORMAT parquet)")
        return str(path)
    finally:
        con.close()


def update(a: argparse.Namespace) -> dict:
    """Run the update job: add a batch to the run. A batch with no new record raises NothingNew, or InputError."""
    out, given, steps = a.out, files(a.given), {}
    with writing(out, compute=limits(a)) as engine:
        nayose.unchanged(engine, nayose.build_again("update", out))
        before = engine.value("SELECT COUNT(*) FROM records")
        timed(steps, "records", nayose.records, engine, given)
        added = engine.value("SELECT COUNT(*) FROM records") - before
        if not added:
            aside = engine.rows("SELECT reason, COUNT(*) FROM set_aside GROUP BY reason ORDER BY reason")
            if any(reason != "already in the run" for reason, _ in aside):
                raise InputError(f"{a.given}: no new record to add ({', '.join(f'{n:,} {r}' for r, n in aside)})",
                                 fix="give the records set aside IDs, one per record")
            raise NothingNew(dict(records=before, added=0, seconds=round(sum(steps.values()), 1), steps=steps))
        timed(steps, "score", nayose.score, engine)
        timed(steps, "decide", nayose.decide, engine, [])
        report(engine, out, steps, "update")
    return dict(records=before + added, added=added, seconds=round(sum(steps.values()), 1), steps=steps)


def decide(a: argparse.Namespace) -> dict:
    """Run the decide job: store people's decisions, and make the entities again."""
    t = time.perf_counter()
    with writing(a.out) as engine:
        before = engine.value("SELECT COUNT(*) FROM decisions")
        nayose.decide(engine, files(a.given))
        stored, matches, entities = engine.rows(
            "SELECT (SELECT COUNT(*) FROM decisions), COUNT(CASE WHEN latest AND decision = 'match' THEN 1 END), "
            "(SELECT COUNT(DISTINCT entity) FROM gold) FROM decisions")[0]
    seconds = round(time.perf_counter() - t, 2)
    return dict(decisions=stored - before, matches=matches, entities=entities, seconds=seconds)


def match(a: argparse.Namespace) -> dict:
    """Run the match job: write the pairs at a threshold to a Parquet table for people."""
    t = time.perf_counter()
    into = a.into or a.out / "matched" / f"points-{a.threshold:g}.parquet"
    into.parent.mkdir(parents=True, exist_ok=True)
    with reading(a.out) as engine:
        nayose.match(engine, a.threshold)
        engine.con.execute(f"COPY (SELECT * FROM matched) TO '{into}' (FORMAT parquet)")
        pairs = engine.value("SELECT COUNT(*) FROM matched")
    return dict(pairs=pairs, threshold=a.threshold, into=str(into), seconds=round(time.perf_counter() - t, 2))


def lookup(a: argparse.Namespace) -> dict:
    """Run the lookup job: one record by its ID or its COLUMN=VALUE words, or each record of a file by its values."""
    values = dict(typed(x) for x in a.given)
    if sum(map(bool, (values, a.record, a.file))) != 1:
        raise InputError("give one of: a record's COLUMN=VALUE words, --record ID, --file FILE",
                         fix="for example: python -m nayose lookup --out runs/main --record 1234")
    with reading(a.out, copy=False) as engine:
        if not a.file:
            return nayose.lookup(engine, record=a.record, values=values or None, at_least=a.at_least, most=a.most)
        inputs = nayose.config()["input"]
        id_column, columns, out = inputs["id"], set(inputs["columns"]), []
        for rec in pq.read_table(files(a.file)[0]).to_pylist():
            asked = {k: str(v) for k, v in rec.items() if k in columns and k != id_column and v is not None}
            entities = (nayose.lookup(engine, values=asked, at_least=a.at_least, most=a.most)["entities"]
                        if asked else [])
            rows = [dict(asked=rec.get(id_column), entity=e["entity"], record=e["record"], points=e["points"],
                         rule=e["rule"], generators=e["generators"]) for e in entities]
            out += rows or [dict(asked=rec.get(id_column), entity=None, record=None, points=None, rule=None,
                                 generators=[])]
        return dict(records=out)


def limits(a: argparse.Namespace) -> dict:
    """Return DuckDB's limits for this run, from --compute KEY=VALUE."""
    if bad := [kv for kv in a.compute if "=" not in kv]:
        raise InputError(f"--compute {' '.join(bad)}: each limit is KEY=VALUE",
                         fix="for example --compute memory_limit=8GB threads=4")
    return dict(kv.split("=", 1) for kv in a.compute)


def typed(item: str) -> tuple[str, str]:
    """Return a COLUMN=VALUE word as (column, value), by the input's column names."""
    column, sep, value = item.partition("=")
    if not sep or not column:
        raise InputError(f"{item}: write COLUMN=VALUE",
                         fix='for example FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234, '
                             "by the input's column names")
    return column, value


def report(engine: DuckDB, out: Path, steps: dict, job: str) -> None:
    """Write report.txt beside the run: what it holds and how it was made."""
    (out / "report.txt").write_text(nayose.report(engine, steps, job), encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    """Return the command line's parser: one subcommand a job, each with its own arguments."""
    p = argparse.ArgumentParser(prog="python -m nayose",
                                description="Entity resolution jobs: build, update, match, decide, lookup.")
    jobs = p.add_subparsers(dest="job", required=True)

    def job(name: str, about: str, given: str | None, nargs: str | None = None) -> argparse.ArgumentParser:
        """Add a job's subcommand: its help (`about`), its positional argument's (`given`, if any), and --out."""
        j = jobs.add_parser(name, help=about, description=about)
        if given:
            j.add_argument("given", nargs=nargs, help=given)
        j.add_argument("--out", required=True, type=Path, help="the run's folder")
        return j

    build = job("build", "a run's first batch", "the records: a Parquet file, a folder of them or a quoted glob")
    update = job("update", "a batch added to the run", "the batch, as build reads records")
    for writer in (build, update):
        writer.add_argument("--compute", nargs="*", default=[], metavar="KEY=VALUE",
                            help="DuckDB's limits for this run: memory_limit=8GB threads=4")
    build.add_argument("--overwrite", action="store_true",
                       help="replace the run the folder holds, keeping people's decisions")
    match = job("match", "the pairs at a threshold, as a table for people", None)
    match.add_argument("--threshold", type=float, required=True, help="the fewest points a pair in the table has")
    match.add_argument("--into", type=Path, help="the table's file (default: <out>/matched/points-<threshold>.parquet)")
    job("decide", "people's decisions applied to the run",
        "Parquet: id_l, id_r, decision, as a match table holds them filled in")
    lookup = job("lookup", "records looked up in the run", "COLUMN=VALUE of one record, by the input's column names",
                 nargs="*")
    lookup.add_argument("--record", help="a stored record's ID, looked up as if it were new")
    lookup.add_argument("--file", help="a file of records, each looked up by its values")
    lookup.add_argument("--at-least", type=float,
                        help="the fewest points an entity shown has (default: config.toml [lookup] at_least)")
    lookup.add_argument("--most", type=int, help="the most entities shown (default: config.toml [lookup] most)")
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the job the command line names, print its JSON, and return its exit code."""
    utf8_output()
    a = parser().parse_args(argv)
    try:
        result = dict(build=build, update=update, match=match, decide=decide, lookup=lookup)[a.job](a)
    except NothingNew as e:
        result = e.result
    except InputError as e:
        print(json.dumps(dict(severity="WARNING" if isinstance(e, Busy) else "ERROR", error=str(e), fix=e.fix),
                         ensure_ascii=False))
        return 75 if isinstance(e, Busy) else 2
    except duckdb.InvalidInputException as e:
        error, fix = refusal(e)
        print(json.dumps(dict(severity="ERROR", error=error, fix=fix), ensure_ascii=False))
        return 2
    print(json.dumps({"severity": "INFO", **result}, ensure_ascii=False, default=str))
    return 0


def utf8_output() -> None:
    """Write stdout and stderr in UTF-8 wherever they go: on Windows, a pipe or a file takes the code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and stream.encoding.replace("-", "").lower() != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def refusal(e: duckdb.InvalidInputException) -> tuple[str, str]:
    """Return what is wrong and its fix, from a refusal the SQL raised (ERROR(...)) or the fit's (em.py's ValueError).

    Its words are "<what is wrong>; <the fix>"; without a "; ", each is the whole of them.
    """
    raised = str(e)
    message = raised.split("ValueError: ", 1)[-1] if "ValueError: " in raised else raised.split("Error: ", 1)[-1]
    return message.split("; ", 1)[0], message.split("; ", 1)[-1]


if __name__ == "__main__":
    sys.exit(main())
