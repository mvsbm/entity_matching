"""Benchmark the method (nayose/sql/, nayose/config.toml) as it runs on real files: nayose's build, without labels, on
DuckDB. Writes reports/benchmark.md. Nothing is re-tuned.

    .venv/bin/python scripts/benchmark.py                 # scenarios and the cost curve up to 60,000 entities
    .venv/bin/python scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB   # reports/benchmark.md: up to a million records, in 8 GB

The report starts with the command that wrote it.

Quality: each scenario generates a population with design.generate (config/generator.toml, varied), fits λ and m on
its train split without labels, resolves its test split with u measured on it, and compares the entities at the
method's design threshold (accepted) with the truth.
Person or company: populations with every kind problem on (design.generate.kind_problems) and one name column, resolved
with names routed by the truth, by the file's flag alone, and by the kind step.
Cost: populations of growing size, each resolved by `python -m nayose build` in a process of its own, so the peak memory
is that run's alone. Past the memory limit (--memory-limit) DuckDB spills to disk.
"""
import argparse
import contextlib
import json
import os
import resource
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

import nayose
from design.evaluate import cluster_metrics, false_pairs, labelled, pair_metrics
from design.generate import KindProblems, generate, kind_problems, load_reference, load_registry, load_spec, split_by_entity
from nayose import entities
from nayose.engines import DuckDB

ROOT = Path(__file__).resolve().parents[1]
REFERENCE, OUT = ROOT / "data" / "reference", ROOT / "data" / "artifacts" / "benchmark"
UID, DATA = "CONT_ID", SimpleNamespace(unique_id="CONT_ID", entity_id="ENTITY_ID", household_id="HOUSEHOLD_ID")
LINE = float(nayose.config()["lookup"]["likely_from"])  # the method's design threshold, in points
SPEC, SPLIT = load_spec(ROOT / "config" / "generator.toml")
PERSONS, COMPANIES, TOWNS = load_reference(REFERENCE)


def population(spec) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Records, and each record's labels (its entity and household). Past len(PERSONS) entities personas repeat: clones
    no matcher can tell apart."""
    persons = PERSONS if spec.entities <= len(PERSONS) else pd.concat([PERSONS] * (spec.entities // len(PERSONS) + 1), ignore_index=True)
    g = generate(spec, persons, COMPANIES, TOWNS)
    return g.df, g.truth.set_index(UID)


@contextlib.contextmanager
def variant(**changed):  # config.toml with these values changed (records' trust_flag, fit's prior_recall, input's columns), for the runs inside
    text = (nayose.HERE / "config.toml").read_text(encoding="utf-8")
    for key, value in changed.items():
        lines = text.splitlines()
        at = next(i for i, x in enumerate(lines) if x.split("=")[0].strip() == key)
        lines[at] = f"{key} = {json.dumps(value)}"
        if key == "columns":  # a list over several lines: the rest of it goes
            while not lines[at + 1].lstrip().startswith(("#", "[")) and "=" not in lines[at + 1]:
                del lines[at + 1]
        text = "\n".join(lines) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "config.toml").write_text(text, encoding="utf-8")
        before = os.environ.get("NAYOSE_CONFIG")
        os.environ["NAYOSE_CONFIG"] = str(Path(tmp) / "config.toml")
        try:
            yield
        finally:
            os.environ.pop("NAYOSE_CONFIG") if before is None else os.environ.__setitem__("NAYOSE_CONFIG", before)


def accepted(engine: DuckDB) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """The method at its design threshold, as a match run there would offer it and people take it whole: every rule
    pair, and the model's pairs there or above with a name compared (named), from the run's scored; the records'
    entities by transitive closure (nayose.entities). Each record's entity, the rules' alone, and the model's pairs taken."""
    scored = engine.frame("SELECT * FROM scored")
    model = scored[scored["generators"].notna() & scored["named"] & (scored["points"] >= LINE)]
    rules = scored.loc[scored["rule"].notna(), ["id_l", "id_r"]]
    ids = engine.frame("SELECT id FROM records ORDER BY id")["id"]

    def closure(edges: pd.DataFrame) -> pd.Series:  # each record's entity, these pairs taken
        joined = {x["id"]: x["entity"] for x in json.loads(entities.of(json.dumps({"pairs": [dict(l=a, r=b) for a, b in edges.itertuples(index=False)]})))}
        return pd.Series([joined.get(x, x) for x in ids], index=ids.to_numpy())
    return closure(pd.concat([rules, model[["id_l", "id_r"]]], ignore_index=True)), closure(rules), model


def links(model: pd.DataFrame) -> dict:
    """The model's links taken, and the false ones the model expects among them (the sum of 1 − match probability)."""
    return dict(model_links=len(model), expected_false=round(float((1 - model["match_probability"]).sum()), 2))


