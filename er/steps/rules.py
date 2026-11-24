"""Step 4, rules: the certain cases. One join per rule, the first rule in order winning a pair. O(N + Σ P_r·L²).

Reads records (with `batch`, an increment's: new_records too). Writes rule_kept (every rule's pairs, with the model's
points), rule_scores (their scores, when a model is given) and er_untrusted_<i> (each rule's values held by an
oversized block)."""
import time

from er.config import q
from er.match import rule_edges, score_fs
from er.steps.job import Job


def rules(job: Job, n: int, scoring: dict | None, batch: str | None = None) -> None:
    """The rules' pairs (er.match.rule_edges: every record, or a batch against all; the first rule in order wins a
    pair), less the values each rule doesn't trust (_untrusted), each scored by the model too (rule_scores: what
    scored/ keeps of them), as rule_kept. Nothing merges: each waits in scored/, with its rule, for people's decisions.
    `scoring`: the model the rules' pairs are scored with (None: design time measures the rules alone, before any
    model is fitted)."""
    t, engine, uid, rules_spec = time.perf_counter(), job.engine, job.uid, job.pipeline.rules
    l, r = q(job.l), q(job.r)
    trust = {}
    for i, st, rule in rules_spec.each():
        if (untrusted := _untrusted(job, i, rule.name, st.keys(rule), within=batch)):
            trust[i] = f"NOT EXISTS (SELECT 1 FROM {untrusted} z WHERE {' AND '.join(f'z.{q(c)} = l.{q(c)}' for c in st.keys(rule))})"
    rule_edges(rules_spec, "records", engine, uid, batch=batch, trust=trust, into="rule_kept")
    if scoring is None:  # design time measures the rules alone, before any model is fitted: nothing reads their weights
        engine.run("CREATE OR REPLACE TABLE rule_kept AS SELECT *, NULL::DOUBLE AS match_weight FROM rule_kept")
    else:
        score_fs(scoring, "records", "rule_kept", engine, uid, into="rule_scores", n_records=job.count("records"))  # O(R·K)
        engine.run(f"CREATE OR REPLACE TABLE rule_kept AS SELECT e.*, s.match_weight FROM rule_kept e JOIN rule_scores s USING ({l}, {r})")
    kept = job.count("rule_kept")
    if batch is None:
        job.log.done("rules", "O(N + Σ P_r·L²)", f"O({n:,} + {kept:,} pairs)", t, pairs=kept, kept=kept)
    else:
        job.log.done("rules", "O(|Δ|·Σ b + scan)", f"O({job.count('new_ids'):,} new records)", t, kept=kept)


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
