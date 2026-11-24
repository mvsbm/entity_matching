"""The jobs, as a machine runs them locally (DuckDB); on BigQuery, the same SQL as the dataset's procedures (deploy).

    python -m nayose build records.parquet --out runs/main          a run's first batch: records, model, scores
    python -m nayose update batch.parquet --out runs/main           a batch added to the run
    python -m nayose match --out runs/main --threshold 8            the pairs at 8 points or more, as a table for people
    python -m nayose decide decided.parquet --out runs/main         people's decisions applied (a match table filled in)
    python -m nayose lookup --out runs/main --record 1234           a stored record looked up, as if it were new
    python -m nayose lookup --out runs/main FULL_NAME_KANA=ヤマダタロウ PHONE_NUM_4=1234
    python -m nayose lookup --out runs/main --file people.parquet  each record of a file looked up

A run is a folder: run.duckdb (its tables), report.txt, matched/. A job that writes takes the folder's lock, works on
a copy of run.duckdb and puts it in place whole when done, so a run is never half written and readers (match, lookup:
each on a copy of its own) never wait. Each prints one JSON object on stdout; each stage, as it ends, one JSON line on
stderr. Exit codes: 0; 2, a mistake people fix (the JSON says what is wrong, and the fix); 75, another job is writing
the run: try again later. The method is nayose/sql/, its values nayose/config.toml, the input's columns mapping.sql.
"""
import argparse
import contextlib
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


class Busy(InputError):  # another job is writing the run: no mistake, so the job exits 75, to be tried again
    pass


def files(given: str) -> list[Path]:  # a Parquet file, a folder of them or a quoted glob, in order
    path = Path(given)
    found = sorted(path.glob("*.parquet")) if path.is_dir() else [path] if path.is_file() else sorted(map(Path, glob.glob(given)))
    if not found:
        raise InputError(f"{given}: no Parquet file there", fix="give a Parquet file, a folder of them, or a quoted glob")
    return found


@contextlib.contextmanager
def writing(out: Path, make: bool = False, compute: dict | None = None):
    """The run in `out` to write: the folder's lock (the system releases it when the process ends, even if it dies),
    a copy of run.duckdb to work on (`make`: a new, empty one), put in place whole when the job is done."""
    if not make and not (out / RUN).is_file():
        raise InputError(f"no run at {out}", fix=f"check the path, or build one: python -m nayose build FILE --out {out}")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / ".lock", "w") as lock:
        if not locked(lock):
            raise Busy(f"another job is writing the run in {out}", fix="wait for it to finish: a run takes one writer at a time")
        new = out / f"{RUN}.new"
        new.unlink(missing_ok=True)
        if not make:
            shutil.copyfile(out / RUN, new)
        engine = DuckDB(new, compute)
        try:
            yield engine
            engine.close()
            os.replace(new, out / RUN)
        finally:
            engine.close()
            new.unlink(missing_ok=True)


@contextlib.contextmanager
def reading(out: Path):  # the run in `out` to read, on a copy of its own: a lookup's or a match's statements write nothing back
    if not (out / RUN).is_file():
        raise InputError(f"no run at {out}", fix=f"check the path, or build one: python -m nayose build FILE --out {out}")
    with tempfile.TemporaryDirectory(prefix="nayose-") as tmp:
        shutil.copyfile(out / RUN, Path(tmp) / RUN)
        engine = DuckDB(Path(tmp) / RUN)
        try:
            yield engine
        finally:
            engine.close()


def locked(f) -> bool:  # an exclusive lock on the open file f until it closes: flock on POSIX, a byte on Windows
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


def timed(steps: dict, name: str, do, *args) -> None:  # a stage, its seconds kept and said on stderr
    t = time.perf_counter()
    do(*args)
    steps[name] = round(time.perf_counter() - t, 2)
    print(json.dumps(dict(severity="INFO", stage=name, seconds=steps[name])), file=sys.stderr, flush=True)


