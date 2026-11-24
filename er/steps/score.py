"""Step 6, score: every candidate that can reach keep_from points scored with the model and the u the fit settled.
O(C·K·L²). Reads records, cands and rule_kept; writes scores.

scored_in_slices is how every scoring of many pairs runs (this step, and the candidates step's gate); scored_sql and
links_sql are the scored pairs with what acceptance reads, and as scored/ keeps them."""
import time
from collections.abc import Callable
from dataclasses import dataclass

from er.config import bits, hashed, q
from er.match import bound_tests, named_sql, review_floor, score_fs
from er.steps.job import Job
from er.steps.rules import alone


BANDS = (-20, -10, 0, 6, 8, 10, 12, 16, 20)  # the score chart's edges, in points: as report.txt's SCORES


def banded(col: str = "match_weight") -> str:  # the SQL of a weight's band in the score chart: 0 below BANDS[0], len(BANDS) at its last edge or above
    return "CASE " + " ".join(f"WHEN {col} < {e} THEN {i}" for i, e in enumerate(BANDS)) + f" ELSE {len(BANDS)} END"

SCORE_PAIRS = 5_000_000  # pairs scored at a time: each slice says how far scoring is, and bounds its memory; each joins every record again


@dataclass
class Scored:
    pairs: int                                # the pairs scored (scores)


def scored_in_slices(job: Job, scoring: dict, pairs: str, into: str, n_records: int | None = None, each: Callable[[str, int], None] | None = None,
                     floor: float | None = None, exempt: str | None = None) -> None:
    """Every pair of `pairs` (a table made fresh, its rowids dense; uid_l, uid_r) scored into `into`, score_pairs at a
    time: a pair's score depends on it alone, so the slices score as the whole would, and only one slice's comparisons
    are ever held (SCORE_PAIRS a slice). each(the slice's scores, its pairs) after each slice. With `floor`, a pair that can't reach it is
    left out, unless `exempt` (a table of pairs) holds it (score_fs)."""
    engine, uid, l, r = job.engine, job.uid, q(job.l), q(job.r)
    bound, score_pairs = bound_tests(job.pipeline.fs.model), SCORE_PAIRS
    for start in range(0, max(1, job.count(pairs)), score_pairs):
        engine.run(f"CREATE OR REPLACE TABLE er_slice AS SELECT {l}, {r} FROM {pairs} WHERE rowid >= {start} AND rowid < {start + score_pairs}")
        score_fs(scoring, "records", "er_slice", engine, uid, into=into if not start else "er_scored", n_records=n_records,
                 floor=floor, bound=bound, exempt=exempt)
        if start:
            engine.run(f"INSERT INTO {into} SELECT * FROM er_scored")
        if each:
            each(into if not start else "er_scored", job.count("er_slice"))
    engine.run("DROP TABLE IF EXISTS er_slice; DROP TABLE IF EXISTS er_scored")


def score(job: Job, scoring: dict, listed: int) -> Scored:
    """Every candidate that can reach keep_from points ([threshold] keep_from, 0 unless set) scored (the rest: a bound
    settles it below, which nothing reads: unscored), and every rule pair; and the patterns the scored pairs fall in
    (patterns). `listed`: the pairs the keys listed, those the candidates step never stored too."""
    t, engine, log, p = time.perf_counter(), job.engine, job.log, job.pipeline
    fs = p.fs
    k, model_line = len(fs.model.comparisons), bits(fs.min_match_weight)
    total, done, likely = job.count("cands"), 0, 0  # likely: the pairs the model scores as matches

    def each(scored: str, sliced: int) -> None:  # how far scoring is, after each slice
        nonlocal done, likely
        hit = engine.value(f"SELECT count(*) FILTER (match_weight >= {model_line} AND {named_sql(fs)}) FROM {scored} s")
        done, likely = done + sliced, likely + hit
        if log.told:
            log.told(done, total, "pairs", likely=likely)
    scored_in_slices(job, scoring, "cands", "scores", each=each, floor=p.threshold.keep_from, exempt="rule_kept")  # scored/ keeps keep_from points and up, and every rule pair
    reached: dict[str, dict[str, int]] = {}  # per comparison, the pairs at each level (gamma, as score_fs gives it): one scan
    for c, g, n in engine.rows("SELECT c, g, count(*) FROM (UNPIVOT scores ON COLUMNS('^gamma_') INTO NAME c VALUE g) GROUP BY ALL"):
        reached.setdefault(c.removeprefix("gamma_"), {})[str(g)] = n
    scored = job.count("scores")
    log.done("score", "O(C·K·L²)", f"O({scored:,}·{k}·L²)", t, reached=reached, patterns=patterns(job), bands=_bands(job),
             unscored=listed - scored)
    return Scored(scored)


