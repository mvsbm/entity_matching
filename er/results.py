"""What a finished run holds, for people to see without running anything again (the pages Results, Review and
Explore): the pairs it scored at 0 points or more, each with the level every comparison reached (scored/); its
entities; each record's full row as the file gave it; and the conditions under which pairs merge without people.

Everything here reads the workspace's own files. The pair index alone is written, once, for a workspace whose run
kept none (written before runs did): from the pairs that run stored, rescored, never by running again."""
from dataclasses import replace
from pathlib import Path


from er.engine.engine import Engine
from er import folder
from er.config import Pipeline, bits, lit, q
from er.match import named_sql
from er.report import no_run
from er.explain import scored_again
from er.review_state import read, said
from er.settings import Settings

BANDS = (-20, -10, 0, 6, 8, 10, 12, 16, 20)  # the score chart's edges, in points: as report.txt's SCORES


def banded(col: str = "match_weight") -> str:  # the SQL of a weight's band in the score chart: 0 below BANDS[0], len(BANDS) at its last edge or above
    return "CASE " + " ".join(f"WHEN {col} < {e} THEN {i}" for i, e in enumerate(BANDS)) + f" ELSE {len(BANDS)} END"
SIZES = ((1, 1, "1 record"), (2, 2, "2 records"), (3, 9, "3–9"), (10, 49, "10–49"), (50, None, "50 or more"))


def joined_by(p: Pipeline) -> str:  # gold's resolved_by as people read it: you, the model, or a rule
    return f"CASE WHEN resolved_by = 'review' THEN 'you' WHEN resolved_by = {lit(p.fs.model.name)} THEN 'model' WHEN resolved_by IS NOT NULL THEN 'rule' END"


def pair_index(engine: Engine, out: Path, s: Settings, p: Pipeline) -> str:
    """scored/ as SQL: every pair the run scored at 0 points or more, the rules' pairs too, with how it was found
    (sources: its keys; rule: the rule that matched it), whether a name was compared (named) and one gamma per
    comparison. A run written before runs kept it gets it here, once, from the pairs it stored (matches/, proposed/,
    rule_kept/, the sheet's pairs to decide), rescored: O(N + P·K) once, under the lock; O(1) after."""
    index = out / folder.SCORED
    if not any(index.glob("part-*.parquet")):
        with folder.run_lock(out):
            folder.finish_writes(out)  # a write cut short is finished first: staging the index replaces its list of moves
            if not any(index.glob("part-*.parquet")):
                _index(engine, out, s, p)
    return read(out, f"{folder.SCORED}/*.parquet")


def _index(engine: Engine, out: Path, s: Settings, p: Pipeline) -> None:
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
    engine.run(f"""CREATE OR REPLACE TABLE er_index AS SELECT {l}, {r}, max(match_weight) AS match_weight, coalesce(max(sources) FILTER (WHERE part = 'model'),
        CASE WHEN bool_or(part = 'rule') THEN NULL ELSE max(sources) END) AS sources, max(rule) AS rule
        FROM ({' UNION ALL BY NAME '.join(parts)}) WHERE {l} IS NOT NULL GROUP BY {l}, {r}""")
    scored_again(engine, out, uid, "er_index", "er_index_scores")
    gammas = [c for c, *_ in engine.rows("DESCRIBE er_index_scores") if c.startswith("gamma_")]
    fs = replace(p.fs, needs=tuple(c for c in p.fs.needs if f"gamma_{c}" in gammas))  # the name check on the comparisons that run had
    engine.run(f"""CREATE OR REPLACE TABLE er_scored_index AS SELECT i.{l}, i.{r}, coalesce(i.match_weight, x.match_weight) AS match_weight,
        x.match_probability, i.sources, i.rule, {named_sql(fs, 'x')} AS named, TRUE AS keep, {', '.join(f'x.{q(g)}' for g in gammas)}
        FROM er_index i JOIN er_index_scores x USING ({l}, {r})""")
    folder.stage(engine, out, [("SELECT * FROM er_scored_index", out / folder.SCORED / "part-00000.parquet")])


def _status_sql(engine: Engine, out: Path, uid: str, index: str) -> str:
    """The index with each pair's status: same / different (people's), merged (one entity already), waiting."""
    l, r, u = q(f"{uid}_l"), q(f"{uid}_r"), q(uid)
    engine.register("er_said", said(out, uid))
    return f"""SELECT x.*, d.decision AS said, d.applied, CASE WHEN d.decision = 'match' THEN 'same' WHEN d.decision = 'no_match' THEN 'different'
            WHEN ga.cluster_id = gb.cluster_id THEN 'merged' ELSE 'waiting' END AS status
        FROM {index} x LEFT JOIN er_said d USING ({l}, {r})
        JOIN {read(out, 'gold.parquet')} ga ON ga.{u} = x.{l} JOIN {read(out, 'gold.parquet')} gb ON gb.{u} = x.{r}"""


def _full_run_patterns(out: Path) -> dict | None:
    full = [x for run in folder.runs(out) if not run.get("part") for x in run.get("steps", []) if x["step"] == "score" and x.get("patterns")]
    return full[-1]["patterns"] if full else None


