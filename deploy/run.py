"""Run a job on BigQuery: load its input into the run's dataset, call its procedure (deploy/deploy.py made it), and
say what it did. A build and an update print report.txt (nayose.report_text, from the job's temporary report_ tables).

    python deploy/run.py PROJECT.DATASET build gs://BUCKET/in/records.parquet [...]   a run's first batch
    python deploy/run.py PROJECT.DATASET update gs://BUCKET/in/batch.parquet          a batch added to the run
    python deploy/run.py PROJECT.DATASET decide gs://BUCKET/in/decided.parquet        people's decisions applied
    python deploy/run.py PROJECT.DATASET match 8                                      the match table at 8 points
    python deploy/run.py PROJECT.DATASET undo                                         a job that never ended, undone
    python deploy/run.py PROJECT.DATASET lookup --record ID | COLUMN=VALUE ...        a lookup, answered in looked_up

It runs as nayose-runtime (deploy/Jenkinsfile's Run stage, from main).

A job is all or nothing, though BigQuery takes no DDL in a transaction:
- It first makes the table job_running, holding the job and the dataset's tables. A second job finds it and refuses
  (exit 75).
- It then clones each table (before__<table>): a clone bills no bytes, and shares its storage until either changes.
- A job that fails is undone: each table is made again from its clone, and each table it made is dropped.
- A job whose process died is undone by `undo`, once no query of its session still runs: BigQuery carries on a
  procedure its caller left. So is a job interrupted while its procedure runs (an interrupt, a client's timeout): it
  exits 75 with what stopped it, and `undo` puts the tables back once the procedure ends.
- The run's views (fit.sql's) aren't tables, so a first build that fails leaves them; the next build makes them again.

A lookup (nayose.lookup) writes its answer, which holds records' values, to the run's table looked_up, and prints only
that it did, as Jenkins keeps what a job prints. It refuses while a job is marked, as that job's tables are half made.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's nayose

import nayose  # noqa: E402
from nayose.engines import BigQuery, bigquery_literal  # noqa: E402

JOBS = ("build", "update", "decide", "match")
MARK, BEFORE = "job_running", "before__"  # the running job's table, and the prefix of its clones
DEPLOYED = ("name_weights",)  # the deploy's tables, no job's: an undo never brings back one a deploy has since replaced


class Running(Exception):
    """The marked job's procedure still runs in BigQuery: undoing it now would race it."""


def script(engine: BigQuery, statements: list[str]) -> None:
    """Run the statements as one script, in order: the first to fail stops it."""
    if statements:
        engine.run(";\n".join(statements))


def tables(engine: BigQuery, dataset: str) -> list[str]:
    """Return the dataset's tables the jobs write: clones too, and tables made from them."""
    return [t for (t,) in engine.rows(f"SELECT table_name FROM `{dataset}`.INFORMATION_SCHEMA.TABLES "
                                      "WHERE table_type IN ('BASE TABLE', 'CLONE') ORDER BY 1") if t not in DEPLOYED]


def begin(engine: BigQuery, dataset: str, job: str) -> bool:
    """Mark the dataset with the job and clone each of its tables; return False where another job's mark is there."""
    now = tables(engine, dataset)
    if MARK in now:
        return False
    # a finished job's clones, left behind: dropped before the mark, so no undo reads them
    script(engine, [f"DROP TABLE `{dataset}`.{t}" for t in now if t.startswith(BEFORE)])
    held = [t for t in now if not t.startswith(BEFORE)]
    # fails where another job made the mark first, which is then never undone here
    engine.run(f"CREATE TABLE `{dataset}`.{MARK} AS SELECT '{job}' AS job, CURRENT_TIMESTAMP() AS started, "
               f"{bigquery_literal(engine.session)} AS session, {bigquery_literal(held or [''])} AS tables")
    try:
        script(engine, [f"CREATE TABLE `{dataset}`.{BEFORE}{t} CLONE `{dataset}`.{t}" for t in held])
    except BaseException:
        undo(engine, dataset)
        raise
    return True