def _bands(job: Job) -> list[int]:  # the pairs in `scores` by the score chart's bands (BANDS), each by its own weight
    n = dict(job.engine.rows(f"SELECT {banded()}, count(*) FROM scores GROUP BY 1"))
    return [n.get(i, 0) for i in range(len(BANDS) + 1)]


def patterns(job: Job) -> dict:
    """The patterns the pairs in `scores` fall in, one step per comparison: per pattern its pairs, their mean weight,
    how many merge and how many wait for people as steps.cluster will take them, and three of them. A full run's and each increment's: together, every pair the run scored."""
    fs, l, r = job.pipeline.fs, q(job.l), q(job.r)
    at, floor = bits(fs.min_match_weight), bits(review_floor(job.pipeline))
    gammas = [c for c, *_ in job.engine.rows("DESCRIBE scores") if c.startswith("gamma_")]
    rows = job.engine.rows(f"""SELECT {', '.join(q(g) for g in gammas)}, count(*), round(avg(match_weight), 2),
        count(*) FILTER (match_weight >= {at} AND {named_sql(fs)}),
        count(*) FILTER (match_weight >= {floor} AND (match_weight < {at} OR NOT {named_sql(fs)})),
        arg_min([{l}, {r}], {hashed(f"{l} || ' ' || {r}")}, 3) FROM scores s GROUP BY ALL""") if gammas else []
    return dict(fields=[g.removeprefix("gamma_") for g in gammas], rows=[list(x) for x in rows])


def scored_sql(job: Job) -> str:
    """Every scored pair with its generators (sources) and what acceptance reads besides the weight: named, a name
    compared (fs.needs); keep, the pair joins two rule clusters (bridge) or touches a record the rules left alone. As
    SQL, for steps.cluster, and for design time to accept at other weights (design.pipeline)."""
    fs, l, r, u = job.pipeline.fs, q(job.l), q(job.r), q(job.uid)
    keep = "a.cluster_id <> b.cluster_id" if fs.bridge else alone(f"s.{l}", f"s.{r}", job.uid)
    return f"""SELECT s.*, c.sources, {named_sql(fs)} AS named, {keep} AS keep FROM scores s JOIN cands c USING ({l}, {r})
        JOIN rule_clusters a ON a.{u} = s.{l} JOIN rule_clusters b ON b.{u} = s.{r}"""


def links_sql(job: Job) -> str:
    """Every pair scored at keep_from points or more and every rule pair, as scored/ keeps them for people (er.results): its
    points, how it was found (sources: the keys; rule: the rule), named, keep, and one gamma per comparison."""
    fs, l, r = job.pipeline.fs, q(job.l), q(job.r)
    gammas = [c for c, *_ in job.engine.rows("DESCRIBE scores") if c.startswith("gamma_")]
    rule = f"(SELECT {l}, {r}, min(rule) AS rule FROM rule_kept GROUP BY ALL)"
    model = f"""SELECT s.{l}, s.{r}, s.match_weight, s.match_probability, s.sources, k.rule, s.named, s.keep, {', '.join(f's.{q(g)}' for g in gammas)}
        FROM ({scored_sql(job)}) s LEFT JOIN {rule} k USING ({l}, {r}) WHERE s.match_weight >= {job.pipeline.threshold.keep_from} OR k.rule IS NOT NULL"""
    if not job.engine.value("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'rule_scores'"):
        return model
    return f"""{model} UNION ALL BY NAME SELECT x.{l}, x.{r}, x.match_weight, x.match_probability, NULL::VARCHAR AS sources, k.rule,
        {named_sql(fs, 'x')} AS named, TRUE AS keep, {', '.join(f'x.{q(g)}' for g in gammas)} FROM rule_scores x JOIN {rule} k USING ({l}, {r})
        WHERE NOT EXISTS (SELECT 1 FROM scores s WHERE s.{l} = x.{l} AND s.{r} = x.{r})"""
