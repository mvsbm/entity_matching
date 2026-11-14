"""The reports for people, from a run's tables (er.run.Run): qa (the label-free checks, and the summary in words),
fill_rates, review_sheet (scored pairs as people judge them), carry_over (the open review queue across increments) and
report_text (the run on a page with no record's value in it). Run.report builds them; Run.write stages them with the
run's files. From a written workspace: describe_workspace (what it holds), describe_entity (one record's entity) and
describe_matching (the pipeline as a graph, with the run's numbers).
"""
import json
import math
import platform
import re
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd

from er.config import COPIES, DeletionKeys, InputError, Key, KeyBlocker, Pipeline, SortedNeighbourhood, TfidfNeighbours, bits, lit, q, sources_text
from er.folder import PENDING, history, latest_decisions, method, rounds, runs
from er.io import code_version, read_parquet, table_after
from er.kind import COMPANY, PERSON, SAYS, UNSURE, sheet_parts
from er.match import ELSE, levels, named_sql, parameters, pattern_coverage, review_floor, scaled_prior
from er.review_state import applied, read, trust_state

if TYPE_CHECKING:
    from er.run import Run
    from er.settings import Settings


def fill_rates(run: "Run", fields: list[str] | None = None, sample: int = 10_000) -> pd.DataFrame:
    """Each field's share of filled records, flagged under 5%: a field almost never filled is often a mapping mistake.
    Then, on a random sample of `sample` records, the share of filled values that look like the field ([locale.detect];
    a low share is a wrong column or a format the comparisons don't expect), the share held by its most common
    value (a placeholder such as 0000 counts as an agreement between the records that hold it), the share with no
    letter or digit (a placeholder such as ＊ or ---), and its values' mean and longest length (a comparison's cost grows
    with both lengths). Numbers only: no value. O(N·F + sample·F)."""
    cols = run.columns()
    fs = [f for f in (run.fields if fields is None else fields) if f in cols]
    if not fs:
        return pd.DataFrame(columns=["field", "filled", "looks_right", "top_value", "no_letters", "length", "longest", "flag"])
    filled = run.con.execute(f"SELECT {', '.join(f'avg(({q(f)} IS NOT NULL)::INT)' for f in fs)} FROM records").fetchall()[0]
    run.con.execute(f"CREATE OR REPLACE TEMP TABLE er_fill_sample AS SELECT {', '.join(f'{q(f)}::VARCHAR AS {q(f)}' for f in fs)} "
                    f"FROM records ORDER BY hash({q(run.uid)}) LIMIT {sample}")  # by ID: the same sample whatever the rows' order
    pattern = {f: run.settings.detect[f] for f in fs if f in run.settings.detect}
    looks = dict(zip(pattern, run.con.execute("SELECT " + ", ".join(f"avg(regexp_matches({q(f)}, {lit(p)})::INT)" for f, p in pattern.items())
                                              + " FROM er_fill_sample").fetchall()[0])) if pattern else {}
    top = dict(run.con.execute("""SELECT field, max(n) / sum(n) FROM (SELECT field, v, count(*) AS n FROM
        (UNPIVOT er_fill_sample ON COLUMNS(*) INTO NAME field VALUE v) GROUP BY ALL) GROUP BY field""").fetchall())
    shape = run.con.execute("SELECT " + ", ".join(f"avg((NOT regexp_matches({q(f)}, '[\\pL\\pN]'))::INT), avg(length({q(f)})), max(length({q(f)}))" for f in fs)
                            + " FROM er_fill_sample").fetchall()[0]
    return pd.DataFrame(dict(field=fs, filled=filled, looks_right=[looks.get(f) for f in fs], top_value=[top.get(f) for f in fs],
                             no_letters=shape[0::3], length=shape[1::3], longest=shape[2::3])).assign(
        flag=lambda d: np.where(d["filled"] < 0.05, "under 5%", ""))


