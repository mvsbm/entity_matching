"""Step 7, cluster: what merges into customers, then connected components over it, then gold. O(C + E·log E + N);
an increment's O(C_Δ + touched clusters). Reads scores, cands, rule_clusters, rule_kept, er_decisions (people's,
load_decisions) and records; writes matches, kept, clusters and gold, and rule_kept again (whether each merged)."""
import time
from dataclasses import dataclass
from pathlib import Path

from er import folder
from er.cluster import merge
from er.config import bits, q
from er.steps.job import Job
from er.steps.score import scored_sql


@dataclass
class Clustered:
    accepted: int                             # the model's pairs accepted (matches)
    expected_false: float                     # the false links the model expects among them: Σ (1 − match probability)


def load_decisions(job: Job, out: Path | None) -> None:
    """The decisions stored in the workspace `out` (None: none), on records of this file, the latest per pair, as
    er_decisions."""
    u, l, r, parts = q(job.uid), q(job.l), q(job.r), out / folder.DECISIONS if out else None
    if parts and any(parts.glob("part-*.parquet")):
        job.engine.run(f"""CREATE OR REPLACE TABLE er_decisions AS SELECT * FROM {folder.latest_decisions(job.engine, out, job.uid)}
            WHERE {l} IN (SELECT {u} FROM records) AND {r} IN (SELECT {u} FROM records)""")


def cluster(job: Job, n: int, old: Path | None = None) -> Clustered:
    """Accept (accept), then cluster every kept pair from single records, or (an increment) from the entities of
    `old` (gold.parquet) and the batch's records alone (new_ids); then gold (_gold)."""
    t, engine, u = time.perf_counter(), job.engine, q(job.uid)
    accept(job)
    if old:  # the stored entities, whose answers stand, and each new record alone
        engine.run(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM {engine.read(old)}")
        engine.run(f"CREATE OR REPLACE TABLE er_single AS SELECT {u}, cluster_id FROM gold_old UNION ALL SELECT {u}, {u} FROM new_ids")
    else:
        engine.run(f"CREATE OR REPLACE TABLE er_single AS SELECT {u}, {u} AS cluster_id FROM records")
    merge(engine, "er_single", "kept", "clusters", job.uid)
    _gold(job, "gold_old" if old else None)
    e = job.count("matches")
    expected = round(engine.value("SELECT coalesce(sum(1 - match_probability), 0) FROM matches"), 2)  # O(E)
    job.log.done("cluster", "O(C_Δ + touched clusters)" if old else "O(C + E·log E + N)", f"O({job.count('scores'):,} + {e:,}·log E + {n:,})", t,
                 accepted=e, expected_false=expected)
    return Clustered(e, expected)


def accept(job: Job) -> None:
    """What merges into customers (kept): every rule pair and the model's named and kept pairs (scored_sql) at its
    threshold or above (matches), less the pairs people decided are no match, and the pairs they decided are a match
    (er_decisions; empty when none). rule_kept says which of its pairs merged."""
    engine, l, r = job.engine, q(job.l), q(job.r)
    engine.run(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
    no = lambda x: f"NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = {x}.{l} AND d.{r} = {x}.{r} AND d.decision = 'no_match')"
    engine.run(f"""CREATE OR REPLACE TABLE matches AS SELECT s.{l}, s.{r}, s.match_weight, s.match_probability, s.sources
        FROM ({scored_sql(job)}) s WHERE s.named AND s.keep AND s.match_weight >= {bits(job.pipeline.fs.min_match_weight)} AND {no('s')}""")
    engine.run(f"""CREATE OR REPLACE TABLE rule_kept AS SELECT k.* EXCLUDE (merged), {no('k')} AS merged
        FROM (SELECT *, NULL AS merged FROM rule_kept) k""")
    engine.run(f"""CREATE OR REPLACE TABLE kept AS SELECT {l}, {r} FROM rule_kept WHERE merged UNION ALL SELECT {l}, {r} FROM matches
        UNION ALL SELECT {l}, {r} FROM er_decisions WHERE decision = 'match'""")


def _gold(job: Job, old: str | None = None) -> None:
    """Each record's cluster, and what resolved it: if a rule pair of it merged, the first rule (in rule order)
    among those; else the model, if one of its pairs was accepted; else people (review), if a pair
    they decided joined it. An increment passes the stored gold as `old`, whose answers stand."""
    p = job.pipeline
    fs, l, r, u = p.fs, q(job.l), q(job.r), q(job.uid)
    order = " ".join(f"WHEN '{rule.name}' THEN {i}" for i, _, rule in p.rules.each())
    stage = f"CASE WHEN f.id IS NOT NULL THEN '{fs.previous_stage}' WHEN m.id IS NOT NULL THEN '{fs.stage}' WHEN z.n > 1 THEN 'review' END"
    by = f"CASE WHEN f.id IS NOT NULL THEN f.rule WHEN m.id IS NOT NULL THEN '{fs.model.name}' WHEN z.n > 1 THEN 'review' END"
    if old:
        stage, by = f"coalesce(o.resolved_stage, {stage})", f"coalesce(o.resolved_by, {by})"
    kinds = "kind" in job.columns()  # each record's kind, and its customer's (customer_kinds)
    job.engine.run(f"""CREATE OR REPLACE TABLE gold AS
        WITH touch AS (SELECT {l} AS id, rule FROM rule_kept WHERE merged UNION ALL SELECT {r}, rule FROM rule_kept WHERE merged),
             first AS (SELECT id, arg_min(rule, CASE rule {order} END) AS rule FROM touch GROUP BY id),
             size AS (SELECT cluster_id, count(*) AS n FROM clusters GROUP BY 1),
             matched AS (SELECT {l} AS id FROM matches UNION SELECT {r} FROM matches)
             {f", customer AS ({customer_kinds('clusters', 'records', u)})" if kinds else ""}
        SELECT k.{u}, k.cluster_id, {stage} AS resolved_stage, {by} AS resolved_by{", x.kind, x.kind_p, x.kind_by, x.kind_flagged, c.customer_kind" if kinds else ""}
        FROM clusters k JOIN size z USING (cluster_id) LEFT JOIN first f ON f.id = k.{u} LEFT JOIN matched m ON m.id = k.{u} {f"LEFT JOIN {old} o USING ({u})" if old else ""}
             {f"JOIN records x USING ({u}) JOIN customer c USING (cluster_id)" if kinds else ""}
        ORDER BY k.{u}""")


def customer_kinds(clusters: str, kinds: str, u: str) -> str:
    """Each cluster's customer_kind, from its records' kind and kind_p (`kinds`: a table holding both): 2 company if any
    record is one (kind 2: the engine's call or the flag's); 1 person if no record leans company and one is a
    person; else 0 not sure. O(N)."""
    return f"""SELECT k.cluster_id, CASE WHEN bool_or(x.kind = 2) THEN 2 WHEN coalesce(max(x.kind_p), 0) < 0.5 AND bool_or(x.kind = 1)
               THEN 1 ELSE 0 END::TINYINT AS customer_kind FROM {clusters} k JOIN {kinds} x USING ({u}) GROUP BY 1"""
