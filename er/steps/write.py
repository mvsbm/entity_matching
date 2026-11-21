"""Step 8, write: the run's files into its workspace, staged (er.folder.stage: each file under a temporary name, the
moves still owed saved, then made), with the reports built first. O(N + C). Reads gold, matches, rule_kept,
rule_clusters, set_aside, scores, cands, rule_scores, and records (a full run) or new_records (an increment)."""
import json
import time
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path

from er import folder
from er.config import FSModel, Pipeline, q
from er.io import code_version, config_hash
from er.settings import Settings
from er.steps.job import Ran
from er.steps.report import report
from er.steps.score import links_sql

PLACEHOLDERS = 3  # how placeholders are told (steps.load.placeholders): a run that told them otherwise takes no increment until it runs again
FINGERPRINTED_ROWS = 30_000  # the fit's sample, as every run's fingerprint holds it: whatever a run samples, its increments take no rerun


def run_config(p: Pipeline, s: Settings) -> str:
    """What an increment needs the full run's to be: the pipeline and the settings that shape the records. The fit's
    sample and EM (the sessions' rules too) are left out: an increment and a lookup score with the stored model."""
    fit = {f.name: f.default for f in fields(FSModel) if f.name in ("em_from_keys", "em_median")}
    p = replace(p, fit_rows=FINGERPRINTED_ROWS, fs=replace(p.fs, model=replace(p.fs.model, em_rules=(), **fit)))
    keep = p.threshold.keep_from  # out of the dataclass's repr, so a workspace that never set it keeps its hash
    return config_hash((p, s.columns, s.standardize, s.flag_company, s.input, PLACEHOLDERS) + ((("keep", keep),) if keep else ()))


def write(ran: Ran, out: Path, replace_files: list[Path] | None = None, reports: tuple[str | Path, Path] | None = None) -> None:
    """Gold (each record's cluster, the stage and rule that resolved it, its kind and its customer's), the accepted
    pairs with their weights, the rules' pairs (with their weights, and whether each merged), as Parquet; and the state
    an increment needs: the standardized records and the rules' clusters. Records, rules' pairs and matches are
    folders that increments append to (ran.part). `replace_files` (a full run): the old run's files, which the new ones
    replace. `reports` (the input and the pipeline file): the reports for people (steps.report), built first and written
    with these files."""
    job, part = ran.job, ran.part
    people, frames = report(ran, reports[0], out, reports[1]) if reports else ([], [])
    t, state, name = time.perf_counter(), out / "state", f"part-{part:05d}.parquet"
    aside = [("SELECT * FROM set_aside", out / "set_aside" / name)] if job.count("set_aside") else []
    texts = [(json.dumps(ran.model, ensure_ascii=False), state / "model.json"), (ran.config, state / "config.txt")] if part == 0 else []
    texts.append((json.dumps(ran.placeholders, ensure_ascii=False), state / "placeholders.json"))  # read as missing: an increment and a lookup read them so too
    if ran.basis:  # the u this run scored with, and what an increment needs to tell when they go stale
        texts.append((json.dumps(dict(model=ran.scoring, basis=ran.basis), ensure_ascii=False), state / "scoring.json"))
    if part == 0:  # the round this method is in, and how it did: lands with the run
        linked = next(x for x in reversed(ran.steps) if x["step"] == "cluster")
        texts.append((folder.round_ran(out, dict(config=ran.config, at=datetime.now().isoformat(timespec="seconds"),
                                                 matched=linked["accepted"], expected_false=linked["expected_false"])), out / folder.ROUNDS))
    earlier = folder.history(out) if part == 0 else None  # the runs before: read before the old log goes with the old run
    # an increment adds to the pair index its full run began; a run written before it had none gets it whole, once (results.pair_index)
    scored = [(links_sql(job), out / folder.SCORED / name)] if part == 0 or (out / folder.SCORED / "part-00000.parquet").exists() else []

    def logged() -> str:  # once the files are written: the write's time, in the entry that lands with them
        job.log.done("write", "O(N + C)", f"O({ran.n:,} + {job.count('matches'):,})", t)
        return log_entry(ran, out, part > 0, earlier, part=part, disabled=ran.disabled, pipeline=str(Path(reports[1]).resolve()) if reports else None)
    folder.stage(job.engine, out, [("SELECT * FROM rule_kept", out / "rule_kept" / name), ("SELECT * FROM matches", out / "matches" / name),
                                   *scored,
                                   (f"SELECT * FROM gold ORDER BY {q(job.uid)}", out / "gold.parquet"),
                                   ("SELECT * FROM rule_clusters", state / "rule_clusters.parquet"),
                                   (f"SELECT * FROM {'records' if part == 0 else 'new_records'}", state / "records" / name), *aside],
                 [*texts, *people, (logged, out / folder.STEPS)], replace_files, frames)


def log_entry(ran: Ran, out: Path, append: bool, earlier: list[dict] | None = None, **entry: object) -> str:
    """steps.json with this run's entry (folder.log): when, the code and config that ran, the files read with their
    SHA-256, and each step; a full run's, after `earlier` (folder.history)."""
    return folder.log(out, dict(at=datetime.now().isoformat(timespec="seconds"), code=code_version(ran.settings.root), config=ran.config,
                                inputs=ran.inputs, **entry, steps=ran.steps), append, earlier)
