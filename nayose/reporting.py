"""report.txt: the run on a page, with no record's value in it, from report.sql's tables.

    report(engine, steps, job)        run report.sql after a build or an update, and return report.txt
    report_text(engine, steps, job)   report.txt from report.sql's tables (deploy/run.py, after a BigQuery procedure)

The package names both too (nayose.report, nayose.report_text), as report.sql and deploy/run.py call them.
"""
import json
import math
import platform
import re
import subprocess
from collections.abc import Callable
from datetime import datetime

import duckdb
import pandas as pd

import nayose
from nayose import BLANK, COMPARISONS, FIELDS, HERE, Engine


def report(engine: Engine, steps: dict[str, float], job: str) -> str:
    """Run report.sql on `engine`, after a build or an update, and return report.txt (report_text)."""
    nayose.stage(engine, "report", **nayose.values_of("report"))
    return report_text(engine, steps, job)


def report_text(engine: Engine, steps: dict[str, float], job: str) -> str:
    """Return report.txt from report.sql's tables: the run on a page, with no record's value in it.

    `steps` holds each stage's seconds. The page has a section each: what ran, the summary, each field's fill and look,
    the input's columns no field reads, the batch's candidates by points and each band's commonest patterns, the
    entities' sizes, each stage, each generator's pairs, the model and the largest blocks. O(F + C) over the report's
    tables.
    """
    c, values = nayose.config(), nayose.values_of("report")
    counts = engine.frame("SELECT * FROM report_counts").iloc[0]
    added = None if job == "build" else int(counts["added"])
    fill = {f: counts[f] / max(counts["records"], 1) for f in FIELDS}
    generators = engine.frame("SELECT * FROM report_generators ORDER BY pairs DESC, g")
    notes = json.loads(engine.value("SELECT notes FROM fit"))
    sections = [report_header(engine, steps, added), report_summary(engine, c, counts, added, fill),
                report_fields(engine, fill), report_unmapped(engine, c, json.loads(values["looks"])),
                report_scores(engine, values["edges"]),
                report_patterns(engine, values["floor"], values["patterns_shown"]),
                report_entities(engine), report_steps(counts, notes, steps, job), report_generators(generators),
                report_model(engine, c, notes), report_blocks(generators, counts)]
    return "\n".join(line for section in sections for line in section) + "\n"


def number(x) -> str:
    """Return a count as people read it, with thousands separated: 12,345."""
    return f"{int(x):,}"


def number_of(counts) -> Callable[[str], str]:
    """Return n(column): that column of report.sql's report_counts as people read it (number)."""
    return lambda column: number(counts[column])


def percent(x) -> str:
    """Return a share as report.txt prints it, or a dash where there is none."""
    return "—" if x is None or pd.isna(x) else f"{x:.1%}"


def text_table(df: pd.DataFrame) -> list[str]:
    """Return `df` as the lines of a plain-text table: numbers right-aligned, text left, so the page stays narrow."""
    if not len(df):
        return ["  none"]
    rows = [list(map(str, df.columns)), *([str(v) for v in r] for r in df.itertuples(index=False))]
    columns = range(len(df.columns))
    width = [max(len(r[i]) for r in rows) for i in columns]
    numeric = [all(re.fullmatch(r"[-+]?[\d,.]+(%|e[-+]\d+)?|—", r[i]) for r in rows[1:]) for i in columns]
    return ["  " + "  ".join(v.rjust(w) if right else v.ljust(w) for v, w, right in zip(r, width, numeric)).rstrip()
            for r in rows]


def report_header(engine: Engine, steps: dict[str, float], added: int | None) -> list[str]:
    """Return the report's first lines: when, what ran, the code, the machine and the time taken."""
    if engine.name == "duckdb":
        threads, memory = engine.rows("SELECT current_setting('threads'), current_setting('memory_limit')")[0]
    else:
        threads, memory = "—", "—"
    run = "build" if added is None else f"update of {added:,} new records"
    machine = f"{platform.system()} {platform.machine()}"
    return [f"RUN REPORT · {datetime.now():%Y-%m-%d %H:%M} · {run} · no record's value in it",
            f"code {code_version()} · method {nayose.fingerprint()[:12]}",
            f"python {platform.python_version()} · duckdb {duckdb.__version__} · {machine}",
            f"{threads} threads · memory limit {memory} · took {sum(steps.values()):,.1f} s", ""]


