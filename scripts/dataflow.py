"""Write docs/dataflow.md: the SQL files and tables explained, the tables' columns (an ERD), the jobs, and each job's
data flow, read from the code as it is, as diagrams GitHub draws (Mermaid).

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


FILES = {  # each SQL file: in short, and in the code
    "mapping.sql": ("Turns the input's columns into the fields nayose works with.",
                    "Each column goes through `read_value`; a field takes its first fully filled source. Writes "
                    "`input_rows` (each distinct row, with `nayose_id`) and `mapped`. The repository's maps the "
                    "generated data; a deployment deploys its own (`deploy.py --mapping`; in prod, the secret "
                    "`nayose-mapping`)."),
    "functions.sql": ("The functions every job creates first.",
                      "The intake (`read_value`, `blank`, `trimmed`); the comparison levels (`name_level` with "
                      "`name_score`, `gamma_company`, `gamma_address`, `gamma_phone`, `gamma_cif`, `gamma_birth`); "
                      "the rules' fuzzy tests (`near_*`); shared steps (`pairs_of`, `padded`, `numbers_dashed`)."),
    "records.sql": ("Stage 1: adds a batch to the run's records, cleaned, each marked person or company.",
                    "(1) `set_aside`: no ID, an ID already in the run, or one ID with two contents. (2) Standardizes: "
                    "`nfkc`, katakana, `strip_spaces`, `strip_separators`, `padded`, `strip_legal_form`, `kana_fold`. "
                    "(3) `kind`: a written legal form; else the name model (logistic regression on character n-grams, "
                    "`name_weights`) at `name_line`; else the file's flag. (4) Each name to its side's fields. "
                    "(5) `placeholders` (`placeholder_min`, `spread`, `crowd`). (6) Writes `records` with each "
                    "field's copies (`field__steps`); a run record holding a new placeholder is made again "
                    "(`redone`)."),
    "fit.sql": ("Stage 2, a build only: estimates how many points each comparison level is worth, without labelled "
                "pairs.",
                "Fellegi–Sunter. The sample: `fit_records` records, whole postal areas by `er_hash`. λ from the "
                "near-certain rules' pairs; m by EM (`fit_model`, `nayose/em.py`) on pairs blocked on phone, then "
                "address; u counted exactly where equality allows and sampled elsewhere, on the sample and on the "
                "file. Writes `model` and `fit`."),
    "score.sql": ("Stage 3: finds the pairs worth comparing and gives each its points. Nothing merges here.",
                  "The rules' pairs (`rule_keys`); the 22 generators' keys (`every_key`: exact, deletion and reading "
                  "keys); the gate on blocks of `oversized` records (kept only if a sample holds a pair at "
                  "`search_floor`); `bound_of`, an upper bound from cheap tests, so the costly comparisons run only "
                  "where needed; then each comparison's level and `points_of` (the prior plus each level's bits). "
                  "Writes `cands` and `scored` (the pairs from `keep_from` points up, and every rule pair)."),
    "decide.sql": ("Stores people's decisions and groups records into entities from them.",
                   "Reads `given` (`given_text`, `said`) and refuses a wrong file with its fix (`ERROR`); adds to "
                   "`decisions` each decision that changes its pair's latest; `gold` is the connected components of "
                   "the latest-`match` pairs (`entities_of`, `nayose/entities.py`), each named by its smallest ID. A "
                   "build and an update run it without `given`."),
    "match.sql": ("Makes the review list.",
                  "`matched`: the `scored` pairs at `@threshold` points or more, less those whose latest decision is "
                  "`no_match`, with both records' fields, each level's label and bits (`model`), `household()`, and "
                  "empty `decision` and `why`."),
    "report.sql": ("The run's counts for `report.txt`, never a record's value.",
                   "The `report_*` temporary tables `nayose.report_text` prints: counts, each field's fill and look "
                   "(`[report.looks]`), score bands, each generator's candidates."),
    "lookup.sql": ("Finds which entities one record would match, changing nothing.",
                   "After `records.sql` and `score.sql` ran on the asked record in temporary tables (`nayose.lookup`): "
                   "its entities at `@at_least` points or more, or joined by a rule, best first, and each generator's "
                   "look-up. On BigQuery, `run.py` stores the answer in `looked_up`."),
}
TABLES = {  # each table: in short, and its key columns (a test holds each to the table's real columns)
    "input": ("The batch a job reads: a file `run.py` loads, or the table the mapping's `FROM` names.", []),
    "name_weights": ("The person-or-company name model, loaded by the deploy.", ["term", "coef"]),
    "given": ("People's decisions, loaded for `decide`.", []),
    "records": ("Every record of the run, cleaned.", ["id", "kind", "customer", "batch"]),
    "set_aside": ("The latest batch's rows that weren't added.", ["reason"]),
    "placeholders": ("Values too common to be evidence, read as missing.", ["field", "value", "n"]),
    "fit": ("The fit's result as a whole; an update scores with it.", ["probability", "fitted"]),
    "model": ("How many points each comparison level gives.", ["comparison", "gamma", "label", "bits"]),
    "rule_keys": ("Each record's keys for the rules.", ["i", "key", "id"]),
    "every_key": ("Each record's keys for finding pairs: the key index.", ["g", "key", "id"]),
    "cands": ("The latest batch's candidate pairs.", ["l", "r", "generators"]),
    "scored": ("Every pair kept, with its points.", ["id_l", "id_r", "points", "rule"]),
    "decisions": ("Every decision people gave, by round.", ["id_l", "id_r", "decision", "latest"]),
    "gold": ("**The answer:** each record's entity.", ["id", "entity"]),
    "matched": ("The review list.", ["decision", "why", "id_l", "id_r", "points"]),
    "method": ("The installed method's fingerprint; every job after a build checks it.", ["fingerprint"]),
}
OTHERS = ["`compared`: a view of `records`, the columns `fit.sql` and `score.sql` read.",
          "`looked_up`: on BigQuery, each lookup's answer (`asked`, `asked_at`, `answer`).",
          "`job_running` and `before__<table>`: `run.py`'s mark of a job under way, and the clones of the tables it "
          "writes; both dropped when it ends."]
LINKS = [  # (table, column, the table it names a row of): the ERD's lines, each column held to the real schema
    ("rule_keys", "id", "records"), ("every_key", "id", "records"), ("cands", "l", "records"),
    ("cands", "r", "records"), ("scored", "id_l", "records"), ("scored", "id_r", "records"),
    ("scored", "gamma_name", "model"), ("decisions", "id_l", "records"), ("decisions", "id_r", "records"),
    ("gold", "id", "records"), ("gold", "entity", "records"), ("matched", "id_l", "records"),
    ("matched", "id_r", "records")]
TYPES = {"VARCHAR": "STRING", "BIGINT": "INT64", "INTEGER": "INT64", "HUGEINT": "INT64", "DOUBLE": "FLOAT64",
         "FLOAT": "FLOAT64", "BOOLEAN": "BOOL"}


def schema() -> dict[str, list[tuple[str, str]]]:
    """The run's tables and their columns, as a build, a decide and a match leave them on DuckDB, typed as BigQuery
    types them: a small generated population built in memory."""
    import tempfile
    from dataclasses import replace
    from design.generate import generate, load_reference, load_spec
    from nayose.engines import DuckDB
    with tempfile.TemporaryDirectory() as tmp:
        spec = replace(load_spec(ROOT / "config" / "generator.toml")[0], entities=400)
        generate(spec, *load_reference(ROOT / "data" / "reference")).df.to_parquet(Path(tmp) / "x.parquet", index=False)
        engine = DuckDB()
        nayose.build(engine, [Path(tmp) / "x.parquet"])
        nayose.match(engine, float(nayose.config()["score"]["keep_from"]))
        kept = [t for (t,) in engine.con.execute("SELECT table_name FROM duckdb_tables() WHERE NOT temporary "
                                                 "ORDER BY 1").fetchall()]
        out = {t: [(c, TYPES.get(k, k.replace(" ", "_"))) for c, k in engine.columns(t)] for t in kept}
        engine.close()
    return {t: [(c, k.replace("VARCHAR", "STRING")) for c, k in cols] for t, cols in out.items()}


def erd(tables: dict) -> str:
    lines = ["```mermaid", "erDiagram"]
    for t in sorted(tables):
        lines.append(f"  {t} {{")
        lines += [f"    {k} {c}{' PK' if (t, c) in (('records', 'id'), ('gold', 'id')) else ''}" for c, k in tables[t]]
        lines.append("  }")
    for t, c, other in LINKS:
        lines.append(f'  {other} ||--o{{ {t} : "{c}"')
    return "\n".join([*lines, "```"])


def jobs() -> str:
    """Each job's stages in order, and which job's tables each job reads (the data flow's: a table a job reads and
    doesn't write itself, written by another job)."""
    lines = ["```mermaid", "flowchart LR"]
    reads, writes = {}, {}
    for job in JOBS:
        found = edges(job)
        writes[job] = {t for _, t, _ in found}
        reads[job] = {s for s, _, _ in found} - writes[job] - set(LOADED)
        stages = [stage for stage, _ in JOBS[job]]
        lines.append(f"  subgraph {job}_job[{job}]")
        lines += [f"    {job}_{a}[{a}] --> {job}_{b}[{b}]" for a, b in zip(stages, stages[1:])]
        lines.append("  end")
    for a in JOBS:
        for b in JOBS:
            if a != b and (shared := sorted(writes[a] & reads[b])):
                lines.append(f"  {a}_job -->|{', '.join(shared)}| {b}_job")
    return "\n".join([*lines, "```"])


def diagram(job: str) -> str:
    lines, found = ["```mermaid", "flowchart LR"], edges(job)
    for n in sorted({x for s, t, _ in found for x in (s, t)}):
        lines.append(f"  {n}[/{n}/]" if n in LOADED else f"  {n}[({n})]")
    for s, t, stage in found:
        lines.append(f"  {s} -->|{stage}| {t}")
    return "\n".join([*lines, "```"])


def page() -> str:
    tables = schema()
    parts = ["[← README](../README.md) · [Architecture](architecture.md)", "",
             "# Data flow", "",
             "The run's SQL files, its tables, its jobs and each job's data flow, all drawn from the code by "
             "`scripts/dataflow.py`, which a test holds this page to.", "",
             "## The SQL files", "", "| File | In short | In the code |", "|---|---|---|"]
    parts += [f"| `{f}` | {short} | {code} |" for f, (short, code) in FILES.items()]
    parts += ["", "## The tables", "", "| Table | In short | Key columns |", "|---|---|---|"]
    parts += [f"| `{t}` | {short} | {', '.join(f'`{c}`' for c in cols)} |" for t, (short, cols) in TABLES.items()]
    parts += ["", "Not drawn below: " + " ".join(OTHERS), "",
              "### Every table's columns", "",
              "Each of the run's tables with its columns, as BigQuery types them; a line joins a column to the table "
              "whose row it names.", "", erd(tables), "",
              "## The jobs", "",
              "Each job's stages, in order; an arrow from one job to another names the tables the first writes "
              "that the second reads and doesn't write itself.", "", jobs(), "",
              "## Each job's data flow", "",
              "A cylinder is one of the run's tables; a slanted box, a table loaded into the dataset (a file, or the "
              "deploy's name model). An arrow says that the stage it names writes its end from its start: a "
              "statement names the one to write the other, even one a build has just emptied. The temporary tables, "
              "views and WITHs between them are folded into the arrow. Not drawn: a table's reads of its own rows, "
              "report.sql (it writes only temporary report_ tables, which report.txt reads), and `method`, which "
              "the procedure writes after a build and checks first in every other job.", ""]
    for job in JOBS:
        stages = ", ".join(stage for stage, _ in JOBS[job])
        parts += [f"### {job}", "", f"Stages: {stages}.", "", diagram(job), ""]
    return "\n".join(parts)


def main() -> int:
    OUT.write_text(page(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: " + ", ".join(f"{job} {len(edges(job))} arrows" for job in JOBS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