def end(engine: BigQuery, dataset: str) -> None:
    """Drop the mark, then the clones: clones left without a mark are dropped by the next job."""
    clones = [f"DROP TABLE `{dataset}`.{t}" for t in tables(engine, dataset) if t.startswith(BEFORE)]
    script(engine, [f"DROP TABLE `{dataset}`.{MARK}", *clones])


def undo(engine: BigQuery, dataset: str) -> bool:
    """Put the dataset's tables back as the marked job found them, and return False where no job is marked.

    Each table is made again from its clone, and each table the job made is dropped; then the mark, then the clones,
    so an undo stopped partway can run again. Raises Running while a query of the marked job's session still runs:
    BigQuery carries on a procedure whose caller left, whether the caller's process died or only stopped waiting
    (an interrupt, a client's timeout).
    """
    engine.session = None  # a session of its own: the marked job's may still be busy, and a session runs one query
    now = tables(engine, dataset)
    if MARK not in now:
        return False
    session, held = engine.rows(f"SELECT session, tables FROM `{dataset}`.{MARK}")[0]
    held = [t for t in held if t]
    if still_running(engine, dataset, session):
        raise Running(session)
    back = [t for t in held if BEFORE + t in now]  # a table without its clone was never touched: the job stopped first
    made = [t for t in now if t not in held and t != MARK and not t.startswith(BEFORE)]
    script(engine, [*(f"CREATE OR REPLACE TABLE `{dataset}`.{t} CLONE `{dataset}`.{BEFORE}{t}" for t in back),
                    *(f"DROP TABLE `{dataset}`.{t}" for t in made), f"DROP TABLE `{dataset}`.{MARK}",
                    *(f"DROP TABLE `{dataset}`.{BEFORE}{t}" for t in back)])
    return True


def still_running(engine: BigQuery, dataset: str, session: str) -> bool:
    """Return whether a query of the marked job's session still runs.

    The check runs outside every session: run in the marked one, as a job's own undo would, it would count itself.
    The session's jobs are listed in the dataset's region (bigquery.jobs.list, iam.tf).
    """
    bq = engine.bigquery
    region = engine.client.get_dataset(dataset).location.lower()
    config = bq.QueryJobConfig(query_parameters=[bq.ScalarQueryParameter("session", "STRING", session)])
    done = engine.client.query(f"SELECT COUNT(*) FROM `region-{region}`.INFORMATION_SCHEMA.JOBS_BY_USER "
                               "WHERE session_info.session_id = @session AND state <> 'DONE'", job_config=config)
    return bool([tuple(r.values()) for r in done.result()][0][0])


