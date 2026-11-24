"""A job on BigQuery: its input loaded into the run's dataset, its procedure called (deploy/deploy.py made it), and
what it did said: build and update print report.txt (nayose.report_text, from the run's report_ tables).

    python deploy/run.py PROJECT.DATASET build gs://BUCKET/in/records.parquet [...]   a run's first batch
    python deploy/run.py PROJECT.DATASET update gs://BUCKET/in/batch.parquet          a batch added to the run
    python deploy/run.py PROJECT.DATASET decide gs://BUCKET/in/decided.parquet        people's decisions applied
    python deploy/run.py PROJECT.DATASET match 8                                      the match table at 8 points: matched
    python deploy/run.py PROJECT.DATASET undo                                         a job that never ended, undone

Runs as nayose-runtime (deploy/Jenkinsfile, Run, from main). All or nothing, though BigQuery takes no DDL in a
transaction: a job first makes the table job_running (the job, and the dataset's tables), which a second job finds and
refuses (exit 75), and clones each table (before__<table>: no bytes billed, its storage shared until either changes).
A job that fails is undone: each table made again from its clone, a table it made dropped. One whose process died is
undone by undo.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's nayose

import nayose  # noqa: E402
from nayose.engines import BigQuery, bigquery_literal  # noqa: E402

JOBS = ("build", "update", "decide", "match")
MARK, BEFORE = "job_running", "before__"


def script(engine: BigQuery, statements: list[str]) -> None:  # one job, its statements in order: the first to fail stops it
    if statements:
        engine.run(";\n".join(statements))


def tables(engine: BigQuery, dataset: str) -> list[str]:
    return [t for (t,) in engine.rows(f"SELECT table_name FROM `{dataset}`.INFORMATION_SCHEMA.TABLES WHERE table_type = 'BASE TABLE' ORDER BY 1")]


def begin(engine: BigQuery, dataset: str, job: str) -> bool:
    """The job marked and each table cloned; False where another job's mark is there."""
    now = tables(engine, dataset)
    if MARK in now:
        return False
    held = [t for t in now if not t.startswith(BEFORE)]
    engine.run(f"CREATE TABLE `{dataset}`.{MARK} AS SELECT '{job}' AS job, CURRENT_TIMESTAMP() AS started, "
               f"{bigquery_literal(held or [''])} AS tables")  # fails where another job made it first: never undone here
    try:
        script(engine, [*(f"DROP TABLE `{dataset}`.{t}" for t in now if t.startswith(BEFORE)),  # a finished job's, left
                        *(f"CREATE TABLE `{dataset}`.{BEFORE}{t} CLONE `{dataset}`.{t}" for t in held)])
    except BaseException:
        undo(engine, dataset)
        raise
    return True


def end(engine: BigQuery, dataset: str) -> None:  # the mark first: clones left without it are dropped by the next job
    script(engine, [f"DROP TABLE `{dataset}`.{MARK}", *(f"DROP TABLE `{dataset}`.{t}" for t in tables(engine, dataset) if t.startswith(BEFORE))])


def undo(engine: BigQuery, dataset: str) -> bool:
    """The dataset's tables as the marked job found them: each from its clone, each it made dropped; then the mark, then
    the clones, so an undo stopped partway can run again. False where no job is marked."""
    now = tables(engine, dataset)
    if MARK not in now:
        return False
    held = [t for t in engine.value(f"SELECT tables FROM `{dataset}`.{MARK}") if t]
    back = [t for t in held if BEFORE + t in now]  # a table without its clone was never touched: the job stopped before it ran
    made = [t for t in now if t not in held and t != MARK and not t.startswith(BEFORE)]
    script(engine, [*(f"CREATE OR REPLACE TABLE `{dataset}`.{t} CLONE `{dataset}`.{BEFORE}{t}" for t in back),
                    *(f"DROP TABLE `{dataset}`.{t}" for t in made), f"DROP TABLE `{dataset}`.{MARK}",
                    *(f"DROP TABLE `{dataset}`.{BEFORE}{t}" for t in back)])
    return True


def main(argv: list[str] | None = None, client: object = None, bigquery: object = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[1] not in (*JOBS, "undo") or (args[1] != "undo" and len(args) < 3):
        print(__doc__, file=sys.stderr)
        return 2
    dataset, job, given = args[0], args[1], args[2:]
    floor = float(nayose.config()["score"]["keep_from"])
    if job == "match" and float(given[0]) < floor:  # as the job does here (nayose.match): the run keeps no pair below it
        print(json.dumps(dict(severity="ERROR", error=f"threshold {given[0]}: the run keeps the pairs from {floor:g} points up only")))
        return 2
    engine, t = BigQuery(dataset, dataset, client=client, bigquery=bigquery), time.perf_counter()
    try:
        if job == "undo":
            print(json.dumps(dict(severity="INFO", job=job, dataset=dataset, undone=undo(engine, dataset))), file=sys.stderr)
            return 0
        if not begin(engine, dataset, job):
            print(json.dumps(dict(severity="WARNING", error=f"a job is marked running in {dataset} ({MARK})",
                                  fix=f"wait for it to finish; if none runs, its process died: python deploy/run.py {dataset} undo")))
            return 75
        try:
            run(engine, dataset, job, given)
        except BaseException:
            undo(engine, dataset)
            raise
        end(engine, dataset)
        seconds = round(time.perf_counter() - t, 1)
        if job in ("build", "update"):
            print(nayose.report_text(engine, {job: seconds}, job))
        print(json.dumps(dict(severity="INFO", job=job, dataset=dataset, seconds=seconds)), file=sys.stderr)
    finally:
        engine.close()
    return 0


def run(engine: BigQuery, dataset: str, job: str, given: list[str]) -> None:  # the job's input loaded, its procedure called
    if job in ("build", "update"):
        engine.read_parquet("input", given, nayose.config()["input"]["columns"])
    if job == "decide":
        engine.read_parquet("given", given, ["why"])
    engine.run(f"CALL `{dataset}`.{job}({float(given[0])!r})" if job == "match" else f"CALL `{dataset}`.{job}()")


if __name__ == "__main__":
    sys.exit(main())
