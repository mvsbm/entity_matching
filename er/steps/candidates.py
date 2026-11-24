"""Step 5, candidates: the pairs the keys list, as cands. O(N·L + Σ P_g); an increment's, those touching its batch:
O(|Δ|·Σ b + scan). Reads records, rule_clusters and rule_kept; writes cands, and er_query (the records the rules left
alone), er_gate and the bound's narrow copies while it runs. A block of 64+ records is joined only if a sample of its
pairs, scored as the run scores, reaches the search floor (the gate)."""
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from er.candidates import candidates as listing
from er.config import hashed, q
from er.match import bound_reads, bound_tests, reaching_sql, rough_reads, search_floor
from er.steps.budget import Budget, capacity
from er.steps.job import Job
from er.steps.rules import alone, sized
from er.steps.score import scored_in_slices


@dataclass
class Listed:
    listed: int                               # the distinct pairs the keys listed
    stored: int                               # of those, the pairs stored in cands: those that can reach keep_from (reaching_only)
    gated: pd.DataFrame = field(default_factory=pd.DataFrame)  # the oversized blocks checked, and what was decided
    gate_seconds: float = 0.0                 # the oversized blocks' samples scored: how long, and how many pairs
    gate_pairs: int = 0
    report: pd.DataFrame = field(default_factory=pd.DataFrame)  # per generator: its pairs and seconds (er.candidates.candidates)


def candidates(job: Job, n: int, scoring: dict, budget: Budget | None, batch: str | None = None,
               reaching_only: bool = True) -> Listed:
    """The pairs the keys list: of the file, or (an increment) those touching `batch`, a table of its IDs. `budget`:
    the full run's (an increment has none), whose estimates the generators read instead of the records.
    `reaching_only`: cands stores only the pairs that can reach keep_from (design time measures every pair the keys
    list)."""
    t, engine, uid, p = time.perf_counter(), job.engine, job.uid, job.pipeline
    fs = p.fs
    gate = _Gate(job, scoring, n)
    if not fs.bridge and not batch:  # the query: the records the rules left alone
        engine.run(f"CREATE OR REPLACE TABLE er_query AS SELECT * FROM {sized('rule_clusters', '=', uid)}")
    _, report = listing(fs.blockers, "records", uid, batch or (None if fs.bridge else "er_query"), fs.budget,
                        clusters="rule_clusters" if fs.bridge else None, engine=engine, into="cands", touching=batch is not None,
                        gate=gate, floor=search_floor(p), capacity=capacity(engine), told=_joined(job, n, budget),
                        known=None if batch or budget is None else budget.estimates, keep=(lambda pairs: reaching(job, scoring, n, pairs)) if reaching_only else None,
                        only=alone("l", "r", uid) if batch and not fs.bridge else None)  # as a full run's query: a pair touches a record the rules left alone
    engine.run("DROP TABLE IF EXISTS er_bound_records; DROP TABLE IF EXISTS er_bound_hashes")
    gated = _gated(job, report.attrs["gated"])
    stored = job.count("cands")
    out = Listed(listed=stored if report.attrs["listed"] is None else report.attrs["listed"], stored=stored, gated=gated,
                 gate_seconds=gate.seconds, gate_pairs=gate.pairs, report=report)
    job.log.done("candidates", *(("O(|Δ|·Σ b + scan)", f"{stored:,} pairs touching the batch") if batch else ("O(N·L + Σ P_g)", f"O({n:,}·L + {int(report['pairs'].sum()):,})")),
                 t, candidates=out.listed, stored=stored,
                 oversized_kept=int((gated.get("decision", pd.Series(dtype=str)) == "kept").sum()),
                 oversized_skipped=int(gated.get("decision", pd.Series(dtype=str)).str.startswith("skipped").sum()),
                 skipped_by={g: int(k) for g, k in gated[gated["decision"].str.startswith("skipped")].groupby("generator").size().items()}
                 if len(gated) else {},  # by the key that made them
                 gate_seconds=round(gate.seconds, 2), gate_pairs=gate.pairs, generators=generators(report))  # the gate: its samples scored
    return out


def generators(report: pd.DataFrame) -> list[dict]:  # each generator's pairs and seconds, kept in steps.json
    return [dict(name=r.generator, pairs=int(r.pairs), seconds=float(r.seconds)) for r in report.itertuples()]


