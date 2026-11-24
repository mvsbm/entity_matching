"""The full run: one records file resolved into a workspace, one line per step (er/steps/), then its lookup index. Its cost is the steps':
O(N·L) to load, O(n + S·K + P_em·K) + O(N + S·K) to fit, O(N + Σ P) for the keys and rules, O(C·K·L²) to score,
O(C + E·log E + N) to cluster, O(N + C) to write. N records, L characters per value, n the fit's sample, S sampled
pairs for u, K comparisons, P a key's or rule's pairs, C candidates, E accepted pairs."""
import gc
from collections.abc import Callable
from pathlib import Path

import duckdb

from er import folder
from er.jobs import index
from er.config import InputError, Pipeline
from er.settings import Settings
from er.source import file_facts, find, readable
from er.steps.budget import budget
from er.steps.candidates import candidates
from er.steps.cluster import cluster, load_decisions
from er.steps.fit import fit
from er.steps.job import Ran, start
from er.steps.load import load
from er.steps.rules import rules
from er.steps.score import score
from er.steps.write import run_config, write


def build(path: str | Path | list[Path], out: Path, settings: Settings, pipeline: Pipeline, *, model: dict | None = None,
          overwrite: bool = False, pipeline_file: Path | None = None, echo: Callable[[dict], None] | None = None,
          told: Callable[..., None] | None = None, reaching_only: bool = True) -> Ran:
    """The records at `path` (a Parquet file, a quoted glob or a folder of them), read by the intake
    (er.source.readable), resolved into the workspace `out` with people's decisions kept there, then the lookup index
    built (er.jobs.index). With `pipeline_file` (named in the reports), the reports are written with the run's files.
    `model`: a fitted model (none: fitted on the file). `reaching_only` False: every pair the keys list is stored,
    whatever it scores (design time). A folder that holds a run is refused unless `overwrite`; the old run goes only
    once the new one is complete."""
    out = Path(out)
    with folder.run_lock(out, make=True):  # one writer at a time
        folder.finish_writes(out)
        held = folder.held(out)
        if held and not overwrite:
            raise InputError(f"{out} already holds a run", fix=f"choose another folder, or replace the run: python -m er build {path} --out {out} --overwrite")
        with readable(path, settings.input, told) as read:
            ran = resolve(read, settings, pipeline, model=model, decided=out, echo=echo, told=told, reaching_only=reaching_only)
            ran.inputs = given(path, ran.inputs, "records")
            write(ran, out, replace_files=held, pipeline_file=pipeline_file)
        ran.index = indexed(out, settings, pipeline, index.build)
        return ran


def resolve(path: str | Path | list[Path], settings: Settings, pipeline: Pipeline, *, model: dict | None = None,
            decided: Path | None = None, echo: Callable[[dict], None] | None = None, told: Callable[..., None] | None = None,
            reaching_only: bool = True) -> Ran:
    """The steps on the records at `path` as the intake read them, writing nothing: each record's cluster (gold), with
    the decisions the workspace `decided` keeps (None: none)."""
    job = start(settings, pipeline, echo, told)
    loaded = load(job, path, model=model)
    job.pipeline = loaded.pipeline  # the method as this file lets it run
    planned = budget(job, loaded.n)
    fitted = fit(job, loaded.n, model)
    ruled = rules(job, loaded.n, fitted.scoring)
    listed = candidates(job, loaded.n, fitted.scoring, planned, reaching_only=reaching_only)
    score(job, fitted.scoring, listed.listed)
    load_decisions(job, decided)
    cluster(job, loaded.n)
    return Ran(job, n=loaded.n, model=fitted.model, scoring=fitted.scoring, basis=fitted.basis, disabled=loaded.disabled,
               present=loaded.present, unmapped=loaded.unmapped, gated=listed.gated, plan=planned.plan, classifier=loaded.classifier,
               placeholders=loaded.placeholders, inputs=loaded.inputs, listed=listed.listed, rule_seconds=ruled.seconds,
               config=run_config(pipeline, settings))


def given(path: str | Path, inputs: list[dict], role: str) -> list[dict]:  # the files people gave, by their own SHA-256, for those the intake read of them
    return [*file_facts(find(path), role), *(x for x in inputs if x["role"] != role)]


def indexed(out: Path, settings: Settings, pipeline: Pipeline, how: Callable[[Path, Settings, Pipeline], dict]) -> dict:
    """The lookup index of the run in `out` built or brought up to date (`how`: index.build or index.update), or why it
    couldn't be: the run is written either way, and a lookup refuses an index older than its run (index.stale)."""
    gc.collect()  # the run's DuckDB, if a cycle holds it: gone before the index's is opened beside it
    try:
        return how(out, settings, pipeline)
    except Exception as e:
        said = e if isinstance(e, InputError) else out_of_memory(e) or InputError(f"{type(e).__name__}: {e}", fix="run the job again")
        return dict(error=str(said), fix=said.fix)


def out_of_memory(e: BaseException) -> InputError | None:  # DuckDB's, raised as it is or as the cause of another: a limit people set, which they can raise
    oom = next((x for x in (e, e.__cause__) if isinstance(x, duckdb.OutOfMemoryException)), None)
    return oom and InputError(f"out of memory: {str(oom).splitlines()[0]}", fix="raise [compute] memory_limit in config/settings.toml, or give "
                              "[compute] temp_directory a folder with more free disk")
