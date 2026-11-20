"""What a finished run holds, for people to see without running anything again (the pages Results, Review and
Explore): the pairs it scored at 0 points or more, each with the level every comparison reached (scored/); its
entities; each record's full row as the file gave it; and the conditions under which pairs merge without people.

Everything here reads the workspace's own files. The pair index alone is written, once, for a workspace whose run
kept none (written before runs did): from the pairs that run stored, rescored, never by running again."""
import math
from dataclasses import replace
from pathlib import Path

import duckdb

from er import folder
from er.cluster import merge
from er.config import InputError, Pipeline, bits, lit, q
from er.match import levels, named_sql
from er.report import no_run
from er.explain import run_model, scored_again
from er.review_state import applied, read, said
from er.settings import Settings

BANDS = (-20, -10, 0, 6, 8, 10, 12, 16, 20)  # the score chart's edges, in points: as report.txt's SCORES


def banded(col: str = "match_weight") -> str:  # the SQL of a weight's band in the score chart: 0 below BANDS[0], len(BANDS) at its last edge or above
    return "CASE " + " ".join(f"WHEN {col} < {e} THEN {i}" for i, e in enumerate(BANDS)) + f" ELSE {len(BANDS)} END"
SIZES = ((1, 1, "1 record"), (2, 2, "2 records"), (3, 9, "3–9"), (10, 49, "10–49"), (50, None, "50 or more"))


def joined_by(p: Pipeline) -> str:  # gold's resolved_by as people read it: you, the model, or a rule
    return f"CASE WHEN resolved_by = 'review' THEN 'you' WHEN resolved_by = {lit(p.fs.model.name)} THEN 'model' WHEN resolved_by IS NOT NULL THEN 'rule' END"


def pair_index(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, p: Pipeline) -> str:
    """scored/ as SQL: every pair the run scored at 0 points or more, the rules' pairs too, with how it was found
    (sources: its keys; rule: the rule that matched it), whether a name was compared (named) and one gamma per
    comparison. A run written before runs kept it gets it here, once, from the pairs it stored (matches/, proposed/,
    rule_kept/, the sheet's pairs to decide), rescored: O(N + P·K) once, under the lock; O(1) after."""
    index = out / folder.SCORED
    if not any(index.glob("part-*.parquet")):
        with folder.run_lock(out):
            folder.finish_writes(out)  # a write cut short is finished first: staging the index replaces its list of moves
            if not any(index.glob("part-*.parquet")):
                _index(con, out, s, p)
    return read(out, f"{folder.SCORED}/*.parquet")


def _index(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, p: Pipeline) -> None:
    uid = s.data.unique_id
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    have = lambda name: any((out / name).glob("*.parquet"))
    parts = [f"SELECT {l}, {r}, match_weight, sources, NULL::VARCHAR AS rule, 'model' AS part FROM {read(out, x + '/*.parquet')}" for x in ("matches", "proposed") if have(x)]
    parts += [f"SELECT {l}, {r}, match_weight, NULL::VARCHAR AS sources, rule, 'rule' AS part FROM {read(out, 'rule_kept/*.parquet')}"] if have("rule_kept") else []
    if (out / "review.parquet").exists():
        parts.append(f"SELECT {l}, {r}, match_weight, sources, NULL::VARCHAR AS rule, 'sheet' AS part FROM read_parquet({lit(out / 'review.parquet')}) WHERE why = 'decide'")
    if not parts:
        raise no_run(out)
    # the sheet names a rule pair's rule where a model pair's keys go: a rule pair's keys come from the model's files alone
    con.execute(f"""CREATE OR REPLACE TABLE er_index AS SELECT {l}, {r}, max(match_weight) AS match_weight, coalesce(max(sources) FILTER (WHERE part = 'model'),
        CASE WHEN bool_or(part = 'rule') THEN NULL ELSE max(sources) END) AS sources, max(rule) AS rule
        FROM ({' UNION ALL BY NAME '.join(parts)}) WHERE {l} IS NOT NULL GROUP BY {l}, {r}""")
    scored_again(con, out, uid, "er_index", "er_index_scores")
    gammas = [c for c, *_ in con.execute("DESCRIBE er_index_scores").fetchall() if c.startswith("gamma_")]
    fs = replace(p.fs, needs=tuple(c for c in p.fs.needs if f"gamma_{c}" in gammas))  # the name check on the comparisons that run had
    con.execute(f"""CREATE OR REPLACE TABLE er_scored_index AS SELECT i.{l}, i.{r}, coalesce(i.match_weight, x.match_weight) AS match_weight,
        x.match_probability, i.sources, i.rule, {named_sql(fs, 'x')} AS named, TRUE AS keep, {', '.join(f'x.{q(g)}' for g in gammas)}
        FROM er_index i JOIN er_index_scores x USING ({l}, {r})""")
    folder.stage(con, out, [("SELECT * FROM er_scored_index", out / folder.SCORED / "part-00000.parquet")])


