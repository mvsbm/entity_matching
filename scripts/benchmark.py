"""Benchmark the chosen pipeline (config/final.toml) as it runs on real files: er.run, without labels, on DuckDB
tables. Writes reports/benchmark.md. Nothing is re-tuned.

    .venv/bin/python scripts/benchmark.py                                         # scenarios and the cost curve
    .venv/bin/python scripts/benchmark.py --entities 10000 800000 --memory-limit 8GB   # cost up to a million records, in 8 GB

Quality: each scenario generates a population with er.generate (config/generator.toml, varied), fits λ, u and m on
its train split without labels, resolves its test split, and compares the clusters with the truth.
Cost: populations of growing size, each resolved by scripts/resolve.py in a process of its own, so the peak memory is
that run's alone. Past the memory limit (--memory-limit, else config/settings.toml [compute]) DuckDB spills to disk.
"""
import argparse
import json
import logging
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from er.config import load_pipeline
from er.evaluate import cluster_metrics, pair_metrics
from er.generate import generate, load_reference, load_spec, split_by_entity
from er.io import markdown
from er.run import Run
from er.settings import load_settings

logging.disable(logging.WARNING)
S = load_settings()
UID, ENT = S.data.unique_id, S.data.entity_id
FINAL = load_pipeline(S.root / "config" / "final.toml", S.standardize, S.chains, S.columns)
SPEC, SPLIT = load_spec(S.root / "config" / "generator.toml")
PERSONS, COMPANIES, TOWNS = load_reference(S.paths["reference"])
OUT = S.paths["artifacts"] / "benchmark"


