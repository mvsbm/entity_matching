"""A job on BigQuery: its input loaded into the run's dataset, its procedure called (deploy/deploy.py made it), and
what it did said: build and update print report.txt (nayose.report_text, from the run's report_ tables).

    python deploy/run.py PROJECT.DATASET build gs://BUCKET/in/records.parquet [...]   a run's first batch
    python deploy/run.py PROJECT.DATASET update gs://BUCKET/in/batch.parquet          a batch added to the run
    python deploy/run.py PROJECT.DATASET decide gs://BUCKET/in/decided.parquet        people's decisions applied
    python deploy/run.py PROJECT.DATASET match 8                                      the match table at 8 points: matched

Runs as nayose-runtime (deploy/Jenkinsfile, Run, from main): Jenkins runs one at a time, BigQuery doesn't keep two
apart. shortcut: a procedure that fails partway leaves the tables it replaced replaced (BigQuery takes no DDL in a
transaction); build the run again; a table snapshot before each job, at the parity step, would undo it.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's nayose

import nayose  # noqa: E402
from nayose.engines import BigQuery  # noqa: E402

JOBS = ("build", "update", "decide", "match")


def main(argv: list[str] | None = None, client: object = None, bigquery: object = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 3 or args[1] not in JOBS:
        print(__doc__, file=sys.stderr)
        return 2
    dataset, job, given = args[0], args[1], args[2:]
    floor = float(nayose.config()["score"]["keep_from"])
    if job == "match" and float(given[0]) < floor:  # as the job does here (nayose.match): the run keeps no pair below it
        print(json.dumps(dict(severity="ERROR", error=f"threshold {given[0]}: the run keeps the pairs from {floor:g} points up only")))
        return 2
    engine, t = BigQuery(dataset, dataset, client=client, bigquery=bigquery), time.perf_counter()
    try:
        if job in ("build", "update"):
            engine.read_parquet("input", given, nayose.config()["input"]["columns"])
        if job == "decide":
            engine.read_parquet("given", given, ["why"])
        engine.run(f"CALL `{dataset}`.{job}({float(given[0])!r})" if job == "match" else f"CALL `{dataset}`.{job}()")
        seconds = round(time.perf_counter() - t, 1)
        if job in ("build", "update"):
            print(nayose.report_text(engine, {job: seconds}, job))
        print(json.dumps(dict(severity="INFO", job=job, dataset=dataset, seconds=seconds)), file=sys.stderr)
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
