"""An increment: a batch of new records added to a written run.

The batch is joined against all records, rule by rule and generator by generator, and scored; its pairs join the
run's scored/, and each new record is an entity of its own until people's decisions join it. Its cost is O(|Δ|·(L + Σ b) + C_Δ·K·L²) plus narrow O(N) scans (the stored
key columns, the exact u counts, gold rewritten), whatever N; b is a block's size, C_Δ the pairs touching the batch.
It keeps the stored model, and samples u again only for a comparison whose drift has outgrown its sampling error
(er.match.refreshed_u). A full run (jobs.build) re-fits and re-scores everything."""
import json
from collections.abc import Callable
from pathlib import Path


from er import folder
from er.jobs import index
from er.jobs.build import given, indexed
from er.config import InputError, Pipeline, q
from er.report import no_run
from er.settings import Settings
from er.source import readable
from er.steps.candidates import candidates
from er.steps.cluster import cluster, load_decisions
from er.steps.fit import u_again
from er.steps.job import Ran, start
from er.steps.load import load, placeholders
from er.steps.rules import rules
from er.steps.score import score
from er.steps.write import run_config, write


def update(path: str | Path, out: Path, settings: Settings, pipeline: Pipeline, *, pipeline_file: Path | None = None,
           echo: Callable[[dict], None] | None = None, told: Callable[..., None] | None = None, reaching_only: bool = True) -> Ran:
    """The batch at `path` (a Parquet file, a quoted glob or a folder of them), read by the intake
    (er.source.readable), added to the run in `out`, with its reports as a full run writes them (with
    `pipeline_file`), then the lookup index brought up to date. Nothing is written when every record is already in the
    run (ran.added 0). `reaching_only` False: every pair the keys list is stored, whatever it scores (design time)."""
    out = Path(out)
    with folder.run_lock(out):
        with readable(path, settings.input, told) as read:
            ran = join(read, out, settings, pipeline, echo, told, reaching_only)
            ran.inputs = given(path, ran.inputs, "records")
        if ran.added:
            write(ran, out, pipeline_file=pipeline_file)
            ran.index = indexed(out, settings, pipeline, index.update)
        return ran


def join(path: str | Path, out: Path, settings: Settings, pipeline: Pipeline, echo: Callable[[dict], None] | None = None,
         told: Callable[..., None] | None = None, reaching_only: bool = True) -> Ran:
    """The increment's steps on the batch at `path` against the run in `out`, up to its clusters (gold), writing
    nothing. ran.added is 0 when every record is already in the run, and nothing else ran."""
    state, config = out / "state", run_config(pipeline, settings)
    folder.finish_writes(out)
    if not (state / "model.json").exists():
        raise no_run(out, "add records to")
    if (state / "config.txt").exists() and (state / "config.txt").read_text(encoding="utf-8") != config:
        raise InputError(f"the pipeline or the column mapping changed since the full run in {out}: an increment would resolve its batch otherwise",
                         fix=f"build the run again with them (python -m er build FILE --out {out} --overwrite), or add these with the pipeline and config/settings.toml that run used")
    job = start(settings, pipeline, echo, told)
    engine, u = job.engine, q(job.uid)
    model = json.loads((state / "model.json").read_text(encoding="utf-8"))
    parts = sorted((state / "records").glob("part-*.parquet"))  # not a glob: this run's own part comes later
    engine.run(f"CREATE OR REPLACE VIEW old_records AS SELECT * FROM {engine.read(parts, by_name=True)}")
    loaded = load(job, path, model=model, into="new_records", stored="old_records")  # a record already in the run is set aside: a retry adds nothing twice
    job.pipeline = loaded.pipeline  # the method as the batch lets it run
    ran = Ran(job, added=loaded.n, model=model, part=folder.next_part(state / "records"), config=config, disabled=loaded.disabled,
              present=loaded.present, unmapped=loaded.unmapped, classifier=loaded.classifier, inputs=loaded.inputs)
    if not loaded.n:
        if engine.value("SELECT count(*) FROM set_aside WHERE reason <> 'already in the run'"):
            raise InputError(f"{path}: no new record to add ({'; '.join(job.log.notes)})", fix="give the records set aside IDs, one per record")
        return ran  # every record is already in the run: nothing to do
    engine.run("CREATE OR REPLACE TABLE records AS SELECT * FROM old_records UNION ALL BY NAME SELECT * FROM new_records")  # read by every step: once
    stored = state / "placeholders.json"
    known = json.loads(stored.read_text(encoding="utf-8")) if stored.exists() else {}
    ran.placeholders = placeholders(job, job.pipeline, "records", known, also=("new_records",))  # the run's own, and any the batch takes past the line
    engine.run(f"CREATE OR REPLACE TABLE new_ids AS SELECT {u} FROM new_records")
    ran.n = job.count("records")
    fitted = u_again(job, ran.n, model, state)
    ran.scoring, ran.basis = fitted.scoring, fitted.basis
    engine.run(f"""CREATE OR REPLACE TABLE rule_clusters AS SELECT * FROM {engine.read(state / 'rule_clusters.parquet')}
        UNION ALL SELECT {u}, {u} AS cluster_id FROM new_ids""")  # the stored clusters, and each new record alone
    ran.rule_seconds = rules(job, ran.n, fitted.scoring, batch="new_records").seconds
    listed = candidates(job, ran.n, fitted.scoring, None, batch="new_ids", reaching_only=reaching_only)  # the full run's steps, on the pairs touching the batch
    ran.gated, ran.listed = listed.gated, listed.listed
    score(job, fitted.scoring, listed.listed)
    load_decisions(job, out)  # people's "different" on a record back in the run stands, as in a full run
    cluster(job, ran.n, old=out / "gold.parquet")
    return ran