def quality(engine: DuckDB, truth: pd.DataFrame) -> dict:
    """A run's entities at the design threshold (accepted) against the truth: after the rules, and at the end; and its
    model links that are false. Pairs of two people of one household are counted apart (household_merges)."""
    gold, rules, model = accepted(engine)
    entity, household = labelled(truth.reset_index(), DATA)
    e, h = entity.reindex(gold.index), household.reindex(gold.index) if household is not None else None
    m = cluster_metrics(gold, e, h)
    return dict(rules_recall=round(pair_metrics(rules, e, h)["recall"], 4), recall=round(m["recall"], 4),
                interval=f"{m['recall_lo']:.3f}–{m['recall_hi']:.3f}", false_merges=int(m["FP"]), fp_rate_at_most=f"{m['fp_rate_hi']:.2%}",
                household_merges=int(m["household"]), **links(model),
                false_links=int(false_pairs(model["id_l"], model["id_r"], entity, household).sum()))


def scenarios() -> pd.DataFrame:
    base, measured = SPEC, float(nayose.config()["fit"]["prior_recall"])
    variants = {"as reported (seed 0)": (base, {}), "seed 1": (replace(base, seed=1), {}), "seed 2": (replace(base, seed=2), {}),
                "typos doubled": (replace(base, name_typo_rate=2 * base.name_typo_rate, phone_typo_rate=2 * base.phone_typo_rate,
                                          address_typo_rate=2 * base.address_typo_rate), {}),
                "fields emptier (last column 45% filled)": (replace(base, rate_end=0.45), {}),
                "prior_recall halved (λ ×2)": (base, {"prior_recall": 0.5 * measured}),  # λ changes by 2×, so every weight by about ±1 bit
                "prior_recall ×1.5 (λ ×⅔)": (base, {"prior_recall": 1.5 * measured})}
    rows, made = [], {}
    for name, (spec, changed) in variants.items():
        if repr(spec) not in made:
            records, truth = population(spec)
            which = split_by_entity(truth.reset_index(), SPLIT).to_numpy()
            d = OUT / f"population_{len(made)}"
            d.mkdir(parents=True, exist_ok=True)
            for part in ("train", "test"):
                records[which == part].to_parquet(d / f"{part}.parquet", index=False)
            made[repr(spec)] = d, truth
        d, truth = made[repr(spec)]
        with variant(**changed):
            train, test = DuckDB(), DuckDB()
            nayose.build(train, [d / "train.parquet"])  # the model fitted on train, as a run fits it
            nayose.build(test, [d / "test.parquet"], model=train.value("SELECT fitted FROM fit"))
            rows.append(dict(scenario=name, **quality(test, truth)))
            train.close()
            test.close()
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


FLAGS = {"good (1% wrong at random, 20% on representatives)": KindProblems(flag_wrong=0.01, flag_wrong_representative=0.2, sole_flagged_company=0.1),
         "medium (3%, 50%)": KindProblems(),
         "poor (10%, 80%)": KindProblems(flag_wrong=0.10, flag_wrong_representative=0.8, sole_flagged_company=0.5)}


def kinds(entities: int) -> pd.DataFrame:
    """Person or company, end to end: populations with one name column for every kind, representative-named companies,
    sole traders, company dates and a flag good, medium or poor, each resolved three ways. The truth routes each name
    (the flag replaced by the truth, taken as it is: the bound); the flag alone (taken as it is); the kind step
    (records.sql: a written legal form, or a name the model is sure of; else the flag). A person–company cluster holds
    a true person and a true company."""
    r, reg = nayose.config()["records"], load_registry(REFERENCE)
    columns = [*nayose.config()["input"]["columns"], "NAME_KANA"]
    os.environ["NAYOSE_MAPPING"] = str(ROOT / "design" / "shared_name_mapping.sql")
    rows = []
    try:
        for i, (name, problems) in enumerate(FLAGS.items()):
            g = kind_problems(generate(replace(SPEC, entities=entities), PERSONS, COMPANIES, TOWNS), problems, reg,
                              r["legal_front"], r["legal_end"], SPEC.kana_confusions, SPEC.branches)
            d = OUT / f"kinds_{i}"
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True)
            g.df.to_parquet(d / "records.parquet", index=False)
            g.df.assign(PERSON_ORG_CODE=np.where(g.truth["KIND"].eq("company"), "2", "1")).to_parquet(d / "truth_flag.parquet", index=False)
            truth = g.truth.set_index(UID)
            for how, trust, records in (("the truth", True, "truth_flag.parquet"), ("the flag alone", True, "records.parquet"),
                                        ("the kind step", False, "records.parquet")):
                with variant(trust_flag=trust, shared_name_column=True, columns=columns):
                    engine, t = DuckDB(), time.perf_counter()
                    nayose.build(engine, [d / records])
                    seconds = round(time.perf_counter() - t, 1)
                    gold = engine.frame("SELECT id, kind FROM gold").set_index("id").assign(cluster_id=accepted(engine)[0]).join(
                        truth[["ENTITY_ID", "KIND", "HOUSEHOLD_ID"]])
                    engine.close()
                m = cluster_metrics(gold["cluster_id"], gold["ENTITY_ID"], gold["HOUSEHOLD_ID"])
                mixed = gold.assign(c=gold["KIND"].eq("company")).groupby("cluster_id")["c"].agg(["any", "all"])
                company, person = gold["KIND"].eq("company"), gold["KIND"].eq("person")
                rows.append(dict(flag=name, routed_by=how, recall=round(m["recall"], 4), false_merges=int(m["FP"]),
                                 person_company_clusters=int((mixed["any"] & ~mixed["all"]).sum()),
                                 sure_companies=f"{(gold['kind'].eq(2) & company).sum() / company.sum():.1%}", wrong_companies=int((gold["kind"].eq(2) & person).sum()),
                                 sure_persons=f"{(gold['kind'].eq(1) & person).sum() / person.sum():.1%}", wrong_persons=int((gold["kind"].eq(1) & company).sum()),
                                 seconds=seconds))
                print(rows[-1], flush=True)
    finally:
        os.environ.pop("NAYOSE_MAPPING", None)
    return pd.DataFrame(rows)


