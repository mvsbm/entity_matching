"""Write docs/dataflow.md: each job's data flow, read from its SQL as it is, as a diagram GitHub draws (Mermaid).

    .venv/bin/python scripts/dataflow.py        # docs/dataflow.md; tests/test_sql.py holds it to the SQL

A job is its stages in order (nayose.procedures.JOBS), each statement as its procedure holds it: one whose
`-- when:` condition the job's values make false is left out, as the deploy leaves it out (in_procedure). Each
statement's table written and tables read come from its parse; a temporary table, a view or a WITH is folded into the
arrows it carries, so an arrow joins two of the run's tables (or a table loaded into the dataset: input, given,
name_weights), named by the stage that writes its end.
"""
import sys
from pathlib import Path

import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # this checkout's nayose

import nayose  # noqa: E402
from nayose.procedures import ARGUMENTS, JOBS, TEMP_TABLE, in_procedure, stage_statements  # noqa: E402

OUT = ROOT / "docs" / "dataflow.md"
LOADED = ("input", "given", "name_weights")  # tables a job reads that no stage writes: files and the deploy's


def flows(job: str) -> tuple[dict[str, dict[str, str]], set[str], set[str]]:
    """The job's procedure as tables: each table its statements write, with each table read to write it and the stage
    that does; the tables folded (temporary, or a view); and the views."""
    declared, plain = {}, []
    for stage, told in JOBS[job]:
        declared |= nayose.values_of(stage, **told)
        plain += [(stage, sql) for sql in stage_statements(stage, None) if not nayose.TEMP_FUNCTION.match(sql)]
    folded = {t for _, sql in plain for t in TEMP_TABLE.findall(nayose.NOT_CODE.sub(" ", sql))}
    known = {f"v_{k}": v for k, v in declared.items() if isinstance(v, bool) and k not in ARGUMENTS.get(job, {})}
    made, views = {}, set()
    for stage, sql in plain:
        head = nayose.WRITE.match(sql)
        if not head or in_procedure(sql, "project.dataset", folded, known) is None:
            continue
        tree = sqlglot.parse_one(sql, read="bigquery")
        target = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
        ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
        reads = {t.name for t in tree.find_all(exp.Table) if t is not target and t.name and t.name not in ctes}
        if "VIEW" in nayose.verb_of(head):
            views.add(head["table"])
        made.setdefault(head["table"], {}).update({r: stage for r in reads - {head["table"]}})
    return made, folded | views, views


def edges(job: str) -> list[tuple[str, str, str]]:
    """The job's arrows between the run's tables: (from, to, the stage of the statement that writes `to`)."""
    made, folded, _ = flows(job)
    for other in JOBS:  # a view outlives the job that makes it: what it reads, as that job makes it
        their, _, views = flows(other)
        for view in views - set(made):
            made[view], folded = their[view], folded | {view}

    def sources(table: str, seen: frozenset) -> set[str]:  # the run's tables a folded one carries
        out = set()
        for read in made.get(table, {}):
            if read not in seen:
                out |= sources(read, seen | {read}) if read in folded else {read}
        return out
    return sorted({(s, t, stage) for t, reads in made.items() if t not in folded for r, stage in reads.items()
                   for s in (sources(r, frozenset({t, r})) if r in folded else {r}) if s != t})


def diagram(job: str) -> str:
    lines = ["```mermaid", "flowchart LR"]
    nodes = sorted({x for s, t, _ in edges(job) for x in (s, t)})
    for n in nodes:
        lines.append(f"  {n}[/{n}/]" if n in LOADED else f"  {n}[({n})]")
    for s, t, stage in edges(job):
        lines.append(f"  {s} -->|{stage}| {t}")
    return "\n".join([*lines, "```"])


def page() -> str:
    parts = ["[← README](../README.md) · [Architecture](architecture.md)", "",
             "# Data flow", "",
             "Each job's data flow, drawn from its SQL by `scripts/dataflow.py`, which a test holds this page to. A "
             "cylinder is one of the run's tables; a slanted box, a table loaded into the dataset (a file, or the "
             "deploy's name model). An arrow says that the stage it names writes its end from its start; the "
             "temporary tables, views and WITHs between them are folded into the arrow.", ""]
    for job in JOBS:
        stages = ", ".join(stage for stage, _ in JOBS[job])
        parts += [f"## {job}", "", f"Stages: {stages}.", "", diagram(job), ""]
    return "\n".join(parts)


def main() -> int:
    OUT.write_text(page(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: " + ", ".join(f"{job} {len(edges(job))} arrows" for job in JOBS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
