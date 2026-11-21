"""The full run: one records file resolved into a workspace, one line per step (er/steps/). Its cost is the steps':
O(N·L) to load, O(n + S·K + P_em·K) + O(N + S·K) to fit, O(N + Σ P) for the keys and rules, O(C·K·L²) to score,
O(C + E·log E + N) to cluster, O(N + C) to write. N records, L characters per value, n the fit's sample, S sampled
pairs for u, K comparisons, P a key's or rule's pairs, C candidates, E accepted pairs."""
from collections.abc import Callable
from pathlib import Path

from er import folder
from er.config import InputError, Pipeline
from er.settings import Settings
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
    """The file at `path` resolved into the workspace `out`, with people's decisions kept there; with `pipeline_file`
    (named in the reports), the reports are written with the run's files. `model`: a fitted model (none: fitted on the
    file). `reaching_only` False: every pair the keys list is stored, whatever it scores (design time). A folder that holds a run is refused unless `overwrite`; the old run goes only once the new one is complete."""
    out = Path(out)
    with folder.run_lock(out, make=True):  # one writer at a time
        folder.finish_writes(out)
        held = folder.held(out)
        if held and not overwrite:
            raise InputError(f"{out} already holds a run", fix="choose another folder, or replace the run: nayose resolve records … --overwrite")
        ran = resolve(path, settings, pipeline, model=model, keep=out, decided=out, echo=echo, told=told, reaching_only=reaching_only)
        write(ran, out, replace_files=held, reports=(path, pipeline_file) if pipeline_file else None)
        return ran


def resolve(path: str | Path | list[Path], settings: Settings, pipeline: Pipeline, *, model: dict | None = None, keep: Path | None = None,
            decided: Path | None = None, echo: Callable[[dict], None] | None = None, told: Callable[..., None] | None = None,
            reaching_only: bool = True) -> Ran:
    """The steps on the file at `path`, writing nothing: each record's cluster (gold), with the decisions the workspace
    `decided` keeps (None: none). `keep`: the workspace whose cleaned records and u samples are read again while
    nothing they rest on changed."""
    job = start(settings, pipeline, echo, told)
    loaded = load(job, path, model=model, keep=keep)
    job.pipeline = loaded.pipeline  # the method as this file lets it run
    planned = budget(job, loaded.n)
    fitted = fit(job, loaded.n, model, keep)
    ruled = rules(job, loaded.n, fitted.scoring)
    listed = candidates(job, loaded.n, fitted.scoring, planned, reaching_only=reaching_only)
    score(job, fitted.scoring, listed.listed)
    load_decisions(job, decided)
    cluster(job, loaded.n)
    return Ran(job, n=loaded.n, model=fitted.model, scoring=fitted.scoring, basis=fitted.basis, disabled=loaded.disabled,
               present=loaded.present, unmapped=loaded.unmapped, gated=listed.gated, plan=planned.plan, classifier=loaded.classifier,
               placeholders=loaded.placeholders, inputs=loaded.inputs, listed=listed.listed, rule_seconds=ruled.seconds,
               config=run_config(pipeline, settings))