def main(argv: list[str] | None = None, client: object = None, bigquery: object = None) -> int:
    """Run the job the arguments name, and return its exit code: 0, 2 for a mistake, 75 to try again later."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[1] not in (*JOBS, "undo", "lookup") or (args[1] != "undo" and len(args) < 3):
        print(__doc__, file=sys.stderr)
        return 2
    dataset, job, given = args[0], args[1], args[2:]
    if job == "match":
        try:
            nayose.check_threshold(float(given[0]))  # before any client, as the job does here
        except nayose.InputError as e:
            print(json.dumps(dict(severity="ERROR", error=str(e), fix=e.fix)), file=sys.stderr)
            return 2
    engine = BigQuery(dataset, client=client, bigquery=bigquery)
    try:
        if job == "lookup":
            return lookup(engine, dataset, given)
        if job == "undo":
            return undone(engine, dataset)
        return marked(engine, dataset, job, given)
    finally:
        engine.close()


def undone(engine: BigQuery, dataset: str) -> int:
    """Undo a job whose process died, once its procedure has ended; return the exit code."""
    try:
        said = dict(severity="INFO", job="undo", dataset=dataset, undone=undo(engine, dataset))
    except Running as e:
        said = dict(severity="WARNING", error=f"the marked job's procedure still runs in BigQuery (session {e})",
                    fix=f"undo once it ends: python deploy/run.py {dataset} undo")
        print(json.dumps(said), file=sys.stderr)
        return 75
    print(json.dumps(said), file=sys.stderr)
    return 0


def marked(engine: BigQuery, dataset: str, job: str, given: list[str]) -> int:
    """Run a job all or nothing, and return its exit code.

    The dataset is marked and its tables cloned (begin), the job run, and undone where it fails; then the mark and
    the clones are dropped (end). A build or an update then prints report.txt.
    """
    t = time.perf_counter()
    if not begin(engine, dataset, job):
        print(json.dumps(dict(severity="WARNING", error=f"a job is marked running in {dataset} ({MARK})",
                              fix="wait for it to finish; if none runs, its process died: "
                                  f"python deploy/run.py {dataset} undo")), file=sys.stderr)
        return 75
    try:
        run(engine, dataset, job, given)
    except BaseException as stopped:
        try:
            undo(engine, dataset)
        except Running as e:  # stopped waiting mid-call: the procedure carries on, so its undo waits for it
            print(json.dumps(dict(severity="WARNING", error=f"the job's procedure still runs in BigQuery (session {e})",
                                  cause=str(stopped) or type(stopped).__name__,
                                  fix=f"undo once it ends: python deploy/run.py {dataset} undo")), file=sys.stderr)
            return 75
        raise
    end(engine, dataset)
    seconds = round(time.perf_counter() - t, 1)
    if job in ("build", "update"):
        print(nayose.report_text(engine, {job: seconds}, job))
    print(json.dumps(dict(severity="INFO", job=job, dataset=dataset, seconds=seconds)), file=sys.stderr)
    return 0


def lookup(engine: BigQuery, dataset: str, given: list[str]) -> int:
    """Look up a record (--record ID, or COLUMN=VALUE words), write its answer to looked_up, return the exit code."""
    record = given[1] if given[0] == "--record" and len(given) == 2 else None
    values = None if record else dict(w.split("=", 1) for w in given if "=" in w)
    if values is not None and len(values) != len(given):
        print(json.dumps(dict(severity="ERROR", error="give --record ID, or COLUMN=VALUE words",
                              fix="for example: lookup --record 1234")), file=sys.stderr)
        return 2
    if MARK in tables(engine, dataset):
        error = f"a job is marked running in {dataset} ({MARK}): its tables are half made"
        print(json.dumps(dict(severity="WARNING", error=error, fix="look up once it ends")), file=sys.stderr)
        return 75
    try:
        answer = nayose.lookup(engine, record=record, values=values)
    except nayose.InputError as e:
        print(json.dumps(dict(severity="ERROR", error=str(e), fix=e.fix), ensure_ascii=False), file=sys.stderr)
        return 2
    engine.run("CREATE TABLE IF NOT EXISTS looked_up (asked STRING, at TIMESTAMP, answer STRING)")
    asked = json.dumps(dict(record=record, values=values), ensure_ascii=False)
    engine.run("INSERT INTO looked_up (asked, at, answer) SELECT @asked, CURRENT_TIMESTAMP(), @answer",
               {"asked": asked, "answer": json.dumps(answer, ensure_ascii=False)})
    print(json.dumps(dict(severity="INFO", job="lookup", dataset=dataset, into=f"{dataset}.looked_up",
                          entities=len(answer["entities"]))), file=sys.stderr)
    return 0


def run(engine: BigQuery, dataset: str, job: str, given: list[str]) -> None:
    """Load the job's input, then call its procedure."""
    if job in ("build", "update"):
        engine.read_parquet("input", given, nayose.config()["input"]["columns"])
    if job == "decide":
        engine.read_parquet("given", given, ["why"])
    engine.run(f"CALL `{dataset}`.{job}({float(given[0])!r})" if job == "match" else f"CALL `{dataset}`.{job}()")


if __name__ == "__main__":
    sys.exit(main())
