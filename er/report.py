"""The reports for people, from what a job did (er.steps.job.Ran) and its tables: qa (the label-free checks, and the
summary in words), fill_rates, review_sheet (scored pairs as people judge them), carry_over (the open review queue across
increments) and report_text (the run on a page with no record's value in it). er.steps.report builds them; er.steps.write
stages them with the run's files."""
import math
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd

from er.engine.engine import Engine
from er.config import GIVEN, InputError, Key, Pipeline, lit, q, sources_text
from er.io import code_version, read_parquet
from er.kind import COMPANY, PERSON, SAYS, UNSURE
from er.match import ELSE, GIVEN_SHARE, _ranked, levels, named_sql, parameters, pattern_coverage, review_floor, scaled_prior, search_floor
from er.source import filled, fit
from er.review_state import applied

if TYPE_CHECKING:
    from er.steps.job import Ran


def fill_rates(run: "Ran", fields: list[str] | None = None, sample: int = 10_000) -> pd.DataFrame:
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
    filled = run.engine.row(f"SELECT {', '.join(f'avg(({q(f)} IS NOT NULL)::INT)' for f in fs)} FROM records")
    run.engine.run(f"CREATE OR REPLACE TEMP TABLE er_fill_sample AS SELECT {', '.join(f'{q(f)}::VARCHAR AS {q(f)}' for f in fs)} "
                    f"FROM records ORDER BY hash({q(run.uid)}) LIMIT {sample}")  # by ID: the same sample whatever the rows' order
    pattern = {f: run.settings.detect[f] for f in fs if f in run.settings.detect}
    looks = dict(zip(pattern, run.engine.row("SELECT " + ", ".join(f"avg(regexp_matches({q(f)}, {lit(p)})::INT)" for f, p in pattern.items())
                                              + " FROM er_fill_sample"))) if pattern else {}
    top = dict(run.engine.rows("""SELECT field, max(n) / sum(n) FROM (SELECT field, v, count(*) AS n FROM
        (UNPIVOT er_fill_sample ON COLUMNS(*) INTO NAME field VALUE v) GROUP BY ALL) GROUP BY field"""))
    shape = run.engine.row("SELECT " + ", ".join(f"avg((NOT regexp_matches({q(f)}, '[\\pL\\pN]'))::INT), avg(length({q(f)})), max(length({q(f)}))" for f in fs)
                            + " FROM er_fill_sample")
    return pd.DataFrame(dict(field=fs, filled=filled, looks_right=[looks.get(f) for f in fs], top_value=[top.get(f) for f in fs],
                             no_letters=shape[0::3], length=shape[1::3], longest=shape[2::3])).assign(
        flag=lambda d: np.where(d["filled"] < 0.05, "under 5%", ""))


def unmapped_columns(engine: Engine, table: str, columns: list[str], fields: list[str], patterns: dict[str, str]) -> pd.DataFrame:
    """Each of `columns` (read by no field) on the sample `table`: its share filled, the share of its filled values
    held once (distinct), and the field its values look most like (er.source.fit), with that share; best fit first.
    Numbers and names only: no value. O(sample · columns · fields)."""
    if not columns:
        return pd.DataFrame(columns=["column", "filled", "distinct", "looks_like", "share"])
    v = filled("v")
    n = max(1, engine.value(f"SELECT count(*) FROM {table}"))
    shape = {c: (k / n, d / max(1, k)) for c, k, d in engine.rows(f"""SELECT c, count(*) FILTER (WHERE {v}), count(DISTINCT v) FILTER (WHERE {v})
        FROM (UNPIVOT (SELECT {', '.join(q(c) for c in columns)} FROM {table}) ON COLUMNS(*) INTO NAME c VALUE v) GROUP BY c""")}
    fits = fit(engine, table, columns, [f for f in fields if f != "id"], patterns)  # id: any column of unique values fits it; distinct says that
    best = {c: max(((f, s[c]) for f, s in fits.items()), key=lambda x: x[1], default=("", 0.0)) for c in columns}
    return pd.DataFrame([dict(column=c, filled=shape.get(c, (0.0, 0.0))[0], distinct=shape.get(c, (0.0, 0.0))[1],
                              looks_like=best[c][0] if best[c][1] > 0 else "", share=best[c][1]) for c in columns]
                        ).sort_values(["share", "filled"], ascending=False, kind="stable", ignore_index=True)