def cost(entities: list[int], memory_limit: str) -> pd.DataFrame:
    """Each population written to Parquet and resolved by `python -m nayose build`, fitted on the file itself, as a real
    run, in a process of its own: its peak memory is the process's."""
    rows = []
    for n in entities:
        records, truth = population(replace(SPEC, entities=n))
        d = OUT / f"cost_{n}"
        d.mkdir(parents=True, exist_ok=True)
        records.to_parquet(d / "records.parquet", index=False)
        size = len(records)
        del records
        shutil.rmtree(d / "run", ignore_errors=True)  # a fresh folder: the run measured whole
        compute = [*([f"memory_limit={memory_limit}"] if memory_limit else []), f"temp_directory={OUT / 'spill'}"]
        done = subprocess.run([sys.executable, "-m", "nayose", "build", str(d / "records.parquet"), "--out", str(d / "run"), "--compute", *compute],
                              cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace")
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)  # the largest run's yet: they grow
        if done.returncode:
            print(f"{size:,} records: failed\n{done.stderr[-2000:]}", flush=True)
            rows.append(dict(records=size, seconds="failed: " + done.stdout.strip().splitlines()[-1][:120]))
            continue
        said = json.loads(done.stdout.strip().splitlines()[-1])
        engine = DuckDB(d / "run" / "run.duckdb")
        row = dict(records=size, seconds=said["seconds"], peak_memory_gb=round(peak, 2), **{f"{k} s": v for k, v in said["steps"].items()},
                   recall="—", false_merges="—", fp_rate_at_most="—", **links(accepted(engine)[2]), false_links="—")
        if n <= len(PERSONS):
            q = quality(engine, truth)
            row |= {k: q[k] for k in ("recall", "false_merges", "fp_rate_at_most", "false_links")}
        engine.close()
        rows.append(row)
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    ok = pd.to_numeric(out["seconds"], errors="coerce").notna()
    out.attrs["alpha"] = round(float(np.polyfit(np.log(out.loc[ok, "records"]), np.log(out.loc[ok, "seconds"].astype(float)), 1)[0]), 2) if ok.sum() > 1 else None
    return out


def markdown(df: pd.DataFrame) -> str:  # a table as GitHub writes one
    rows = [list(map(str, df.columns)), ["---"] * len(df.columns), *([str(v) for v in r] for r in df.itertuples(index=False))]
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--entities", type=int, nargs="+", default=[10_000, 20_000, 40_000, 60_000], help="population sizes of the cost curve")
    parser.add_argument("--memory-limit", default="", help="DuckDB's, e.g. 8GB (default: DuckDB's own, 80%% of RAM)")
    args = parser.parse_args()
    robust, kind, curve = scenarios(), kinds(20_000), cost(args.entities, args.memory_limit)
    limit, c = args.memory_limit or "DuckDB's default (80% of RAM)", nayose.config()
    report = ["# Benchmark", "",
              f"Written by `{shlex.join(['scripts/benchmark.py', *sys.argv[1:]])}`: the method (`nayose/sql/`, `nayose/config.toml`) through nayose's build, the run "
              "without labels on DuckDB, on generated populations. Nothing is re-tuned. A run merges nothing by itself; each is "
              f"measured at the method's design threshold ({LINE:g} points), as people would take a match run there "
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
              f"Each file is resolved by `python -m nayose build` in a process of its own, fitted on the file itself; DuckDB memory limit: "
              f"{limit}. Peak memory is the process's, Python included. Each stage's seconds: its own column. `fit` (on {int(c['fit']['fit_records']):,} "
              f"records) and the u sample of the file inside it ({float(c['fit']['u_max_pairs']):,.0f} pairs) grow far slower than the file (the fit's sample is fixed; only u's exact counts read every record), so at "
              f"these sizes the total grows far slower than N. Above {len(PERSONS):,} entities personas repeat, so those rows measure "
              "cost only.", "", markdown(curve), ""]
    path = ROOT / "reports" / "benchmark.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