def population(spec) -> tuple[pd.DataFrame, pd.Series]:
    """Records, and each record's entity. Past len(PERSONS) entities personas repeat: clones no matcher can tell apart."""
    persons = PERSONS if spec.entities <= len(PERSONS) else pd.concat([PERSONS] * (spec.entities // len(PERSONS) + 1), ignore_index=True)
    g = generate(spec, persons, COMPANIES, TOWNS)
    return g.df, g.truth.set_index(UID)[ENT]


def quality(run: Path, entity: pd.Series) -> dict:
    """A written run's clusters against the truth: after the rules, and at the end."""
    gold = pd.read_parquet(run / "gold.parquet").set_index(UID)["cluster_id"]
    rules = pd.read_parquet(run / "state" / "rule_clusters.parquet").set_index(UID)["cluster_id"].reindex(gold.index)
    e = entity.reindex(gold.index)
    m = cluster_metrics(gold, e)
    return dict(rules_recall=round(pair_metrics(rules, e)["recall"], 4), recall=round(m["recall"], 4),
                interval=f"{m['recall_lo']:.3f}–{m['recall_hi']:.3f}", false_merges=int(m["FP"]), fp_rate_at_most=f"{m['fp_rate_hi']:.2%}")


def scenarios() -> pd.DataFrame:
    base = SPEC
    measured = FINAL.fs.model.prior_recall  # what choose.py measured on train
    with_prior = lambda x: replace(FINAL, fs=replace(FINAL.fs, model=replace(FINAL.fs.model, prior_recall=x * measured)))
    variants = {"as reported (seed 0)": (base, FINAL), "seed 1": (replace(base, seed=1), FINAL), "seed 2": (replace(base, seed=2), FINAL),
                "typos doubled": (replace(base, name_typo_rate=2 * base.name_typo_rate, phone_typo_rate=2 * base.phone_typo_rate,
                                          address_typo_rate=2 * base.address_typo_rate), FINAL),
                "fields emptier (last column 45% filled)": (replace(base, rate_end=0.45), FINAL),
                "prior_recall halved (λ ×2)": (base, with_prior(0.5)),  # λ changes by 2×, so every weight by about ±1 bit
                "prior_recall ×1.5 (λ ×⅔)": (base, with_prior(1.5))}
    rows, made = [], {}
    for i, (name, (spec, p)) in enumerate(variants.items()):
        if repr(spec) not in made:
            records, entity = population(spec)
            which = split_by_entity(entity.rename(ENT).reset_index(), SPLIT).to_numpy()
            d = OUT / f"population_{len(made)}"
            d.mkdir(parents=True, exist_ok=True)
            for part in ("train", "test"):
                records[which == part].to_parquet(d / f"{part}.parquet", index=False)
            made[repr(spec)] = d, entity
        d, entity = made[repr(spec)]
        fit = Run(p, S)
        fit.load(d / "train.parquet")
        Run(p, S, model=fit.fit()).full(d / "test.parquet", OUT / f"scenario_{i}", overwrite=True)  # this script's own folders
        rows.append(dict(scenario=name, **quality(OUT / f"scenario_{i}", entity)))
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


def cost(entities: list[int], memory_limit: str) -> pd.DataFrame:
    """Each population written to Parquet and resolved by scripts/resolve.py, fitted on the file itself, as a real run."""
    rows = []
    for n in entities:
        records, entity = population(replace(SPEC, entities=n))
        d = OUT / f"cost_{n}"
        d.mkdir(parents=True, exist_ok=True)
        records.to_parquet(d / "records.parquet", index=False)
        size = len(records)
        del records
        compute = [f"memory_limit={memory_limit}"] if memory_limit else []
        done = subprocess.run([sys.executable, str(S.root / "scripts" / "resolve.py"), "--input", str(d / "records.parquet"), "--output", str(d / "run"),
                               "--overwrite", "--compute", *compute, f"temp_directory={OUT / 'spill'}"], cwd=S.root, capture_output=True, text=True)
        if done.returncode:
            print(f"{size:,} records: failed\n{done.stderr[-2000:]}", flush=True)
            rows.append(dict(records=size, seconds="failed: " + done.stderr.strip().splitlines()[-1][:120]))
            continue
        steps = json.loads((d / "run" / "steps.json").read_text())["runs"][-1]["steps"]
        row = dict(records=size, seconds=round(sum(x["seconds"] for x in steps), 1), peak_memory_gb=max(x["peak_memory_gb"] for x in steps),
                   **{x["step"]: x["seconds"] for x in steps}, recall="—", false_merges="—", fp_rate_at_most="—")
        if n <= len(PERSONS):
            q = quality(d / "run", entity)
            row |= dict(recall=q["recall"], false_merges=q["false_merges"], fp_rate_at_most=q["fp_rate_at_most"])
        rows.append(row)
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    ok = pd.to_numeric(out["seconds"], errors="coerce").notna()
    out.attrs["alpha"] = round(float(np.polyfit(np.log(out.loc[ok, "records"]), np.log(out.loc[ok, "seconds"].astype(float)), 1)[0]), 2) if ok.sum() > 1 else None
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--entities", type=int, nargs="+", default=[10_000, 20_000, 40_000, 60_000], help="population sizes of the cost curve")
    parser.add_argument("--memory-limit", default=S.compute.get("memory_limit", ""), help="DuckDB's, e.g. 8GB (default: [compute])")
    args = parser.parse_args()
    robust, curve = scenarios(), cost(args.entities, args.memory_limit)
    limit = args.memory_limit or "DuckDB's default (80% of RAM)"
    report = ["# Benchmark", "",
              "Written by `scripts/benchmark.py`: `config/final.toml` through `er.run`, the run without labels on DuckDB tables, on "
              "generated populations. Nothing is re-tuned.", "",
              "## Quality: scenarios", "",
              "Each population's test split, with λ, u and m fitted on its train split without labels.", "", markdown(robust), "",
              f"## Cost: files of growing size (time grows like N^{curve.attrs['alpha']})", "",
              f"Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: "
              f"{limit}. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on {FINAL.fit_rows:,} "
              f"records) and the u sample inside `score` ({FINAL.fs.model.u_max_pairs:,.0f} pairs) cost the same at any size, so at "
              f"these sizes the total grows far slower than N. Above {len(PERSONS):,} entities personas repeat, so those rows measure "
              "cost only.", "", markdown(curve), ""]
    path = S.root / "reports" / "benchmark.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
