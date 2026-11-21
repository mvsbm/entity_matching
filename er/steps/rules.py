"""Step 4, rules: the certain cases. One join per rule (the first rule wins a pair), then the cascade: a later stage
adds a pair only if it touches a record still unresolved, and the stage's pairs are merged into rule_clusters.
O(N + Σ P_r·L²) + O(E·log E + N).

Reads records (with `batch`, an increment's: new_records too) and rule_clusters (each record alone, or the stored
clusters and each new record alone). Writes rule_edges (every rule's pairs, with the model's points), rule_scores
(their scores, when a model is given), rule_kept (the pairs the cascade kept), rule_clusters, and er_untrusted_<i>
(each rule's values held by an oversized block)."""
import time
from dataclasses import dataclass

from er.cluster import merge
from er.config import q
from er.match import rule_edges, score_fs
from er.steps.job import Job


@dataclass
class Ruled:
    seconds: dict[str, float]                 # each rule's join, in seconds


def sized(clusters: str, op: str, uid: str) -> str:  # the records in a cluster whose size is `op` 1: "> 1" joined, "= 1" alone
    return f"(SELECT {q(uid)} FROM {clusters} WHERE cluster_id IN (SELECT cluster_id FROM {clusters} GROUP BY 1 HAVING count(*) {op} 1))"


def alone(a: str, b: str, uid: str) -> str:  # SQL: the pair (a, b) touches a record the rules left alone; without bridging, only such a pair counts
    joined = sized("rule_clusters", ">", uid)
    return f"NOT ({a} IN {joined} AND {b} IN {joined})"


def rules(job: Job, n: int, scoring: dict | None, batch: str | None = None) -> Ruled:
    """The rules' pairs and their cascade. A full run starts rule_clusters here, each record alone; an increment
    (`batch`: new_records) has started it from the stored clusters. `scoring`: the model the rules' pairs are scored
    with, for the review sheet (None: design time measures the rules alone, before any model is fitted)."""
    t, engine, uid = time.perf_counter(), job.engine, job.uid
    if batch is None:
        engine.run(f"CREATE OR REPLACE TABLE rule_clusters AS SELECT {q(uid)}, {q(uid)} AS cluster_id FROM records")
    seconds = _cascade(job, scoring, batch)
    if batch is None:
        p = job.count("rule_edges")
        job.log.done("rules", "O(N + Σ P_r·L²) + O(E·log E + N)", f"O({n:,} + {p:,} pairs)", t, pairs=p, kept=job.count("rule_kept"))
    else:
        job.log.done("rules", "O(|Δ|·Σ b + scan)", f"O({job.count('new_ids'):,} new records)", t, kept=job.count("rule_kept"))
    return Ruled(seconds)


def _cascade(job: Job, scoring: dict | None, batch: str | None) -> dict[str, float]:
    """The rules' pairs (er.match.rule_edges: every record, or a batch against all), less the values each rule
    doesn't trust (_untrusted), each scored by the model too (rule_scores: what the review sheet reads), then the
    cascade into rule_clusters: a stage's pair is kept only if it touches a record still unresolved, and merged in
    (er.cluster.merge). The rule clusters steer the candidates; what merges into customers is steps.cluster's."""
    engine, uid, rules_spec = job.engine, job.uid, job.pipeline.rules
    l, r = q(job.l), q(job.r)
    trust = {}
    for i, st, rule in rules_spec.each():
        if (untrusted := _untrusted(job, i, rule.name, st.keys(rule), within=batch)):
            trust[i] = f"NOT EXISTS (SELECT 1 FROM {untrusted} z WHERE {' AND '.join(f'z.{q(c)} = l.{q(c)}' for c in st.keys(rule))})"
    _, seconds = rule_edges(rules_spec, "records", engine, uid, batch=batch, trust=trust, into="rule_edges", told=job.log.told)
    if scoring is None:  # design time measures the rules alone, before any model is fitted: nothing reads their weights
        engine.run("CREATE OR REPLACE TABLE rule_edges AS SELECT *, NULL::DOUBLE AS match_weight FROM rule_edges")
    else:
        score_fs(scoring, "records", "rule_edges", engine, uid, into="rule_scores", n_records=job.count("records"))  # O(R·K)
        engine.run(f"CREATE OR REPLACE TABLE rule_edges AS SELECT e.*, s.match_weight FROM rule_edges e JOIN rule_scores s USING ({l}, {r})")
    engine.run("CREATE OR REPLACE TABLE rule_kept AS SELECT * FROM rule_edges WHERE FALSE")
    for st in rules_spec.stages:
        engine.run(f"""CREATE OR REPLACE TABLE er_stage AS SELECT * FROM rule_edges WHERE stage = '{st.name}' AND {alone(l, r, uid)}""")
        engine.run("INSERT INTO rule_kept SELECT * FROM er_stage")
        merge(engine, "rule_clusters", "er_stage", "rule_clusters", uid)
    return seconds


def _untrusted(job: Job, i: int, rule: str, rule_keys: list[str], within: str | None = None) -> str | None:
    """The values of a rule's keys held by an oversized block (with `within`, a table of records: only the values
    they hold), as a table; None if none. One value on that many records is not one entity's, so the rule leaves
    it out, and the summary names it. O(N), a group-by."""
    engine = job.engine
    m, cols = job.pipeline.fs.budget.min_oversized(), ", ".join(q(c) for c in rule_keys)
    filled = " AND ".join(f"{q(c)} IS NOT NULL" for c in rule_keys)
    held = f" AND ({cols}) IN (SELECT {cols} FROM {within})" if within else ""
    name = f"er_untrusted_{i}"
    engine.run(f"CREATE OR REPLACE TABLE {name} AS SELECT {cols}, count(*) AS __n FROM records WHERE {filled}{held} "
               f"GROUP BY {cols} HAVING count(*) >= {m} ORDER BY __n DESC")
    n, records = engine.row(f"SELECT count(*), coalesce(sum(__n), 0) FROM {name}")
    if not n:
        return None
    top = engine.row(f"SELECT * FROM {name} LIMIT 1")
    job.log.notes.append(f"rule {rule} doesn't trust {n:,} value{'s' if n > 1 else ''} held by {m}+ records ({int(records):,} records)")
    job.log.examples.append(f"rule {rule}: {', '.join(f'{c} = {v}' for c, v in zip(rule_keys, top))} in {top[-1]:,} records")
    return name
