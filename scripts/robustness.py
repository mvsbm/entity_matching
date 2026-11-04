"""Robustness evidence for the final configurations, computed in memory. Only a report is written:
data/artifacts/robustness/report.md.

    .venv/bin/python scripts/robustness.py            # replicates, noise, prior sensitivity, scale curve (~5 min)
    .venv/bin/python scripts/robustness.py --smoke    # also one cost run at about a million records (about 6 GB peak memory)

The configurations are the ones the matching notebooks ended with: data/artifacts/models/*_final.json records the
adopted changes, and they are re-applied to the notebooks' own Configuration cells. Nothing is re-tuned. Each
scenario builds a population with the generator from dataset_generation.ipynb, refits the probabilistic model's
parameters on its own train split (as the notebook does), and reports its test split.
"""
import json
import logging
import resource
import sys
import time
from dataclasses import replace
from functools import reduce
from pathlib import Path

import nbformat
import numpy as np
import pandas as pd

from er.config import OverBudget
from er.match import sample_u, train_fs
from er.pipeline import run_fs, run_rules
from er.settings import load_settings
from er.standardize import prepare
from er.strings import connect

logging.disable(logging.WARNING)
ROOT = Path(__file__).resolve().parents[1]
S = load_settings()
DATA, UID, ENT = S.data, S.data.unique_id, S.data.entity_id


def namespace(notebook: str, code_cells: int) -> dict:
    """Run a notebook's first code cells (imports, definitions, configuration: nothing that writes) and return them."""
    nb = nbformat.read(ROOT / "notebooks" / f"{notebook}.ipynb", as_version=4)
    ns = {"display": lambda *_: None}
    for cell in [c for c in nb.cells if c.cell_type == "code"][:code_cells]:
        exec(cell.source, ns)
    return ns


def final(ns: dict, name: str):
    saved = json.loads((DATA.models_dir / f"{name}.json").read_text(encoding="utf-8"))
    spec = reduce(lambda s, change: ns["CHANGES"][change](s), saved["adopted"], ns["SPEC"])
    return replace(spec, min_match_weight=saved["min_match_weight"]) if "min_match_weight" in saved else spec


GEN = namespace("dataset_generation", 3)
DET = final(namespace("deterministic_matching", 2), "deterministic_final")
PROB = final(namespace("probabilistic_matching", 2), "probabilistic_final")
PERSONS, COMPANIES, TOWNS = GEN["load_reference"](S.paths["reference"])
_, DB = connect()


def population(spec) -> tuple[pd.DataFrame, pd.DataFrame]:
    g = GEN["generate"](spec, PERSONS, COMPANIES, TOWNS)
    return g.df, g.truth