def qa(run: "Run", fields: list[str] | None = None, review: int = 50, previous: Path | None = None) -> dict[str, pd.DataFrame]:
    """The label-free report of a run: a summary in words (records, entities, who joined them, the model's links and the
    false ones it expects among them, what to decide, what the loader fixed), fill rate per field (flagged under 5%)
    (of `fields`, by default every logical field) with the share that looks like the field and the share of its most common value, what was disabled, every step's cost,
    accepted pairs by weight band, cluster sizes, the largest clusters (the over-merge alarm), and the review sheet
    for people (review_sheet). Its rows are of two kinds. "decide": every pair of clusters whose best link scored in the
    threshold's safety margin [review_floor, min_match_weight), or above it with no name compared, not decided yet, best link first. "audit": accepted pairs
    up to 4 bits above the threshold not decided yet, `review` of them, stratified by 1-bit band. `previous`, the workspace's sheet
    before an increment: its open rows stay (carry_over), since the scores behind them aren't kept."""
    con, u, t = run.con, q(run.uid), run.pipeline.fs.min_match_weight
    fill = fill_rates(run, fields)
    l, r, lo = q(run.l), q(run.r), review_floor(run.pipeline)
    bands = con.sql(f"""SELECT floor(s.match_weight / 2) * 2 AS weight_from, count(*) AS pairs, count(m.{l}) AS accepted
                        FROM scores s LEFT JOIN matches m USING ({l}, {r}) GROUP BY 1 ORDER BY 1""").df()
    sizes = con.sql("SELECT n AS cluster_size, count(*) AS clusters FROM (SELECT count(*) AS n FROM gold GROUP BY cluster_id) GROUP BY 1 ORDER BY 1").df()
    largest = con.sql("SELECT cluster_id, count(*) AS records FROM gold GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10").df()
    con.execute(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
    if run.pipeline.trust.line is not None:  # with a trust line: the next range's sample, and spot-checks above the line
        decide, audit = trust_sheet(run, previous.parent if previous is not None else None)
        lo, t = run.pipeline.trust.below() or (run.pipeline.trust.line, run.pipeline.trust.line)
    else:
        decide = con.sql(f"""SELECT * EXCLUDE (k1, k2) FROM (
                SELECT s.*, c.sources, least(ga.cluster_id, gb.cluster_id) AS k1, greatest(ga.cluster_id, gb.cluster_id) AS k2
                FROM scores s JOIN cands c USING ({l}, {r}) JOIN gold ga ON ga.{u} = s.{l} JOIN gold gb ON gb.{u} = s.{r}
                WHERE s.match_weight >= {lo} AND (s.match_weight < {t} OR NOT {named_sql(run.pipeline.fs)}) AND ga.cluster_id <> gb.cluster_id
                  AND NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = s.{l} AND d.{r} = s.{r}))
            QUALIFY row_number() OVER (PARTITION BY k1, k2 ORDER BY match_weight DESC, {l}, {r}) = 1
            ORDER BY match_weight DESC, {l}, {r}""").df().assign(why="decide")
        audit = con.sql(f"""SELECT * EXCLUDE (k) FROM (SELECT s.*, m.sources, row_number() OVER (PARTITION BY floor(s.match_weight) ORDER BY hash(s.{l}, s.{r})) AS k
                            FROM matches m JOIN scores s USING ({l}, {r}) WHERE s.match_weight < {t + 4}
                              AND NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = s.{l} AND d.{r} = s.{r}))
                            WHERE k <= {max(1, review // 4)} ORDER BY match_weight, {l}, {r}""").df().assign(why="audit")
    steps = pd.DataFrame(run.steps)
    base = ["step", "big_o", "filled", "seconds", "peak_memory_gb"]
    number = lambda v: isinstance(v, int | float) and not isinstance(v, bool) and not math.isnan(v)  # a list (generators) is no fact
    steps = steps[base].assign(facts=steps.drop(columns=base).apply(lambda r: " · ".join(
        f"{k} {v:,.0f}" if float(v).is_integer() else f"{k} {v:,.2f}" for k, v in r.items() if number(v)), axis=1))
    coverage = pattern_coverage(run.pipeline.fs, run.scoring, run.n)
    sheet = review_sheet(run, pd.concat([decide, audit], ignore_index=True))
    if previous is not None and previous.exists():
        sheet = carry_over(run, read_parquet(previous), sheet, previous.parent)
    decide = sheet[sheet["why"] == "decide"]
    queue = pd.DataFrame(dict(why=["decide", "audit"], pairs=[len(decide), len(audit)], from_bits=[lo, t], below_bits=[t, t + 4]))
    queue = queue.replace([math.inf, -math.inf], None)  # no trust line yet: the range from the top step up
    fs, aside = run.pipeline.fs, run.con.execute("SELECT count(*) FROM set_aside").fetchall()[0][0]
    total, entities, biggest, by_rules, by_model, by_people = con.execute(f"""SELECT count(*), count(DISTINCT cluster_id), max(n),
        count(*) FILTER (WHERE resolved_stage = '{fs.previous_stage}'), count(*) FILTER (WHERE resolved_stage = '{fs.stage}'),
        count(*) FILTER (WHERE resolved_stage = 'review') FROM gold JOIN (SELECT cluster_id, count(*) AS n FROM gold GROUP BY 1) USING (cluster_id)""").fetchall()[0]
    linked = next(x for x in reversed(run.steps) if x["step"] == "cluster")
    kinds, mixed, kind_rows = pd.DataFrame(), pd.DataFrame(), []
    if "kind" in con.sql("DESCRIBE gold").df()["column_name"].tolist():
        kinds = con.sql("""SELECT 'records' AS of, kind, count(*) AS how_many FROM gold GROUP BY ALL
                           UNION ALL SELECT 'customers', customer_kind, count(DISTINCT cluster_id) FROM gold GROUP BY ALL ORDER BY ALL""").df()
        mixed = con.sql("""SELECT cluster_id, count(*) AS records, count(*) FILTER (WHERE kind = 2) AS companies,
                                  count(*) FILTER (WHERE kind = 1) AS persons FROM gold GROUP BY 1
                           HAVING companies > 0 AND persons > 0 ORDER BY records DESC, cluster_id""").df()
        n = {(x.of, x.kind): x.how_many for x in kinds.itertuples()}
        kind_rows = [("kinds", " · ".join(f"{n.get((of, k), 0):,} × {SAYS[k]}" for k in (COMPANY, PERSON, UNSURE)) + f" ({of})")
                     for of in ("records", "customers")]
        c = run.classifier
        if c is not None and c.spec.trust_flag:
            how = "the file's flag, as it is (trust_flag)"
        elif c is not None and (f := c.fitted) is not None:
            side = lambda line, at: at if line <= 1 else "never (no line holds its budget)"
            how = (f"{c.labels:,} answers ({c.measured:,} drawn to measure): company {side(f.line_company, f'at P ≥ {f.line_company:g}')}, "
                   f"person {side(f.line_person, f'at P ≤ {1 - f.line_person:.4g}, its labelled error {f.person_error:.2%}' if f.person_error is not None else '')}")
        else:  # no line placed: a written legal form, or a name the model is sure of
            how = ((f"{c.labels:,} answers, {c.measured:,} of them drawn to measure: a line needs 50 drawn to measure, of both kinds"
                    if c is not None and c.labels else "no answers yet")
                   + (f"; the engine's own: a written legal form, or a name {c.spec.name_line:.0%} sure; else the flag" if c is not None else ""))
        if c is not None and c.decided:
            how += f"; people decided {len(c.decided):,} records"
        flagged, unknown = con.execute("SELECT count(*) FILTER (WHERE kind_flagged), count(*) FILTER (WHERE kind_held AND kind_by = 'people') FROM gold").fetchall()[0]  # held by the engine: a record an older run held
        if flagged:
            kind_rows.append(("flagged", f"{flagged:,} records the engine is sure of against the flag: matched as the engine says; "
                                         "answer them in kind_review.parquet if you want, surest first"))
        if unknown:
            kind_rows.append(("held back", f"{unknown:,} records people can't tell: their names stay out of matching, and their pairs come to review.parquet"))
        if c is not None and c.flag_error is not None:
            how += f"; the flag wrong on {c.flag_error:.1%} of {c.flag_checked:,} answers drawn at random"
        kind_rows += [("kinds from", how)] if c is not None else []
        if c is not None and not c.spec.trust_flag and "kind_flag" in run.columns():  # the flag's likely errors, for its owners
            says = "x.kind_flag IN (" + ", ".join(map(lit, c.flag_company)) + ")"
            a, b = con.execute(f"""SELECT count(*) FILTER (WHERE g.kind = 2 AND NOT {says}), count(*) FILTER (WHERE g.kind = 1 AND {says})
                                   FROM gold g JOIN records x USING ({u}) WHERE x.kind_flag IS NOT NULL""").fetchall()[0]
            kind_rows.append(("flag", f"a kind the engine or people are sure of contradicts it on {a + b:,} records: {a:,} 2 company flagged 1, "
                                      f"{b:,} 1 person flagged 2"))
        if len(mixed):
            kind_rows.append(("note", f"{len(mixed):,} cluster{'s hold' if len(mixed) > 1 else ' holds'} a sure person and a sure company: see qa.md, mixed kinds"))
    probed = next((x["strata"] for x in reversed(run.steps) if x["step"] == "probe"), [])  # er.probe: counts only
    apart = con.execute(f"""SELECT count(*) FROM er_decisions d JOIN gold a ON a.{u} = d.{q(run.l)} JOIN gold b ON b.{u} = d.{q(run.r)}
        WHERE d.decision = 'no_match' AND a.cluster_id = b.cluster_id""").fetchall()[0][0]  # kept apart, joined by others
    summary = pd.DataFrame([
        ("records", f"{total:,}" + (f", {run.added:,} of them new" if run.added is not None else "") + (f"; {aside:,} set aside (set_aside/)" if aside else "")),
        ("entities", f"{entities:,}; the largest holds {biggest:,} record{'s' * (biggest != 1)}"),
        ("joined by", f"the rules {by_rules:,} · the model {by_model:,} · people {by_people:,} records"),
        ("model links", f"{linked['accepted']:,}{' in this batch' if run.added is not None else ''}; about {linked['expected_false']:,.{1 if linked['expected_false'] >= 1 else 2}f} "
                        "of them false, as the model expects (the sum of 1 − match probability)"),
        ("to decide", f"{len(decide):,} pair{'' if len(decide) == 1 else 's'} in review.parquet (why = decide)"),
        *(("missed", f"about {x['missed']:,} matches the method missed ({x['low']:,}–{x['high']:,}) among pairs that share {' + '.join(x['fields'])}: "
                     f"{x['hits']:,} found in {x['scored']:,} of its {x['pairs']:,} pairs, scored" + (f"; {x['between_rules']:,} of them between two entities the rules formed (bridge off)"
                     if x["between_rules"] else "")) for x in probed),
        *kind_rows,
        *([("note", f"{apart:,} pair{'s' if apart > 1 else ''} people called different {'are' if apart > 1 else 'is'} in one entity through other links: "
                    "see it with describe entity, part it with split entity")] if apart else []),
        *(("note", f"{f} only {x:.1%} filled: check its mapping") for f, x in fill.loc[fill["flag"] != "", ["field", "filled"]].itertuples(index=False)),
        *(("note", f"turned off, a field it reads is missing: {d}") for d in run.disabled),
        *(("note", note) for note in run.notes),
        *(("example", x) for x in run.examples)], columns=["what", "value"])
    return dict(summary=summary, fill=fill, disabled=pd.DataFrame({"disabled": run.disabled}), steps=steps, weight_bands=bands,
                cluster_sizes=sizes, largest_clusters=largest, patterns_without_a_key=coverage.head(20), review=queue,
                kinds=kinds, mixed_kinds=mixed,
                oversized_blocks=run.gated,
                review_sheet=sheet)


def report_text(run: "Run", tables: dict[str, pd.DataFrame], pipeline: Path) -> str:
    """The run on a page of plain text that holds no record's value (no ID, name, phone or address: the notes that
    quote one are run.examples, in qa.md only), so it can leave the machine that holds the records. `tables` is qa()'s.
    It shows what ran (the code, the tracked files changed in this copy, the pipeline, the machine's limits), the
    summary, each field's fill and shape, scores and accepted links by weight with the false links the model expects,
    cluster sizes, each step's time and memory, its time in each string comparison, the model (the prior, and m, u and bits per level), the costliest
    blocks, and the patterns no key pairs. O(C + E) over scores and matches."""
    con, fs = run.con, run.pipeline.fs
    t, lo = fs.min_match_weight, review_floor(run.pipeline)

    def table(df: pd.DataFrame) -> list[str]:  # numbers right-aligned, text left, so the page stays narrow
        if not len(df):
            return ["  none"]
        rows = [list(map(str, df.columns)), *([str(v) for v in r] for r in df.itertuples(index=False))]
        width = [max(len(r[i]) for r in rows) for i in range(len(df.columns))]
        number = [all(re.fullmatch(r"[-+]?[\d,.]+(%|e[-+]\d+)?|—", r[i]) for r in rows[1:]) for i in range(len(df.columns))]
        return ["  " + "  ".join(v.rjust(w) if n else v.ljust(w) for v, w, n in zip(r, width, number)).rstrip() for r in rows]

    def pct(x: object) -> str:
        return "—" if x is None or pd.isna(x) else f"{x:.1%}"

    code = code_version(run.settings.root)
    threads, memory = con.execute("SELECT current_setting('threads'), current_setting('memory_limit')").fetchall()[0]
    kind = "full run" if run.added is None else f"increment of {run.added:,} new records"
    out = [f"RUN REPORT · {datetime.now():%Y-%m-%d %H:%M} · {kind} · no record's value in it",
           f"code {code} · pipeline {pipeline.name}",
           f"python {platform.python_version()} · duckdb {duckdb.__version__} · splink {version('splink')} · {platform.system()} {platform.machine()}",
           f"{threads} threads · memory limit {memory} · spill room {run.spill_room() / 1e9:,.0f} GB · "
           f"took {sum(x['seconds'] for x in run.steps):,.1f} s · peak {max(x['peak_memory_gb'] for x in run.steps):.2f} GB", ""]

    summary = tables["summary"][tables["summary"]["what"] != "example"]
    out += ["SUMMARY", *(f"  {what:<12} {value}" for what, value in summary.itertuples(index=False)), ""]

    fill = tables["fill"]
    out += ["FIELDS  (looks right, top value, no letters, length: on a sample of 10,000 records)", *table(pd.DataFrame(dict(
        field=fill["field"], filled=fill["filled"].map(pct), looks_right=fill["looks_right"].map(pct), top_value=fill["top_value"].map(pct),
        no_letters=fill["no_letters"].map(pct), length=fill["length"].map(lambda x: "" if pd.isna(x) else f"{x:.0f}"),
        longest=fill["longest"].map(lambda x: "" if pd.isna(x) else f"{int(x):,}"), columns=[sources_text(run.present.get(f)) for f in fill["field"]]))), ""]

    edges = sorted({-20, -10, 0, lo, t, t + 2, t + 4, t + 8, t + 12})
    band = "CASE " + " ".join(f"WHEN match_weight < {b} THEN {i}" for i, b in enumerate(edges)) + f" ELSE {len(edges)} END"
    scored = dict(con.execute(f"SELECT {band}, count(*) FROM scores GROUP BY 1").fetchall())
    accepted = {k: (n, x) for k, n, x in con.execute(f"SELECT {band}, count(*), sum(1 - match_probability) FROM matches GROUP BY 1").fetchall()}
    label = lambda i: f"below {edges[0]:g}" if i == 0 else f"{edges[-1]:g} and up" if i == len(edges) else f"{edges[i - 1]:g} to {edges[i]:g}"
    if unscored := sum(x.get("unscored", 0) for x in run.steps if x["step"] == "score"):  # pairs a bound put below 0, never scored: one row below 0
        below = [i for i in scored if i < len(edges) and edges[i] <= 0]
        scored = {-1: sum(scored.pop(i) for i in below) + unscored, **scored}
        label = (lambda f: lambda i: "below 0" if i == -1 else f(i))(label)
    out += [f"SCORES  (bits; review from {lo:g}, accept from {t:g}; expected false = the sum of 1 − match probability)", *table(pd.DataFrame(
        [dict(bits=label(i), candidates=f"{scored[i]:,}", accepted=f"{accepted.get(i, (0, 0))[0]:,}", expected_false=f"{accepted.get(i, (0, 0))[1]:.2f}")
         for i in sorted(scored)])), ""]

    sizes = tables["cluster_sizes"]
    by = pd.cut(sizes["cluster_size"], [0, 1, 2, 3, 4, 9, 49, np.inf], labels=["1", "2", "3", "4", "5–9", "10–49", "50+"])
    out += ["CLUSTERS  (size: how many)", "  " + " · ".join(f"{k}: {v:,}" for k, v in sizes.groupby(by, observed=True)["clusters"].sum().items()), ""]

    steps = tables["steps"]
    out += ["STEPS", *table(steps[["step", "seconds", "peak_memory_gb", "facts"]].rename(columns={"peak_memory_gb": "peak_gb"})), ""]
    by_step = {x["step"]: x for x in run.steps}
    if g := by_step.get("gap"):  # what the keys lose against comparing every pair (er.keys.gap)
        out += [f"GAP  (pairs the model would accept that no key or rule lists; {g['sampled_records']:,} records sampled, each paired with every record "
                "that shares a value or a near one; about 95%)", *table(pd.DataFrame([dict(
                    bits=f"{x['bits']:g}+", pairs=f"{x['pairs']:,}", missed=f"{x['missed']:,}", interval=f"{x['missed_lo']:,}–{x['missed_hi']:,}")
                    for x in g["thresholds"]])),
                *(["  missed pairs agree on: " + " · ".join(f"{x['atom']} {x['pairs']:,}" for x in g["missed_agree"][:12])] if g["missed_agree"] else []), ""]
    if (c := by_step.get("candidates")) and c.get("generators"):  # where the candidates' time goes
        only = g.get("only", {}) if g else None  # the gap's sampled pairs at the floor no other key or rule lists, scaled
        out += [f"KEYS  (pairs each lists, seconds{'; only: pairs at the review floor no other key or rule lists, estimated from the gap' if only is not None else ''}; slowest first)",
                *table(pd.DataFrame([dict(key=x["name"], pairs=f"{x['pairs']:,}", seconds=f"{x['seconds']:.1f}", **({"only": f"{only.get(x['name'], 0):,}"} if only is not None else {}))
                                     for x in sorted(c["generators"], key=lambda x: -x["seconds"])])),
                *([f"  not run: {', '.join(k['dropped'])} (its agreement weighs nothing, and other keys list its pairs)"] if (k := by_step.get("keys")) and k.get("dropped") else []), ""]

    def row(x: dict, f: str, c: dict) -> dict:
        every = f == "all"
        return dict(step=x["step"], function="all of them" if every else f, wall=f"{c['wall']:,.2f}" if every else "",
                    share=pct(min(1, c["wall"] / x["seconds"])) if every and x["seconds"] else "", cpu=f"{c['cpu']:,.2f}",
                    cores=f"{c['cpu'] / c['wall']:,.1f}" if every and c["wall"] else "", values=f"{c['values']:,}",
                    per_call=f"{c['values'] / c['calls']:,.0f}", us_per_value=f"{1e6 * c['cpu'] / c['values']:,.2f}")
    spent = [row(x, f, c) for x in run.steps for f, c in sorted(x.get("compared", {}).items(), key=lambda fc: (fc[0] != "all", -fc[1]["cpu"]))
             if c["cpu"] >= 0.05 or (f == "all" and c["wall"] >= 0.01)]
    out += ["TIME IN COMPARISONS  (all of them: a step's wall seconds while any string function ran, its share of the step, and the cores "
            "they kept busy on average (Python runs one at a time: about 1 means the others waited); per function: its CPU seconds, "
            "from 0.05 s, the values it compared, per_call at a time, and CPU per value; the rest of a step is DuckDB's joins and sums, "
            "and the comparisons DuckDB makes itself)",
            *table(pd.DataFrame(spent)), ""]

    lam, m = scaled_prior(run.scoring, run.n), run.scoring["er"]
    params = parameters(run.scoring)
    out += [f"MODEL  (prior {math.log2(lam / (1 - lam)):.2f} bits at {run.n:,} records; fitted on {m['fit_rows']:,} records"
            + (f"; learned nothing about {', '.join(m['skipped'])}" if m.get("skipped") else "") + ")", *table(pd.DataFrame(dict(
                comparison=params["comparison"], level=params["level"], m=params["m"].map(lambda x: f"{x:.4f}" if x >= 1e-3 else f"{x:.2e}"),
                u=params["u"].map(lambda x: f"{x:.2e}"), bits=params["weight"].map(lambda x: f"{x:.2f}")))),
            *(f"  {c} {lv}: {why} (EM said {was:+.2f} bits)" for c, lv, why, was in m.get("adjusted", [])), ""]

    plan = getattr(run, "plan", None)  # the budget runs before a full run only
    if plan is not None:
        shown = plan[(plan["oversized_blocks"] > 0) | plan["name"].isin(plan.nlargest(6, "per_record")["name"])].sort_values("per_record", ascending=False)
        out += [f"BLOCKS  ({int(plan['est_pairs'].sum()):,} pairs before dedupe; room for {run.capacity():,})", *table(pd.DataFrame(dict(
            kind=shown["kind"], name=shown["name"], per_record=shown["per_record"].map(lambda x: f"{x:.2f}"),
            largest=shown["largest_block"].map(lambda x: f"{x:,}"), oversized=shown["oversized_blocks"].map(lambda x: f"{x:,}")))), ""]

    patterns = tables["patterns_without_a_key"].head(5)
    out += ["PATTERNS WITHOUT A KEY  (they reach the threshold, but no key is sure to pair them; share of matches, at most)",
            *table(patterns.assign(bits=patterns["bits"].map(lambda x: f"{x:.2f}"), share_of_matches=patterns["share_of_matches"].map(lambda x: f"{x:.3%}")))]
    return "\n".join(out) + "\n"


def trust_sheet(run: "Run", out: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """With a trust line: the next range's links (the rules' pairs and the model's named ones, from its next step down
    to the line) that people have not decided, in a fixed random order (hash), as many as `checks` less those of the
    range they decided already; once they found one of its links false, the line can't step past it, so its open
    links and every range's below go to people one by one instead, best first, `checks` at a time; and the model's
    pairs above its threshold with no name compared, which no line joins; and `watch` spot-checks of the links at the
    line or above. An increment (`out`, its workspace) counts the false pairs the workspace holds: its own links are
    the batch's. O(E)."""
    con, l, r, trust, u = run.con, q(run.l), q(run.r), run.pipeline.trust, q(run.uid)
    # once, those every question below reads (from the lowest step or the line up): each would join every scored pair again
    con.execute(f"""CREATE OR REPLACE TEMP TABLE er_trust_links AS SELECT * FROM (SELECT s.* EXCLUDE (named, keep) FROM ({run.scored()}) s WHERE s.named AND s.keep
                UNION ALL BY NAME SELECT x.*, k.rule AS sources FROM rule_kept k JOIN rule_scores x USING ({l}, {r}))
                QUALIFY row_number() OVER (PARTITION BY {l}, {r} ORDER BY sources) = 1 AND match_weight >= {bits(min((*trust.steps, trust.line)))}""")
    links = "SELECT * FROM er_trust_links"
    open_ = f"NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = x.{l} AND d.{r} = x.{r})"
    decide = pd.DataFrame()
    holds = lambda lo, hi: con.execute(f"SELECT count(*) > 0 FROM ({links}) x WHERE x.match_weight >= {bits(lo)} AND x.match_weight < {bits(hi)}").fetchall()[0][0]
    if (span := trust.below(holds)) is not None:
        within = f"x.match_weight >= {bits(span[0])} AND x.match_weight < {bits(span[1])}"
        done, false = con.execute(f"""SELECT count(*) FILTER (WHERE NOT {open_}), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM er_decisions d
            WHERE d.{l} = x.{l} AND d.{r} = x.{r} AND d.decision = 'no_match')) FROM ({links}) x WHERE {within}""").fetchall()[0]
        false = (trust_state(con, out, run.pipeline, run.uid) or {}).get("false", 0) if out is not None else false
        decide = con.sql(f"""SELECT x.* FROM ({links}) x JOIN gold ga ON ga.{u} = x.{l} JOIN gold gb ON gb.{u} = x.{r}
            WHERE x.match_weight >= {bits(min(trust.steps))} AND x.match_weight < {bits(span[1])} AND {open_} AND ga.cluster_id <> gb.cluster_id
            ORDER BY x.match_weight DESC, x.{l}, x.{r} LIMIT {trust.checks}""").df() if false else \
            con.sql(f"SELECT * FROM ({links}) x WHERE {within} AND {open_} ORDER BY hash(x.{l}, x.{r}) LIMIT {max(0, trust.checks - done)}").df()
    audit = con.sql(f"SELECT * FROM ({links}) x WHERE x.match_weight >= {bits(trust.line)} AND {open_} ORDER BY hash(x.{l}, x.{r}) LIMIT {trust.watch}").df()
    unnamed = con.sql(f"""SELECT * EXCLUDE (named, keep) FROM ({run.scored()}) x WHERE NOT x.named AND x.keep
        AND x.match_weight >= {run.pipeline.fs.min_match_weight} AND {open_} ORDER BY x.match_weight DESC, x.{l}, x.{r}""").df()  # no line joins them: people do
    con.execute("DROP TABLE er_trust_links")
    return pd.concat([decide, unnamed], ignore_index=True).assign(why="decide"), audit.assign(why="audit")


def carry_over(run: "Run", previous: pd.DataFrame, sheet: pd.DataFrame, out: Path, full: bool = False) -> pd.DataFrame:
    """The review queue across runs: the previous sheet's rows holding a decision typed in and not given back (one other
    than the pair's latest in decisions/: the sheet keeps what was applied), and, across increments, its decide rows
    nobody gave back whose records are still in different clusters; a full run (`full`) makes the rest again. Those
    rows as they were, with this run's other rows. O(previous rows)."""
    l, r, u = q(run.l), q(run.r), q(run.uid)
    prev = previous if "why" in previous else previous.iloc[:0]  # a sheet from before the queue: nothing to keep
    if prev.empty:
        return sheet
    run.con.register("er_prev", prev[[run.l, run.r, "decision", "why"]])
    run.con.register("er_stored", applied(out, run.uid)[[run.l, run.r, "decision"]].astype("string"))
    keep = run.con.execute(f"""SELECT p.{l}, p.{r} FROM er_prev p JOIN gold a ON a.{u} = p.{l} JOIN gold b ON b.{u} = p.{r}
        WHERE (p.decision IS NOT NULL OR ({'FALSE' if full else 'TRUE'} AND p.why = 'decide' AND a.cluster_id <> b.cluster_id))
          AND NOT EXISTS (SELECT 1 FROM er_stored d WHERE d.{l} = p.{l} AND d.{r} = p.{r} AND (p.decision IS NULL OR d.decision = p.decision))""").df()
    run.con.unregister("er_prev")
    run.con.unregister("er_stored")
    kept = prev.merge(keep, on=[run.l, run.r]).reindex(columns=sheet.columns)  # a column this run's sheet lacks goes, one it adds is empty
    both = pd.concat([sheet[~sheet.set_index([run.l, run.r]).index.isin(kept.set_index([run.l, run.r]).index)], kept], ignore_index=True)
    decide = both[both["why"] == "decide"].sort_values("match_weight", ascending=False, ignore_index=True)
    return pd.concat([decide, both[both["why"] != "decide"]], ignore_index=True)


def carry_kinds(run: "Run", sheet: pd.DataFrame, previous: Path) -> pd.DataFrame:
    """The person/company sheet a full run makes again, with the previous one's rows holding a kind typed in and not
    given back (none of run.labels) on records the run still holds, as they were; the rest new. O(sheet rows)."""
    old = read_parquet(previous) if previous.exists() else sheet.iloc[:0]
    typed = old[old["kind"].notna()] if "kind" in old else old.iloc[:0]
    if run.labels is not None:
        typed = typed[~typed[run.uid].astype("string").isin(run.labels[run.uid].astype("string"))]
    if typed.empty:
        return sheet
    run.con.register("er_typed", typed[[run.uid]].astype("string"))
    held = {x for (x,) in run.con.execute(f"SELECT {q(run.uid)} FROM records WHERE {q(run.uid)} IN (SELECT {q(run.uid)} FROM er_typed)").fetchall()}
    run.con.unregister("er_typed")
    typed = typed[typed[run.uid].astype("string").isin(held)].reindex(columns=sheet.columns)
    return pd.concat([sheet[~sheet[run.uid].astype("string").isin(typed[run.uid].astype("string"))], typed], ignore_index=True)


def households(con: duckdb.DuckDBPyConnection, records: str, pairs: str, uid: str, p: Pipeline) -> set[tuple[str, str]]:
    """The pairs of `pairs` (SQL: uid_l, uid_r) labelled maybe one household ([household]), read on `records` (SQL, the
    run's standardized records). O(pairs)."""
    have = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {records}").fetchall()}
    if (cond := p.household.sql(have)) == "FALSE":
        return set()
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    return set(con.execute(f"""SELECT x.{l}, x.{r} FROM ({pairs}) x JOIN {records} l ON l.{u} = x.{l} JOIN {records} r ON r.{u} = x.{r}
        WHERE {cond}""").fetchall())


def review_sheet(run: "Run", pairs: pd.DataFrame) -> pd.DataFrame:
    """Scored pairs as people judge them, in the order given: both records' compared fields side by side, and per
    comparison the level the pair landed in and the bits it earned, which with the prior sum to its weight; whether the
    run merged it (in kept: a rule's pair, the model's, or people's); whether it may be two people of one household
    (households); an empty `decision` for people to fill in (match or no_match) and give to Run.decide. O(pairs)."""
    comps, uid = run.pipeline.fs.model.comparisons, run.uid
    fields = [f for f in dict.fromkeys(col for c in comps for col in (*c.null_if_missing, *(x for lv in c.levels for x, _ in lv.any_of)))
              if f in run.columns()]
    run.con.register("er_review_ids", pd.DataFrame({uid: pd.concat([pairs[run.l], pairs[run.r]]).unique()}))
    records = run.con.sql(f"SELECT {', '.join(q(c) for c in [uid, *fields])} FROM records JOIN er_review_ids USING ({q(uid)})").df()
    run.con.unregister("er_review_ids")
    run.con.register("er_review_pairs", pairs[[run.l, run.r]])
    accepted = run.con.sql(f"""SELECT p.*, EXISTS (SELECT 1 FROM kept k WHERE k.{q(run.l)} = p.{q(run.l)} AND k.{q(run.r)} = p.{q(run.r)}) AS accepted
        FROM er_review_pairs p""").df()
    homes = households(run.con, "records", "SELECT * FROM er_review_pairs", uid, run.pipeline)
    run.con.unregister("er_review_pairs")
    accepted["household"] = [(a, b) in homes for a, b in zip(accepted[run.l], accepted[run.r])]
    out = pairs.merge(accepted, on=[run.l, run.r]).merge(records.add_suffix("_l"), on=run.l).merge(records.add_suffix("_r"), on=run.r)
    out["decision"] = pd.Series(pd.NA, index=out.index, dtype="string")
    by_gamma = levels(run.scoring)
    for c in comps:
        gamma = out.pop(f"gamma_{c.name}").astype(int)
        out[c.name] = gamma.map(lambda g: by_gamma[c.name][g][0])
        out[f"{c.name}_bits"] = gamma.map(lambda g: round(by_gamma[c.name][g][1], 2))
    return out[[*(["why"] if "why" in out else []), "decision", run.l, run.r, "match_weight", "match_probability", "accepted", "household", "sources",
                *(f"{f}_{side}" for f in fields for side in ("l", "r")), *(x for c in comps for x in (c.name, f"{c.name}_bits"))]
               ].reset_index(drop=True)


def describe_workspace(con: duckdb.DuckDBPyConnection, out: Path, uid: str) -> dict:
    """What the workspace `out` holds, for people: records and entities, the largest entities, each run so far
    (steps.json), the pairs and kinds still open and the answers written in but not given back, the records set
    aside, a write still owed, and the last summary (qa.md); a workspace with no run yet holds none of them.
    O(N) in SQL + O(sheet rows)."""
    if not out.is_dir():
        raise InputError(f"no workspace at {out}", fix="create it: nayose create workspace NAME; or see them: nayose list workspaces")
    gold = f"read_parquet({lit(out / 'gold.parquet')})"
    ran = (out / "gold.parquet").exists()
    records, entities = con.execute(f"SELECT count(*), count(DISTINCT cluster_id) FROM {gold}").fetchall()[0] if ran else (0, 0)
    largest = con.execute(f"SELECT cluster_id AS entity, count(*) AS records FROM {gold} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10").fetchall() if ran else []
    activity = history(out)

    def queue(sheet: str, answer: str, whys: tuple[str, ...]) -> dict:  # each kind of row still open, and the answers written in, not yet applied
        rows = read_parquet(out / sheet) if (out / sheet).exists() else pd.DataFrame(columns=["why", answer])
        rows = rows.assign(why=sheet_parts(rows)) if answer == "kind" and len(rows) else rows  # a flagged record drawn at random is to decide
        written = rows[answer].notna()
        if answer == "decision" and len(rows):  # a decision applied since stays in the sheet until the next run writes it
            done = rows.merge(applied(out, uid), on=[f"{uid}_l", f"{uid}_r"], how="left", suffixes=("", "_applied"))["decision_applied"]
            written &= ~(done == rows["decision"]).fillna(False).to_numpy()
        return {**{w: int(((rows["why"] == w) & rows[answer].isna()).sum()) for w in whys}, "written_in": int(written.sum())}
    aside = out / "set_aside"
    summary = table_after((out / "qa.md").read_text(encoding="utf-8"), "## summary") if (out / "qa.md").exists() else pd.DataFrame()
    now, decided = len(rounds(out)), applied(out, uid)
    audits = decided[(decided["why"] == "audit") & (decided["round"] == now)] if {"why", "round"} <= set(decided) else decided.iloc[:0]  # this round's
    return dict(workspace=str(out), records=records, entities=entities, largest=[dict(entity=e, records=n) for e, n in largest], runs=activity,
                round=now, audits=dict(checked=len(audits), false=int((audits["decision"] == "no_match").sum())),
                pairs=queue("review.parquet", "decision", ("decide", "audit")), kinds=queue("kind_review.parquet", "kind", ("decide", "measure")),
                set_aside=con.execute(f"SELECT count(*) FROM read_parquet({lit(aside / '*.parquet')})").fetchall()[0][0]
                if any(aside.glob("*.parquet")) else 0,
                write_owed=(out / PENDING).exists(), summary=summary.values.tolist())


def describe_entity(con: duckdb.DuckDBPyConnection, out: Path, uid: str, record: str, fields: list[str], most: int = 200) -> dict:
    """The entity of `record` in the workspace `out`: its size, and of its first `most` records (`record` among them)
    each with its fields and kind, and every link between them, from a rule (rule_kept), the model (matches, with its
    weight) or people (decisions), as frames. O(N) in SQL."""
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    gold = f"read_parquet({lit(out / 'gold.parquet')})"
    if not (out / "gold.parquet").exists():
        raise no_run(out)
    if not (hit := con.execute(f"SELECT cluster_id FROM {gold} WHERE {u} = ?", [record]).fetchall()):
        raise InputError(f"{record}: no record of the run in {out}",
                         fix="check the ID as the run wrote it: a spreadsheet may read 0000000151 as the number 151")
    entity = hit[0][0]
    size = con.execute(f"SELECT count(*) FROM {gold} WHERE cluster_id = ?", [entity]).fetchall()[0][0]
    con.execute(f"CREATE OR REPLACE TEMP TABLE er_entity AS SELECT * FROM {gold} WHERE cluster_id = ? ORDER BY {u} = ? DESC, {u} LIMIT {most}",
                [entity, record])  # an over-merge of thousands: the page draws a few hundred, and says so
    stored = read(out, "state/records/*.parquet")
    have = [f for f, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM {stored})").fetchall() if f in fields]
    rows = con.execute(f"SELECT e.*, {', '.join(f's.{q(f)}' for f in have) or 'NULL AS none'} FROM er_entity e "
                       f"JOIN {stored} s USING ({u}) ORDER BY e.{u}").df()
    among = f"WHERE {l} IN (SELECT {u} FROM er_entity) AND {r} IN (SELECT {u} FROM er_entity)"
    links = [f"""SELECT {l}, {r}, rule AS by, NULL::DOUBLE AS weight FROM {read(out, 'rule_kept/*.parquet')}
                 {among} AND merged""",
             f"SELECT {l}, {r}, 'fs' AS by, match_weight AS weight FROM read_parquet({lit(out / 'matches' / '*.parquet')}) {among}"]
    if len(latest := applied(out, uid)[[f"{uid}_l", f"{uid}_r", "decision"]]):  # each pair's latest: a "same" changed since is no link
        con.register("er_entity_said", latest)
        links.append(f"SELECT {l}, {r}, 'people: ' || decision AS by, NULL FROM er_entity_said {among}")
    found = con.execute(" UNION ALL ".join(links) + " ORDER BY 1, 2").df()
    if len(latest):
        con.unregister("er_entity_said")
    return dict(record=record, entity=entity, size=size, records=rows, links=found)


GRAPH_NODES = ("records", "prepare", "rules", "candidates", "score", "accept", "people", "group", "kind", "customers")


def reached_by_gamma(facts: list[dict]) -> dict[tuple[str, int], int]:
    """The pairs that stopped at each comparison step, (comparison, gamma) → count, summed over the run log's score steps."""
    reached: dict[tuple[str, int], int] = {}
    for x in facts:
        for c, by in x.get("reached", {}).items():
            for g, k in by.items():
                reached[(c, int(g))] = reached.get((c, int(g)), 0) + k
    return reached


def describe_matching(con: duckdb.DuckDBPyConnection, out: Path | None, p: Pipeline, s: "Settings") -> dict:
    """The pipeline as a graph, for people to see what is computed and how: one node per stage (GRAPH_NODES) with its
    method and parameters and the fields it reads, and the edges between them. With `out`, a written run, each node also
    holds the run's numbers (records, pairs per rule and per generator, each level's m, u, bits and pairs, the weight bands,
    accepted pairs, pairs for people, customers) and real examples. O(E + R + N) in SQL over the run's files."""
    uid, ran = s.data.unique_id, out is not None and (out / "gold.parquet").exists()
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    rows = lambda sql: con.execute(sql).fetchall() if ran else []
    parquet = lambda name: read(out, name) if ran else ""  # no run: nothing to read
    log = runs(out) if ran else []
    facts = [x for run in log for x in run["steps"]]
    turned_off = list(log[-1].get("disabled", [])) if log else []  # what the last run turned off: a field it reads is missing
    n = rows(f"SELECT count(*) FROM {parquet('gold.parquet')}")[0][0] if ran else None

    # prepare: each field's columns, how it is made comparable, how full it is, and one real record
    stored = parquet("state/records/*.parquet")
    have = {c for c, in rows(f"SELECT column_name FROM (DESCRIBE SELECT * FROM {stored})")}
    variants = {}
    for col, norm in [*p.rules.normalized(), *p.fs.normalized()]:
        if not norm or norm[-1] not in COPIES:  # the comparisons' own copy, not a way people's values are made comparable
            variants.setdefault(col, set()).add(norm)
    shown_fields = [f for f in s.columns if f not in ("id", "entity") and f in have]
    filled = dict(zip(shown_fields, rows(f"SELECT {', '.join(f'avg(({q(f)} IS NOT NULL)::DOUBLE)' for f in shown_fields)} FROM {stored}")[0])) if shown_fields else {}
    fields = []  # one scan for every field's fill rate, then one row per field for its example
    for f, alts in s.columns.items():
        if f in ("id", "entity"):
            continue
        chain = next((list(d.normalize) for d in s.standardize.derived if d.name == f), [])
        forms = sorted(variants.get(f, ()))
        item = dict(field=f, columns=[list(a) for a in alts], normalize=chain, compared_as=[list(v) for v in forms], filled=None, example=None)
        if f in have:
            item["filled"] = filled[f]
            raw = [c for a in alts for c in a if c in have]
            shown = [c for c in (*raw, f, *(f"{f}__{'_'.join(v)}" for v in forms)) if c in have]
            got = con.execute(f"SELECT {', '.join(q(c) for c in shown)} FROM {stored} WHERE {q(f)} IS NOT NULL LIMIT 1").fetchall()
            item["example"] = dict(zip(shown, got[0])) if got else None
        fields.append(item)

    # rules: what each compares, how, and the pairs it kept
    kept = {name: (k, a, b, m) for name, k, a, b, m in rows(f"""SELECT rule, count(*), min({l}), arg_min({r}, {l}),
        count(*) FILTER (WHERE merged) FROM {parquet('rule_kept/*.parquet')} GROUP BY 1""")}  # found, and merged: below a trust line, none until people check
    t = p.fs.min_match_weight
    rule_cols = {c for c, in rows(f"SELECT column_name FROM (DESCRIBE SELECT * FROM {parquet('rule_kept/*.parquet')})")} if ran and any((out / "rule_kept").glob("*.parquet")) else set()
    scored_rules = "match_weight" in rule_cols  # the model's points for a rule's pairs: a run's rules are scored (Run._rules)
    split = {name: (hi, mid, lo) for name, hi, mid, lo in rows(f"""SELECT rule, count(*) FILTER (WHERE match_weight >= {t}),
        count(*) FILTER (WHERE match_weight >= 0 AND match_weight < {t}), count(*) FILTER (WHERE match_weight < 0) FROM {parquet('rule_kept/*.parquet')} GROUP BY 1""")} if scored_rules else {}
    lowest = {name: [[a, b, round(float(w), 1)] for a, b, w in got] for name, got in rows(f"""SELECT rule, list([{l}, {r}, match_weight::VARCHAR] ORDER BY match_weight)
        FROM (SELECT *, row_number() OVER (PARTITION BY rule ORDER BY match_weight, {l}, {r}) AS k FROM {parquet('rule_kept/*.parquet')}) WHERE k <= 3 GROUP BY 1""")} if scored_rules else {}
    rules = [dict(stage=st.name, name=x.name, exact=list(x.exact), scores=dict(zip(("high", "mid", "low"), split[x.name])) if x.name in split else None,
                  lowest=lowest.get(x.name, []),
                  fuzzy=rule_how(st, x)["fuzzy"], blocking=[key(k) for k in x.blocking], pairs=kept.get(x.name, (0,))[0] if ran else None,
                  merged=kept.get(x.name, (0, 0, 0, 0))[3] if ran else None,
                  example=list(kept[x.name][1:3]) if x.name in kept else None) for _, st, x in p.rules.each()]

    # candidates: each generator, its method, the pairs it listed, the accepted pairs it found, and one of them
    listed = key_listed(facts)
    likely = likely_links(out, p) if ran else ""
    found = key_found(con, likely, l, r) if ran else {}
    by_keys = [dict(keys=k, links=c) for k, c in rows(f"SELECT least(len(string_split(sources, '+')), 11) AS k, count(*) FROM ({likely}) GROUP BY 1 ORDER BY 1")]
    off = {m.group(1) for d in turned_off for m in [re.match(r"generator (\S+)", d)] if m}
    shown = next((x for x in reversed(facts) if x["step"] == "report"), {})  # the weight bands qa.md shows, kept by the run that wrote it
    qa_text = (out / "qa.md").read_text(encoding="utf-8") if ran and (out / "qa.md").exists() else ""  # the blocks' values: in qa.md, never steps.json
    section = qa_text.split("## oversized blocks", 1)[1].split("\n## ", 1)[0] if "## oversized blocks" in qa_text else ""
    big = table_after(qa_text, "## oversized blocks") if "|" in section else pd.DataFrame()  # a run without one writes "none"
    skipped = big[big["decision"].astype(str).str.startswith("skipped")].astype({"records": int, "pairs": int}).sort_values("records", ascending=False) if len(big) else big
    generators, idle = [], {n for x in facts if x["step"] == "keys" for n in x.get("dropped", ())}  # not run: other keys list its pairs (er.keys.idle)
    for b in p.fs.blockers:
        generators.append(dict(name=b.name, **key_how(b), pairs=listed.get(b.name, (None,))[0] if ran else None, matched=found.get(b.name, (0,))[0] if ran else None,
                               only=found.get(b.name, (0, 0))[1] if ran else None, seconds=round(listed[b.name][1], 2) if b.name in listed else None, off=b.name in off, idle=b.name in idle,
                               example=list(found[b.name][2:]) if b.name in found else None))

    # score: each comparison's levels, the tests behind each, and what the fitted model says each is worth
    model = None
    if ran:
        scoring = out / "state" / "scoring.json"
        model = (json.loads(scoring.read_text(encoding="utf-8"))["model"] if scoring.exists()
                 else json.loads((out / "state" / "model.json").read_text(encoding="utf-8")))
    worth = {(x.comparison, x.level): (x.m, x.u, x.weight) for x in parameters(model).itertuples()} if model else {}
    reach, gamma = reached_by_gamma(facts), {(c, label): g for c, by in levels(model).items() for g, (label, _) in by.items()} if model else {}
    pairs = lambda c, label: reach.get((c, gamma.get((c, label))), 0) if ran else None  # the pairs that stopped at this step
    comparisons = [dict(name=c.name, missing=pairs(c.name, "missing"),
                        levels=[dict(label=lv.label, tests=[dict(field=col, function=t.function, threshold=t.threshold,
                                                                 normalize=list(t.normalize)) for col, t in lv.any_of],
                                     **dict(zip(("m", "u", "bits"), worth.get((c.name, lv.label), (None,) * 3))), pairs=pairs(c.name, lv.label))
                                for lv in c.levels] + [dict(label=ELSE, tests=[], **dict(zip(("m", "u", "bits"), worth.get((c.name, ELSE), (None,) * 3))),
                                                            pairs=pairs(c.name, ELSE))])
                   for c in p.fs.model.comparisons]
    lam = scaled_prior(model, n) if model else None
    scored = sum(x.get("candidates", 0) for x in facts if x["step"] == "candidates") if ran else None  # the keys' pairs: the levels count these
    compared = scored + rows(f"SELECT count(*) FROM {parquet('scored/*.parquet')} WHERE sources IS NULL")[0][0] \
        if scored is not None and any((out / "scored").glob("*.parquet")) else scored  # and the rules' pairs no key listed, as describe results counts them

    # accept, people, group: the line, the band below it for people, and what joined into customers
    bands = shown.get("weight_bands", [])
    accepted = rows(f"SELECT count(*) FROM {parquet('matches/*.parquet')}")[0][0] if ran else None
    rule_pairs = sum(v[0] for v in kept.values()) if ran else None
    rule_merged = sum(v[3] for v in kept.values()) if ran else None
    review = read_parquet(out / "review.parquet") if ran and (out / "review.parquet").exists() else None
    latest = latest_decisions(out, uid) if ran else None  # a pair decided again: once, as last said
    decided = rows(f"SELECT count(*) FROM {latest}")[0][0] if latest else 0
    by = dict(rows(f"SELECT resolved_by, count(*) FROM {parquet('gold.parquet')} WHERE resolved_by = 'review' GROUP BY 1"))
    sizes = rows(f"SELECT n, count(*) FROM (SELECT count(*) AS n FROM {parquet('gold.parquet')} GROUP BY cluster_id) GROUP BY 1 ORDER BY 1")
    customers = sum(k for _, k in sizes) if ran else None
    kinds = dict(rows(f"SELECT kind, count(*) FROM {parquet('gold.parquet')} GROUP BY 1")) if ran and "kind" in {
        c for c, in rows(f"SELECT column_name FROM (DESCRIBE SELECT * FROM {parquet('gold.parquet')})")} else {}
    open_ = int(((review["why"] == "decide") & review["decision"].isna()).sum()) if review is not None else None
    decide = review[review["why"] == "decide"] if review is not None else pd.DataFrame(columns=["match_weight"])
    band_of = lambda w: (w // 2 * 2).astype(int)
    review_bands = [[int(k), int(c)] for k, c in band_of(decide["match_weight"]).value_counts().sort_index().items()] if len(decide) else []
    rule_bands = [[int(k), int(c)] for k, c in rows(f"""SELECT floor(match_weight / 2) * 2, count(*) FROM {parquet('rule_kept/*.parquet')}
        WHERE merged GROUP BY 1 ORDER BY 1""")] if scored_rules else []
    examples = {int(b): got for b, got in rows(f"""SELECT b, list([a, z, w, what] ORDER BY what, k) FROM (
        SELECT *, row_number() OVER (PARTITION BY b, what ORDER BY hash(a || z)) AS k FROM (
          SELECT floor(match_weight / 2) * 2 AS b, {l} AS a, {r} AS z, round(match_weight, 1)::VARCHAR AS w, 'merged' AS what FROM {parquet('matches/*.parquet')}
          {f"UNION ALL SELECT floor(match_weight / 2) * 2, {l}, {r}, round(match_weight, 1)::VARCHAR, 'to review' FROM {parquet('review.parquet')} WHERE why = 'decide'" if review is not None else ""}))
        WHERE k <= 2 GROUP BY 1""")}  # two of each kind per 2-point band: what a click on a bar shows
    expected = sum(x.get("expected_false", 0) for x in facts if x["step"] == "cluster") if ran else None
    comps_on = [c.name for c in p.fs.model.comparisons if review is not None and c.name in review.columns]
    waiting = (decide.groupby(comps_on, dropna=False).size().sort_values(ascending=False) if comps_on and len(decide) else pd.Series(dtype=int))
    patterns = [dict(steps={c: (None if pd.isna(v) else v) for c, v in zip(comps_on, key if isinstance(key, tuple) else (key,))}, pairs=int(k)) for key, k in waiting.head(5).items()]
    gold, kept_rules = parquet("gold.parquet"), parquet("rule_kept/*.parquet")
    model_name = p.fs.model.name
    joined = dict(rows(f"""SELECT CASE WHEN resolved_by = '{model_name}' THEN 'model' WHEN resolved_by = 'review' THEN 'people' ELSE 'rules' END, count(*)
        FROM {gold} WHERE resolved_by IS NOT NULL GROUP BY 1"""))
    size_eg = {a: e for a, e in rows(f"SELECT n, min(cluster_id) FROM (SELECT cluster_id, count(*) AS n FROM {gold} GROUP BY 1) GROUP BY 1")}
    links = [f"SELECT {l} AS a, {r} AS z FROM {parquet('matches/*.parquet')}"] + ([f"SELECT {l}, {r} FROM {kept_rules} WHERE merged"] if rule_cols else []) + (
        [f"SELECT {l}, {r} FROM {latest} WHERE decision = 'match'"] if decided else [])
    look = dict(
        largest=[dict(customer=c, records=k) for c, k in rows(f"SELECT cluster_id, count(*) FROM {gold} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5")],
        single_links=rows(f"""WITH g AS (SELECT {q(uid)} AS id, cluster_id AS c FROM {gold}), big AS (SELECT c, count(*) AS n FROM g GROUP BY 1 HAVING count(*) >= 3),
            e AS (SELECT g.c, count(*) AS e FROM ({' UNION '.join(links)}) x JOIN g ON g.id = x.a GROUP BY 1)
            SELECT count(*), list(c ORDER BY c)[:5] FROM big JOIN e USING (c) WHERE e.e = big.n - 1""")[0] if ran else (0, []),  # every link a bridge: one lost splits it
        mixed=rows(f"""SELECT count(*), list(cluster_id ORDER BY cluster_id)[:5] FROM (SELECT cluster_id FROM {gold} GROUP BY 1
            HAVING count(*) FILTER (WHERE kind = {PERSON}) > 0 AND count(*) FILTER (WHERE kind = {COMPANY}) > 0)""")[0] if ran and kinds else (0, []),
        weak_rule=rows(f"""SELECT count(DISTINCT g.cluster_id), list(DISTINCT g.cluster_id ORDER BY g.cluster_id)[:5] FROM {kept_rules} x JOIN {gold} g ON g.{q(uid)} = x.{l}
            WHERE coalesce(x.merged, TRUE) AND x.match_weight < 0""")[0] if scored_rules else (0, []))
    look = {k: v if k == "largest" else dict(customers=int(v[0]), examples=list(v[1] or [])) for k, v in look.items()}
    inputs = [f for run in log for f in run.get("inputs", []) if f.get("role") == "records"]
    load = [x for x in facts if x["step"] == "load"]
    probed = [x for x in facts if x["step"] == "probe"]
    columns = None
    if inputs and Path(inputs[-1]["file"]).exists():
        import pyarrow.parquet as pq
        columns = len(pq.read_schema(inputs[-1]["file"]).names)
    took = lambda step: round(sum(x["seconds"] for x in facts if x["step"] == step), 1) if ran else None  # a step's seconds, over the run and its increments
    nodes = [
        dict(id="records", name="Records", count=n, files=[f["file"] for f in inputs], bytes=sum(f.get("bytes", 0) for f in inputs) if inputs else None,
             columns=columns, seconds=round(sum(x["seconds"] for x in load), 1) if load else None,
             set_aside=sum(x.get("set_aside", 0) for x in load) if load else None, turned_off=turned_off,
             kinds={"company": kinds.get(2, 0), "person": kinds.get(1, 0), "unsure": kinds.get(0, 0)} if kinds else None),
        dict(id="prepare", name="Make values comparable", method="normalizers per field", fields=fields),
        dict(id="rules", name="Rules", method="certain cases first: exact, then fuzzy", rules=rules, pairs=rule_pairs, merged=rule_merged),
        dict(id="candidates", name="Candidates", method="list the pairs worth comparing", generators=generators, pairs=compared,
             possible=n * (n - 1) // 2 if n else None, listed=sum(k for k, _ in listed.values()) if ran else None, by_keys=by_keys, seconds=took("candidates"),
             skipped=dict(blocks=len(skipped), largest=[dict(key=x.generator, value=x.value, records=x.records, pairs=x.pairs) for x in skipped.head(5).itertuples()]),
             missed=[{**x, "examples": x["examples"][:20]} for x in probed[-1]["strata"]] if probed else None),  # the last full run's probe (er.probe)
        dict(id="score", name="Score", method="Fellegi–Sunter: each comparison adds evidence, in bits", comparisons=comparisons,
             prior_bits=math.log2(lam / (1 - lam)) if lam else None, pairs=scored, seconds=took("score"),
             unscored=sum(x.get("unscored", 0) for x in facts if x["step"] == "score") if ran else None),  # a bound left them below 0: no level counted
        dict(id="accept", name="Accept", method="at the line, with a name compared", threshold=p.fs.min_match_weight, review_from=review_floor(p),
             trust=None if p.trust.line is None else "none" if math.isinf(p.trust.line) else p.trust.line,
             merge=method(out).get("merge") if out else None,  # people's merge conditions (er.results): they decide in place of the line
             needs=list(p.fs.needs), bands=bands, accepted=accepted, review_bands=review_bands, rule_bands=rule_bands, examples=examples,
             expected_false=round(expected, 1) if expected is not None else None),
        dict(id="people", name="People decide", method="close calls go to people", to_decide=open_, decided=decided, joined=by.get("review", 0) if ran else None,
             below=int((decide["match_weight"] < t).sum()), unnamed=int((decide["match_weight"] >= t).sum()),
             audits=int((review["why"] == "audit").sum()) if review is not None else 0, sheet=len(decide), answered=int(decide["decision"].notna().sum()) if len(decide) else 0,
             comparisons=comps_on, patterns=patterns),
        dict(id="group", name="Group", method="connected components: linked records are one customer", customers=customers,
             sizes=[dict(records=a, customers=k, example=size_eg.get(a)) for a, k in sizes], joined=joined if ran else None, look=look if ran else None),
        dict(id="kind", name="Person or company", method="legal form, name model, combiner", on=p.kind is not None,
             legal_forms=len(s.standardize.legal_forms), ngram=p.kind.ngram if p.kind else None,
             counts={"company": kinds.get(2, 0), "person": kinds.get(1, 0), "unsure": kinds.get(0, 0)} if kinds else None),
        dict(id="customers", name="Customers", count=customers),
    ]
    edges = [dict(source=a, target=b, count=c) for a, b, c in (
        ("records", "prepare", n), ("prepare", "rules", n), ("prepare", "candidates", n), ("prepare", "kind", n), ("kind", "score", n),
        ("rules", "group", rule_merged), ("candidates", "score", scored), ("score", "accept", scored), ("accept", "group", accepted),
        ("accept", "people", open_), ("people", "group", decided), ("group", "customers", customers))]
    assert [x["id"] for x in nodes] == list(GRAPH_NODES)
    return dict(nodes=nodes, edges=edges)


def no_run(out: Path, to: str = "") -> InputError:  # a command that needs a run, on a folder without one
    return InputError(f"no run in {out}" + (f" to {to}" if to else ""), fix="find matches first: nayose resolve records --workspace …")


def key(k: Key) -> dict:  # a field a key or rule reads, as the page words it
    return dict(field=k.column, normalize=list(k.normalize))


def key_how(b) -> dict:  # what a pair key looks for: its method and fields
    match b:
        case KeyBlocker():
            return dict(method="same value", keys=[key(k) for k in b.keys])
        case SortedNeighbourhood():
            return dict(method="sorted neighbours", keys=[key(b.key)], window=b.window)
        case TfidfNeighbours():
            return dict(method="TF-IDF nearest", keys=[key(b.key)], ngram=list(b.ngram), k=b.k, min_cosine=b.min_cosine)
        case DeletionKeys():
            return dict(method="one letter deleted", keys=[key(b.key)], within=[key(k) for k in b.within])


def rule_how(st, x) -> dict:  # what a match rule compares: the fields it needs equal, and the tests of the others
    return dict(exact=list(x.exact), fuzzy=[dict(field=c, function=st.comparators[c].function, threshold=st.comparators[c].threshold,
                                                 normalize=list(st.comparators[c].normalize)) for c in x.fuzzy])


def key_listed(facts: list[dict]) -> dict[str, tuple[int, float]]:  # each key's pairs listed and seconds, over the runs' steps
    out: dict[str, tuple[int, float]] = {}
    for x in facts:
        for g in x.get("generators", ()):
            pairs, seconds = out.get(g["name"], (0, 0.0))
            out[g["name"]] = (pairs + g["pairs"], seconds + g["seconds"])
    return out


def key_found(con: duckdb.DuckDBPyConnection, likely: str, l: str, r: str) -> dict[str, tuple]:
    """Each key's likely links (likely_links): how many it found, how many it alone found, and one of them (l, r)."""
    return {g: (k, only, a, b) for g, k, only, a, b in con.execute(f"""SELECT g, count(*), count(*) FILTER (WHERE alone), min(a), arg_min(b, a)
        FROM (SELECT unnest(string_split(sources, '+')) AS g, NOT contains(sources, '+') AS alone, {l} AS a, {r} AS b FROM ({likely})) GROUP BY 1""").fetchall()}


def likely_links(out: Path, p: Pipeline) -> str:
    """The run's likely links in `out`, as SQL: its matches, and the model's pairs at its line that a trust line holds
    back for people (proposed). What a key found is counted on these, so a strict workspace still sees its keys work."""
    waiting = f" UNION ALL BY NAME SELECT * FROM {read(out, 'proposed/*.parquet')} WHERE match_weight >= {p.fs.min_match_weight!r}" if any((out / "proposed").glob("*.parquet")) else ""
    return f"SELECT * FROM {read(out, 'matches/*.parquet')}{waiting}"


# ---------- how a match was found: one pair, a customer's pairs, the patterns of the whole file ----------