def _status_sql(con: duckdb.DuckDBPyConnection, out: Path, uid: str, index: str) -> str:
    """The index with each pair's status: same / different (people's), merged (one entity already), waiting."""
    l, r, u = q(f"{uid}_l"), q(f"{uid}_r"), q(uid)
    con.register("er_said", said(out, uid))
    return f"""SELECT x.*, d.decision AS said, d.applied, CASE WHEN d.decision = 'match' THEN 'same' WHEN d.decision = 'no_match' THEN 'different'
            WHEN ga.cluster_id = gb.cluster_id THEN 'merged' ELSE 'waiting' END AS status
        FROM {index} x LEFT JOIN er_said d USING ({l}, {r})
        JOIN {read(out, 'gold.parquet')} ga ON ga.{u} = x.{l} JOIN {read(out, 'gold.parquet')} gb ON gb.{u} = x.{r}"""


def _full_run_patterns(out: Path) -> dict | None:
    full = [x for run in folder.runs(out) if not run.get("part") for x in run.get("steps", []) if x["step"] == "score" and x.get("patterns")]
    return full[-1]["patterns"] if full else None


def describe_results(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, p: Pipeline, review_from: float = 6.0) -> dict:
    """What the run found, for the Results page: how the scores came out (every pair the run scored, each by its own
    points: the full run's and each increment's bands, as they logged them; a run logged before them, the full run's
    patterns, each pattern at its mean weight; the rules' own pairs from the pair index), the pairs waiting for people from `review_from` up, by range, what
    merged and how, entities by size, the merge conditions and what they merge, whether matches could be missed (the
    probe), the groups too big to compare by the key that made them, and person or company: the records flagged (the
    engine sure against the file's flag). O(N + P + E)."""
    uid, gold = s.data.unique_id, read(out, "gold.parquet")
    index, chart, counts = pair_index(con, out, s, p), None, None
    scored = [x for run in folder.runs(out) for x in run.get("steps", []) if x["step"] == "score"]
    if scored and all("bands" in x for x in scored):  # the keys' pairs, each by its own weight: the full run's and each increment's
        counts = [sum(n) for n in zip(*(x["bands"] for x in scored))]
    elif pats := _full_run_patterns(out):  # logged before the bands: the full run's patterns, each at its mean weight; an increment's pairs uncounted
        counts, k = [0] * (len(BANDS) + 1), len(pats["fields"])
        for row in pats["rows"]:
            counts[sum(float(row[k + 1]) >= e for e in BANDS)] += int(row[k])
    if counts is not None:  # and the rules' pairs the keys did not list, from the index
        for i, n in con.execute(f"SELECT {banded()}, count(*) FROM {index} WHERE rule IS NOT NULL AND sources IS NULL GROUP BY 1").fetchall():
            counts[i] += n
        edges = [float("-inf"), *BANDS, float("inf")]
        chart = [dict(down_to=None if edges[i] == float("-inf") else edges[i], up_to=None if edges[i + 1] == float("inf") else edges[i + 1], pairs=n)
                 for i, n in enumerate(counts)]
        if unscored := sum(x.get("unscored", 0) for x in scored):  # pairs a bound put below 0, never scored: below 0 is one band
            chart = [dict(down_to=None, up_to=0, pairs=sum(x["pairs"] for x in chart if x["up_to"] is not None and x["up_to"] <= 0) + unscored),
                     *(x for x in chart if x["up_to"] is None or x["up_to"] > 0)]
    rows = _status_sql(con, out, uid, index)
    cuts = sorted({review_from, *(c for c in (8.0, 12.0, 20.0) if c > review_from)}, reverse=True)  # the waiting pairs' ranges, from review_from up
    band = "CASE " + " ".join(f"WHEN match_weight >= {bits(c)} THEN {i}" for i, c in enumerate(cuts)) + " END"
    waiting = con.execute(f"""SELECT {band}, count(*) FROM ({rows}) WHERE status = 'waiting' AND match_weight >= {bits(review_from)} GROUP BY 1 ORDER BY 1""").fetchall()
    by_status = dict(con.execute(f"SELECT status, count(*) FROM ({rows}) GROUP BY 1").fetchall())
    sizes = con.execute(f"SELECT n, count(*) FROM (SELECT count(*) AS n FROM {gold} GROUP BY cluster_id) GROUP BY 1").fetchall()
    size_of = lambda lo, hi: sum(c for n, c in sizes if n >= lo and (hi is None or n <= hi))
    joined = dict(con.execute(f"SELECT coalesce({joined_by(p)}, 'none'), count(*) FROM {gold} GROUP BY 1").fetchall())
    steps = {x["step"]: x for run in folder.runs(out) if not run.get("part") for x in run.get("steps", [])}
    probe = [dict(stratum=x["stratum"], fields=x["fields"], pairs=x["pairs"], scored=x["scored"], missed=x["missed"], low=x["low"], high=x["high"])
             for x in steps.get("probe", {}).get("strata", [])]
    cand = steps.get("candidates", {})
    has = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {gold}").fetchall()}
    flagged = con.execute(f"SELECT count(*) FROM {gold} WHERE kind_flagged").fetchall()[0][0] if "kind_flagged" in has else 0
    uncounted = 0 if chart is None or all("bands" in x for x in scored) else sum(  # from the full run's patterns: every increment's records left out
        next((x.get("records") or 0 for x in run["steps"] if x["step"] == "load"), 0) for run in folder.runs(out) if run.get("part"))
    listed = con.execute(f"SELECT count(*) FROM {index} WHERE match_weight >= 0").fetchall()[0][0]  # the pairs kept from 0 points
    return dict(records=sum(c * n for n, c in sizes), entities=sum(c for _, c in sizes), joined=size_of(2, None),
                sizes=[dict(label=label, entities=size_of(lo, hi)) for lo, hi, label in SIZES],
                scores=chart, candidates=sum(x["pairs"] for x in chart) if chart else cand.get("candidates"), uncounted=uncounted, listed=listed,
                review_from=review_from, waiting=[dict(down_to=cuts[i], up_to=cuts[i - 1] if i else None, pairs=n) for i, n in waiting],
                pairs=dict(kept=sum(by_status.values()), **by_status), merged_by=joined,
                merging=merging_of(out, p), missed=probe,
                too_big=dict(skipped=cand.get("oversized_skipped", 0), kept=cand.get("oversized_kept", 0), by=cand.get("skipped_by", {}), min=p.fs.budget.min_oversized()),
                kinds=dict(flagged=int(flagged)))