def report_summary(engine: Engine, c: dict, counts, added: int | None, fill: dict) -> list[str]:
    """Return the SUMMARY section: records, pairs scored, entities, kinds, and notes on placeholders and empty
    fields."""
    n = number_of(counts)
    placeholders = engine.rows("SELECT p.field, COUNT(*) FROM placeholders AS p GROUP BY p.field ORDER BY p.field")
    without = {f: int(counts["records"] - counts[f]) for f, _ in placeholders if f in counts}
    records_line = n("records") + (f", {added:,} of them new" if added is not None else "")
    if counts["set_aside"]:
        records_line += f"; {n('set_aside')} set aside (set_aside)"
    in_batch = " in this batch" if added is not None else ""
    section = c["records"]
    summary = [
        ("records", records_line),
        ("scored", f"{n('scored')} pairs scored{in_batch}, {n('ruled')} of them a rule's too: "
                   "scored, which a match run reads at its threshold (python -m nayose match)"),
        ("entities", f"{n('entities')}; {n('by_people')} records joined by people's decisions; "
                     f"the largest holds {n('largest')} record{'s' * bool(counts['largest'] != 1)}"),
        ("kinds", f"{n('companies')} × 2 company · {n('persons')} × 1 person · "
                  f"{n('unsure')} × 0 not sure (records)"),
        ("kinds", f"{n('company_entities')} × 2 company · {n('person_entities')} × 1 person · "
                  f"{n('unsure_entities')} × 0 not sure (entities)"),
    ]
    if counts["flagged"]:
        summary.append(("flagged", f"{n('flagged')} records the engine is sure of against the flag: "
                                   "matched as the engine says (gold: kind_flagged)"))
    summary.append(("kinds from", "the file's flag, as it is (trust_flag)" if section["trust_flag"]
                    else f"a written legal form, or a name {section['name_line']:.0%} sure; else the flag"))
    summary += [("note", placeholder_note(f, k, without[f], section["placeholder_min"]))
                for f, k in placeholders if f in without]
    summary += [("note", f"{f} only {x:.1%} filled: check its mapping") for f, x in fill.items() if x < 0.05]
    return ["SUMMARY", *(f"  {what:<12} {value}" for what, value in summary), ""]


def placeholder_note(field: str, count: int, without: int, placeholder_min: int) -> str:
    """Return the SUMMARY's note on a field's `count` placeholders, and the records `without` a value since."""
    owner = "one entity" if field == "customer_id" else "evidence"
    return (f"{field}: {count:,} value{'s' * bool(count != 1)} held by {placeholder_min}+ records read as missing, "
            f"a placeholder and not {owner}'s ({without:,} records without one)")


def report_fields(engine: Engine, fill: dict) -> list[str]:
    """Return the FIELDS section: each field's fill, and how its values look on a sample."""
    shape = engine.frame("SELECT * FROM report_fields").set_index("field")
    rows = []
    for f in FIELDS:
        length, longest = shape.at[f, "length"], shape.at[f, "longest"]
        rows.append(dict(field=f, filled=percent(fill[f]), looks_right=percent(shape.at[f, "looks_right"]),
                         top_value=percent(shape.at[f, "top_value"]), no_letters=percent(shape.at[f, "no_letters"]),
                         length="" if pd.isna(length) else f"{length:.0f}",
                         longest="" if pd.isna(longest) else number(longest)))
    sample = int(nayose.config()["report"]["sample_records"])
    return [f"FIELDS  (looks right, top value, no letters, length: on a sample of {sample:,} records)",
            *text_table(pd.DataFrame(rows)), ""]


def report_unmapped(engine: Engine, c: dict, looks: dict[str, str]) -> list[str]:
    """Return the COLUMNS NOT MAPPED section, on DuckDB only, where the input's own columns can be read by name."""
    columns = unmapped(engine, c, looks) if engine.name == "duckdb" else None
    if columns is None or not len(columns):
        return []
    shown = columns.head(30)
    share = [percent(x) if f else "" for f, x in zip(shown["looks_like"], shown["share"])]
    table = pd.DataFrame(dict(column=shown["column"], filled=shown["filled"].map(percent),
                              distinct=shown["distinct"].map(percent), looks_like=shown["looks_like"], share=share))
    more = [f"  and {len(columns) - len(shown):,} more"] if len(columns) > len(shown) else []
    return ["COLUMNS NOT MAPPED  (no field reads them; filled, distinct and the field their values look most like: "
            f"on the first {int(c['report']['sample_records']):,} records)", *text_table(table), *more, ""]


