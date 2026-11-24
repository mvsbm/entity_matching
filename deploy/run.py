"""A job on BigQuery: its input loaded into the run's dataset, its procedure called (deploy/deploy.py made it), and
what it did said: build and update print report.txt (nayose.report_text, from the run's report_ tables).

    python deploy/run.py PROJECT.DATASET build gs://BUCKET/in/records.parquet [...]   a run's first batch
    python deploy/run.py PROJECT.DATASET update gs://BUCKET/in/batch.parquet          a batch added to the run
    python deploy/run.py PROJECT.DATASET decide gs://BUCKET/in/decided.parquet        people's decisions applied
    python deploy/run.py PROJECT.DATASET match 8                                      the match table at 8 points: matched
    python deploy/run.py PROJECT.DATASET undo                                         a job that never ended, undone
    python deploy/run.py PROJECT.DATASET lookup --record ID | COLUMN=VALUE ...        a lookup, its answer in looked_up

Runs as nayose-runtime (deploy/Jenkinsfile, Run, from main). All or nothing, though BigQuery takes no DDL in a
transaction: a job first makes the table job_running (the job, and the dataset's tables), which a second job finds and
refuses (exit 75), and clones each table (before__<table>: no bytes billed, its storage shared until either changes).
A job that fails is undone: each table made again from its clone, a table it made dropped. One whose process died is
undone by undo, once no query of its session still runs (BigQuery carries on a procedure its caller left). The run's
views (fit.sql's) aren't tables: a first build that fails leaves them, and the next build makes them again.
A lookup (nayose.lookup) writes its answer, which holds records' values, to the run's table looked_up and prints only
that it did: Jenkins keeps what a job prints. It refuses while a job is marked, whose tables are half made.
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
DEPLOYED = ("name_weights",)  # the deploy's, no job's: an undo never brings back one a deploy has since replaced


class Running(Exception):  # the marked job's procedure still runs in BigQuery: undone, it would race it
    pass


def script(engine: BigQuery, statements: list[str]) -> None:  # one job, its statements in order: the first to fail stops it
    if statements:
        engine.run(";\n".join(statements))


def tables(engine: BigQuery, dataset: str) -> list[str]:  # the dataset's tables the jobs write; a clone is one, and a table made from it too
    return [t for (t,) in engine.rows(f"SELECT table_name FROM `{dataset}`.INFORMATION_SCHEMA.TABLES "
                                      "WHERE table_type IN ('BASE TABLE', 'CLONE') ORDER BY 1") if t not in DEPLOYED]


def begin(engine: BigQuery, dataset: str, job: str) -> bool:
    """The job marked and each table cloned; False where another job's mark is there."""
    now = tables(engine, dataset)
    if MARK in now:
        return False
    script(engine, [f"DROP TABLE `{dataset}`.{t}" for t in now if t.startswith(BEFORE)])  # a finished job's, left: gone before the mark, so no undo reads them
    held = [t for t in now if not t.startswith(BEFORE)]
    engine.run(f"CREATE TABLE `{dataset}`.{MARK} AS SELECT '{job}' AS job, CURRENT_TIMESTAMP() AS started, "
               f"{bigquery_literal(engine.session)} AS session, {bigquery_literal(held or [''])} AS tables")  # fails where another job made it first: never undone here
    try:
        script(engine, [f"CREATE TABLE `{dataset}`.{BEFORE}{t} CLONE `{dataset}`.{t}" for t in held])
    except BaseException:
        undo(engine, dataset)
        raise
    return True


def end(engine: BigQuery, dataset: str) -> None:  # the mark first: clones left without it are dropped by the next job
    script(engine, [f"DROP TABLE `{dataset}`.{MARK}", *(f"DROP TABLE `{dataset}`.{t}" for t in tables(engine, dataset) if t.startswith(BEFORE))])


