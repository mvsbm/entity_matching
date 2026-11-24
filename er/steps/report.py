"""Step 9, report, for people: report.txt, the run on a page with no record's value in it, the label-free checks among
it. O(C + N) in SQL. Built before the run's files are written, and staged with them by steps.write: a run never lands
without its report, which a retry could not make again, since nothing is new by then."""
import json
import time
from pathlib import Path

from er.match import review_floor
from er.report import diagnosis, qa, report_text
from er.steps.job import Ran


def report(ran: Ran, out: Path, pipeline: Path) -> list[tuple[str, Path]]:
    """The report as text for the write step to stage: `pipeline` is the pipeline file, named in it. Keeps qa's tables,
    the summary first, in ran.tables, and its weight bands (counts) in the step's facts (steps.json), with what limits
    what the run finds (report.diagnosis)."""
    t = time.perf_counter()
    ran.tables = tables = qa(ran)
    items = diagnosis(ran, tables, review_floor(ran.pipeline))  # report.txt prints them
    bands = json.loads(tables["weight_bands"].round(4).to_json(orient="values"))
    ran.job.log.done("report", "O(C + N)", f"O({ran.count('scores'):,} + {ran.n:,})", t, weight_bands=bands, diagnosis=items)
    return [(report_text(ran, tables, pipeline, items), out / "report.txt")]