def report_scores(engine: Engine, edges: list[float]) -> list[str]:
    """Return the SCORES section: the candidates scored, by bands of points between `edges`."""
    scored = dict(engine.rows("SELECT band, pairs FROM report_scores"))

    def label(i: int) -> str:
        if i == -1:
            return "below 0"
        if i == 0:
            return f"below {edges[0]:g}"
        if i == len(edges):
            return f"{edges[-1]:g} and up"
        return f"{edges[i - 1]:g} to {edges[i]:g}"

    rows = [dict(points=label(i), candidates=f"{scored[i]:,}") for i in sorted(scored) if scored[i]]
    return ["SCORES  (the candidates scored, by points)", *text_table(pd.DataFrame(rows)), ""]


def report_patterns(engine: Engine, floor: float, shown: int) -> list[str]:
    """Return the PATTERNS BY SCORE section: each band's `shown` most common patterns of levels, below and from
    `floor`."""
    label_of = {(comparison, gamma): label
                for comparison, gamma, label in engine.rows("SELECT comparison, gamma, label FROM model")}
    patterns = engine.frame("SELECT * FROM report_patterns ORDER BY up DESC, nth")

    def band(up: bool) -> str:
        return f"{floor:g} and up" if up else f"0 to {floor:g}"

    def level(x, k: str) -> str:
        gamma = x[f"gamma_{k}"]
        return "missing" if pd.isna(gamma) or gamma < 0 else label_of[k, int(gamma)]

    rows = [dict(band=band(x["up"]), pairs=number(x["n"]), points=f"{x['mean_points']:.1f}",
                 **{k: level(x, k) for k in COMPARISONS}) for _, x in patterns.iterrows()]
    more = []  # a band with more than the patterns shown: how many more, and their pairs
    for up, band_rows in patterns.groupby("up", sort=False):
        if band_rows["patterns"].iloc[0] > shown:
            pairs = int(band_rows["total"].iloc[0]) - int(band_rows["n"].sum())
            more.append(f"  {band(up)}: {int(band_rows['patterns'].iloc[0]) - shown:,} patterns more, {pairs:,} pairs")
    return ["PATTERNS BY SCORE  (the keys' pairs at 0 points and up, below and from the review floor: "
            f"each band's {shown} most common levels)", *text_table(pd.DataFrame(rows)), *more, ""]


def report_entities(engine: Engine) -> list[str]:
    """Return the ENTITIES section: how many entities hold each number of records."""
    sizes = dict(engine.rows("SELECT size, entities FROM report_entities"))
    bins = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5–9", 5, 9), ("10–49", 10, 49),
            ("50+", 50, math.inf)]
    counted = []
    for name, low, high in bins:
        if total := sum(v for k, v in sizes.items() if low <= k <= high):
            counted.append(f"{name}: {total:,}")
    return ["ENTITIES  (size: how many)", "  " + " · ".join(counted), ""]


def report_steps(counts, notes: dict, steps: dict[str, float], job: str) -> list[str]:
    """Return the STEPS section: each stage's seconds, with what it made."""
    n = number_of(counts)
    facts = dict(
        records=f"added {n('added')} · set_aside {n('set_aside')} · companies {n('companies')} · "
                f"persons {n('persons')} · not sure {n('unsure')}",
        fit=f"fit_records {notes['fit_records']:,}",
        score=f"candidates {n('candidates')} · scored {n('scored')} · rule pairs {n('ruled')} · "
              f"oversized_joined {n('oversized_joined')} · oversized_skipped {n('oversized_skipped')}",
        decide=f"decided {n('decided')} · entities {n('entities')}")
    rows = [dict(step=s, seconds=f"{x:.2f}", facts=facts.get(s, "")) for s, x in steps.items()]
    return ["STEPS", *text_table(pd.DataFrame(rows)), ""]


def report_generators(generators: pd.DataFrame) -> list[str]:
    """Return the GENERATORS section: the pairs each generator's keys list, most first."""
    table = pd.DataFrame(dict(generator=generators["name"], pairs=generators["pairs"].map(number)))
    return ["GENERATORS  (pairs each lists, most first)", *text_table(table), ""]


