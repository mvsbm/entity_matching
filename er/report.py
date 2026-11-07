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

from er.candidates import q
from er.config import DeletionKeys, InputError, KeyBlocker, Pipeline, SortedNeighbourhood, TfidfNeighbours, sources_text
from er.folder import DECISIONS, PENDING, method, rounds
from er.io import code_version, table_after
from er.kind import COMPANY, PERSON, SAYS, UNSURE
from er.match import ELSE, levels, named_sql, parameters, pattern_coverage, review_floor, scaled_prior, score_fs
from er.source import lit

if TYPE_CHECKING:
    from er.run import Run
    from er.settings import Settings


def fill_rates(run: "Run", fields: list[str] | None = None, sample: int = 10_000) -> pd.DataFrame:
    """Each field's share of filled records, flagged under 5%: a field almost never filled is often a mapping mistake.
    Then, on a random sample of `sample` records, the share of filled values that look like the field ([locale.detect];
    a low share is a wrong column or a format the comparisons don't expect), and the share held by its most common
    value (a placeholder such as 0000 counts as an agreement between the records that hold it). O(N·F + sample·F)."""
    cols = run.columns()
    fs = [f for f in (run.fields if fields is None else fields) if f in cols]
    if not fs:
        return pd.DataFrame(columns=["field", "filled", "looks_right", "top_value", "flag"])
    filled = run.con.execute(f"SELECT {', '.join(f'avg(({q(f)} IS NOT NULL)::INT)' for f in fs)} FROM records").fetchall()[0]
    run.con.execute(f"CREATE OR REPLACE TEMP TABLE er_fill_sample AS SELECT {', '.join(f'{q(f)}::VARCHAR AS {q(f)}' for f in fs)} "
                    f"FROM records USING SAMPLE reservoir({sample} ROWS) REPEATABLE (0)")
    pattern = {f: run.settings.detect[f].replace("'", "''") for f in fs if f in run.settings.detect}
    looks = dict(zip(pattern, run.con.execute("SELECT " + ", ".join(f"avg(regexp_matches({q(f)}, '{p}')::INT)" for f, p in pattern.items())
                                              + " FROM er_fill_sample").fetchall()[0])) if pattern else {}
    top = dict(run.con.execute("""SELECT field, max(n) / sum(n) FROM (SELECT field, v, count(*) AS n FROM
        (UNPIVOT er_fill_sample ON COLUMNS(*) INTO NAME field VALUE v) GROUP BY ALL) GROUP BY field""").fetchall())
    return pd.DataFrame(dict(field=fs, filled=filled, looks_right=[looks.get(f) for f in fs], top_value=[top.get(f) for f in fs])).assign(
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
        sheet = carry_over(run, pd.read_parquet(previous), sheet, previous.parent)
    decide = sheet[sheet["why"] == "decide"]
    queue = pd.DataFrame(dict(why=["decide", "audit"], pairs=[len(decide), len(audit)], from_bits=[lo, t], below_bits=[t, t + 4]))
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
        else:  # no line placed: a written legal form decides
            how = ((f"{c.labels:,} answers, {c.measured:,} of them drawn to measure: a line needs 50 drawn to measure, of both kinds"
                    if c is not None and c.labels else "no answers yet")
                   + "; 2 company only where a legal form is written; answer them (nayose list kinds), then nayose apply answers")
        if c is not None and c.decided:
            how += f"; people decided {len(c.decided):,} records"
        held, unknown = con.execute("SELECT count(*) FILTER (WHERE kind_held AND kind_by <> 'people'), count(*) FILTER (WHERE kind_held AND kind_by = 'people') FROM gold").fetchall()[0]
        if held:
            kind_rows.append(("held back", f"{held:,} records from matching: the engine and the flag disagree; decide them in kind_review.parquet"))
        if unknown:
            kind_rows.append(("held back", f"{unknown:,} records people can't tell: their names stay out of matching, and their pairs come to review.parquet"))
        if c is not None and c.flag_error is not None:
            how += f"; the flag wrong on {c.flag_error:.1%} of {c.flag_checked:,} answers drawn at random"
        kind_rows += [("kinds from", how)] if c is not None else []
        if c is not None and not c.spec.trust_flag and "kind_flag" in run.columns():  # the flag's likely errors, for its owners
            says = "x.kind_flag IN (" + ", ".join(f"'{v}'" for v in c.flag_company) + ")"
            a, b = con.execute(f"""SELECT count(*) FILTER (WHERE g.kind = 2 AND NOT {says}), count(*) FILTER (WHERE g.kind = 1 AND {says})
                                   FROM gold g JOIN records x USING ({u}) WHERE x.kind_flag IS NOT NULL""").fetchall()[0]
            kind_rows.append(("flag", f"a sure kind contradicts it on {a + b:,} records: {a:,} sure 2 company flagged 1, "
                                      f"{b:,} sure 1 person flagged 2 (sent to decide in kind_review.parquet)"))
        if len(mixed):
            kind_rows.append(("note", f"{len(mixed):,} cluster{'s hold' if len(mixed) > 1 else ' holds'} a sure person and a sure company: see qa.md, mixed kinds"))
    summary = pd.DataFrame([
        ("records", f"{total:,}" + (f", {run.added:,} of them new" if run.added is not None else "") + (f"; {aside:,} set aside (set_aside/)" if aside else "")),
        ("entities", f"{entities:,}; the largest holds {biggest:,} records"),
        ("joined by", f"the rules {by_rules:,} · the model {by_model:,} · people {by_people:,} records"),
        ("model links", f"{linked['accepted']:,}{' in this batch' if run.added is not None else ''}; about {linked['expected_false']:,.{1 if linked['expected_false'] >= 1 else 2}f} "
                        "of them false, as the model expects (the sum of 1 − match probability)"),
        ("to decide", f"{len(decide):,} pair{'' if len(decide) == 1 else 's'} in review.parquet (why = decide)"),
        *kind_rows,
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
    cluster sizes, each step's time and memory, the model (the prior, and m, u and bits per level), the costliest
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
    out += ["FIELDS  (looks right, top value: on a sample of 10,000 records)", *table(pd.DataFrame(dict(
        field=fill["field"], filled=fill["filled"].map(pct), looks_right=fill["looks_right"].map(pct), top_value=fill["top_value"].map(pct),
        columns=[sources_text(run.present.get(f)) for f in fill["field"]]))), ""]

    edges = sorted({-20, -10, 0, lo, t, t + 2, t + 4, t + 8, t + 12})
    band = "CASE " + " ".join(f"WHEN match_weight < {b} THEN {i}" for i, b in enumerate(edges)) + f" ELSE {len(edges)} END"
    scored = dict(con.execute(f"SELECT {band}, count(*) FROM scores GROUP BY 1").fetchall())
    accepted = {k: (n, x) for k, n, x in con.execute(f"SELECT {band}, count(*), sum(1 - match_probability) FROM matches GROUP BY 1").fetchall()}
    label = lambda i: f"below {edges[0]:g}" if i == 0 else f"{edges[-1]:g} and up" if i == len(edges) else f"{edges[i - 1]:g} to {edges[i]:g}"
    out += [f"SCORES  (bits; review from {lo:g}, accept from {t:g}; expected false = the sum of 1 − match probability)", *table(pd.DataFrame(
        [dict(bits=label(i), candidates=f"{scored[i]:,}", accepted=f"{accepted.get(i, (0, 0))[0]:,}", expected_false=f"{accepted.get(i, (0, 0))[1]:.2f}")
         for i in sorted(scored)])), ""]

    sizes = tables["cluster_sizes"]
    by = pd.cut(sizes["cluster_size"], [0, 1, 2, 3, 4, 9, 49, np.inf], labels=["1", "2", "3", "4", "5–9", "10–49", "50+"])
    out += ["CLUSTERS  (size: how many)", "  " + " · ".join(f"{k}: {v:,}" for k, v in sizes.groupby(by, observed=True)["clusters"].sum().items()), ""]

    steps = tables["steps"]
    out += ["STEPS", *table(steps[["step", "seconds", "peak_memory_gb", "facts"]].rename(columns={"peak_memory_gb": "peak_gb"})), ""]

    lam, m = scaled_prior(run.scoring, run.n), run.scoring["er"]
    params = parameters(run.scoring)
    out += [f"MODEL  (prior {math.log2(lam / (1 - lam)):.2f} bits at {run.n:,} records; fitted on {m['fit_rows']:,} records"
            + (f"; learned nothing about {', '.join(m['skipped'])}" if m.get("skipped") else "") + ")", *table(pd.DataFrame(dict(
                comparison=params["comparison"], level=params["level"], m=params["m"].map(lambda x: f"{x:.4f}" if x >= 1e-3 else f"{x:.2e}"),
                u=params["u"].map(lambda x: f"{x:.2e}"), bits=params["weight"].map(lambda x: f"{x:.2f}")))), ""]

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

def carry_over(run: "Run", previous: pd.DataFrame, sheet: pd.DataFrame, out: Path) -> pd.DataFrame:
    """The open review queue across increments: the previous sheet's decide rows that nobody gave back yet (none in
    decisions/) and whose records are still in different clusters, or that hold a decision typed in but not given back,
    with this run's new rows; this run's audit rows only. O(previous rows)."""
    l, r, u = q(run.l), q(run.r), q(run.uid)
    prev = previous[previous["why"] == "decide"] if "why" in previous else previous.iloc[:0]  # a sheet from before the queue: nothing to keep
    if prev.empty:
        return sheet
    run.con.register("er_prev", prev[[run.l, run.r, "decision"]])
    stored = (f"SELECT {l}, {r} FROM read_parquet({lit(out / DECISIONS / 'part-*.parquet')})"
              if any((out / DECISIONS).glob("part-*.parquet")) else f"SELECT NULL AS {l}, NULL AS {r} WHERE FALSE")
    keep = run.con.execute(f"""SELECT p.{l}, p.{r} FROM er_prev p JOIN gold a ON a.{u} = p.{l} JOIN gold b ON b.{u} = p.{r}
        WHERE (p.decision IS NOT NULL OR a.cluster_id <> b.cluster_id)
          AND NOT EXISTS (SELECT 1 FROM ({stored}) d WHERE d.{l} = p.{l} AND d.{r} = p.{r})""").df()
    run.con.unregister("er_prev")
    kept = prev.merge(keep, on=[run.l, run.r])
    new = sheet[(sheet["why"] == "decide") & ~sheet.set_index([run.l, run.r]).index.isin(kept.set_index([run.l, run.r]).index)]
    decide = pd.concat([new, kept[sheet.columns]], ignore_index=True).sort_values("match_weight", ascending=False, ignore_index=True)
    return pd.concat([decide, sheet[sheet["why"] == "audit"]], ignore_index=True)


def review_sheet(run: "Run", pairs: pd.DataFrame) -> pd.DataFrame:
    """Scored pairs as people judge them, in the order given: both records' compared fields side by side, and per
    comparison the level the pair landed in and the bits it earned, which with the prior sum to its weight; whether the
    run accepted it (in matches); an empty `decision` for people to fill in (match or no_match) and give to Run.decide. O(pairs)."""
    comps, uid = run.pipeline.fs.model.comparisons, run.uid
    fields = [f for f in dict.fromkeys(col for c in comps for col in (*c.null_if_missing, *(x for lv in c.levels for x, _ in lv.any_of)))
              if f in run.columns()]
    run.con.register("er_review_ids", pd.DataFrame({uid: pd.concat([pairs[run.l], pairs[run.r]]).unique()}))
    records = run.con.sql(f"SELECT {', '.join(q(c) for c in [uid, *fields])} FROM records JOIN er_review_ids USING ({q(uid)})").df()
    run.con.unregister("er_review_ids")
    run.con.register("er_review_pairs", pairs[[run.l, run.r]])
    accepted = run.con.sql(f"SELECT p.*, m.{q(run.l)} IS NOT NULL AS accepted FROM er_review_pairs p LEFT JOIN matches m USING ({q(run.l)}, {q(run.r)})").df()
    run.con.unregister("er_review_pairs")
    out = pairs.merge(accepted, on=[run.l, run.r]).merge(records.add_suffix("_l"), on=run.l).merge(records.add_suffix("_r"), on=run.r)
    out["decision"] = pd.Series(pd.NA, index=out.index, dtype="string")
    by_gamma = levels(run.scoring)
    for c in comps:
        gamma = out.pop(f"gamma_{c.name}").astype(int)
        out[c.name] = gamma.map(lambda g: by_gamma[c.name][g][0])
        out[f"{c.name}_bits"] = gamma.map(lambda g: round(by_gamma[c.name][g][1], 2))
    return out[[*(["why"] if "why" in out else []), "decision", run.l, run.r, "match_weight", "match_probability", "accepted", "sources",
                *(f"{f}_{side}" for f in fields for side in ("l", "r")), *(x for c in comps for x in (c.name, f"{c.name}_bits"))]
               ].reset_index(drop=True)


def applied(out: Path, uid: str) -> pd.DataFrame:  # each pair's latest decision the folder holds
    parts = sorted((out / DECISIONS).glob("part-*.parquet"))
    if not parts:
        return pd.DataFrame(columns=[f"{uid}_l", f"{uid}_r", "decision"])
    return pd.concat([pd.read_parquet(f) for f in parts]).drop_duplicates([f"{uid}_l", f"{uid}_r"], keep="last")


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
    log = json.loads((out / "steps.json").read_text(encoding="utf-8"))["runs"] if (out / "steps.json").exists() else []
    runs = [dict(at=x["at"], what="decisions" if "decisions" in x else "increment" if x.get("part") else "full run",
                 files=[f["file"] for f in x.get("inputs", []) if f.get("role") != "name model"],
                 seconds=round(sum(step["seconds"] for step in x["steps"]), 1)) for x in log]

    def queue(sheet: str, answer: str, whys: tuple[str, ...]) -> dict:  # each kind of row still open, and the answers written in, not yet applied
        rows = pd.read_parquet(out / sheet) if (out / sheet).exists() else pd.DataFrame(columns=["why", answer])
        written = rows[answer].notna()
        if answer == "decision" and len(rows):  # a decision applied since stays in the sheet until the next run writes it
            done = rows.merge(applied(out, uid), on=[f"{uid}_l", f"{uid}_r"], how="left", suffixes=("", "_applied"))["decision_applied"]
            written &= ~(done == rows["decision"]).fillna(False).to_numpy()
        return {**{w: int(((rows["why"] == w) & rows[answer].isna()).sum()) for w in whys}, "written_in": int(written.sum())}
    aside = out / "set_aside"
    summary = table_after((out / "qa.md").read_text(encoding="utf-8"), "## summary") if (out / "qa.md").exists() else pd.DataFrame()
    return dict(workspace=str(out), records=records, entities=entities, largest=[dict(entity=e, records=n) for e, n in largest], runs=runs,
                pairs=queue("review.parquet", "decision", ("decide", "audit")), kinds=queue("kind_review.parquet", "kind", ("decide", "measure")),
                set_aside=con.execute(f"SELECT count(*) FROM read_parquet({lit(aside / '*.parquet')})").fetchall()[0][0]
                if any(aside.glob("*.parquet")) else 0,
                write_owed=(out / PENDING).exists(), summary=summary.values.tolist())


def describe_entity(con: duckdb.DuckDBPyConnection, out: Path, uid: str, record: str, fields: list[str]) -> dict:
    """The entity of `record` in the workspace `out`: each of its records with its fields and kind, and every link
    between them, from a rule (rule_kept), the model (matches, with its weight) or people (decisions). O(N) in SQL."""
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    gold = f"read_parquet({lit(out / 'gold.parquet')})"
    if not (out / "gold.parquet").exists():
        raise InputError(f"no run in {out}", fix="resolve records into that folder first")
    if not (hit := con.execute(f"SELECT cluster_id FROM {gold} WHERE {u} = ?", [record]).fetchall()):
        raise InputError(f"{record}: no record of the run in {out}",
                         fix="check the ID as the run wrote it: a spreadsheet may read 0000000151 as the number 151")
    entity = hit[0][0]
    con.execute(f"CREATE OR REPLACE TEMP TABLE er_entity AS SELECT * FROM {gold} WHERE cluster_id = ?", [entity])
    stored = f"read_parquet({lit(out / 'state' / 'records' / '*.parquet')}, union_by_name = true)"
    have = [f for f, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM {stored})").fetchall() if f in fields]
    rows = con.execute(f"SELECT e.*, {', '.join(f's.{q(f)}' for f in have) or 'NULL AS none'} FROM er_entity e "
                       f"JOIN {stored} s USING ({u}) ORDER BY e.{u}").df()
    among = f"WHERE {l} IN (SELECT {u} FROM er_entity) AND {r} IN (SELECT {u} FROM er_entity)"
    links = [f"SELECT {l}, {r}, rule AS by, NULL::DOUBLE AS weight FROM read_parquet({lit(out / 'rule_kept' / '*.parquet')}) {among}",
             f"SELECT {l}, {r}, 'fs' AS by, match_weight AS weight FROM read_parquet({lit(out / 'matches' / '*.parquet')}) {among}"]
    if any((out / DECISIONS).glob("*.parquet")):
        links.append(f"SELECT {l}, {r}, 'people: ' || decision AS by, NULL FROM read_parquet({lit(out / DECISIONS / '*.parquet')}) {among}")
    found = con.execute(" UNION ALL ".join(links) + " ORDER BY 1, 2").df()
    plain = lambda d: d.astype(object).where(d.notna(), None).to_dict("records")  # JSON has no NaN
    return dict(record=record, entity=entity, records=plain(rows), links=plain(found))


GRAPH_NODES = ("records", "prepare", "rules", "candidates", "score", "accept", "people", "group", "kind", "customers")


def describe_matching(con: duckdb.DuckDBPyConnection, out: Path | None, p: Pipeline, s: "Settings") -> dict:
    """The pipeline as a graph, for people to see what is computed and how: one node per stage (GRAPH_NODES) with its
    method and parameters and the fields it reads, and the edges between them. With `out`, a written run, each node also
    holds the run's numbers (records, pairs per rule and per generator, each level's m, u and bits, the weight bands,
    accepted pairs, pairs for people, customers) and real examples. O(E + R + N) in SQL over the run's files."""
    uid, ran = s.data.unique_id, out is not None and (out / "gold.parquet").exists()
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    rows = lambda sql: con.execute(sql).fetchall() if ran else []
    parquet = lambda name: f"read_parquet({lit(out / name)}, union_by_name = true)" if ran else ""  # no run: nothing to read
    log = json.loads((out / "steps.json").read_text(encoding="utf-8"))["runs"] if ran and (out / "steps.json").exists() else []
    facts = [x for run in log for x in run["steps"]]
    key = lambda k: dict(field=k.column, normalize=list(k.normalize))
    n = rows(f"SELECT count(*) FROM {parquet('gold.parquet')}")[0][0] if ran else None

    # prepare: each field's columns, how it is made comparable, how full it is, and one real record
    stored = parquet("state/records/*.parquet")
    have = {c for c, in rows(f"SELECT column_name FROM (DESCRIBE SELECT * FROM {stored})")}
    variants = {}
    for col, norm in [*p.rules.normalized(), *p.fs.normalized()]:
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
    kept = {name: (k, a, b) for name, k, a, b in rows(f"SELECT rule, count(*), min({l}), arg_min({r}, {l}) FROM {parquet('rule_kept/*.parquet')} GROUP BY 1")}
    rules = [dict(stage=st.name, name=x.name, exact=list(x.exact),
                  fuzzy=[dict(field=c, function=st.comparators[c].function, threshold=st.comparators[c].threshold,
                              normalize=list(st.comparators[c].normalize)) for c in x.fuzzy],
                  blocking=[key(k) for k in x.blocking], pairs=kept.get(x.name, (0,))[0] if ran else None,
                  example=list(kept[x.name][1:]) if x.name in kept else None) for _, st, x in p.rules.each()]

    # candidates: each generator, its method, the pairs it listed, the accepted pairs it found, and one of them
    listed = {}
    for x in facts:
        for g in x.get("generators", ()):
            listed[g["name"]] = listed.get(g["name"], 0) + g["pairs"]
    found = {g: (k, a, b) for g, k, a, b in rows(f"""SELECT g, count(*), min(a), arg_min(b, a) FROM (SELECT unnest(string_split(sources, '+')) AS g,
        {l} AS a, {r} AS b FROM {parquet('matches/*.parquet')}) GROUP BY 1""")}
    generators = []
    for b in p.fs.blockers:
        match b:
            case KeyBlocker():
                how = dict(method="same value", keys=[key(k) for k in b.keys])
            case SortedNeighbourhood():
                how = dict(method="sorted neighbours", keys=[key(b.key)], window=b.window)
            case TfidfNeighbours():
                how = dict(method="TF-IDF nearest", keys=[key(b.key)], ngram=list(b.ngram), k=b.k, min_cosine=b.min_cosine)
            case DeletionKeys():
                how = dict(method="one letter deleted", keys=[key(b.key)], within=[key(k) for k in b.within])
        generators.append(dict(name=b.name, **how, pairs=listed.get(b.name) if ran else None, matched=found.get(b.name, (0,))[0] if ran else None,
                               example=list(found[b.name][1:]) if b.name in found else None))

    # score: each comparison's levels, the tests behind each, and what the fitted model says each is worth
    model = None
    if ran:
        scoring = out / "state" / "scoring.json"
        model = (json.loads(scoring.read_text(encoding="utf-8"))["model"] if scoring.exists()
                 else json.loads((out / "state" / "model.json").read_text(encoding="utf-8")))
    worth = {(x.comparison, x.level): (x.m, x.u, x.weight) for x in parameters(model).itertuples()} if model else {}
    comparisons = [dict(name=c.name, levels=[dict(label=lv.label, tests=[dict(field=col, function=t.function, threshold=t.threshold,
                                                                                normalize=list(t.normalize)) for col, t in lv.any_of],
                                                   **dict(zip(("m", "u", "bits"), worth.get((c.name, lv.label), (None,) * 3))))
                                              for lv in c.levels] + [dict(label=ELSE, tests=[], **dict(zip(("m", "u", "bits"), worth.get((c.name, ELSE), (None,) * 3))))])
                   for c in p.fs.model.comparisons]
    lam = scaled_prior(model, n) if model else None
    scored = sum(x.get("candidates", 0) for x in facts if x["step"] == "candidates") if ran else None

    # accept, people, group: the line, the band below it for people, and what joined into customers
    bands = table_after((out / "qa.md").read_text(encoding="utf-8"), "## weight bands").values.tolist() if ran and (out / "qa.md").exists() else []
    accepted = rows(f"SELECT count(*) FROM {parquet('matches/*.parquet')}")[0][0] if ran else None
    rule_pairs = sum(v[0] for v in kept.values()) if ran else None
    review = pd.read_parquet(out / "review.parquet") if ran and (out / "review.parquet").exists() else None
    decided = rows(f"SELECT count(*) FROM {parquet(DECISIONS + '/*.parquet')}")[0][0] if ran and any((out / DECISIONS).glob("*.parquet")) else 0
    by = dict(rows(f"SELECT resolved_by, count(*) FROM {parquet('gold.parquet')} WHERE resolved_by = 'review' GROUP BY 1"))
    sizes = rows(f"SELECT n, count(*) FROM (SELECT count(*) AS n FROM {parquet('gold.parquet')} GROUP BY cluster_id) GROUP BY 1 ORDER BY 1")
    customers = sum(k for _, k in sizes) if ran else None
    kinds = dict(rows(f"SELECT kind, count(*) FROM {parquet('gold.parquet')} GROUP BY 1")) if ran and "kind" in {
        c for c, in rows(f"SELECT column_name FROM (DESCRIBE SELECT * FROM {parquet('gold.parquet')})")} else {}
    open_ = int(((review["why"] == "decide") & review["decision"].isna()).sum()) if review is not None else None
    nodes = [
        dict(id="records", name="Records", count=n, files=[f["file"] for run in log for f in run.get("inputs", []) if f.get("role") == "records"]),
        dict(id="prepare", name="Make values comparable", method="normalizers per field", fields=fields),
        dict(id="rules", name="Rules", method="certain cases first: exact, then fuzzy", rules=rules, pairs=rule_pairs),
        dict(id="candidates", name="Candidates", method="list the pairs worth comparing", generators=generators, pairs=scored),
        dict(id="score", name="Score", method="Fellegi–Sunter: each comparison adds evidence, in bits", comparisons=comparisons,
             prior_bits=math.log2(lam / (1 - lam)) if lam else None, pairs=scored),
        dict(id="accept", name="Accept", method="at the line, with a name compared", threshold=p.fs.min_match_weight, review_from=review_floor(p),
             needs=list(p.fs.needs), bands=bands, accepted=accepted),
        dict(id="people", name="People decide", method="close calls go to people", to_decide=open_, decided=decided, joined=by.get("review", 0) if ran else None),
        dict(id="group", name="Group", method="connected components: linked records are one customer", customers=customers,
             sizes=[dict(records=a, customers=k) for a, k in sizes]),
        dict(id="kind", name="Person or company", method="legal form, name model, combiner", on=p.kind is not None,
             legal_forms=len(s.standardize.legal_forms), ngram=p.kind.ngram if p.kind else None,
             counts={"company": kinds.get(2, 0), "person": kinds.get(1, 0), "unsure": kinds.get(0, 0)} if kinds else None),
        dict(id="customers", name="Customers", count=customers),
    ]
    edges = [dict(source=a, target=b, count=c) for a, b, c in (
        ("records", "prepare", n), ("prepare", "rules", n), ("prepare", "candidates", n), ("prepare", "kind", n), ("kind", "score", n),
        ("rules", "group", rule_pairs), ("candidates", "score", scored), ("score", "accept", scored), ("accept", "group", accepted),
        ("accept", "people", open_), ("people", "group", decided), ("group", "customers", customers))]
    assert [x["id"] for x in nodes] == list(GRAPH_NODES)
    return dict(nodes=nodes, edges=edges)



def line_change(decided: pd.DataFrame, t: float) -> tuple[float, int] | None:
    """The acceptance line that sets right the most pairs people decided, against the model alone (accepted: named and
    at the line or above), and sets wrong none it gets right at `t`; the nearest such line on a tie. None: no line
    does better. Rows: weight, named, same (people said match). Lines tried: the half bit at or just below each
    pair's weight, and the next one up. O(D·B) with numpy, D decided, B the half bits between the lowest weight and the highest."""
    if decided.empty:
        return None
    w, named, same = decided["weight"].to_numpy(), decided["named"].to_numpy(bool), decided["same"].to_numpy(bool)
    right = lambda x: (named & (w >= x)) == same
    now, best = right(t), None
    for x in sorted({float(v) for f in np.floor(w * 2) / 2 for v in (f, f + 0.5)}):
        at = right(x)
        if (now & ~at).any():
            continue
        fixes = int((at & ~now).sum())
        if fixes and (best is None or (fixes, -abs(x - t)) > (best[1], -abs(best[0] - t))):
            best = (x, fixes)
    return best


def describe_method(out: Path, p: Pipeline, s: "Settings") -> dict:
    """What the run in the workspace `out` shows about its method, for people improving it: each round so far
    (rounds.json), with the links it made and the audits people decided in it; the line, the weight bands, and each pair
    people decided, scored again with the run's model; each sure-match rule's pairs, how many of them score below the
    line, and how many people said are different; each pair key's pairs and seconds, the links it found and those only
    it found; each comparison step's bits and the pairs that reached it; and the changes worth trying. Changes nothing.
    O((D + R)·K) to score the D decided pairs and the R rule pairs again, + O(E) over the run's files."""
    from scipy.stats import beta

    from er.strings import connect
    if not (out / "gold.parquet").exists():
        raise InputError(f"no run in {out}", fix="find matches first: nayose resolve records --workspace …")
    uid, t, fs = s.data.unique_id, p.fs.min_match_weight, p.fs
    l, r = f"{uid}_l", f"{uid}_r"
    con, db = connect(s.compute)
    read = lambda name: f"read_parquet({lit(out / name)}, union_by_name = true)"
    scoring = out / "state" / "scoring.json"
    model = json.loads(scoring.read_text(encoding="utf-8"))["model"] if scoring.exists() else json.loads((out / "state" / "model.json").read_text(encoding="utf-8"))
    n = con.execute(f"SELECT count(*) FROM {read('gold.parquet')}").fetchall()[0][0]

    # the pairs people decided, the latest decision per pair, and the rules' pairs: scored again, with the name check
    parts = out / DECISIONS / "part-*.parquet"
    con.execute(f"""CREATE TABLE er_decided AS SELECT {q(l)}, {q(r)}, arg_max(decision, filename) AS decision, arg_max(why, filename) AS why,
        arg_max(round, filename) AS round FROM read_parquet({lit(parts)}, filename = true, union_by_name = true) GROUP BY ALL"""
                if any(parts.parent.glob("part-*.parquet")) else
                f"CREATE TABLE er_decided ({q(l)} VARCHAR, {q(r)} VARCHAR, decision VARCHAR, why VARCHAR, round INTEGER)")
    con.execute(f"CREATE TABLE er_rule AS SELECT {q(l)}, {q(r)}, rule FROM {read('rule_kept/*.parquet')}")
    con.execute(f"CREATE TABLE er_pairs AS SELECT {q(l)}, {q(r)} FROM er_decided UNION SELECT {q(l)}, {q(r)} FROM er_rule")
    con.execute(f"""CREATE TABLE er_touched AS SELECT * FROM {read('state/records/*.parquet')}
        WHERE {q(uid)} IN (SELECT {q(l)} FROM er_pairs UNION SELECT {q(r)} FROM er_pairs)""")
    score_fs(model, "er_touched", "er_pairs", db, uid, into="er_scored", n_records=n)
    scored = f"SELECT {q(l)}, {q(r)}, match_weight AS weight, {named_sql(fs)} AS named FROM er_scored s"
    decided = con.execute(f"""SELECT d.*, s.weight, s.named, d.decision = 'match' AS same, x.rule FROM er_decided d JOIN ({scored}) s USING ({q(l)}, {q(r)})
        LEFT JOIN (SELECT {q(l)}, {q(r)}, min(rule) AS rule FROM er_rule GROUP BY ALL) x USING ({q(l)}, {q(r)}) ORDER BY s.weight""").df()
    rules = {name: (pairs, below, apart) for name, pairs, below, apart in con.execute(f"""SELECT x.rule, count(*), count(*) FILTER (WHERE s.weight < {t} OR NOT s.named),
        count(d.decision) FILTER (WHERE d.decision = 'no_match') FROM er_rule x JOIN ({scored}) s USING ({q(l)}, {q(r)})
        LEFT JOIN er_decided d USING ({q(l)}, {q(r)}) GROUP BY 1""").fetchall()}

    # what the run's log and files say: the rounds, each key's pairs and seconds, each step's reach, the links by key
    log = json.loads((out / "steps.json").read_text(encoding="utf-8"))["runs"] if (out / "steps.json").exists() else []
    facts = [x for run in log for x in run["steps"]]
    listed, reached = {}, {}
    for x in facts:
        for g in x.get("generators", ()):
            pairs, seconds = listed.get(g["name"], (0, 0.0))
            listed[g["name"]] = (pairs + g["pairs"], seconds + g["seconds"])
        for c, by in x.get("reached", {}).items():
            for g, k in by.items():
                reached[(c, int(g))] = reached.get((c, int(g)), 0) + k
    found = {g: (k, only) for g, k, only in con.execute(f"""SELECT g, count(*), count(*) FILTER (WHERE alone)
        FROM (SELECT unnest(string_split(sources, '+')) AS g, NOT contains(sources, '+') AS alone FROM {read('matches/*.parquet')}) GROUP BY 1""").fetchall()}
    ran = rounds(out)
    now = len(ran)
    audits = decided[(decided["why"] == "audit") & (decided["round"] == now)] if now else decided.iloc[:0]
    false = int((~audits["same"].astype(bool)).sum())
    review = pd.read_parquet(out / "review.parquet") if (out / "review.parquet").exists() else pd.DataFrame(columns=["why", "decision"])
    bands = table_after((out / "qa.md").read_text(encoding="utf-8"), "## weight bands").values.tolist() if (out / "qa.md").exists() else []
    by_round = lambda i, x: decided[(decided["round"] == i) & x(decided)]
    ran = [dict(round=i, method=x["method"], at=x["at"], matched=x["matched"], expected_false=x["expected_false"],
                   decided=len(by_round(i, lambda d: True)), audited=len(by_round(i, lambda d: d["why"] == "audit")),
                   false_found=len(by_round(i, lambda d: (d["why"] == "audit") & ~d["same"].astype(bool))))
              for i, x in enumerate(ran, 1)]

    # the changes worth trying: none applies itself
    proposals = []
    if line := line_change(decided[decided["rule"].isna()], t):
        proposals.append(dict(change=dict(line=line[0]), why=f"sets right {line[1]:,} pair{'s' if line[1] > 1 else ''} people decided, and wrong none"))
    proposals += [dict(change=dict(drop_rules=[name]), why=f"people said {apart:,} of its pairs {'are' if apart > 1 else 'is'} different")
                  for name, (_, _, apart) in rules.items() if apart]
    total = sum(pairs for pairs, _ in listed.values())  # a key worth leaving out: a tenth of the pairs or more, and no link only it finds
    proposals += [dict(change=dict(drop_keys=[b.name]), why=f"{listed[b.name][0] / total:.0%} of the pairs, and no link only it finds")
                  for b in fs.blockers if listed.get(b.name, (0,))[0] >= total / 10 and not found.get(b.name, (0, 0))[1]]
    by_gamma = levels(model)
    return dict(
        line=t, review_from=review_floor(p), method=method(out), round=now, rounds=ran,
        audits=dict(checked=len(audits), false=false,  # the false rate's one-sided 95% bound, as er.evaluate.fp_upper (design time)
                    at_most=float(beta.ppf(0.95, false + 1, len(audits) - false)) if len(audits) > false else 1.0),
        to_decide=int(((review["why"] == "decide") & review["decision"].isna()).sum()),
        bands=[dict(weight_from=float(a), pairs=int(b), accepted=int(c)) for a, b, c in bands],
        decided=[dict(id_l=x[l], id_r=x[r], decision=x["decision"], why=x["why"], round=None if pd.isna(x["round"]) else int(x["round"]),
                      weight=round(float(x["weight"]), 2), named=bool(x["named"]), rule=x["rule"]) for x in decided.to_dict("records")],
        rules=[dict(name=x.name, pairs=rules.get(x.name, (0, 0, 0))[0], below=rules.get(x.name, (0, 0, 0))[1],
                    different=rules.get(x.name, (0, 0, 0))[2]) for _, _, x in p.rules.each()],
        keys=[dict(name=b.name, pairs=listed.get(b.name, (0, 0.0))[0], seconds=round(listed.get(b.name, (0, 0.0))[1], 2),
                   matched=found.get(b.name, (0, 0))[0], only=found.get(b.name, (0, 0))[1]) for b in fs.blockers],
        steps=[dict(comparison=c, level=label, bits=round(bits, 2), reached=reached.get((c, g), 0))
               for c, by in by_gamma.items() for g, (label, bits) in sorted(by.items(), reverse=True)],
        proposals=proposals)
