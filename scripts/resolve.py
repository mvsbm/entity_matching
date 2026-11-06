"""Resolve a file of records, without labels: the chosen pipeline (config/final.toml by default), on DuckDB tables.

    .venv/bin/python scripts/resolve.py --input customers.parquet --check                                  # will it run?
    .venv/bin/python scripts/resolve.py --input customers.parquet --output data/medallion/gold/customers
    .venv/bin/python scripts/resolve.py --input 'data/in/*.parquet' --output data/medallion/gold/all     # a glob, or a folder
    .venv/bin/python scripts/resolve.py --input new.parquet --output data/medallion/gold/all --increment   # add new records
    .venv/bin/python scripts/resolve.py --input big.parquet --output data/medallion/gold/big --compute memory_limit=8GB threads=4
    .venv/bin/python scripts/resolve.py --input customers.parquet --output data/medallion/gold/customers --overwrite
    .venv/bin/python scripts/resolve.py --output data/medallion/gold/customers --decisions reviewed.parquet   # people's decisions
    .venv/bin/python scripts/resolve.py --input customers.parquet --output data/medallion/gold/customers --overwrite --kind-labels labelled.parquet

Input is Parquet, read through er.source: a file, a glob or a folder. Records that can't be resolved (no ID, one ID with
different content, or in an increment, already in the run) are set aside in set_aside/ and the run goes on.
A mistake people must fix stops the run with two lines, what is wrong and how to fix it, and exit code 2.

Fits λ and m by EM on a fixed-size sample of the file (config/pipeline.toml [model] fit_rows), or uses --model, a
fitted model (data/artifacts/models/probabilistic_final.json). Writes to --output: gold.parquet (each record's cluster,
the stage and rule that resolved it, and its kind and its customer's: company, person or unsure), matches/ (accepted
pairs, their weights and the generators that found them) and rule_kept/ as Parquet parts, steps.json (each step's
Big-O and time), qa.md (label-free checks), report.txt (the run on one page with no record's value in it, to send to
whoever helps you with it), review.parquet (pairs for people: "decide", every cluster pair whose best link scored in the threshold's safety margin or above it
with no name compared, and "audit",
a sample of accepted pairs just above it; both records' compared fields side by side, each field's level and bits,
and an empty decision column; it holds records, so keep it with the data), kind_review.parquet (a full run's
records for people to answer 1 person, 2 company or 0 can't tell: "decide", where the engine or the name disagrees with
the file's flag, and "measure", a draw that measures the flag and the engine; each row says why in words; it holds
names, so keep it with the data), and state/ for increments. --kind-labels gives an answered sheet to a run: its
answers join those the run in --output keeps, the newest per record standing, and a blank row erases nothing; they
stand for their records, train the engine, and the measuring draw places its lines (er.kind).
--decisions applies people's decisions (review.parquet with decision filled in as match or no_match, or any file with
the two ids and decision) to the run in --output, scoring nothing; they are kept in decisions/, and a full run on that
folder applies them again.
"""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from er.config import InputError, load_pipeline, sources_text
from er.io import markdown
from er.kind import kind_review_sheet
from er.run import Run, fill_rates, qa, report_text
from er.settings import load_settings