def report_model(engine: Engine, c: dict, notes: dict) -> list[str]:
    """Return the MODEL section: the prior, what EM learned from, and each level's m, u and bits."""
    fit_row = engine.frame("SELECT * FROM fit").iloc[0]
    levels = engine.frame("SELECT comparison, label, file_m, file_u, bits FROM model ORDER BY position, gamma DESC")
    prior = json.loads(fit_row["fitted"])["prior_bits"]
    skipped = f"; learned nothing about {', '.join(notes['skipped'])}" if notes.get("skipped") else ""
    head = (f"MODEL  (prior {prior:.2f} bits at the build's {number(fit_row['records'])} records; "
            f"fitted on {number(fit_row['fit_records'])} records{skipped})")
    grown = engine.value("SELECT COUNT(*) FROM records") / max(int(fit_row["records"]), 1) - 1
    if grown >= float(c["fit"]["rebuild_after"]):  # a pair drifts k·log2(1 + grown) bits: k exact levels
        head += f"\n  the run has grown {grown:.0%} since its build, whose u it scores with: build again"
    em = []
    if notes.get("em_pairs"):
        em.append("  EM learned from: " + " · ".join(f"{k} {v:,} pairs" for k, v in notes["em_pairs"].items()))
    table = pd.DataFrame(dict(comparison=levels["comparison"], level=levels["label"],
                              m=levels["file_m"].map(lambda x: f"{x:.4f}" if x >= 1e-3 else f"{x:.2e}"),
                              u=levels["file_u"].map(lambda x: f"{x:.2e}"),
                              bits=levels["bits"].map(lambda x: f"{x:.2f}")))
    adjusted = [f"  {k} {lv}: {why} (EM said {was:+.2f} bits)" for k, lv, why, was in notes.get("file_adjusted", [])]
    return [head, *em, *text_table(table), *adjusted, ""]


def report_blocks(generators: pd.DataFrame, counts) -> list[str]:
    """Return the BLOCKS section: the generators with oversized blocks, and the six that list the most pairs a
    record."""
    blocks = generators.assign(per_record=generators["pairs"] / max(int(counts["records"]), 1))
    busiest = blocks.nlargest(6, "per_record")["name"]
    shown = blocks[(blocks["oversized"] > 0) | blocks["name"].isin(busiest)]
    shown = shown.sort_values("per_record", ascending=False, kind="stable")
    table = pd.DataFrame(dict(generator=shown["name"], per_record=shown["per_record"].map(lambda x: f"{x:.2f}"),
                              largest=shown["largest"].map(number), oversized=shown["oversized"].map(number)))
    return [f"BLOCKS  ({number(generators['pairs'].sum())} pairs the generators' keys list, before dedupe)",
            *text_table(table)]


def unmapped(engine: Engine, c: dict, looks: dict[str, str]) -> pd.DataFrame | None:
    """Return the input's columns that no field reads (config.toml's [input] columns), on its first rows.

    For each column: the share filled, the share of filled values held once, and the field whose look ([report.looks])
    its values have most, with that share; best fit first. DuckDB only: it reads the file's own columns by
    their names. O(sample · columns · fields).
    """
    read = {x.casefold() for x in c["input"]["columns"]}
    columns = [x for x, _ in engine.columns("input") if x.casefold() not in read]
    if not columns:
        return None

    def quote(x: str) -> str:
        return '"' + x.replace('"', '""') + '"'

    con = engine.con
    cast = ", ".join(f"CAST({quote(x)} AS VARCHAR) AS {quote(x)}" for x in columns)
    sample = int(c["report"]["sample_records"])
    con.execute(f"CREATE OR REPLACE TEMP TABLE nayose_sample AS SELECT {cast} FROM input LIMIT {sample}")
    n = max(1, con.execute("SELECT COUNT(*) FROM nayose_sample").fetchall()[0][0])
    filled = "SELECT * FROM (UNPIVOT nayose_sample ON COLUMNS(*) INTO NAME c VALUE v) WHERE trim(v, ?) <> ''"
    counted = con.execute(f"SELECT c, COUNT(*), COUNT(DISTINCT v) FROM ({filled}) GROUP BY c", [BLANK]).fetchall()
    shape = {x: (k / n, d / max(1, k)) for x, k, d in counted}
    fits = {x: {} for x in columns}
    for field, pattern in looks.items():
        matched = con.execute(f"SELECT c, AVG(regexp_matches(v, ?)::INT) FROM ({filled}) GROUP BY c", [pattern, BLANK])
        for x, share in matched.fetchall():
            fits[x][field] = share
    best = {x: max(fits[x].items(), key=lambda kv: kv[1], default=("", 0.0)) for x in columns}
    rows = [dict(column=x, filled=shape.get(x, (0.0, 0.0))[0], distinct=shape.get(x, (0.0, 0.0))[1],
                 looks_like=best[x][0] if best[x][1] > 0 else "", share=best[x][1]) for x in columns]
    return pd.DataFrame(rows).sort_values(["share", "filled"], ascending=False, kind="stable", ignore_index=True)


def code_version() -> str:
    """Return the commit the code is at, with a + when this copy's tracked files differ from it."""
    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, text=True, timeout=10)
        return done.stdout.strip()

    try:
        head, dirty = git("rev-parse", "--short", "HEAD"), git("status", "--porcelain", "--untracked-files=no")
        return (head or "unknown") + ("+" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"
