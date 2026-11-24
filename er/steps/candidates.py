"""Step 5, candidates: the pairs the keys list, as cands. O(N·L + Σ P_g); an increment's, those touching its batch:
O(|Δ|·Σ b + scan). Reads records and rule_kept; writes cands, and er_gate and the bound's narrow copies while it
runs. A block of 64+ records is joined only if a sample of its
pairs, scored as the run scores, reaches the search floor (the gate)."""
import time
from dataclasses import dataclass, field

import pandas as pd

from er.candidates import candidates as listing
from er.config import hashed, q
from er.match import bound_reads, bound_tests, reaching_sql, rough_reads, search_floor
from er.steps.budget import capacity
from er.steps.job import Job
from er.steps.score import scored_in_slices


@dataclass
class Listed:
    listed: int                               # the distinct pairs the keys listed: what scoring counts as unscored, less those stored
    gated: pd.DataFrame = field(default_factory=pd.DataFrame)  # the oversized blocks checked, and what was decided


def candidates(job: Job, n: int, scoring: dict, batch: str | None = None, reaching_only: bool = True) -> Listed:
    """The pairs the keys list: of the file, or (an increment) those touching `batch`, a table of its IDs.
    `reaching_only`: cands stores only the pairs that can reach keep_from (design time measures every pair the keys
    list)."""
    t, engine, uid, p = time.perf_counter(), job.engine, job.uid, job.pipeline
    fs = p.fs
    gate = _Gate(job, scoring, n)
    _, report = listing(fs.blockers, "records", uid, batch, fs.budget, engine=engine, into="cands", touching=batch is not None,
                        gate=gate, floor=search_floor(p), capacity=capacity(engine),
                        keep=(lambda pairs: reaching(job, scoring, n, pairs)) if reaching_only else None)
    engine.run("DROP TABLE IF EXISTS er_bound_records; DROP TABLE IF EXISTS er_bound_hashes")
    gated = _gated(job, report.attrs["gated"])
    stored = job.count("cands")
    out = Listed(listed=stored if report.attrs["listed"] is None else report.attrs["listed"], gated=gated)
    job.log.done("candidates", *(("O(|Δ|·Σ b + scan)", f"{stored:,} pairs touching the batch") if batch else ("O(N·L + Σ P_g)", f"O({n:,}·L + {int(report['pairs'].sum()):,})")),
                 t, candidates=out.listed, stored=stored,
                 oversized_kept=int((gated.get("decision", pd.Series(dtype=str)) == "kept").sum()),
                 oversized_skipped=int(gated.get("decision", pd.Series(dtype=str)).str.startswith("skipped").sum()),
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


class _Gate:
    """The oversized blocks' sampled pairs (a table), scored as the candidates will be, a slice at a time; how long
    that took and how many pairs, summed over the blocks."""

    def __init__(self, job: Job, scoring: dict, n: int) -> None:
        self.job, self.scoring, self.n = job, scoring, n
        self.seconds, self.pairs = 0.0, 0

    def __call__(self, pairs: str) -> str:
        job = self.job
        start, total = time.perf_counter(), job.count(pairs)
        scored_in_slices(job, self.scoring, pairs, "er_gate", n_records=self.n, floor=search_floor(job.pipeline))  # a block is kept by a pair at its floor
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