def qa(run: "Ran", fields: list[str] | None = None, review: int = 50, previous: Path | None = None) -> dict[str, pd.DataFrame]:
    """The label-free report of a run: a summary in words (records, entities, who joined them, the model's links and the
    false ones it expects among them, what to decide, what the loader fixed), fill rate per field (flagged under 5%)
    (of `fields`, by default every logical field) with the share that looks like the field and the share of its most common value, what was disabled, every step's cost,
    accepted pairs by weight band, cluster sizes, the largest clusters (the over-merge alarm), and the review sheet
    for people (review_sheet). Its rows are of two kinds. "decide": every pair of clusters whose best link scored in the
    threshold's safety margin [review_floor, min_match_weight), or above it with no name compared, not decided yet, best link first. "audit": accepted pairs
    up to 4 bits above the threshold not decided yet, `review` of them, stratified by 1-bit band. `previous`, the workspace's sheet
    before an increment: its open rows stay (carry_over), since the scores behind them aren't kept."""
    engine, u, t = run.engine, q(run.uid), run.pipeline.fs.min_match_weight
    fill = fill_rates(run, fields)
    l, r, lo = q(run.l), q(run.r), review_floor(run.pipeline)
    bands = engine.frame(f"""SELECT floor(s.match_weight / 2) * 2 AS weight_from, count(*) AS pairs, count(m.{l}) AS accepted
                        FROM scores s LEFT JOIN matches m USING ({l}, {r}) GROUP BY 1 ORDER BY 1""")
    sizes = engine.frame("SELECT n AS cluster_size, count(*) AS clusters FROM (SELECT count(*) AS n FROM gold GROUP BY cluster_id) GROUP BY 1 ORDER BY 1")
    largest = engine.frame("SELECT cluster_id, count(*) AS records FROM gold GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10")
    engine.run(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
    decide = engine.frame(f"""SELECT * EXCLUDE (k1, k2) FROM (
            SELECT s.*, c.sources, least(ga.cluster_id, gb.cluster_id) AS k1, greatest(ga.cluster_id, gb.cluster_id) AS k2
            FROM scores s JOIN cands c USING ({l}, {r}) JOIN gold ga ON ga.{u} = s.{l} JOIN gold gb ON gb.{u} = s.{r}
            WHERE s.match_weight >= {lo} AND (s.match_weight < {t} OR NOT {named_sql(run.pipeline.fs)}) AND ga.cluster_id <> gb.cluster_id
              AND NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = s.{l} AND d.{r} = s.{r}))
        QUALIFY row_number() OVER (PARTITION BY k1, k2 ORDER BY match_weight DESC, {l}, {r}) = 1
        ORDER BY match_weight DESC, {l}, {r}""").assign(why="decide")
    audit = engine.frame(f"""SELECT * EXCLUDE (k) FROM (SELECT s.*, m.sources, row_number() OVER (PARTITION BY floor(s.match_weight) ORDER BY hash(s.{l}, s.{r})) AS k
                        FROM matches m JOIN scores s USING ({l}, {r}) WHERE s.match_weight < {t + 4}
                          AND NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = s.{l} AND d.{r} = s.{r}))
                        WHERE k <= {max(1, review // 4)} ORDER BY match_weight, {l}, {r}""").assign(why="audit")
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
    fs, aside = run.pipeline.fs, run.engine.value("SELECT count(*) FROM set_aside")
    total, entities, biggest, by_rules, by_model, by_people = engine.row(f"""SELECT count(*), count(DISTINCT cluster_id), max(n),
        count(*) FILTER (WHERE resolved_stage = '{fs.previous_stage}'), count(*) FILTER (WHERE resolved_stage = '{fs.stage}'),
        count(*) FILTER (WHERE resolved_stage = 'review') FROM gold JOIN (SELECT cluster_id, count(*) AS n FROM gold GROUP BY 1) USING (cluster_id)""")
    linked = next(x for x in reversed(run.steps) if x["step"] == "cluster")
    kinds, mixed, kind_rows = pd.DataFrame(), pd.DataFrame(), []
    if "kind" in engine.frame("DESCRIBE gold")["column_name"].tolist():
        kinds = engine.frame("""SELECT 'records' AS of, kind, count(*) AS how_many FROM gold GROUP BY ALL
                           UNION ALL SELECT 'customers', customer_kind, count(DISTINCT cluster_id) FROM gold GROUP BY ALL ORDER BY ALL""")
        mixed = engine.frame("""SELECT cluster_id, count(*) AS records, count(*) FILTER (WHERE kind = 2) AS companies,
                                  count(*) FILTER (WHERE kind = 1) AS persons FROM gold GROUP BY 1
                           HAVING companies > 0 AND persons > 0 ORDER BY records DESC, cluster_id""")
        n = {(x.of, x.kind): x.how_many for x in kinds.itertuples()}
        kind_rows = [("kinds", " · ".join(f"{n.get((of, k), 0):,} × {SAYS[k]}" for k in (COMPANY, PERSON, UNSURE)) + f" ({of})")
                     for of in ("records", "customers")]
        c = run.classifier
        flagged = engine.value("SELECT count(*) FILTER (WHERE kind_flagged) FROM gold")
        if flagged:
            kind_rows.append(("flagged", f"{flagged:,} records the engine is sure of against the flag: matched as the engine says (gold: kind_flagged)"))
        if c is not None:
            kind_rows.append(("kinds from", "the file's flag, as it is (trust_flag)" if c.spec.trust_flag
                              else f"a written legal form, or a name {c.spec.name_line:.0%} sure; else the flag"))
        if c is not None and not c.spec.trust_flag and "kind_flag" in run.columns():  # the flag's likely errors, for its owners
            says = "x.kind_flag IN (" + ", ".join(map(lit, c.flag_company)) + ")"
            a, b = engine.row(f"""SELECT count(*) FILTER (WHERE g.kind = 2 AND NOT {says}), count(*) FILTER (WHERE g.kind = 1 AND {says})
                                   FROM gold g JOIN records x USING ({u}) WHERE x.kind_flag IS NOT NULL""")
            kind_rows.append(("flag", f"a kind the engine is sure of contradicts it on {a + b:,} records: {a:,} 2 company flagged 1, "
                                      f"{b:,} 1 person flagged 2"))
        if len(mixed):
            kind_rows.append(("note", f"{len(mixed):,} cluster{'s hold' if len(mixed) > 1 else ' holds'} a sure person and a sure company: see qa.md, mixed kinds"))
    apart = engine.value(f"""SELECT count(*) FROM er_decisions d JOIN gold a ON a.{u} = d.{q(run.l)} JOIN gold b ON b.{u} = d.{q(run.r)}
        WHERE d.decision = 'no_match' AND a.cluster_id = b.cluster_id""")  # kept apart, joined by others
    summary = pd.DataFrame([
        ("records", f"{total:,}" + (f", {run.added:,} of them new" if run.added is not None else "") + (f"; {aside:,} set aside (set_aside/)" if aside else "")),
        ("entities", f"{entities:,}; the largest holds {biggest:,} record{'s' * (biggest != 1)}"),
        ("joined by", f"the rules {by_rules:,} · the model {by_model:,} · people {by_people:,} records"),
        ("model links", f"{linked['accepted']:,}{' in this batch' if run.added is not None else ''}; about {linked['expected_false']:,.{1 if linked['expected_false'] >= 1 else 2}f} "
                        "of them false, as the model expects (the sum of 1 − match probability)"),
        ("to decide", f"{len(decide):,} pair{'' if len(decide) == 1 else 's'} in review.parquet (why = decide)"),
        *kind_rows,
        *([("note", f"{apart:,} pair{'s' if apart > 1 else ''} people called different {'are' if apart > 1 else 'is'} in one entity through other links: "
                    "a full run parts it only where no other link holds it")] if apart else []),
        *(("note", f"{f} only {x:.1%} filled: check its mapping") for f, x in fill.loc[fill["flag"] != "", ["field", "filled"]].itertuples(index=False)),
        *(("note", f"turned off, a field it reads is missing: {d}") for d in run.disabled),
        *(("note", note) for note in run.notes),
        *(("example", x) for x in run.examples)], columns=["what", "value"])
    return dict(summary=summary, fill=fill, disabled=pd.DataFrame({"disabled": run.disabled}), steps=steps, weight_bands=bands,
                cluster_sizes=sizes, largest_clusters=largest, patterns_without_a_key=coverage.head(20), review=queue,
                kinds=kinds, mixed_kinds=mixed,
                oversized_blocks=run.gated,
                review_sheet=sheet)


SPARSE = 0.3  # a compared field filled in fewer records than this: DIAGNOSIS names it
THIN = 200    # a kept EM session that learned from fewer pairs: DIAGNOSIS asks for more records
NEAR = 2.0    # bits: a skipped oversized block whose best sampled pair came this close to the search floor
SHOWN = 8     # DIAGNOSIS's lines at most


def diagnosis(run: "Ran", tables: dict[str, pd.DataFrame], lo: float) -> list[dict]:
    """What limits what the run finds, the most pairs at stake first, at most SHOWN items, each what (with its number),
    the pairs at stake and the fix (the setting to change, where there is one): report.txt prints them (diagnosis_lines),
    steps.json keeps them. What is fine is left out: EM sessions of the run's own fit that learned
    households, compared fields under SPARSE filled (with a column no field reads that looks like one), pairs below the
    review floor that agree exactly on a name and another field, levels that learned nothing yet hold pairs, oversized
    blocks skipped that came within NEAR bits, and, last, EM
    sessions of under THIN pairs. No record's value:
    field, column and level names, counts and shares. O(C) over the scores."""
    engine, model, m, fs = run.engine, run.scoring, run.scoring["er"], run.pipeline.fs
    gammas = {c for c, *_ in engine.rows("DESCRIBE scores") if c.startswith("gamma_")}
    below = f"match_weight >= 0 AND match_weight < {lo}"
    count = lambda where: engine.value(f"SELECT count(*) FROM scores WHERE {where}")
    n_below, expected = engine.row(f"SELECT count(*), coalesce(sum(match_probability), 0) FROM scores WHERE {below}")
    gamma = {c["output_column_name"]: {lv["label_for_charts"]: g for g, lv in _ranked(c)} for c in model["comparisons"]}
    out: list[tuple[float, str]] = []

    if households := [x for x in m.get("em_given", []) if x["given_share"] is not None and x["given_share"] < GIVEN_SHARE]:  # EM taught by households: first of equals
        out.append((n_below, "EM learned households from " + ", ".join(f"{x['session']} ({x['given_share']:.0%} of its matches agree on the given name)" for x in households)
                    + f": it scores the {n_below:,} pairs below review → EM sessions that hold the given name fixed, chosen at design time ([model] em_rules)"))

    fill = tables["fill"].set_index("field")["filled"]  # compared fields mostly empty (one comparison a line), and a column that looks like one
    either = {f for group in run.pipeline.fields.one_of for f in group}  # a person's name or a company's: each kind fills one
    cols = getattr(run, "unmapped", None)
    for c in (c for c in fs.model.comparisons if f"gamma_{c.name}" in gammas):
        sparse = [f for f in dict.fromkeys([*(col for lv in c.levels for col, _ in lv.any_of), *c.null_if_missing]) if f in fill and fill[f] < SPARSE and f not in either]
        if not sparse:
            continue
        if not (stake := count(f"{below} AND {q('gamma_' + c.name)} = -1")):
            continue
        line = f"{', '.join(f'{f} {fill[f]:.0%}' for f in sparse)} filled: {stake:,} pairs below review compare no {c.name}"
        for f in sparse:
            like = cols[(cols["looks_like"] == f) & (cols["share"] >= 0.5)].sort_values("filled", ascending=False) if cols is not None and len(cols) else []
            if len(like):
                col = like.iloc[0]["column"]
                line += f"; column {col} looks like {f} ({like.iloc[0]['filled']:.0%} filled) → add {col} to {f}'s sources in config/settings.toml [columns]"
                break
        out.append((stake, line))

    agree, named = [], ["given name"]  # near misses: a name and another field agree exactly, below the review floor (a phone and an address alone: a household's)
    for c in fs.model.comparisons:
        named += [c.name] if {col for lv in c.levels for col, _ in lv.any_of} & either else []
        if f"gamma_{c.name}" in gammas:
            exact = [gamma[c.name][lv.label] for lv in c.levels if all(x.function == "exact" for _, x in lv.any_of) and GIVEN not in {col for col, _ in lv.any_of}]
            given = [gamma[c.name][lv.label] for lv in c.levels if GIVEN in {col for col, _ in lv.any_of}]
            agree += [f"CASE WHEN {q('gamma_' + c.name)} IN ({', '.join(map(str, gs))}) THEN '{what}' END" for what, gs in ((c.name, exact), ("given name", given)) if gs]
    if len(agree) > 1 and n_below:
        got = engine.rows(f"""SELECT p, count(*) AS n FROM (SELECT concat_ws(' + ', {', '.join(agree)}) AS p FROM scores WHERE {below})
            WHERE p LIKE '% + %' AND list_has_any(string_split(p, ' + '), {named!r}) GROUP BY 1 ORDER BY n DESC, p""")
        if total := sum(n for _, n in got):
            out.append((total, f"{total:,} pairs below review agree exactly on a name and another field ({', '.join(f'{p} {n:,}' for p, n in got[:3])}); "
                               f"the model expects {expected:,.0f} true pairs among the {n_below:,} below review"))

    held, empty = [], 0  # levels that learned nothing (m = u: 0 bits)
    for c, lv in (tuple(x) for x in m.get("filled", {}).get("m", [])):
        if lv != ELSE and f"gamma_{c}" in gammas and lv in gamma.get(c, {}):
            if n := count(f"{q('gamma_' + c)} = {gamma[c][lv]}"):
                held.append((n, f"{c} {lv} {n:,}"))
            else:
                empty += 1
    if held:
        out.append((sum(n for n, _ in held), "levels that learned nothing hold pairs, at 0 bits: " + ", ".join(x for _, x in sorted(held, reverse=True))
                    + (f" ({empty} more hold none)" if empty else "") + " → a larger fit sample: [model] fit_rows"))

    gated, floor = getattr(run, "gated", pd.DataFrame()), search_floor(run.pipeline)
    if len(gated) and "best" in gated:
        near = gated[gated["decision"].str.startswith("skipped") & (gated["best"] >= floor - NEAR)]
        if len(near):
            out.append((int(near["pairs"].sum()), f"{len(near):,} oversized blocks skipped ({int(near['pairs'].sum()):,} pairs) held a sampled pair within {NEAR:g} bits "
                                                   f"of {floor:g} → a narrower key for them, chosen at design time"))

    if thin := [(x, n) for x, n in m.get("em_pairs", {}).items() if n < THIN]:  # thin sessions
        out.append((0, f"EM learned from few pairs: {', '.join(f'{x} {n:,}' for x, n in thin)} → a larger fit sample: [model] fit_rows"))
    return [dict(what=what, pairs=int(n), fix=fix) for n, x in sorted(out, key=lambda x: -x[0])[:SHOWN] for what, _, fix in [x.partition(" → ")]]


def diagnosis_lines(items: list[dict]) -> list[str]:  # report.txt's DIAGNOSIS, from diagnosis's items
    lines = [x["what"] + (f" → {x['fix']}" if x["fix"] else "") for x in items] or ["nothing found"]
    return ["DIAGNOSIS  (what limits what the run finds, the most pairs at stake first)", *(f"  {x}" for x in lines), ""]


def report_text(run: "Ran", tables: dict[str, pd.DataFrame], pipeline: Path, items: list[dict] | None = None) -> str:
    """The run on a page of plain text that holds no record's value (no ID, name, phone or address: the notes that
    quote one are run.examples, in qa.md only), so it can leave the machine that holds the records. `tables` is qa()'s.
    It shows what ran (the code, the tracked files changed in this copy, the pipeline, the machine's limits), what limits
    what the run finds (diagnosis's `items`, made here when not given), the summary, each field's fill and shape, the columns no field reads, scores and accepted links by weight with the false links the
    model expects, each score band's commonest patterns, cluster sizes, each step's time and memory, its time in each string comparison, the model (the prior, the pairs each EM session learned from, and m, u and bits per level), the costliest
    blocks, and the patterns no key pairs. O(C + E) over scores and matches."""
    engine, fs = run.engine, run.pipeline.fs
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
    threads, memory = engine.row("SELECT current_setting('threads'), current_setting('memory_limit')")
    kind = "full run" if run.added is None else f"increment of {run.added:,} new records"
    out = [f"RUN REPORT · {datetime.now():%Y-%m-%d %H:%M} · {kind} · no record's value in it",
           f"code {code} · pipeline {pipeline.name}",
           f"python {platform.python_version()} · duckdb {duckdb.__version__} · {platform.system()} {platform.machine()}",
           f"{threads} threads · memory limit {memory} · spill room {run.spill_room() / 1e9:,.0f} GB · "
           f"took {sum(x['seconds'] for x in run.steps):,.1f} s · peak {max(x['peak_memory_gb'] for x in run.steps):.2f} GB", ""]

    out += diagnosis_lines(diagnosis(run, tables, lo) if items is None else items)
    summary = tables["summary"][tables["summary"]["what"] != "example"]
    out += ["SUMMARY", *(f"  {what:<12} {value}" for what, value in summary.itertuples(index=False)), ""]

    fill = tables["fill"]
    out += ["FIELDS  (looks right, top value, no letters, length: on a sample of 10,000 records)", *table(pd.DataFrame(dict(
        field=fill["field"], filled=fill["filled"].map(pct), looks_right=fill["looks_right"].map(pct), top_value=fill["top_value"].map(pct),
        no_letters=fill["no_letters"].map(pct), length=fill["length"].map(lambda x: "" if pd.isna(x) else f"{x:.0f}"),
        longest=fill["longest"].map(lambda x: "" if pd.isna(x) else f"{int(x):,}"), columns=[sources_text(run.present.get(f)) for f in fill["field"]]))), ""]

    if (cols := getattr(run, "unmapped", None)) is not None and len(cols):  # a Run made without load (er.sizes) has none
        shown = cols.head(30)
        out += ["COLUMNS NOT MAPPED  (no field reads them; filled, distinct and the field their values look most like: on the first 10,000 records)",
                *table(pd.DataFrame(dict(column=shown["column"], filled=shown["filled"].map(pct), distinct=shown["distinct"].map(pct),
                                         looks_like=shown["looks_like"], share=[pct(x) if f else "" for f, x in zip(shown["looks_like"], shown["share"])]))),
                *([f"  and {len(cols) - len(shown):,} more"] if len(cols) > len(shown) else []), ""]

    edges = sorted({-20, -10, 0, lo, t, t + 2, t + 4, t + 8, t + 12})
    band = "CASE " + " ".join(f"WHEN match_weight < {b} THEN {i}" for i, b in enumerate(edges)) + f" ELSE {len(edges)} END"
    scored = dict(engine.rows(f"SELECT {band}, count(*) FROM scores GROUP BY 1"))
    accepted = {k: (n, x) for k, n, x in engine.rows(f"SELECT {band}, count(*), sum(1 - match_probability) FROM matches GROUP BY 1")}
    label = lambda i: f"below {edges[0]:g}" if i == 0 else f"{edges[-1]:g} and up" if i == len(edges) else f"{edges[i - 1]:g} to {edges[i]:g}"
    if unscored := sum(x.get("unscored", 0) for x in run.steps if x["step"] == "score"):  # pairs a bound put below 0, never scored: one row below 0
        below = [i for i in scored if i < len(edges) and edges[i] <= 0]
        scored = {-1: sum(scored.pop(i) for i in below) + unscored, **scored}
        label = (lambda f: lambda i: "below 0" if i == -1 else f(i))(label)
    out += [f"SCORES  (bits; review from {lo:g}, accept from {t:g}; expected false = the sum of 1 − match probability)", *table(pd.DataFrame(
        [dict(bits=label(i), candidates=f"{scored[i]:,}", accepted=f"{accepted.get(i, (0, 0))[0]:,}", expected_false=f"{accepted.get(i, (0, 0))[1]:.2f}")
         for i in sorted(scored)])), ""]

    gammas = [c for c, *_ in engine.rows("DESCRIBE scores") if c.startswith("gamma_")]
    if gammas:  # each band's most common patterns among the keys' pairs scored/ keeps, one level per comparison as MODEL names it
        named = levels(run.scoring)
        got = engine.rows(f"""WITH p AS (SELECT match_weight >= {lo} AS up, {', '.join(q(g) for g in gammas)}, count(*) AS n, avg(match_weight) AS w
                FROM scores WHERE match_weight >= 0 GROUP BY ALL)
            SELECT * EXCLUDE (k) FROM (SELECT *, sum(n) OVER (PARTITION BY up) AS total, count(*) OVER (PARTITION BY up) AS kinds,
                row_number() OVER (PARTITION BY up ORDER BY n DESC, w DESC) AS k FROM p) WHERE k <= 12 ORDER BY up DESC, k""")
        band = lambda up: f"{lo:g} and up" if up else f"0 to {lo:g}"
        out += ["PATTERNS BY SCORE  (the keys' pairs at 0 bits and up, below and from the review floor: each band's 12 most common levels)",
                *table(pd.DataFrame([dict(band=band(x[0]), pairs=f"{x[len(gammas) + 1]:,}", bits=f"{x[len(gammas) + 2]:.1f}",
                                          **{g.removeprefix("gamma_"): named.get(g.removeprefix("gamma_"), {}).get(int(v), (str(v),))[0] if v is not None else "missing"
                                             for g, v in zip(gammas, x[1:])}) for x in got])),
                *(f"  {band(up)}: {kinds - 12:,} patterns more, {int(total) - sum(y[len(gammas) + 1] for y in got if y[0] == up):,} pairs"
                  for up, total, kinds in dict.fromkeys((x[0], x[-2], x[-1]) for x in got) if kinds > 12), ""]

    sizes = tables["cluster_sizes"]
    by = pd.cut(sizes["cluster_size"], [0, 1, 2, 3, 4, 9, 49, np.inf], labels=["1", "2", "3", "4", "5–9", "10–49", "50+"])
    out += ["CLUSTERS  (size: how many)", "  " + " · ".join(f"{k}: {v:,}" for k, v in sizes.groupby(by, observed=True)["clusters"].sum().items()), ""]

    steps = tables["steps"]
    out += ["STEPS", *table(steps[["step", "seconds", "peak_memory_gb", "facts"]].rename(columns={"peak_memory_gb": "peak_gb"})), ""]
    by_step = {x["step"]: x for x in run.steps}
    if (c := by_step.get("candidates")) and c.get("generators"):  # where the candidates' time goes
        out += ["KEYS  (pairs each lists, seconds; slowest first)",
                *table(pd.DataFrame([dict(key=x["name"], pairs=f"{x['pairs']:,}", seconds=f"{x['seconds']:.1f}") for x in sorted(c["generators"], key=lambda x: -x["seconds"])])), ""]

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
            + (f"; learned nothing about {', '.join(m['skipped'])}" if m.get("skipped") else "") + ")",
            *(["  EM learned from: " + " · ".join(f"{f} {n:,} pairs" for f, n in m["em_pairs"].items())] if m.get("em_pairs") else []),
            *table(pd.DataFrame(dict(
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


def carry_over(run: "Ran", previous: pd.DataFrame, sheet: pd.DataFrame, out: Path, full: bool = False) -> pd.DataFrame:
    """The review queue across runs: the previous sheet's rows holding a decision typed in and not given back (one other
    than the pair's latest in decisions/: the sheet keeps what was applied), and, across increments, its decide rows
    nobody gave back whose records are still in different clusters; a full run (`full`) makes the rest again. Those
    rows as they were, with this run's other rows. O(previous rows)."""
    l, r, u = q(run.l), q(run.r), q(run.uid)
    prev = previous if "why" in previous else previous.iloc[:0]  # a sheet from before the queue: nothing to keep
    if prev.empty:
        return sheet
    run.engine.register("er_prev", prev[[run.l, run.r, "decision", "why"]])
    run.engine.register("er_stored", applied(out, run.uid)[[run.l, run.r, "decision"]].astype("string"))
    keep = run.engine.frame(f"""SELECT p.{l}, p.{r} FROM er_prev p JOIN gold a ON a.{u} = p.{l} JOIN gold b ON b.{u} = p.{r}
        WHERE (p.decision IS NOT NULL OR ({'FALSE' if full else 'TRUE'} AND p.why = 'decide' AND a.cluster_id <> b.cluster_id))
          AND NOT EXISTS (SELECT 1 FROM er_stored d WHERE d.{l} = p.{l} AND d.{r} = p.{r} AND (p.decision IS NULL OR d.decision = p.decision))""")
    run.engine.unregister("er_prev")
    run.engine.unregister("er_stored")
    kept = prev.merge(keep, on=[run.l, run.r]).reindex(columns=sheet.columns)  # a column this run's sheet lacks goes, one it adds is empty
    both = pd.concat([sheet[~sheet.set_index([run.l, run.r]).index.isin(kept.set_index([run.l, run.r]).index)], kept], ignore_index=True)
    decide = both[both["why"] == "decide"].sort_values("match_weight", ascending=False, ignore_index=True)
    return pd.concat([decide, both[both["why"] != "decide"]], ignore_index=True)


def households(engine: Engine, records: str, pairs: str, uid: str, p: Pipeline) -> set[tuple[str, str]]:
    """The pairs of `pairs` (SQL: uid_l, uid_r) labelled maybe one household ([household]), read on `records` (SQL, the
    run's standardized records). O(pairs)."""
    have = {c for c, *_ in engine.rows(f"DESCRIBE SELECT * FROM {records}")}
    if (cond := p.household.sql(have)) == "FALSE":
        return set()
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    return set(engine.rows(f"""SELECT x.{l}, x.{r} FROM ({pairs}) x JOIN {records} l ON l.{u} = x.{l} JOIN {records} r ON r.{u} = x.{r}
        WHERE {cond}"""))


def review_sheet(run: "Ran", pairs: pd.DataFrame) -> pd.DataFrame:
    """Scored pairs as people judge them, in the order given: both records' compared fields side by side, and per
    comparison the level the pair landed in and the bits it earned, which with the prior sum to its weight; whether the
    run merged it (in kept: a rule's pair, the model's, or people's); whether it may be two people of one household
    (households); an empty `decision` for people to fill in (match or no_match) and give to Run.decide. O(pairs)."""
    comps, uid = run.pipeline.fs.model.comparisons, run.uid
    fields = [f for f in dict.fromkeys(col for c in comps for col in (*c.null_if_missing, *(x for lv in c.levels for x, _ in lv.any_of)))
              if f in run.columns()]
    run.engine.register("er_review_ids", pd.DataFrame({uid: pd.concat([pairs[run.l], pairs[run.r]]).unique()}))
    records = run.engine.frame(f"SELECT {', '.join(q(c) for c in [uid, *fields])} FROM records JOIN er_review_ids USING ({q(uid)})")
    run.engine.unregister("er_review_ids")
    run.engine.register("er_review_pairs", pairs[[run.l, run.r]])
    accepted = run.engine.frame(f"""SELECT p.*, EXISTS (SELECT 1 FROM kept k WHERE k.{q(run.l)} = p.{q(run.l)} AND k.{q(run.r)} = p.{q(run.r)}) AS accepted
        FROM er_review_pairs p""")
    homes = households(run.engine, "records", "SELECT * FROM er_review_pairs", uid, run.pipeline)
    run.engine.unregister("er_review_pairs")
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


def no_run(out: Path, to: str = "") -> InputError:  # a command that needs a run, on a folder without one
    return InputError(f"no run in {out}" + (f" to {to}" if to else ""), fix="find matches first: nayose resolve records --workspace …")


def key(k: Key) -> dict:  # a field a key or rule reads, as the page words it
    return dict(field=k.column, normalize=list(k.normalize))


# ---------- how a match was found: one pair, a customer's pairs, the patterns of the whole file ----------