def split(records: pd.DataFrame, truth: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """The notebook's split: entities shuffled with SPLIT.seed and cut by SPLIT.shares."""
    shares = GEN["SPLIT"].shares
    entities = np.random.default_rng(GEN["SPLIT"].seed).permutation(truth[ENT].unique())
    cuts = np.round(np.cumsum(list(shares.values())) * len(entities)).astype(int)[:-1]
    of = {e: name for name, part in zip(shares, np.split(entities, cuts)) for e in part}
    which = truth[ENT].map(of).to_numpy()
    return {name: (records[which == name].reset_index(drop=True), truth[which == name].reset_index(drop=True)) for name in shares}


def fit(records: pd.DataFrame, truth: pd.DataFrame, model=None, u: dict | None = None) -> dict:
    model = model or PROB.model
    df = prepare(PROB.standardize, records, PROB.normalized(), PROB.used())
    return train_fs(model, df, DB, UID, labels=truth.set_index(UID)[ENT], u=u)


def u_of(records: pd.DataFrame) -> dict:  # u sampled on these records: no labels needed, fixed cost (u_max_pairs)
    return sample_u(PROB.model, list(PROB.model.comparisons), prepare(PROB.standardize, records, PROB.normalized(), PROB.used()), DB, UID)


def peak_gb() -> float:  # the process's peak resident memory so far (ru_maxrss: bytes on macOS, KB on Linux)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)


def resolve(records: pd.DataFrame, truth: pd.DataFrame, model_json: dict) -> tuple[dict, dict, float, float]:
    """Both stages on one file: rules, then the probabilistic stage on what they left. → metrics after each, seconds."""
    t = time.perf_counter()
    det = run_rules(DET, records, truth, DB, DATA)
    t_det = time.perf_counter() - t
    pairs = det.edges[[f"{UID}_l", f"{UID}_r", "stage", "rule", "score", "kept"]].astype("string")
    clusters = det.records[[UID, "CLUSTER_ID"]].set_axis([UID, "cluster_id"], axis=1).astype("string")
    t = time.perf_counter()
    res = run_fs(PROB, model_json, records, truth, pairs, clusters, DB, DATA)
    return res.metrics.iloc[0].to_dict(), res.metrics.iloc[-1].to_dict(), t_det, time.perf_counter() - t


def row(name: str, before: dict, after: dict) -> dict:
    return dict(scenario=name, rules_recall=round(before["recall"], 4), recall=round(after["recall"], 4),
                interval=f"{after['recall_lo']:.3f}–{after['recall_hi']:.3f}", false_merges=int(after["FP"]),
                fp_rate_at_most=f"{after['fp_rate_hi']:.2%}")


def markdown(df: pd.DataFrame) -> str:
    rows = [list(df.columns)] + df.astype(str).to_numpy().tolist()
    return "\n".join("| " + " | ".join(map(str, r)) + " |" for r in rows[:1] + [["---"] * len(df.columns)] + rows[1:])


def scenarios() -> pd.DataFrame:
    base, rows = GEN["SPEC"], []
    variants = {"as reported (seed 0)": base, "seed 1": replace(base, seed=1), "seed 2": replace(base, seed=2),
                "typos doubled": replace(base, name_typo_rate=2 * base.name_typo_rate, phone_typo_rate=2 * base.phone_typo_rate,
                                         address_typo_rate=2 * base.address_typo_rate),
                "fields emptier (last column 45% filled)": replace(base, rate_end=0.45)}
    for name, spec in variants.items():
        parts = split(*population(spec))
        before, after, *_ = resolve(*parts["test"], fit(*parts["train"]))
        rows.append(row(name, before, after))
        print(rows[-1], flush=True)
    parts = split(*population(base))
    for prior_recall in (0.25, 0.75):  # λ changes by 2×, so every weight by about ±1 bit
        model = fit(*parts["train"], replace(PROB.model, prior_recall=prior_recall))
        before, after, *_ = resolve(*parts["test"], model)
        rows.append(row(f"prior_recall {prior_recall} (λ {'×2' if prior_recall < 0.5 else '×⅔'})", before, after))
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


def scale(smoke: bool) -> pd.DataFrame:
    """Production cost: one model fitted on a train-sized split scores files of growing size, both stages. Up to
    len(PERSONS) entities every entity is a distinct persona. Above that, personas repeat and two entities can be
    clones no matcher can tell apart, so those rows measure cost only. `recall_u_from_file` re-samples u on the scored
    file (m and λ still from train): the fields whose value sets grow with N (address, CIF ID) then keep their weight."""
    base = GEN["SPEC"]
    train = split(*population(base))["train"]
    model = fit(*train)
    sizes = [10_000, 20_000, 40_000, 60_000] + ([800_000] if smoke else [])
    rows = []
    for n in sizes:
        persons = PERSONS if n <= len(PERSONS) else pd.concat([PERSONS] * (n // len(PERSONS) + 1), ignore_index=True)
        g = GEN["generate"](replace(base, entities=n), persons, COMPANIES, TOWNS)
        try:
            _, after, t_det, t_prob = resolve(g.df, g.truth, model)
        except OverBudget as e:
            print(f"{len(g.df):,} records: over budget: {e}", flush=True)
            continue
        row = dict(records=len(g.df), rules_seconds=round(t_det, 1), probabilistic_seconds=round(t_prob, 1),
                   peak_memory_gb=round(peak_gb(), 1), recall="—", false_merges="—", fp_rate_at_most="—", recall_u_from_file="—")
        if n <= len(PERSONS):
            _, local, *_ = resolve(g.df, g.truth, fit(*train, u=u_of(g.df)))
            row |= dict(recall=round(after["recall"], 4), false_merges=int(after["FP"]), fp_rate_at_most=f"{after['fp_rate_hi']:.2%}",
                        recall_u_from_file=round(local["recall"], 4))
        rows.append(row)
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    total = out["rules_seconds"] + out["probabilistic_seconds"]
    alpha = np.polyfit(np.log(out["records"]), np.log(total), 1)[0]
    out.attrs["alpha"] = round(float(alpha), 2)
    return out


if __name__ == "__main__":
    smoke = "--smoke" in sys.argv
    robust, cost = scenarios(), scale(smoke)
    report = ("# Robustness report\n\n## Scenarios (test split, fixed final configurations, nothing re-tuned)\n\n"
              + markdown(robust)
              + f"\n\n## Cost: both stages on files of growing size (time grows like N^{cost.attrs['alpha']})\n\n"
              + f"One model fitted on train. Above {len(PERSONS):,} entities personas repeat, so those rows measure cost only.\n\n"
              + markdown(cost) + "\n")
    path = DATA.artifacts_dir / "robustness" / "report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(report)