def build(a: argparse.Namespace) -> dict:
    out, given, steps = a.out, files(a.given), {}
    if (out / RUN).is_file() and not a.overwrite:
        raise InputError(f"{out} already holds a run", fix=f"choose another folder, or replace the run: python -m nayose build {a.given} --out {out} --overwrite")
    with writing(out, make=True, compute=limits(a)) as engine:
        if (out / RUN).is_file() and (said := kept(out)):  # people's decisions stay with the run that replaces it
            engine.con.execute(f"CREATE TABLE decisions AS SELECT * FROM read_parquet('{said}')")
            Path(said).unlink()
        timed(steps, "records", nayose.records, engine, given)
        timed(steps, "fit", nayose.fit, engine)
        timed(steps, "score", nayose.score, engine)
        timed(steps, "decide", nayose.decide, engine, [])
        n = engine.value("SELECT COUNT(*) FROM records")
        report(engine, out, steps, "build")
    return dict(records=n, seconds=round(sum(steps.values()), 1), steps=steps)


def kept(out: Path) -> str | None:  # the run's decisions as a Parquet file beside it, for the run that replaces it
    con = duckdb.connect(str(out / RUN), read_only=True)
    try:
        if not con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'decisions'").fetchall()[0][0]:
            return None
        path = out / "decisions.parquet"
        con.execute(f"COPY decisions TO '{path}' (FORMAT parquet)")
        return str(path)
    finally:
        con.close()


def update(a: argparse.Namespace) -> dict:
    out, given, steps = a.out, files(a.given), {}
    with writing(out, compute=limits(a)) as engine:
        before = engine.value("SELECT COUNT(*) FROM records")
        timed(steps, "records", nayose.records, engine, given)
        added = engine.value("SELECT COUNT(*) FROM records") - before
        if not added:
            aside = engine.rows("SELECT reason, COUNT(*) FROM set_aside GROUP BY reason ORDER BY reason")
            if any(reason != "already in the run" for reason, _ in aside):
                raise InputError(f"{a.given}: no new record to add ({', '.join(f'{n:,} {r}' for r, n in aside)})", fix="give the records set aside IDs, one per record")
            raise Unchanged(dict(records=before, added=0, seconds=round(sum(steps.values()), 1), steps=steps))
        timed(steps, "fit", nayose.fit, engine, False)
        timed(steps, "score", nayose.score, engine)
        timed(steps, "decide", nayose.decide, engine, [])
        report(engine, out, steps, "update")
    return dict(records=before + added, added=added, seconds=round(sum(steps.values()), 1), steps=steps)


class Unchanged(Exception):  # nothing new: the run stays as it was, and the job says so
    def __init__(self, said: dict) -> None:
        self.said = said


def decide(a: argparse.Namespace) -> dict:
    t = time.perf_counter()
    with writing(a.out) as engine:
        before = engine.value("SELECT COUNT(*) FROM decisions")
        nayose.decide(engine, files(a.given))
        stored, matches, entities = engine.rows("""SELECT (SELECT COUNT(*) FROM decisions), COUNT(CASE WHEN latest AND decision = 'match' THEN 1 END),
                                                         (SELECT COUNT(DISTINCT cluster_id) FROM gold) FROM decisions""")[0]
    return dict(decisions=stored - before, matches=matches, entities=entities, seconds=round(time.perf_counter() - t, 2))


def match(a: argparse.Namespace) -> dict:
    t = time.perf_counter()
    into = a.into or a.out / "matched" / f"points-{a.threshold:g}.parquet"
    into.parent.mkdir(parents=True, exist_ok=True)
    with reading(a.out) as engine:
        nayose.match(engine, a.threshold)
        engine.con.execute(f"COPY (SELECT * FROM matched) TO '{into}' (FORMAT parquet)")
        pairs = engine.value("SELECT COUNT(*) FROM matched")
    return dict(pairs=pairs, threshold=a.threshold, into=str(into), seconds=round(time.perf_counter() - t, 2))


def lookup(a: argparse.Namespace) -> dict:
    values = dict(typed(x) for x in a.given)
    if sum(map(bool, (values, a.record, a.file))) != 1:
        raise InputError("give one of: a record's COLUMN=VALUE words, --record ID, --file FILE", fix="for example: python -m nayose lookup --out runs/main --record 1234")
    with reading(a.out) as engine:
        if not a.file:
            return nayose.lookup(engine, record=a.record, values=values or None, at_least=a.at_least, most=a.count)
        id_column, out = nayose.config()["input"]["id"], []
        for rec in pq.read_table(files(a.file)[0]).to_pylist():
            asked = {k: str(v) for k, v in rec.items() if k in nayose.config()["input"]["columns"] and k != id_column and v is not None}
            found = nayose.lookup(engine, values=asked, at_least=a.at_least, most=a.count)["entities"] if asked else []
            out += [dict(asked=rec.get(id_column), entity=e["entity"], record=e["record"], points=e["points"], rule=e["rule"], keys=e["keys"]) for e in found] or \
                   [dict(asked=rec.get(id_column), entity=None, record=None, points=None, rule=None, keys=[])]
        return dict(records=out)


