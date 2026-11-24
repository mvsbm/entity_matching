"""Benchmark the chosen pipeline (config/pipeline.toml) as it runs on real files: er.jobs.build, without labels, on DuckDB
tables. Writes reports/benchmark.md. Nothing is re-tuned.

    .venv/bin/python scripts/benchmark.py                 # scenarios and the cost curve up to 60,000 entities
    .venv/bin/python scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB   # reports/benchmark.md: up to a million records, in 8 GB

The report starts with the command that wrote it.

Quality: each scenario generates a population with design.generate (config/generator.toml, varied), fits λ and m on
its train split without labels, resolves its test split with u measured on it, and compares the entities at the
method's design threshold (accepted) with the truth.
Person or company: populations with every kind problem on (design.generate.kind_problems) and one name column, resolved
with names routed by the truth, by the file's flag alone, and by the kind step.
Cost: populations of growing size, each resolved by `python -m er build` in a process of its own, so the peak memory is
that run's alone. Past the memory limit (--memory-limit, else config/settings.toml [compute]) DuckDB spills to disk.
"""
import argparse
import json
import logging
import shlex
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from er.config import load_pipeline
from design.evaluate import cluster_metrics, false_pairs, labelled, pair_metrics
from design.generate import KindProblems, generate, kind_problems, load_reference, load_registry, load_spec, split_by_entity
from er.io import markdown, read_parquet
from er.cluster import merge
from er.engine.duckdb import connect
from er.steps.fit import fit
from er.steps.job import start
from er.steps.load import load
from er.jobs.build import build
from er.settings import load_settings, shared_name

logging.disable(logging.WARNING)
S = load_settings()
UID, ENT = S.data.unique_id, S.data.entity_id
FINAL = load_pipeline(S.root / "config" / "pipeline.toml", S.standardize, S.chains, S.columns)
SPEC, SPLIT = load_spec(S.root / "config" / "generator.toml")
PERSONS, COMPANIES, TOWNS = load_reference(S.paths["reference"])
OUT = S.paths["artifacts"] / "benchmark"


def population(spec) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Records, and each record's labels (its entity and household). Past len(PERSONS) entities personas repeat: clones
    no matcher can tell apart."""
    persons = PERSONS if spec.entities <= len(PERSONS) else pd.concat([PERSONS] * (spec.entities // len(PERSONS) + 1), ignore_index=True)
    g = generate(spec, persons, COMPANIES, TOWNS)
    return g.df, g.truth.set_index(UID)


def accepted(run: Path, p) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """The method at its design threshold, as a match run at min_match_weight would offer it and people take it whole:
    every rule pair, and the model's pairs there or above with a name compared (named), from the run's scored/; the
    records' entities by transitive closure (er.cluster.merge). Each record's entity, the rules' alone, and the model's
    pairs taken."""
    l, r = f"{UID}_l", f"{UID}_r"
    scored = read_parquet(run / "scored")
    model = scored[scored["sources"].notna() & scored["named"] & (scored["match_weight"] >= p.fs.min_match_weight)]
    rules = scored.loc[scored["rule"].notna(), [l, r]]
    ids = read_parquet(run / "gold.parquet")[UID]
    engine = connect()
    engine.register("er_base", pd.DataFrame({UID: ids, "cluster_id": ids}))

    def closure(edges: pd.DataFrame) -> pd.Series:  # each record's entity, these pairs taken
        engine.register("er_edges", edges)
        merge(engine, "er_base", "er_edges", "er_entities", UID)
        return engine.frame("SELECT * FROM er_entities").set_index(UID)["cluster_id"].reindex(ids.to_numpy())
    entity, by_rules = closure(pd.concat([rules, model[[l, r]]], ignore_index=True)), closure(rules)
    engine.close()
    return entity, by_rules, model


def links(model: pd.DataFrame) -> dict:
    """The model's links taken, and the false ones the model expects among them (the sum of 1 − match probability)."""
    return dict(model_links=len(model), expected_false=round(float((1 - model["match_probability"]).sum()), 2))


def quality(run: Path, truth: pd.DataFrame, p) -> dict:
    """A written run's entities at the design threshold (accepted) against the truth: after the rules, and at the end;
    and its model links that are false. Pairs of two people of one household are counted apart (household_merges)."""
    gold, rules, model = accepted(run, p)
    entity, household = labelled(truth.reset_index(), S.data)
    e, h = entity.reindex(gold.index), household.reindex(gold.index) if household is not None else None
    m = cluster_metrics(gold, e, h)
    return dict(rules_recall=round(pair_metrics(rules, e, h)["recall"], 4), recall=round(m["recall"], 4),
                interval=f"{m['recall_lo']:.3f}–{m['recall_hi']:.3f}", false_merges=int(m["FP"]), fp_rate_at_most=f"{m['fp_rate_hi']:.2%}",
                household_merges=int(m["household"]), **links(model),
                false_links=int(false_pairs(model[f"{UID}_l"], model[f"{UID}_r"], entity, household).sum()))