# ---------- merging without people ----------

def merging_of(out: Path, p: Pipeline) -> dict:
    """The workspace's merge conditions (method.toml `merge`): {join: and|or, when: [...]}, none when unset; and what
    the method merges by itself when there are none (own): pairs at `line` points or more with a name compared, and
    with `rules` every rule's pair; None when nothing does (a trust line above every step)."""
    return _merging(folder.method(out), p)


def _merging(method: dict, p: Pipeline) -> dict:  # merging_of, for a method as given
    m = method.get("merge") or {}
    return dict(join=m.get("join", "and"), when=list(m.get("when", [])), own=own_merging(p))


def own_merging(p: Pipeline) -> dict | None:  # what a run merges with no conditions (Run._accept): the tuned threshold, else the trust line
    line = p.trust.line
    return None if line is not None and math.isinf(line) else dict(line=p.fs.min_match_weight if line is None else line, rules=line is None)


def check_merging(m: dict, p: Pipeline, model: dict | None = None) -> dict:
    """`m` as method.toml may hold it, refused with what to fix when a condition names what the method lacks: points
    (a number), rules (rule names), fields (comparison → the lowest level that counts), the comparisons and levels of
    the run's `model` when given (a comparison of a field the file lacks is not in it)."""
    fix = "each condition: {points = 12}, {rules = [\"…\"]} or {fields = {name = \"…\"}}; join = \"and\" or \"or\""
    if not isinstance(m, dict) or m.get("join", "and") not in ("and", "or") or not isinstance(m.get("when", []), list):
        raise InputError("merge: join is \"and\" or \"or\", when a list of conditions", fix)
    rules = {r.name for _, _, r in p.rules.each()}
    labels = {c: [label for label, _ in by.values()] for c, by in levels(model).items()} if model else {c.name: [lv.label for lv in c.levels] for c in p.fs.model.comparisons}
    for c in m.get("when", []):
        if not isinstance(c, dict) or len(c) != 1 or next(iter(c)) not in ("points", "rules", "fields"):
            raise InputError(f"merge: a condition is one of points, rules, fields: {c}", fix)
        (k, v), = c.items()
        if k == "points" and (isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v)):
            raise InputError(f"merge: points is a finite number: {v}", fix)
        if k == "rules" and (not isinstance(v, list) or not v or set(v) - rules):
            raise InputError(f"merge: rules are names among {sorted(rules)}: {v}", fix)
        if k == "fields" and (not isinstance(v, dict) or not v or any(f not in labels or lv not in labels[f] for f, lv in v.items())):
            raise InputError(f"merge: fields are comparisons and one of their levels: {v}", fix=f"{fix}; levels: {labels}")
    return dict(join=m.get("join", "and"), when=list(m.get("when", [])))


