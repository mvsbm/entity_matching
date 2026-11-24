"""Step 2, budget: exact block sizes on this file, per rule and generator, before any join. O(N) per rule and
generator, a group-by each. Reads records."""
import time
from dataclasses import dataclass

import pandas as pd

from er.candidates import estimate
from er.config import InputError
from er.engine.engine import Engine
from er.steps.job import Job

BYTES_PER_PAIR = 350  # shortcut: measured at 1M (candidate and score tables held together); measure again if those tables change


@dataclass
class Budget:
    plan: pd.DataFrame                        # per rule and generator: pairs, pairs per record, the largest block, the oversized blocks
    estimates: dict[str, dict]                # each generator's estimate, by name: the candidates step reads them, not the records


def capacity(engine: Engine) -> int:
    """The pairs that fit in the engine's room (memory and the disk it may spill to), at BYTES_PER_PAIR."""
    return int(engine.room() / BYTES_PER_PAIR)


def budget(job: Job, n: int, stop: bool = True) -> Budget:
    """Pairs, pairs per record, the largest block and the oversized blocks (budget.min_oversized() records or more) of
    each rule and generator, by group-by. Those blocks are never joined blind: a generator checks each on a sample
    first (er.candidates), and a rule never trusts their values (steps.rules). The run stops only if the pairs of the
    normal blocks alone would not fit (capacity); `stop` False (a check before a run) leaves that to the caller,
    which reads plan["normal"] against capacity."""
    t, rows, p = time.perf_counter(), [], job.pipeline
    m = p.fs.budget.min_oversized()
    estimates = {}
    for kind, x in [*(("rule", k) for k in p.rules.blockers()), *(("generator", g) for g in p.fs.blockers)]:
        est = estimate(x, "records", job.engine, oversized_from=m)
        if kind == "generator":
            estimates[x.name] = est
        rows.append(dict(kind=kind, name=x.name, **est))
    plan = pd.DataFrame(rows).assign(per_record=lambda d: (d["est_pairs"] / max(n, 1)).round(2),
                                     normal=lambda d: d["normal_pairs"])
    job.log.done("budget", "O(N)", f"O({n:,}) per rule and generator", t, pairs=int(plan["est_pairs"].sum()),
                 oversized_blocks=int(plan["oversized_blocks"].sum()))
    if stop and (normal := int(plan["normal"].sum())) > (cap := capacity(job.engine)):
        raise InputError(f"the normal blocks alone would make {normal:,} pairs, more than fit in memory and the temp disk "
                         f"({cap:,} pairs at about {BYTES_PER_PAIR} bytes each); the most: " +
                         ", ".join(f"{x.name} {x.normal:,}" for x in plan.nlargest(3, "normal").itertuples()),
                         fix="give DuckDB more room (--compute memory_limit=… temp_directory=<a disk with space>), or resolve the file in parts")
    return Budget(plan, estimates)
