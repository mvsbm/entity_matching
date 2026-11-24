"""Step 7, cluster: the entities people's decisions make, as gold. O(D + N). Reads er_decisions (people's,
load_decisions) and records; writes kept, clusters and gold."""
import time
from pathlib import Path

from er import folder
from er.cluster import merge
from er.config import q
from er.steps.job import Job


def load_decisions(job: Job, out: Path | None) -> None:
    """The decisions stored in the workspace `out` (None: none), on records of this file, the latest per pair, as
    er_decisions."""
    u, l, r, parts = q(job.uid), q(job.l), q(job.r), out / folder.DECISIONS if out else None
    if parts and any(parts.glob("part-*.parquet")):
        job.engine.run(f"""CREATE OR REPLACE TABLE er_decisions AS SELECT * FROM {folder.latest_decisions(job.engine, out, job.uid)}
            WHERE {l} IN (SELECT {u} FROM records) AND {r} IN (SELECT {u} FROM records)""")


def cluster(job: Job, n: int, old: Path | None = None) -> None:
    """Gold: each record an entity of its own until people's "match" decisions (er_decisions) join it, then connected
    components over those pairs (kept); an increment starts from the entities of `old` (gold.parquet) and the batch's
    records alone (new_ids). Nothing merges by itself: the rules' and the model's pairs wait in scored/ for a match run
    (er.jobs.match) and people's decisions. O(D + N) for D decisions."""
    t, engine, u, l, r = time.perf_counter(), job.engine, q(job.uid), q(job.l), q(job.r)
    engine.run(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
    engine.run(f"CREATE OR REPLACE TABLE kept AS SELECT {l}, {r} FROM er_decisions WHERE decision = 'match'")
    if old:  # the stored entities, whose answers stand, and each new record alone
        engine.run(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM {engine.read(old)}")
        engine.run(f"CREATE OR REPLACE TABLE er_single AS SELECT {u}, cluster_id FROM gold_old UNION ALL SELECT {u}, {u} FROM new_ids")
    else:
        engine.run(f"CREATE OR REPLACE TABLE er_single AS SELECT {u}, {u} AS cluster_id FROM records")
    merge(engine, "er_single", "kept", "clusters", job.uid)
    engine.run(gold_sql(u, "records" if "kind" in job.columns() else None, "gold_old" if old else None))
    d = job.count("kept")
    job.log.done("cluster", "O(D + N)", f"O({d:,} decisions + {n:,})", t, decided=d)


def gold_sql(u: str, kinds: str | None, old: str | None = None, flagged: str = "x.kind_flagged") -> str:
    """Gold, from `clusters`: each record's entity (cluster_id), and what joined it: people (review), when a decision put
    it with another record; else nothing. `kinds`: a table holding each record's kind (the records, or the stored gold),
    which gold keeps with its entity's (customer_kinds); `flagged`: the kind_flagged column it is read as. An increment
    passes the stored gold as `old`, whose answers stand. `u`: the ID column, quoted."""
    stage = "CASE WHEN z.n > 1 THEN 'review' END"
    stage, by = (f"coalesce(o.resolved_stage, {stage})", f"coalesce(o.resolved_by, {stage})") if old else (stage, stage)
    return f"""CREATE OR REPLACE TABLE gold AS
        WITH size AS (SELECT cluster_id, count(*) AS n FROM clusters GROUP BY 1)
             {f", customer AS ({customer_kinds('clusters', kinds, u)})" if kinds else ""}
        SELECT k.{u}, k.cluster_id, {stage} AS resolved_stage, {by} AS resolved_by{f", x.kind, x.kind_p, x.kind_by, {flagged}, c.customer_kind" if kinds else ""}
        FROM clusters k JOIN size z USING (cluster_id) {f"LEFT JOIN {old} o USING ({u})" if old else ""}
             {f"JOIN {kinds} x USING ({u}) JOIN customer c USING (cluster_id)" if kinds else ""}
        ORDER BY k.{u}"""


def customer_kinds(clusters: str, kinds: str, u: str) -> str:
    """Each cluster's customer_kind, from its records' kind and kind_p (`kinds`: a table holding both): 2 company if any
    record is one (kind 2: the engine's call or the flag's); 1 person if no record leans company and one is a
    person; else 0 not sure. O(N)."""
    return f"""SELECT k.cluster_id, CASE WHEN bool_or(x.kind = 2) THEN 2 WHEN coalesce(max(x.kind_p), 0) < 0.5 AND bool_or(x.kind = 1)
               THEN 1 ELSE 0 END::TINYINT AS customer_kind FROM {clusters} k JOIN {kinds} x USING ({u}) GROUP BY 1"""
