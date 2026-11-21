"""Step 9, report, for people: qa.md (the label-free checks), report.txt (the run on a page with no record's value in
it) and review.parquet (the pairs to decide and to audit). O(review pairs) + O(N) in SQL. Built before the run's files
are written, and staged with them by steps.write: a run never lands without its reports, which a retry could not make
again, since nothing is new by then."""
import json
import time
from pathlib import Path

import pandas as pd

from er.io import markdown, read_parquet
from er.match import review_floor
from er.report import carry_over, diagnosis, qa, report_text
from er.steps.job import Ran


def report(ran: Ran, path: str | Path, out: Path, pipeline: Path) -> tuple[list[tuple[str, Path]], list[tuple[pd.DataFrame, Path]]]:
    """The reports as texts and frames for the write step to stage: `path` is the input, `pipeline` the pipeline file,
    both named in them; an increment keeps the previous sheet's open rows. Keeps qa's tables, the summary first, in
    ran.tables, and its weight bands (counts) in the step's facts (steps.json), with what limits what the run finds
    (report.diagnosis)."""
    t = time.perf_counter()
    tables = qa(ran, previous=out / "review.parquet" if ran.added is not None else None)
    sheet = tables.pop("review_sheet")
    if ran.added is None and (out / "review.parquet").exists():  # a full run makes the queue again: what people typed in and haven't given back stays
        sheet = carry_over(ran, read_parquet(out / "review.parquet"), sheet, out, full=True)
    frames = [(sheet, out / "review.parquet")]
    text = ["# Run checks", "", f"Input: `{path}` · {ran.n:,} records", ""]
    for name, table in tables.items():
        text += [f"## {name.replace('_', ' ')}", "", markdown(table.round(4)) if len(table) else "none", ""]
    ran.tables = tables
    items = diagnosis(ran, tables, review_floor(ran.pipeline))  # report.txt prints them
    texts = [("\n".join(text), out / "qa.md"), (report_text(ran, tables, pipeline, items), out / "report.txt")]
    bands = json.loads(tables["weight_bands"].round(4).to_json(orient="values"))  # as qa.md shows them
    ran.job.log.done("report", "O(review pairs) + O(N)", f"O({len(frames[0][0]):,} review pairs + {ran.n:,})", t, weight_bands=bands, diagnosis=items)
    return texts, frames