def scenarios() -> pd.DataFrame:
    base = SPEC
    measured = FINAL.fs.model.prior_recall  # as config/pipeline.toml sets it
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
            records, truth = population(spec)
            which = split_by_entity(truth.reset_index(), SPLIT).to_numpy()
            d = OUT / f"population_{len(made)}"
            d.mkdir(parents=True, exist_ok=True)
            for part in ("train", "test"):
                records[which == part].to_parquet(d / f"{part}.parquet", index=False)
            made[repr(spec)] = d, truth
        d, truth = made[repr(spec)]
        job = start(S, p)  # the model fitted on train, as a run fits it
        loaded = load(job, d / "train.parquet")
        job.pipeline = loaded.pipeline
        model = fit(job, loaded.n).model
        job.engine.close()
        build(d / "test.parquet", OUT / f"scenario_{i}", S, p, model=model, overwrite=True)  # this script's own folders
        rows.append(dict(scenario=name, **quality(OUT / f"scenario_{i}", truth, p)))
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


FLAGS = {"good (1% wrong at random, 20% on representatives)": KindProblems(flag_wrong=0.01, flag_wrong_representative=0.2, sole_flagged_company=0.1),
         "medium (3%, 50%)": KindProblems(),
         "poor (10%, 80%)": KindProblems(flag_wrong=0.10, flag_wrong_representative=0.8, sole_flagged_company=0.5)}