def describe_results(engine: Engine, out: Path, s: Settings, p: Pipeline, review_from: float = 6.0) -> dict:
    """What the run found, for the Results page: how the scores came out (every pair the run scored, each by its own
    points: the full run's and each increment's bands, as they logged them; a run logged before them, the full run's
    patterns, each pattern at its mean weight; the rules' own pairs from the pair index), the pairs waiting for people from `review_from` up, by range, what
    merged and how, entities by size, what the run merges without people (merging), the groups too big to compare by the
    key that made them, and person or company: the records flagged (the engine sure against the file's flag). O(N + P + E)."""
    uid, gold = s.data.unique_id, read(out, "gold.parquet")
    index, chart, counts = pair_index(engine, out, s, p), None, None
    scored = [x for run in folder.runs(out) for x in run.get("steps", []) if x["step"] == "score"]
    if scored and all("bands" in x for x in scored):  # the keys' pairs, each by its own weight: the full run's and each increment's
        counts = [sum(n) for n in zip(*(x["bands"] for x in scored))]
    elif pats := _full_run_patterns(out):  # logged before the bands: the full run's patterns, each at its mean weight; an increment's pairs uncounted
        counts, k = [0] * (len(BANDS) + 1), len(pats["fields"])
        for row in pats["rows"]:
            counts[sum(float(row[k + 1]) >= e for e in BANDS)] += int(row[k])
    if counts is not None:  # and the rules' pairs the keys did not list, from the index
        for i, n in engine.rows(f"SELECT {banded()}, count(*) FROM {index} WHERE rule IS NOT NULL AND sources IS NULL GROUP BY 1"):
            counts[i] += n
        edges = [float("-inf"), *BANDS, float("inf")]
        chart = [dict(down_to=None if edges[i] == float("-inf") else edges[i], up_to=None if edges[i + 1] == float("inf") else edges[i + 1], pairs=n)
                 for i, n in enumerate(counts)]
        if unscored := sum(x.get("unscored", 0) for x in scored):  # pairs a bound put below 0, never scored: below 0 is one band
            chart = [dict(down_to=None, up_to=0, pairs=sum(x["pairs"] for x in chart if x["up_to"] is not None and x["up_to"] <= 0) + unscored),
                     *(x for x in chart if x["up_to"] is None or x["up_to"] > 0)]
    rows = _status_sql(engine, out, uid, index)
    cuts = sorted({review_from, *(c for c in (8.0, 12.0, 20.0) if c > review_from)}, reverse=True)  # the waiting pairs' ranges, from review_from up
    band = "CASE " + " ".join(f"WHEN match_weight >= {bits(c)} THEN {i}" for i, c in enumerate(cuts)) + " END"
    waiting = engine.rows(f"""SELECT {band}, count(*) FROM ({rows}) WHERE status = 'waiting' AND match_weight >= {bits(review_from)} GROUP BY 1 ORDER BY 1""")
    by_status = dict(engine.rows(f"SELECT status, count(*) FROM ({rows}) GROUP BY 1"))
    sizes = engine.rows(f"SELECT n, count(*) FROM (SELECT count(*) AS n FROM {gold} GROUP BY cluster_id) GROUP BY 1")
    size_of = lambda lo, hi: sum(c for n, c in sizes if n >= lo and (hi is None or n <= hi))
    joined = dict(engine.rows(f"SELECT coalesce({joined_by(p)}, 'none'), count(*) FROM {gold} GROUP BY 1"))
    steps = {x["step"]: x for run in folder.runs(out) if not run.get("part") for x in run.get("steps", [])}
    cand = steps.get("candidates", {})
    has = {c for c, *_ in engine.rows(f"DESCRIBE SELECT * FROM {gold}")}
    flagged = engine.value(f"SELECT count(*) FROM {gold} WHERE kind_flagged") if "kind_flagged" in has else 0
    uncounted = 0 if chart is None or all("bands" in x for x in scored) else sum(  # from the full run's patterns: every increment's records left out
        next((x.get("records") or 0 for x in run["steps"] if x["step"] == "load"), 0) for run in folder.runs(out) if run.get("part"))
    listed = engine.value(f"SELECT count(*) FROM {index} WHERE match_weight >= 0")  # the pairs kept from 0 points
    return dict(records=sum(c * n for n, c in sizes), entities=sum(c for _, c in sizes), joined=size_of(2, None),
                sizes=[dict(label=label, entities=size_of(lo, hi)) for lo, hi, label in SIZES],
                scores=chart, candidates=sum(x["pairs"] for x in chart) if chart else cand.get("candidates"), uncounted=uncounted, listed=listed,
                review_from=review_from, waiting=[dict(down_to=cuts[i], up_to=cuts[i - 1] if i else None, pairs=n) for i, n in waiting],
                pairs=dict(kept=sum(by_status.values()), **by_status), merged_by=joined,
                merging=dict(line=p.fs.min_match_weight),
                too_big=dict(skipped=cand.get("oversized_skipped", 0), kept=cand.get("oversized_kept", 0), by=cand.get("skipped_by", {}), min=p.fs.budget.min_oversized()),
                kinds=dict(flagged=int(flagged)))
