"""A match run: the pairs of a written run at the threshold people set, as one table for them to review and decide on
(decide reads their decisions back). The build merges nothing by itself; this is where pairs become matches, and only
those people then say are one.

    match   O(C) to scan scored/ + O(P·F) to join the P pairs kept to their records' F fields
"""
import time
from collections.abc import Callable
from pathlib import Path

from er import folder
from er.config import InputError, Pipeline, bits, lit, q
from er.jobs.index import _pipeline, run_model
from er.match import levels
from er.report import no_run
from er.settings import Settings
from er.steps.job import start


def match(out: Path, settings: Settings, pipeline: Pipeline, threshold: float, into: Path | None = None,
          echo: Callable[[dict], None] | None = None) -> dict:
    """Every pair the run in `out` scored (scored/) at `threshold` points or more, less the pairs people said are
    no_match, as one Parquet table at `into` (default: <out>/matched/points-<threshold>.parquet), highest points first.
    Each row: an empty `decision` for people (match or no_match); the pair; its points and probability; the rule that
    joins it too, if one does (rule pairs are in it only where they reach the threshold too); the keys that listed it
    (sources); whether a name was compared (named); whether it may be two people of one household; both records'
    compared fields side by side; and each comparison's level and the bits it earned. A threshold below [threshold]
    keep_from is refused: the run keeps no pair below it."""
    out, t = Path(out), time.perf_counter()
    floor = pipeline.threshold.keep_from
    if threshold < floor:
        raise InputError(f"--threshold {threshold:g}: the run keeps the pairs from {floor:g} points up only",
                         fix=f"give a threshold of {floor:g} or more, or lower [threshold] keep_from in the pipeline and build the run again")
    with folder.run_lock(out):
        folder.finish_writes(out)
        parts = sorted((out / "state" / "records").glob("part-*.parquet"))
        if not parts or not any((out / folder.SCORED).glob("part-*.parquet")):
            raise no_run(out, "match")
        job = start(settings, pipeline, echo)
        engine, u, l, r = job.engine, q(job.uid), q(job.l), q(job.r)
        records = engine.read(parts, by_name=True)
        have = [c for c, _ in engine.columns(records)]
        p, model = _pipeline(out, settings, pipeline, have), run_model(out)
        comps = p.fs.model.comparisons
        fields = [f for f in dict.fromkeys(col for c in comps for col in (*c.null_if_missing, *(x for lv in c.levels for x, _ in lv.any_of))) if f in have]
        by = levels(model)
        level = lambda c, i: f"CASE s.{q('gamma_' + c)} " + " ".join(f"WHEN {g} THEN {lit(x[0]) if i == 0 else f'CAST({round(x[1], 2)} AS DOUBLE)'}" for g, x in by[c].items()) + " END"
        said = folder.latest_decisions(engine, out, job.uid)
        apart = f"AND NOT EXISTS (SELECT 1 FROM {said} d WHERE d.{l} = s.{l} AND d.{r} = s.{r} AND d.decision = 'no_match')" if said else ""
        sql = f"""SELECT CAST(NULL AS VARCHAR) AS decision, s.{l}, s.{r}, s.match_weight, s.match_probability, s.rule, s.named,
                {p.household.sql(set(have))} AS household, s.sources,
                {', '.join(f'l.{q(f)} AS {q(f + "_l")}, r.{q(f)} AS {q(f + "_r")}' for f in fields)},
                {', '.join(f'{level(c.name, 0)} AS {q(c.name)}, {level(c.name, 1)} AS {q(c.name + "_bits")}' for c in comps)}
            FROM {engine.read(out / folder.SCORED / 'part-*.parquet', by_name=True)} s
            JOIN {records} l ON l.{u} = s.{l} JOIN {records} r ON r.{u} = s.{r}
            WHERE s.match_weight >= {bits(threshold)} {apart}
            ORDER BY s.match_weight DESC, s.{l}, s.{r}"""
        dest = Path(into) if into else out / folder.MATCHED / f"points-{threshold:g}.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        folder.stage(engine, out, [(sql, dest)])
        pairs = engine.value(f"SELECT count(*) FROM {engine.read(dest)}")
        engine.close()
    return dict(pairs=pairs, threshold=threshold, into=str(dest), seconds=round(time.perf_counter() - t, 2))
