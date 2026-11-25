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
- It first makes the table job_running (the mark), holding the job and the dataset's tables. A second job finds it
  and refuses (exit 75).
- It then clones each table its procedure writes, as deployed (before__<table>): a clone bills no bytes, and
  shares its storage until either changes.
- A job that fails is undone: each table is made again from its clone, and each table it made is dropped. It exits 1.
- A job whose process died is undone by `undo`, once no query of its session still runs: BigQuery carries on a
  query its caller left. So is a job interrupted while its clones are made or its procedure runs (an interrupt, a
  client's timeout): it exits 75 with what stopped it, and `undo` puts the tables back once that query ends.
- A job done renames its mark before__job_running, so that no job, undo or lookup finds it, then drops it and the
  clones. The next job drops what is left of them.
- The run's view (fit.sql's compared) isn't a table: a first build that fails leaves it; the next build makes it again.

Each run ends with one JSON line on stderr. Its outcomes, their exit codes and their fixes:

    outcome                                                  exit  fix
    the job done                                             0
    a job already marked (job_running)                       75    wait; if none runs, undo
    stopped while its query runs on in BigQuery (cause)      75    undo once it ends
    failed or interrupted, and undone (error)                1     run it again
    refused, as another method built the run (error)         2     build again, or run it with the build's code
    refused, as what it was given is wrong (error, fix)      2     the fix it names (the SQL's own words)
    failed, and its undo failed too (error, undo_error)      1     undo, then run it again
    done, but ending it or report.txt failed (finished)      1     run nothing again; drop a mark left, never undo
    undo: done, or nothing marked                            0
    undo: the marked job's query still runs                  75    undo once it ends
    undo: failed (error)                                     1     undo again
    a lookup: answered; a job marked; a mistake in it        0; 75; 2
    a mistake in the command (a threshold under keep_from)   2     the fix it names

A lookup (nayose.lookup) writes its answer, which holds records' values, to the run's table looked_up, and prints only
that it did, as Jenkins keeps what a job prints. It refuses while a job is marked, as that job's tables are half made.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's nayose

import nayose  # noqa: E402
from nayose.engines import BigQuery, bigquery_literal  # noqa: E402
from nayose.procedures import JOBS as PROCEDURES  # noqa: E402

JOBS = tuple(PROCEDURES)  # the jobs with a procedure: build, update, decide, match
MARK, BEFORE = "job_running", "before__"  # the running job's table, and the prefix of its clones
DEPLOYED = ("name_weights",)  # the deploy's tables, no job's: an undo never brings back one a deploy has since replaced
# One of the SQL's own refusals (ERROR), as BigQuery says it: each names what it refuses first, given or config.toml,
# then says what is wrong and, after the last "; ", what to do. What is wrong may quote people's values, a ; among
# them; what to do holds none. A mistake in what the job was given: running it again won't do.
REFUSED = re.compile(r"Query error: (?P<error>(?:given|config\.toml)\b.*?); (?P<fix>[^;]*?) at \[")
SEVERITY = {0: "INFO", 75: "WARNING"}  # what an exit code says, as a log reads it: any other is an ERROR
NO_TABLE = ""  # what the mark's tables hold for an empty dataset, never an empty array: an undo reads past it


class Running(Exception):
    """A query of the marked job's session still runs in BigQuery: undoing it now would race it."""


class UndoFailed(Exception):
    """The job failed (`stopped`), and so did its undo (`failed`): the job stays marked."""

    def __init__(self, stopped: BaseException, failed: BaseException) -> None:
        super().__init__(described(failed))
        self.stopped, self.failed = stopped, failed


def described(e: BaseException) -> str:
    """Return what an exception says, or its type's name where it says nothing (an interrupt)."""
    return str(e) or type(e).__name__


def say(code: int, **fields: object) -> int:
    """Print one JSON line on stderr, `fields` with the severity of the exit code `code` (SEVERITY); return `code`."""
    print(json.dumps({"severity": SEVERITY.get(code, "ERROR"), **fields}, ensure_ascii=False), file=sys.stderr)
    return code


def script(engine: BigQuery, statements: list[str]) -> None:
    """Run the statements as one script, in order: the first to fail stops it."""
    if statements:
        engine.run(";\n".join(statements))


def tables(engine: BigQuery, dataset: str) -> list[str]:
    """Return the dataset's tables the jobs write: clones too, and tables made from them."""
    return [t for (t,) in engine.rows(f"SELECT table_name FROM `{dataset}`.INFORMATION_SCHEMA.TABLES "
                                      "WHERE table_type IN ('BASE TABLE', 'CLONE') ORDER BY 1") if t not in DEPLOYED]


def begin(engine: BigQuery, dataset: str, job: str) -> list[str] | None:
    """Mark the dataset with the job and clone each table the job writes; return those tables, or None where another
    job's mark is there.

    The mark lists every table, so an undo drops each table the job made; a table the job doesn't write is left as it
    is, so it needs no clone. The job writes what its procedure writes as deployed (written), which the code here
    may not match until the next deploy, and the tables a file is loaded into (LOADS).
    """
    now = tables(engine, dataset)
    if MARK in now:
        return None
    # a finished job's renamed mark and clones, left behind: dropped before the mark, so no undo reads them
    script(engine, [f"DROP TABLE `{dataset}`.{t}" for t in now if t.startswith(BEFORE)])
    held = [t for t in now if not t.startswith(BEFORE)]
    writes = written(engine, dataset, job)  # before the mark: a failure here leaves none
    cloned = [t for t in held if writes is None or t in writes or t in LOADS.values()]
    # fails where another job made the mark first, which is then never undone here
    engine.run(f"CREATE TABLE `{dataset}`.{MARK} AS SELECT '{job}' AS job, CURRENT_TIMESTAMP() AS started, "
               f"{bigquery_literal(engine.session)} AS session, {bigquery_literal(held or [NO_TABLE])} AS tables")
    try:
        script(engine, [f"CREATE TABLE `{dataset}`.{BEFORE}{t} CLONE `{dataset}`.{t}" for t in cloned])
    except BaseException as stopped:
        undo_after(engine, dataset, stopped)
    return cloned


# A statement of a procedure that writes one of the run's tables: the deploy names each of them with its dataset
# (nayose.procedures.in_dataset), and none of the job's temporary tables.
WRITES = r"(?:CREATE(?: OR REPLACE)? TABLE(?: IF NOT EXISTS)?|INSERT INTO|DELETE FROM|UPDATE|MERGE(?: INTO)?|"\
         r"TRUNCATE TABLE|DROP TABLE(?: IF EXISTS)?)\s+`{dataset}`\.(\w+)"


def written(engine: BigQuery, dataset: str, job: str) -> set[str] | None:
    """Return the run's tables the job's procedure writes, as the dataset holds it; None where it holds none."""
    found = engine.rows(f"SELECT routine_definition FROM `{dataset}`.INFORMATION_SCHEMA.ROUTINES "
                        "WHERE routine_name = @job", {"job": job})
    return set(re.findall(WRITES.format(dataset=re.escape(dataset)), found[0][0], re.I)) if found else None


def undo_after(engine: BigQuery, dataset: str, stopped: BaseException) -> None:
    """Undo the marked job that `stopped` ended, then raise `stopped` again.

    Raises Running, caused by `stopped`, while a query of the job still runs, and UndoFailed where the undo fails.
    """
    try:
        undo(engine, dataset)
    except Running as e:
        raise e from stopped
    except (Exception, KeyboardInterrupt) as e:
        raise UndoFailed(stopped, e) from e
    raise stopped


LOADS = {"build": "input", "update": "input", "decide": "given"}  # the table a job's file is loaded into, for it alone


def end(engine: BigQuery, dataset: str, job: str, cloned: list[str]) -> None:
    """Rename the mark before__job_running, then drop it, the loaded files and the clones begin made (`cloned`).

    Once renamed, the mark is no mark: no job, undo or lookup finds it. A mark left by a DROP that failed would make
    an undo take back what the job did. The loaded files (input, given) are the raw records and decisions: only a
    job reads them, so none outlives one, whatever job left it. The next job drops what a failed DROP leaves of the
    clones.
    """
    loaded = [f"DROP TABLE IF EXISTS `{dataset}`.{t}" for t in dict.fromkeys(LOADS.values())]
    script(engine, [f"ALTER TABLE `{dataset}`.{MARK} RENAME TO {BEFORE}{MARK}", *loaded,  # the raw records go first
                    f"DROP TABLE `{dataset}`.{BEFORE}{MARK}", *(f"DROP TABLE `{dataset}`.{BEFORE}{t}" for t in cloned)])


def undo(engine: BigQuery, dataset: str) -> bool:
    """Put the dataset's tables back as the marked job found them, and return False where no job is marked.

    Each table is made again from its clone, and each table the job made is dropped; then the mark, then the clones,
    so an undo stopped partway can run again. Raises Running while a query of the marked job's session still runs:
    BigQuery carries on a query whose caller left, whether the caller's process died or only stopped waiting (an
    interrupt, a client's timeout).
    """
    # A session of its own: the marked job's may still be busy, and a session runs one query at a time. The old
    # session is left to expire, not aborted: aborting it would stop a procedure that still runs in it.
    engine.session = None
    now = tables(engine, dataset)
    if MARK not in now:
        return False
    session, held = engine.rows(f"SELECT session, tables FROM `{dataset}`.{MARK}")[0]
    held = [t for t in held if t != NO_TABLE]
    if still_running(engine, dataset, session):
        raise Running(session)
    back = [t for t in held if BEFORE + t in now]  # a table without its clone wasn't written: not the job's, or not yet
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
    config = bq.QueryJobConfig(query_parameters=[bq.ScalarQueryParameter("session", "STRING", session)],
                               labels=engine.labels)
    done = engine.client.query(f"SELECT COUNT(*) FROM `region-{region}`.INFORMATION_SCHEMA.JOBS_BY_USER "
                               "WHERE session_info.session_id = @session AND state <> 'DONE'", job_config=config)
    return bool([tuple(r.values()) for r in done.result()][0][0])


def main(argv: list[str] | None = None, client: object = None, bigquery: object = None) -> int:
    """Run the job the arguments name, and return its exit code: 0, 1 if the job failed, 2 for a mistake, 75 to try
    again later."""
    args = sys.argv[1:] if argv is None else argv
    known = len(args) >= 2 and args[1] in (*JOBS, "undo", "lookup")
    given_enough = known and (args[1] == "undo" or len(args) >= 3)  # undo takes nothing more, every other job some
    if not given_enough:
        print(__doc__, file=sys.stderr)
        return 2
    dataset, job, given = args[0], args[1], args[2:]
    if job == "match":
        try:
            nayose.check_threshold(float(given[0]))  # before any client, as the job does here
        except nayose.InputError as e:
            return say(2, error=str(e), fix=e.fix)
    engine = BigQuery(dataset, client=client, bigquery=bigquery, job=job)
    try:
        return dispatch(engine, dataset, job, given)
    finally:
        engine.close()


def dispatch(engine: BigQuery, dataset: str, job: str, given: list[str]) -> int:
    """Run a lookup, an undo, or a job all or nothing (all_or_nothing), and return its exit code: 1 if it failed."""
    if job == "lookup":
        return lookup(engine, dataset, given)
    if job == "undo":
        return undone(engine, dataset)
    try:
        return all_or_nothing(engine, dataset, job, given)
    except UndoFailed as e:  # the job is still marked
        return say(1, job=job, dataset=dataset, error=described(e.stopped), undo_error=described(e.failed),
                   fix=f"undo it (python deploy/run.py {dataset} undo), then run this job again")
    except (Exception, KeyboardInterrupt) as e:  # all_or_nothing undid the job, or never marked the dataset
        if nayose.CHANGED in str(e):  # the procedure's check of the method's fingerprint (nayose.UNCHANGED)
            return say(2, job=job, dataset=dataset, error=described(e), fix=nayose.build_again(job))
        if refused := REFUSED.search(str(e)):
            return say(2, job=job, dataset=dataset, error=refused["error"], fix=refused["fix"])
        return say(1, job=job, dataset=dataset, error=described(e), fix="run this job again")


def undone(engine: BigQuery, dataset: str) -> int:
    """Undo a job whose process died, once its query has ended; return the exit code."""
    try:
        undid = undo(engine, dataset)
    except Running as e:
        return say(75, error=f"the marked job's query still runs in BigQuery (session {e})",
                   fix=f"undo once it ends: python deploy/run.py {dataset} undo")
    except Exception as e:  # an undo stopped partway can run again
        return say(1, job="undo", dataset=dataset, error=described(e),
                   fix=f"undo again: python deploy/run.py {dataset} undo")
    return say(0, job="undo", dataset=dataset, undone=undid)


def all_or_nothing(engine: BigQuery, dataset: str, job: str, given: list[str]) -> int:
    """Run a job all or nothing, and return its exit code.

    The dataset is marked and its tables cloned (begin), the job run, and undone where it fails (undo_after); then the
    mark and the clones are dropped (end), and a build or an update prints report.txt (finished).
    """
    t = time.perf_counter()
    try:
        if (cloned := begin(engine, dataset, job)) is None:
            return say(75, error=f"a job is marked running in {dataset} ({MARK})", fix="wait for it to finish; "
                       f"if none runs, its process died: python deploy/run.py {dataset} undo")
        try:
            call_procedure(engine, dataset, job, given)
        except BaseException as stopped:
            undo_after(engine, dataset, stopped)
    except Running as e:  # stopped waiting mid-query (its clones, its procedure): it carries on, so its undo waits
        return say(75, error=f"the job's query still runs in BigQuery (session {e})", cause=described(e.__cause__),
                   fix=f"undo once it ends: python deploy/run.py {dataset} undo")
    return finished(engine, dataset, job, round(time.perf_counter() - t, 1), cloned)


def finished(engine: BigQuery, dataset: str, job: str, seconds: float, cloned: list[str]) -> int:
    """End a job whose procedure succeeded (end), print a build's or an update's report.txt, and return the exit code.

    Where either step fails, or is interrupted, the job is done all the same: it exits 1, saying so and never to run
    it again, which would run it twice. The next job drops the renamed mark and the clones left. A mark left, where
    the renaming failed, would make the next job refuse and offer an undo, which would take back what the job did, so
    the fix then is to drop the mark alone.
    """
    step = "ending it (the mark and the clones)"
    try:
        end(engine, dataset, job, cloned)
        step = "report.txt"
        if job in ("build", "update"):
            print(nayose.report_text(engine, {job: seconds}, job))
    except (Exception, KeyboardInterrupt) as e:
        try:
            marked = MARK in tables(engine, dataset)
        except Exception:  # unknown: said as if it stayed
            marked = True
        fix = (f"run nothing again; drop the mark alone (DROP TABLE `{dataset}`.{MARK}), never undo: an undo would "
               "take back what the job did" if marked else "run nothing again: the next job drops the clones left")
        return say(1, job=job, dataset=dataset, finished=True, failed=step, error=described(e), fix=fix)
    return say(0, job=job, dataset=dataset, seconds=seconds)


def lookup(engine: BigQuery, dataset: str, given: list[str]) -> int:
    """Look up a record (--record ID, or COLUMN=VALUE words), write its answer to looked_up, return the exit code."""
    record = given[1] if given[0] == "--record" and len(given) == 2 else None
    values = None if record else dict(w.split("=", 1) for w in given if "=" in w)
    if values is not None and len(values) != len(given):
        return say(2, error="give --record ID, or COLUMN=VALUE words", fix="for example: lookup --record 1234")
    if MARK in tables(engine, dataset):
        return say(75, error=f"a job is marked running in {dataset} ({MARK}): its tables are half made",
                   fix="look up once it ends")
    try:
        answer = nayose.lookup(engine, record=record, values=values)
    except nayose.InputError as e:
        return say(2, error=str(e), fix=e.fix)
    engine.run("CREATE TABLE IF NOT EXISTS looked_up (asked STRING, asked_at TIMESTAMP, answer STRING)")
    asked = json.dumps(dict(record=record, values=values), ensure_ascii=False)
    engine.run("INSERT INTO looked_up (asked, asked_at, answer) SELECT @asked, CURRENT_TIMESTAMP(), @answer",
               {"asked": asked, "answer": json.dumps(answer, ensure_ascii=False)})
    return say(0, job="lookup", dataset=dataset, into=f"{dataset}.looked_up", entities=len(answer["entities"]))


def call_procedure(engine: BigQuery, dataset: str, job: str, given: list[str]) -> None:
    """Load the job's input, then call its procedure."""
    if job in ("build", "update"):
        engine.read_parquet("input", given, nayose.config()["input"]["columns"])
    if job == "decide":
        engine.read_parquet("given", given, ["why"])
    engine.run(f"CALL `{dataset}`.{job}({float(given[0])!r})" if job == "match" else f"CALL `{dataset}`.{job}()")


if __name__ == "__main__":
    sys.exit(main())