def merge_where(m: dict, model: dict, p: Pipeline, x: str = "x") -> str:
    """The pairs the conditions merge, as SQL on scored/ rows aliased `x`. With none, those the method merges by
    itself, as Run._accept does: every rule's pair and the model's kept pairs with a name compared at its threshold,
    or the pairs at the trust line; FALSE with the line above every step."""
    if not m.get("when"):
        own = own_merging(p)
        if own is None:
            return "FALSE"
        rule = "TRUE" if own["rules"] else f"{x}.match_weight >= {bits(own['line'])}"
        return f"(({x}.rule IS NOT NULL AND {rule}) OR ({x}.named AND {x}.keep AND {x}.match_weight >= {bits(own['line'])}))"
    gamma = {c: {label: g for g, (label, _) in by.items()} for c, by in levels(model).items()}
    parts = []
    for c in m["when"]:
        (k, v), = c.items()
        if k == "points":
            parts.append(f"{x}.match_weight >= {bits(v)}")
        elif k == "rules":
            parts.append(f"{x}.rule IN ({', '.join(lit(n) for n in v)})")
        elif all(lv in gamma.get(f, {}) for f, lv in v.items()):
            parts.append("(" + " AND ".join(f"{x}.{q('gamma_' + f)} >= {gamma[f][lv]}" for f, lv in v.items()) + ")")
        else:  # a comparison this run's model lacks (its field gone from the file): never met
            parts.append("FALSE")
    return "(" + f" {m.get('join', 'and').upper()} ".join(parts) + ")"


def _regroup(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, p: Pipeline, m: dict, model: dict) -> None:
    """gold_new: every record's entity from people's "same" and the pairs the conditions merge, people's "different"
    never merged; resolved_by review where people joined it, else the conditions'. O(E·log E + N)."""
    uid = s.data.unique_id
    l, r, u = q(f"{uid}_l"), q(f"{uid}_r"), q(uid)
    con.register("er_applied", applied(out, uid)[[f"{uid}_l", f"{uid}_r", "decision"]])  # what merges is what was applied; typed answers wait for Apply
    index = pair_index(con, out, s, p)
    con.execute(f"""CREATE OR REPLACE TABLE er_auto AS SELECT {l}, {r}, rule FROM {index} x WHERE {merge_where(m, model, p)}
        AND NOT EXISTS (SELECT 1 FROM er_applied d WHERE d.{l} = x.{l} AND d.{r} = x.{r} AND d.decision = 'no_match')""")
    con.execute(f"CREATE OR REPLACE TABLE er_people AS SELECT {l}, {r} FROM er_applied WHERE decision = 'match'")
    con.execute(f"CREATE OR REPLACE TABLE er_base AS SELECT {u}, {u} AS cluster_id FROM {read(out, 'gold.parquet')}")
    con.execute(f"CREATE OR REPLACE TABLE er_links AS SELECT * FROM er_people UNION SELECT {l}, {r} FROM er_auto")
    merge(con, "er_base", "er_links", "gold_new", uid)