def limits(a: argparse.Namespace) -> dict:  # --compute KEY=VALUE: DuckDB's limits for this run
    if bad := [kv for kv in a.compute if "=" not in kv]:
        raise InputError(f"--compute {' '.join(bad)}: each limit is KEY=VALUE", fix="for example --compute memory_limit=8GB threads=4")
    return dict(kv.split("=", 1) for kv in a.compute)


def typed(item: str) -> tuple[str, str]:  # a COLUMN=VALUE word, by the input's column names
    column, sep, value = item.partition("=")
    if not sep or not column:
        raise InputError(f"{item}: write COLUMN=VALUE", fix='for example FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234, by the input\'s column names')
    return column, value


def report(engine: DuckDB, out: Path, steps: dict, job: str) -> None:  # report.txt beside the run: what it holds and how it was made
    (out / "report.txt").write_text(nayose.report(engine, steps, job), encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m nayose", description="Entity resolution jobs: build, update, match, decide, lookup.")
    jobs = p.add_subparsers(dest="job", required=True)
    for name, about, given in (("build", "a run's first batch", "the records: a Parquet file, a folder of them or a quoted glob"),
                               ("update", "a batch added to the run", "the batch, as build reads records"),
                               ("match", "the pairs at a threshold, as a table for people", None),
                               ("decide", "people's decisions applied to the run", "Parquet: id_l, id_r, decision, as a match table holds them filled in"),
                               ("lookup", "records looked up in the run", "COLUMN=VALUE of one record, by the input's column names")):
        j = jobs.add_parser(name, help=about, description=about)
        if given:
            j.add_argument("given", nargs="*" if name == "lookup" else None, help=given)
        j.add_argument("--out", required=True, type=Path, help="the run's folder")
        if name in ("build", "update"):
            j.add_argument("--compute", nargs="*", default=[], metavar="KEY=VALUE", help="DuckDB's limits for this run: memory_limit=8GB threads=4")
        if name == "build":
            j.add_argument("--overwrite", action="store_true", help="replace the run the folder holds, keeping people's decisions")
        if name == "match":
            j.add_argument("--threshold", type=float, required=True, help="the fewest points a pair in the table has")
            j.add_argument("--into", type=Path, help="the table's file (default: <out>/matched/points-<threshold>.parquet)")
        if name == "lookup":
            j.add_argument("--record", help="a stored record's ID, looked up as if it were new")
            j.add_argument("--file", help="a file of records, each looked up by its values")
            j.add_argument("--from", dest="at_least", type=float, help="the fewest points an entity shown has (default: config.toml [lookup] at_least)")
            j.add_argument("--count", type=int, help="the most entities shown (default: config.toml [lookup] most)")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # UTF-8 wherever it goes: a pipe or a file on Windows would take the locale's code page
        if hasattr(stream, "reconfigure") and stream.encoding.replace("-", "").lower() != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    a = parser().parse_args(argv)
    try:
        result = dict(build=build, update=update, match=match, decide=decide, lookup=lookup)[a.job](a)
    except Unchanged as e:
        result = e.said
    except InputError as e:
        print(json.dumps(dict(severity="WARNING" if isinstance(e, Busy) else "ERROR", error=str(e), fix=e.fix), ensure_ascii=False))
        return 75 if isinstance(e, Busy) else 2
    except duckdb.InvalidInputException as e:  # a refusal the SQL raised (ERROR(...)) or the fit did (em.py's ValueError): its words say what to fix
        said = str(e).split("ValueError: ", 1)[-1] if "ValueError: " in str(e) else str(e).split("Error: ", 1)[-1]
        print(json.dumps(dict(severity="ERROR", error=said.split("; ", 1)[0], fix=said.split("; ", 1)[-1]), ensure_ascii=False))
        return 2
    print(json.dumps({"severity": "INFO", **result}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