def kinds(entities: int) -> pd.DataFrame:
    """Person or company, end to end: populations with one name column for every kind, representative-named companies,
    sole traders, company dates and a flag good, medium or poor, each resolved three ways. The truth routes each name
    (the flag replaced by the truth, taken as it is: the bound); the flag alone (taken as it is); the kind step (er.kind:
    a written legal form, or a name the model is sure of; else the flag). A person–company cluster holds a true person
    and a true company."""
    std, reg = S.standardize, load_registry(S.paths["reference"])
    s = shared_name(S, "NAME_KANA")
    p = load_pipeline(S.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    flag_only = replace(p, kind=replace(p.kind, trust_flag=True))
    rows = []
    for i, (name, problems) in enumerate(FLAGS.items()):
        g = kind_problems(generate(replace(SPEC, entities=entities), PERSONS, COMPANIES, TOWNS), problems, reg,
                          std.legal_front, std.legal_end, SPEC.kana_confusions, SPEC.branches)
        d = OUT / f"kinds_{i}"
        shutil.rmtree(d, ignore_errors=True)  # fresh: a workspace keeps people's decisions across --overwrite
        d.mkdir(parents=True)
        g.df.to_parquet(d / "records.parquet", index=False)
        g.df.assign(PERSON_ORG_CODE=np.where(g.truth["KIND"].eq("company"), "2", "1")).to_parquet(d / "truth_flag.parquet", index=False)
        truth = g.truth.set_index(UID)
        for how, folder, pipeline, records in (("the truth", "truth", flag_only, "truth_flag.parquet"),
                                               ("the flag alone", "flag", flag_only, "records.parquet"),
                                               ("the kind step", "kind", p, "records.parquet")):
            run = build(d / records, d / folder, s, pipeline)
            gold = read_parquet(d / folder / "gold.parquet").set_index(UID).assign(cluster_id=accepted(d / folder, pipeline)[0]).join(
                truth[["ENTITY_ID", "KIND", "HOUSEHOLD_ID"]])
            m = cluster_metrics(gold["cluster_id"], gold["ENTITY_ID"], gold["HOUSEHOLD_ID"])
            mixed = gold.assign(c=gold["KIND"].eq("company")).groupby("cluster_id")["c"].agg(["any", "all"])
            company, person = gold["KIND"].eq("company"), gold["KIND"].eq("person")
            rows.append(dict(flag=name, routed_by=how, recall=round(m["recall"], 4), false_merges=int(m["FP"]),
                             person_company_clusters=int((mixed["any"] & ~mixed["all"]).sum()), 
                             sure_companies=f"{(gold['kind'].eq(2) & company).sum() / company.sum():.1%}", wrong_companies=int((gold["kind"].eq(2) & person).sum()),
                             sure_persons=f"{(gold['kind'].eq(1) & person).sum() / person.sum():.1%}", wrong_persons=int((gold["kind"].eq(1) & company).sum()),
                             seconds=round(sum(x["seconds"] for x in run.steps), 1)))
            print(rows[-1], flush=True)
    return pd.DataFrame(rows)


def cost(entities: list[int], memory_limit: str) -> pd.DataFrame:
    """Each population written to Parquet and resolved by `python -m er build`, fitted on the file itself, as a real run."""
    rows = []
    for n in entities:
        records, truth = population(replace(SPEC, entities=n))
        d = OUT / f"cost_{n}"
        d.mkdir(parents=True, exist_ok=True)
        records.to_parquet(d / "records.parquet", index=False)
        size = len(records)
        del records
        compute = [f"memory_limit={memory_limit}"] if memory_limit else []
        shutil.rmtree(d / "run", ignore_errors=True)  # a fresh folder: the run measured whole
        done = subprocess.run([sys.executable, "-m", "er", "build", str(d / "records.parquet"), "--out", str(d / "run"),
                               "--overwrite", "--compute", *compute, f"temp_directory={OUT / 'spill'}"], cwd=S.root, capture_output=True, encoding="utf-8", errors="replace")
        if done.returncode:
            print(f"{size:,} records: failed\n{done.stderr[-2000:]}", flush=True)
            rows.append(dict(records=size, seconds="failed: " + done.stderr.strip().splitlines()[-1][:120]))
            continue
        steps = json.loads((d / "run" / "steps.json").read_text(encoding="utf-8"))["runs"][-1]["steps"]
        row = dict(records=size, seconds=round(sum(x["seconds"] for x in steps), 1), peak_memory_gb=max(x["peak_memory_gb"] for x in steps),
                   **{x["step"]: x["seconds"] for x in steps}, recall="—", false_merges="—", fp_rate_at_most="—", **links(accepted(d / "run", FINAL)[2]),
                   false_links="—")
        if n <= len(PERSONS):
            q = quality(d / "run", truth, FINAL)
            row |= {k: q[k] for k in ("recall", "false_merges", "fp_rate_at_most", "false_links")}
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
    robust, kind, curve = scenarios(), kinds(20_000), cost(args.entities, args.memory_limit)
    limit = args.memory_limit or "DuckDB's default (80% of RAM)"
    report = ["# Benchmark", "",
              f"Written by `{shlex.join(['scripts/benchmark.py', *sys.argv[1:]])}`: `config/pipeline.toml` through `jobs.build.build`, the run "
              "without labels on DuckDB tables, on generated populations. Nothing is re-tuned. A run merges nothing by itself; each is "
              f"measured at the method's design threshold ({FINAL.fs.min_match_weight:g} points), as people would take a match run there "
              "whole: every rule pair, and the model's pairs at it or above with a name compared, joined by transitive closure.", "",
              "## Quality: scenarios", "",
              "Each population's test split, with λ and m fitted on its train split without labels and u measured on the test split, as a run does. `false_merges` are pairs of "
              "records in one cluster that are two entities; `false_links` are the model's links between two entities, and "
              "`expected_false` the false links the model expects among its own (the sum of 1 − match probability), known "
              "without labels.", "", markdown(robust), "",
              "## Person or company: end to end", "",
              "Populations with one name column for every kind (`design.generate.kind_problems`): real company names from the registry, "
              "held out of the name model's training and written as banks write them; companies with records under their representative's name, the representative a person of "
              "the file (half at that person's address and phone); sole traders named like a shop; company dates; and a flag good, "
              "medium or poor. Each resolved three ways: names routed by the truth (the flag replaced by it, taken as it is); by the "
              "flag alone; by the kind step (a written legal form, or a name the model is sure of, never a person's against a company flag; else "
              "the flag). `person_company_clusters` hold "
              "a true person and a true company; `sure_*` is the share of true companies called 2 and of true persons called 1; "
              "`wrong_*` the records called 2 that are persons and called 1 that are companies.", "", markdown(kind), "",
              f"## Cost: files of growing size (time grows like N^{curve.attrs['alpha']})", "",
              f"Each file is resolved by `python -m er build` in a process of its own, fitted on the file itself; DuckDB memory limit: "
              f"{limit}. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on {FINAL.fit_rows:,} "
              f"records) and the u sample of the file inside it ({FINAL.fs.model.u_max_pairs:,.0f} pairs) grow far slower than the file (the fit's sample is fixed; only u's exact counts read every record), so at "
              f"these sizes the total grows far slower than N. Above {len(PERSONS):,} entities personas repeat, so those rows measure "
              "cost only.", "", markdown(curve), ""]
    path = S.root / "reports" / "benchmark.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