def apply_merging(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, p: Pipeline, method: dict | None = None) -> dict:
    """gold.parquet rebuilt from people's applied "same" and the pairs the workspace's conditions merge (none: the pairs
    the method merges by itself), as a run would: a condition turned off parts what it joined, people's answers stand.
    `method`: method.toml as it becomes, written with gold, so the two never disagree. No run: O(E·log E + N) on the
    stored pairs."""
    from er.run import customer_kinds  # er.run reads merge_where from here
    uid, model = s.data.unique_id, run_model(out)
    u = q(uid)
    with folder.run_lock(out):
        m = merging_of(out, p) if method is None else _merging(method, p)
        folder.finish_writes(out)
        _regroup(con, out, s, p, m, model)
        old = read(out, "gold.parquet")
        cols = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {old}").fetchall()}
        kinds = "kind" in cols
        # what resolved each record, as Run._gold says it: a rule pair of it that merged, the first rule; else the model; else people
        order = " ".join(f"WHEN {lit(rule.name)} THEN {i}" for i, _, rule in p.rules.each())
        l, r, fs = q(f"{uid}_l"), q(f"{uid}_r"), p.fs
        con.execute(f"""CREATE OR REPLACE TABLE gold AS WITH size AS (SELECT cluster_id, count(*) AS n FROM gold_new GROUP BY 1),
                touch AS (SELECT {l} AS id, rule FROM er_auto WHERE rule IS NOT NULL UNION ALL SELECT {r}, rule FROM er_auto WHERE rule IS NOT NULL),
                first AS (SELECT id, arg_min(rule, {f"CASE rule {order} END" if order else "rule"}) AS rule FROM touch GROUP BY id),
                model AS (SELECT {l} AS id FROM er_auto WHERE rule IS NULL UNION SELECT {r} FROM er_auto WHERE rule IS NULL)
                {f", customer AS ({customer_kinds('gold_new', old, u)})" if kinds else ""}
            SELECT c.{u}, c.cluster_id,
                   CASE WHEN f.id IS NOT NULL THEN {lit(fs.previous_stage)} WHEN m.id IS NOT NULL THEN {lit(fs.stage)} WHEN z.n > 1 THEN 'review' END AS resolved_stage,
                   CASE WHEN f.id IS NOT NULL THEN f.rule WHEN m.id IS NOT NULL THEN {lit(fs.model.name)} WHEN z.n > 1 THEN 'review' END AS resolved_by
                   {f", o.kind, o.kind_p, o.kind_by, {'o.kind_flagged' if 'kind_flagged' in cols else 'FALSE AS kind_flagged'}, k.customer_kind" if kinds else ""}
            FROM gold_new c JOIN size z USING (cluster_id) JOIN {old} o USING ({u}) LEFT JOIN first f ON f.id = c.{u} LEFT JOIN model m ON m.id = c.{u}
            {"JOIN customer k USING (cluster_id)" if kinds else ""} ORDER BY c.{u}""")
        joined = con.execute("SELECT count(*) FROM (SELECT cluster_id FROM gold GROUP BY 1 HAVING count(*) > 1)").fetchall()[0][0]
        folder.stage(con, out, [(f"SELECT * FROM gold ORDER BY {u}", out / "gold.parquet")],
                     [(folder.method_text(method), out / folder.METHOD)] if method is not None else [])
    return dict(join=m["join"], when=m["when"], entities=int(joined), merged=con.execute("SELECT count(*) FROM er_auto").fetchall()[0][0])