def reaching(job: Job, scoring: dict, n: int, pairs: str) -> str:  # a generator's pairs that the score step scores: those that can reach keep_from, and the rules', never stored otherwise
    engine, uid, p = job.engine, job.uid, job.pipeline
    bound, have = bound_tests(p.fs.model), job.columns()
    cols = [c for c in sorted(bound_reads(scoring, bound)) if c in have]
    engine.run(f"CREATE TABLE IF NOT EXISTS er_bound_records AS SELECT {', '.join(q(c) for c in [uid, *cols])} FROM records")  # what the bound reads, narrow
    rough = [c for c in sorted(rough_reads(scoring, bound)) if c in have]
    engine.run(f"CREATE TABLE IF NOT EXISTS er_bound_hashes AS SELECT {q(uid)}, "  # what the rough test reads: a hash of each, NULL where missing
               f"{', '.join(f'CASE WHEN {q(c)} IS NOT NULL THEN {hashed(q(c))} END AS {q(c)}' for c in rough) or 'NULL AS __none'} FROM records")
    return reaching_sql(scoring, "er_bound_records", pairs, uid, set(cols), n, p.threshold.keep_from, bound, "rule_kept", hashed="er_bound_hashes")


def _joined(job: Job, n: int, budget: Budget | None) -> Callable[..., None] | None:
    """told for the generators' joins, each weighed as the budget counted it (the records it reads, the pairs it lists;
    an increment has no budget: alike), with `more` while the gate on oversized blocks may follow."""
    told = job.log.told
    if not told:
        return None
    plan = budget.plan[budget.plan["kind"] == "generator"] if budget is not None else None
    w = [1] * len(job.pipeline.fs.blockers) if plan is None else [n + int(x) for x in plan["normal"]]
    more = plan is None or bool(plan["oversized_blocks"].sum())
    return lambda i, k, unit: told(sum(w[:i]), sum(w), unit, more=more)


class _Gate:
    """The oversized blocks' sampled pairs (a table), scored as the candidates will be, a slice at a time; how long
    that took and how many pairs, summed over the blocks."""

    def __init__(self, job: Job, scoring: dict, n: int) -> None:
        self.job, self.scoring, self.n = job, scoring, n
        self.seconds, self.pairs = 0.0, 0

    def __call__(self, pairs: str) -> str:
        job, told = self.job, self.job.log.told
        if not job.pipeline.fs.bridge:  # a pair of two records the rules joined is no pair the run lists: it keeps no block
            job.engine.run(f"CREATE OR REPLACE TEMP TABLE {pairs} AS SELECT * FROM {pairs} WHERE {alone(q(job.l), q(job.r), job.uid)}")  # made again: its rowids dense, as scored_in_slices slices them
        start, total, done = time.perf_counter(), job.count(pairs), 0
        if told:
            told(0, total, "sampled pairs")

        def each(scored: str, sliced: int) -> None:
            nonlocal done
            done += sliced
            if told:
                told(done, total, "sampled pairs")
        scored_in_slices(job, self.scoring, pairs, "er_gate", n_records=self.n, each=each, floor=search_floor(job.pipeline))  # a block is kept by a pair at its floor
        self.seconds, self.pairs = self.seconds + time.perf_counter() - start, self.pairs + total
        return "er_gate"


def _gated(job: Job, records: list[dict]) -> pd.DataFrame:  # the oversized blocks' decisions, kept for qa and named in the summary
    gated = pd.DataFrame(records)
    if gated.empty:
        return gated
    floor = search_floor(job.pipeline)
    for x in gated.sort_values("pairs", ascending=False).head(5).itertuples():
        job.log.notes.append(f"{x.generator}: a block of {x.records:,} records ({x.pairs:,} pairs); {int(x.hits)} of {int(x.sampled)} "
                             f"sampled pairs reach {floor:g} bits: {x.decision}")
        job.log.examples.append(f"{x.generator}: {x.value} holds {x.records:,} records: {x.decision}")
    if len(gated) > 5:
        kept = (gated["decision"] == "kept").sum()
        job.log.notes.append(f"{len(gated):,} oversized blocks in all: {kept:,} kept, {len(gated) - kept:,} skipped")
    return gated