def undo(engine: BigQuery, dataset: str) -> bool:
    """The dataset's tables as the marked job found them: each from its clone, each it made dropped; then the mark, then
    the clones, so an undo stopped partway can run again. False where no job is marked; Running while a query of the
    marked job's session (another process's) still runs."""
    now = tables(engine, dataset)
    if MARK not in now:
        return False
    session, held = engine.rows(f"SELECT session, tables FROM `{dataset}`.{MARK}")[0]
    held = [t for t in held if t]
    if session != engine.session:  # a job of another process: its procedure may outlive it (bigquery.jobs.list, iam.tf)
        region = engine.client.get_dataset(dataset).location.lower()
        if engine.value(f"SELECT COUNT(*) FROM `region-{region}`.INFORMATION_SCHEMA.JOBS_BY_USER "
                        "WHERE session_info.session_id = @session AND state <> 'DONE'", {"session": session}):
            raise Running(session)
    back = [t for t in held if BEFORE + t in now]  # a table without its clone was never touched: the job stopped before it ran
    made = [t for t in now if t not in held and t != MARK and not t.startswith(BEFORE)]
    script(engine, [*(f"CREATE OR REPLACE TABLE `{dataset}`.{t} CLONE `{dataset}`.{BEFORE}{t}" for t in back),
                    *(f"DROP TABLE `{dataset}`.{t}" for t in made), f"DROP TABLE `{dataset}`.{MARK}",
                    *(f"DROP TABLE `{dataset}`.{BEFORE}{t}" for t in back)])
    return True


def main(argv: list[str] | None = None, client: object = None, bigquery: object = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[1] not in (*JOBS, "undo", "lookup") or (args[1] != "undo" and len(args) < 3):
        print(__doc__, file=sys.stderr)
        return 2
    dataset, job, given = args[0], args[1], args[2:]
    floor = float(nayose.config()["score"]["keep_from"])
    if job == "match" and float(given[0]) < floor:  # as the job does here (nayose.match): the run keeps no pair below it
        print(json.dumps(dict(severity="ERROR", error=f"threshold {given[0]}: the run keeps the pairs from {floor:g} points up only")), file=sys.stderr)
        return 2
    engine, t = BigQuery(dataset, dataset, client=client, bigquery=bigquery), time.perf_counter()
    try:
        if job == "lookup":
            return lookup(engine, dataset, given)
        if job == "undo":
            try:
                print(json.dumps(dict(severity="INFO", job=job, dataset=dataset, undone=undo(engine, dataset))), file=sys.stderr)
            except Running as e:
                print(json.dumps(dict(severity="WARNING", error=f"the marked job's procedure still runs in BigQuery (session {e})",
                                      fix=f"undo once it ends: python deploy/run.py {dataset} undo")), file=sys.stderr)
                return 75
            return 0
        if not begin(engine, dataset, job):
            print(json.dumps(dict(severity="WARNING", error=f"a job is marked running in {dataset} ({MARK})",
                                  fix=f"wait for it to finish; if none runs, its process died: python deploy/run.py {dataset} undo")), file=sys.stderr)
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


def lookup(engine: BigQuery, dataset: str, given: list[str]) -> int:
    record = given[1] if given[0] == "--record" and len(given) == 2 else None
    values = None if record else dict(w.split("=", 1) for w in given if "=" in w)
    if values is not None and len(values) != len(given):
        print(json.dumps(dict(severity="ERROR", error="give --record ID, or COLUMN=VALUE words", fix="for example: lookup --record 1234")), file=sys.stderr)
        return 2
    if MARK in tables(engine, dataset):
        print(json.dumps(dict(severity="WARNING", error=f"a job is marked running in {dataset} ({MARK}): its tables are half made",
                              fix="look up once it ends")), file=sys.stderr)
        return 75
    try:
        answer = nayose.lookup(engine, record=record, values=values)
    except nayose.InputError as e:
        print(json.dumps(dict(severity="ERROR", error=str(e), fix=e.fix), ensure_ascii=False), file=sys.stderr)
        return 2
    engine.run("CREATE TABLE IF NOT EXISTS looked_up (asked STRING, at TIMESTAMP, answer STRING)")
    engine.run("INSERT INTO looked_up (asked, at, answer) SELECT @asked, CURRENT_TIMESTAMP(), @answer",
               {"asked": json.dumps(dict(record=record, values=values), ensure_ascii=False), "answer": json.dumps(answer, ensure_ascii=False)})
    print(json.dumps(dict(severity="INFO", job="lookup", dataset=dataset, into=f"{dataset}.looked_up", entities=len(answer["entities"]))), file=sys.stderr)
    return 0


def run(engine: BigQuery, dataset: str, job: str, given: list[str]) -> None:  # the job's input loaded, its procedure called
    if job in ("build", "update"):
        engine.read_parquet("input", given, nayose.config()["input"]["columns"])
    if job == "decide":
        engine.read_parquet("given", given, ["why"])
    engine.run(f"CALL `{dataset}`.{job}({float(given[0])!r})" if job == "match" else f"CALL `{dataset}`.{job}()")


if __name__ == "__main__":
    sys.exit(main())
