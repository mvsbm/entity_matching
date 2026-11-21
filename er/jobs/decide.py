"""People's decisions on review pairs applied to a written run, scoring nothing. O(D + touched clusters) + O(N) to
rewrite gold, for D decisions."""
import time
from collections.abc import Callable
from pathlib import Path

from er import folder
from er.cluster import merge
from er.config import Pipeline, lit, q
from er.report import no_run
from er.settings import Settings
from er.source import decisions, file_facts, known
from er.steps.cluster import customer_kinds
from er.steps.job import Ran, start
from er.steps.write import log_entry, run_config


def decide(path: str | Path, out: Path, settings: Settings, pipeline: Pipeline, echo: Callable[[dict], None] | None = None,
           told: Callable[..., None] | None = None) -> Ran:
    """The decisions in `path` (a Parquet file: uid_l, uid_r, decision) applied to the run in `out`. Each `match` pair
    merges its two clusters, each cluster one node, and a record joined only this way is resolved by `review`. A
    `no_match` pair splits nothing here; every decision is stored in decisions/, with the round it was made in
    (rounds.json), and a full run on this folder applies them again, never accepting a `no_match` pair. Rows without a
    decision are skipped, and so is a decision the folder already holds as its pair's latest: a sheet given twice
    changes nothing."""
    out = Path(out)
    with folder.run_lock(out):
        job = start(settings, pipeline, echo, told)
        engine, log, u, l, r = job.engine, job.log, q(job.uid), q(job.l), q(job.r)
        t = time.perf_counter()
        folder.finish_writes(out)
        if not (out / "gold.parquet").exists():
            raise no_run(out, "apply decisions to")
        engine.run(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM read_parquet({lit(out / 'gold.parquet')})")
        ran = Ran(job, config=run_config(pipeline, settings),
                  inputs=file_facts(decisions(path, engine, job.l, job.r, into="er_decisions"), "decisions"))  # the door: er.source checks them
        known(engine, f"SELECT {l} AS id FROM er_decisions UNION SELECT {r} FROM er_decisions", "gold_old", job.uid, path, f"the run in {out}")
        if latest := folder.latest_decisions(out, job.uid):
            engine.run(f"""DELETE FROM er_decisions d USING {latest} p WHERE p.{l} = d.{l} AND p.{r} = d.{r} AND p.decision = d.decision""")
        if not job.count("er_decisions"):
            log.done("decide", "O(D)", "O(0 new decisions)", t, decisions=0, matches=0, clusters_joined=0)
            return ran
        ran.n = job.count("gold_old")
        engine.run(f"CREATE OR REPLACE TABLE er_base AS SELECT {u}, cluster_id FROM gold_old")
        engine.run(f"CREATE OR REPLACE TABLE er_review AS SELECT {l}, {r} FROM er_decisions WHERE decision = 'match'")
        merge(engine, "er_base", "er_review", "clusters", job.uid)
        have = job.columns("gold_old")
        kinds = "kind" in have  # each record's kind stands; its customer's follows the merge
        flagged = "o.kind_flagged" if "kind_flagged" in have else "FALSE AS kind_flagged"  # a run written before flags: none
        engine.run(f"""CREATE OR REPLACE TABLE gold AS WITH size AS (SELECT cluster_id, count(*) AS n FROM clusters GROUP BY 1)
                 {f", customer AS ({customer_kinds('clusters', 'gold_old', u)})" if kinds else ""}
            SELECT c.{u}, c.cluster_id, coalesce(o.resolved_stage, CASE WHEN z.n > 1 THEN 'review' END) AS resolved_stage,
                   coalesce(o.resolved_by, CASE WHEN z.n > 1 THEN 'review' END) AS resolved_by
                   {f", o.kind, o.kind_p, o.kind_by, {flagged}, k.customer_kind" if kinds else ""}
            FROM clusters c JOIN size z USING (cluster_id) JOIN gold_old o USING ({u}) {"JOIN customer k USING (cluster_id)" if kinds else ""}
            ORDER BY c.{u}""")
        d, m = job.count("er_decisions"), job.count("er_review")
        before, after = (engine.value(f"SELECT count(DISTINCT cluster_id) FROM {x}") for x in ("gold_old", "gold"))
        log.done("decide", "O(D + touched clusters) + O(N)", f"O({d:,} decisions + {ran.n:,})", t, decisions=d, matches=m, clusters_joined=before - after)
        parts, sheet = out / folder.DECISIONS, out / "review.parquet"
        parts.mkdir(exist_ok=True)
        restamp = [(f"""SELECT s.* EXCLUDE (file_row_number) REPLACE (coalesce(d.decision, s.decision::VARCHAR) AS decision)
            FROM read_parquet({lit(sheet)}, file_row_number = true) s LEFT JOIN er_decisions d ON d.{l} = s.{l} AND d.{r} = s.{r}
            ORDER BY file_row_number""", sheet)] if sheet.exists() and Path(path).resolve() != sheet.resolve() else []  # the sheet shows each pair's latest: an answer given elsewhere never comes back from it
        folder.stage(engine, out, [(f"SELECT * FROM gold ORDER BY {u}", out / "gold.parquet"),
                                   (f"SELECT *, {len(folder.rounds(out)) or 'NULL'}::INTEGER AS round FROM er_decisions",
                                    parts / f"part-{folder.next_part(parts):05d}.parquet"), *restamp],
                     [(log_entry(ran, out, True, decisions=str(path)), out / folder.STEPS)])
        return ran
