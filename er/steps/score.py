"""Step 6, score: every candidate that can reach keep_from points scored with the model and the u the fit settled.
O(C·K·L²). Reads records, cands and rule_kept; writes scores.

scored_in_slices is how every scoring of many pairs runs (this step, and the candidates step's gate); scored_sql and
links_sql are the scored pairs with what acceptance reads, and as scored/ keeps them."""
import time

from er.config import q
from er.match import bound_tests, named_sql, score_fs
from er.steps.job import Job
from er.steps.rules import alone


SCORE_PAIRS = 5_000_000  # pairs scored at a time: a slice bounds memory; each joins every record again


def scored_in_slices(job: Job, scoring: dict, pairs: str, into: str, n_records: int | None = None,
                     floor: float | None = None, exempt: str | None = None) -> None:
    """Every pair of `pairs` (a table made fresh: engine.slices; uid_l, uid_r) scored into `into`, score_pairs at a
    time: a pair's score depends on it alone, so the slices score as the whole would, and only one slice's comparisons
    are ever held (SCORE_PAIRS a slice). With `floor`, a pair that can't reach it is
    left out, unless `exempt` (a table of pairs) holds it (score_fs)."""
    engine, uid, l, r = job.engine, job.uid, q(job.l), q(job.r)
    bound, score_pairs = bound_tests(job.pipeline.fs.model), SCORE_PAIRS
    for i, where in enumerate(engine.slices(pairs, score_pairs, job.count(pairs))):
        engine.run(f"CREATE OR REPLACE TABLE er_slice AS SELECT {l}, {r} FROM {pairs} WHERE {where}")
        score_fs(scoring, "records", "er_slice", engine, uid, into=into if not i else "er_scored", n_records=n_records,
                 floor=floor, bound=bound, exempt=exempt)
        if i:
            engine.run(f"INSERT INTO {into} SELECT * FROM er_scored")
    engine.run("DROP TABLE IF EXISTS er_slice; DROP TABLE IF EXISTS er_scored")


def score(job: Job, scoring: dict, listed: int) -> None:
    """Every candidate that can reach keep_from points ([threshold] keep_from, 0 unless set) scored (the rest: a bound
    settles it below, which nothing reads: unscored), and every rule pair. `listed`: the pairs the keys listed, those the
    candidates step never stored too."""
    t, p = time.perf_counter(), job.pipeline
    scored_in_slices(job, scoring, "cands", "scores", floor=p.threshold.keep_from, exempt="rule_kept")  # scored/ keeps keep_from points and up, and every rule pair
    scored = job.count("scores")
    job.log.done("score", "O(C·K·L²)", f"O({scored:,}·{len(p.fs.model.comparisons)}·L²)", t, unscored=listed - scored)


def scored_sql(job: Job) -> str:
    """Every scored pair with its generators (sources) and what acceptance reads besides the weight: named, a name
    compared (fs.needs); keep, the pair joins two rule clusters (bridge) or touches a record the rules left alone. As
    SQL, for steps.cluster, and for design time to accept at other weights (design.pipeline)."""
    fs, l, r, u = job.pipeline.fs, q(job.l), q(job.r), q(job.uid)
    keep = "a.cluster_id <> b.cluster_id" if fs.bridge else alone(f"s.{l}", f"s.{r}", job.uid)
    return f"""SELECT s.*, c.sources, {named_sql(fs)} AS named, {keep} AS keep FROM scores s JOIN cands c USING ({l}, {r})
        JOIN rule_clusters a ON a.{u} = s.{l} JOIN rule_clusters b ON b.{u} = s.{r}"""


def links_sql(job: Job) -> str:
    """Every pair scored at keep_from points or more and every rule pair, as scored/ keeps them for match runs (er.jobs.match): its
    points, how it was found (sources: the keys; rule: the rule), named, keep, and one gamma per comparison."""
    fs, l, r = job.pipeline.fs, q(job.l), q(job.r)
    gammas = [c for c, _ in job.engine.columns("scores") if c.startswith("gamma_")]
    rule = f"(SELECT {l}, {r}, min(rule) AS rule FROM rule_kept GROUP BY ALL)"
    model = f"""SELECT s.{l}, s.{r}, s.match_weight, s.match_probability, s.sources, k.rule, s.named, s.keep, {', '.join(f's.{q(g)}' for g in gammas)}
        FROM ({scored_sql(job)}) s LEFT JOIN {rule} k USING ({l}, {r}) WHERE s.match_weight >= {job.pipeline.threshold.keep_from} OR k.rule IS NOT NULL"""
    if not job.engine.exists("rule_scores"):
        return model
    return f"""{model} UNION ALL BY NAME SELECT x.{l}, x.{r}, x.match_weight, x.match_probability, NULL::VARCHAR AS sources, k.rule,
        {named_sql(fs, 'x')} AS named, TRUE AS keep, {', '.join(f'x.{q(g)}' for g in gammas)} FROM rule_scores x JOIN {rule} k USING ({l}, {r})
        WHERE NOT EXISTS (SELECT 1 FROM scores s WHERE s.{l} = x.{l} AND s.{r} = x.{r})"""
