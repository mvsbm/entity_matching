"""Step 9, report, for people: report.txt, the run on a page with no record's value in it, the label-free checks among
it. O(C + N) in SQL. Built before the run's files are written, and staged with them by steps.write: a run never lands
without its report, which a retry could not make again, since nothing is new by then."""
import time
from pathlib import Path

from er.match import review_floor
from er.report import diagnosis, qa, report_text
from er.steps.job import Ran


def report(ran: Ran, out: Path, pipeline: Path) -> list[tuple[str, Path]]:
    """The report as text for the write step to stage: `pipeline` is the pipeline file, named in it. What limits what
    the run finds (report.diagnosis) is in the step's facts (steps.json) too."""
    t = time.perf_counter()
    tables = qa(ran)
    items = diagnosis(ran, tables, review_floor(ran.pipeline))  # report.txt prints them
    ran.job.log.done("report", "O(C + N)", f"O({ran.count('scores'):,} + {ran.n:,})", t, diagnosis=items)
    return [(report_text(ran, tables, pipeline, items), out / "report.txt")]
