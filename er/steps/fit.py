"""Step 3, fit: the model learned on a fixed-size sample, then u measured on this file. O(n + S·K + P_em·K) for the fit
on its sample of n records, then O(N + S·K) for u on the file. Reads records."""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from er.match import fit_model, fit_sample_sql, refreshed_u, scored_u, train_fs, u_basis
from er.steps.job import Job


@dataclass
class Fitted:
    model: dict                               # the model as fitted on the sample (state/model.json)
    scoring: dict                             # the model with u from this file: what the gate and the scores use
    basis: dict = field(default_factory=dict)  # what an increment needs to tell whether those u went stale (er.match.u_basis)


def fit(job: Job, n: int, model: dict | None = None) -> Fitted:
    """λ from the near-certain rules, u by random sampling, m by EM, on a fixed-size sample of whole postal areas
    (households stay together, and the cost doesn't grow with the file); skipped when a fitted `model` was given. Then
    u measured on this file (the model's choice), which the gate on oversized blocks and the scores both use: the
    sample's u would under-credit a field whose values grow with the file."""
    t, p, engine, uid = time.perf_counter(), job.pipeline, job.engine, job.uid
    if model is None:
        method = fit_model(p.fs)
        sample = engine.frame(f"{fit_sample_sql([method], uid, job.columns())} LIMIT {p.fit_rows}").astype("string")
        model = train_fs(method, sample, engine, uid)
        job.log.notes += [f"the fit found no two records sharing {f} in its sample of {len(sample):,}, so it learned nothing from them"
                          for f in model["er"].get("skipped", [])]
    fitted, sampled_at = Fitted(model, model), time.perf_counter()
    if p.fs.model.u_from_scored:
        fitted.scoring, sampled, exact = scored_u(p.fs.model, model, "records", engine, uid)
        fitted.basis = u_basis(p.fs.model, sampled, exact, "records", engine)
    job.log.done("fit", "O(n + S·K + P_em·K) + O(N + S·K)", f"n = {model['er']['fit_rows']:,}; u on {n:,} records", t,
                 sample_seconds=round(sampled_at - t, 2), file_u_seconds=round(time.perf_counter() - sampled_at, 2))  # the fit on its sample, then u on this file
    return fitted


def u_again(job: Job, n: int, model: dict, state: Path) -> Fitted:
    """An increment's: the stored model, and its u settled before the gate needs them: the exact levels counted again
    on every record, a comparison sampled again only once it is stale (er.match.refreshed_u). O(N + S·K_stale)."""
    t, again, p = time.perf_counter(), [], job.pipeline
    fitted = Fitted(model, model)
    if p.fs.model.u_from_scored:
        stored = state / "scoring.json"
        basis = json.loads(stored.read_text(encoding="utf-8"))["basis"] if stored.exists() else {}
        fitted.scoring, fitted.basis, again = refreshed_u(p.fs.model, model, basis, "records", job.engine, job.uid)
        job.log.notes += [f"u of {c} measured again: it drifted {fitted.basis[c]['last_check']['drift_bits']:.3f} bits, more than "
                          f"its sampling error ({fitted.basis[c]['last_check']['se_bits']:.3f})" for c in again if fitted.basis[c]['last_check']['drift_bits'] is not None]
    job.log.done("fit", "O(N + S·K_stale)", f"O({n:,} + {p.fs.model.u_max_pairs:,.0f}·{len(again)})", t, sampled_again=len(again))
    return fitted