def step(x: dict) -> None:  # one line per step, as it finishes: what it did, and how long it took
    base = ("step", "big_o", "filled", "seconds", "peak_memory_gb")
    facts = " · ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in x.items() if k not in base and isinstance(v, int | float))
    print(f"  {x['step']:<11} {x['seconds']:>6.1f} s  {facts}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="examples:\n" + __doc__.split("\n\n")[1])
    parser.add_argument("--input", help="a Parquet file, a glob of them, or a folder holding them")
    parser.add_argument("--output", type=Path, help="the run folder")
    parser.add_argument("--check", action="store_true", help="read and map --input and check the budget, in seconds; resolve nothing")
    parser.add_argument("--pipeline", type=Path, help="default: config/final.toml")
    parser.add_argument("--model", type=Path, help="a fitted model (its 'model' key, or the Splink JSON itself)")
    parser.add_argument("--increment", action="store_true", help="add these records to the run in --output")
    parser.add_argument("--overwrite", action="store_true", help="replace the run already in --output (a full run refuses otherwise)")
    parser.add_argument("--decisions", type=Path, help="people's decisions to apply to the run in --output (without --input)")
    parser.add_argument("--kind-labels", type=Path, help="people's person/company answers: a filled-in kind_review.parquet, added to those the run keeps")
    parser.add_argument("--compute", nargs="*", default=[], metavar="KEY=VALUE",
                        help="override config/settings.toml [compute] for this run, e.g. memory_limit=8GB")
    args = parser.parse_args()
    if bool(args.input) == bool(args.decisions):
        parser.error("give either --input (a run or an increment) or --decisions (applied to the run in --output)")
    if not args.output and not args.check:
        parser.error("give --output, the run folder")

    s = load_settings()
    s = replace(s, compute={**s.compute, **dict(kv.split("=", 1) for kv in args.compute)})
    pipeline = args.pipeline or s.root / "config" / "final.toml"
    p = load_pipeline(pipeline, s.standardize, s.chains, s.columns)
    model = None
    if args.model:
        saved = json.loads(args.model.read_text(encoding="utf-8"))
        model = saved.get("model", saved)
    run = Run(p, s, model=model, echo=step, kind_labels=args.kind_labels)  # added to the answers the run in --output keeps
    fields = [f for f in s.columns if f not in ("id", "entity")]
    if args.check:
        run.load(args.input)
        plan = run.budget()
        present = run.present
        fill = fill_rates(run, fields).set_index("field")
        pct = lambda x: "  —" if pd.isna(x) else f"{x:>3.0%}"
        print(f"{run.n:,} records · filled · looks right, top value: on a sample of 10,000")
        for f in fields:
            x = fill.loc[f] if f in fill.index else None
            print(f"  {f:<13} " + (f"{x.filled:>5.0%} filled · looks right {pct(x.looks_right)} · top value {pct(x.top_value)}  ← {sources_text(present[f])}"
                                   if x is not None else "—  no column"))
        print("\n".join(f"  turned off: {x}" for x in run.disabled) or "  nothing turned off")
        m = p.fs.budget.min_oversized()
        shown = plan[(plan["oversized_blocks"] > 0) | plan["name"].isin(plan.nlargest(5, "per_record")["name"])]
        print(f"pairs per record, and blocks of {m}+ records (checked by sampling; a rule doesn't trust their values):")
        for x in shown.sort_values("per_record", ascending=False).itertuples():
            print(f"  {x.name:<34} {x.per_record:>6.2f} / record  largest block {x.largest_block:>6,}" +
                  (f"  {x.oversized_blocks:,} oversized ({x.oversized_records:,} records): checked by sampling" if x.oversized_blocks else ""))
        for x in run.notes:
            print(f"  {x}")
        print("ready: run it with --output <run folder>")
        return
    if args.decisions:
        run.decide(args.decisions, args.output)
        x = run.steps[-1]
        print(f"applied {x['decisions']:,} decisions ({x['matches']:,} match): {x['clusters_joined']:,} clusters joined; wrote {args.output}/gold.parquet")
        return
    if args.increment:
        run.increment(args.input, args.output)
        if run.added == 0:
            print(f"nothing new: every record of {args.input} is already in the run in {args.output}")
            return
    else:
        run.full(args.input, args.output, overwrite=args.overwrite)
    report = qa(run, fields, previous=args.output / "review.parquet" if args.increment else None)
    report.pop("review_sheet").to_parquet(args.output / "review.parquet")
    text = ["# Run checks", "", f"Input: `{args.input}` · {run.n:,} records", ""]
    for name, table in report.items():
        text += [f"## {name.replace('_', ' ')}", "", markdown(table.round(4)) if len(table) else "none", ""]
    (args.output / "qa.md").write_text("\n".join(text), encoding="utf-8")
    (args.output / "report.txt").write_text(report_text(run, report, pipeline), encoding="utf-8")
    if run.classifier is not None and not args.increment:  # records for people: to decide and to measure; none answered already
        cols = [c for c in ("kind_flag", "birth_date") if c in run._columns()]
        records = run.con.sql(f'SELECT "{run.uid}", kind_name AS name, {", ".join(cols)}{", " if cols else ""}'
                              "kind, kind_p, kind_by, name_p, kind_held FROM records").df()
        done = set(run.labels[run.uid].astype("string")) if run.labels is not None else set()  # answered: blank rows come back
        kind_review_sheet(records, run.uid, p.kind, s.flag_company, done).to_parquet(args.output / "kind_review.parquet")
    print("\n".join(f"{what:<12} {value}" for what, value in report["summary"].itertuples(index=False)))
    print(f"{sum(x['seconds'] for x in run.steps):.1f} s · wrote {args.output}: gold.parquet, review.parquet, qa.md (each step's cost), "
          "report.txt (no record's value in it: to share)" + (", kind_review.parquet (persons and companies to decide and to measure)" if run.classifier is not None and not args.increment else "")
          + ", matches/, state/")


if __name__ == "__main__":
    try:
        main()
    except (InputError, FileExistsError) as e:  # a mistake people fix: what is wrong, and how; anything else keeps its traceback
        print(f"error: {e}", file=sys.stderr)
        if getattr(e, "fix", ""):
            print(f"fix: {e.fix}", file=sys.stderr)
        sys.exit(2)
