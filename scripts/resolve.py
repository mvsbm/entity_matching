"""Resolve a file of records, without labels: the chosen pipeline (config/final.toml by default), on DuckDB tables.

    .venv/bin/python scripts/resolve.py --input customers.csv --output data/medallion/gold/customers
    .venv/bin/python scripts/resolve.py --input 'data/in/*.parquet' --output data/medallion/gold/all --pipeline config/final.toml
    .venv/bin/python scripts/resolve.py --input new.csv --output data/medallion/gold/all --increment      # add new records
    .venv/bin/python scripts/resolve.py --input big.parquet --output data/medallion/gold/big --compute memory_limit=8GB threads=4
    .venv/bin/python scripts/resolve.py --input customers.csv --output data/medallion/gold/customers --overwrite   # replace that run

Fits λ and m by EM on a fixed-size sample of the file (config/pipeline.toml [model] fit_rows), or uses --model, a
fitted model (data/artifacts/models/probabilistic_final.json). Writes to --output: gold.parquet (each record's cluster,
and the stage and rule that resolved it), matches/ (accepted pairs, their weights and the generators that found them)
and rule_kept/ as Parquet parts, steps.json (each step's Big-O and time), qa.md (label-free checks), review.parquet
(about 50 pairs around the threshold for people to check: both records' compared fields side by side, and each
field's level and bits; it holds records, so keep it with the data), and state/ for increments.
"""
import argparse
import json
from dataclasses import replace
from pathlib import Path

from er.config import load_pipeline
from er.io import markdown
from er.run import Run, qa
from er.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", required=True, help="a CSV or Parquet file, or a glob of them")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pipeline", type=Path, help="default: config/final.toml")
    parser.add_argument("--model", type=Path, help="a fitted model (its 'model' key, or the Splink JSON itself)")
    parser.add_argument("--increment", action="store_true", help="add these records to the run in --output")
    parser.add_argument("--overwrite", action="store_true", help="replace the run already in --output (a full run refuses otherwise)")
    parser.add_argument("--compute", nargs="*", default=[], metavar="KEY=VALUE",
                        help="override config/settings.toml [compute] for this run, e.g. memory_limit=8GB")
    args = parser.parse_args()

    s = load_settings()
    s = replace(s, compute={**s.compute, **dict(kv.split("=", 1) for kv in args.compute)})
    p = load_pipeline(args.pipeline or s.root / "config" / "final.toml", s.standardize, s.chains, s.columns)
    model = None
    if args.model:
        saved = json.loads(args.model.read_text(encoding="utf-8"))
        model = saved.get("model", saved)
    run = Run(p, s, model=model)
    if args.increment:
        run.increment(args.input, args.output)
    else:
        run.full(args.input, args.output, overwrite=args.overwrite)
    report = qa(run, [f for f in s.columns if f not in ("id", "entity")])
    report.pop("review_sample").to_parquet(args.output / "review.parquet")
    text = ["# Run report", "", f"Input: `{args.input}` · {run.n:,} records", ""]
    for name, table in report.items():
        text += [f"## {name.replace('_', ' ')}", "", markdown(table.round(4)) if len(table) else "none", ""]
    (args.output / "qa.md").write_text("\n".join(text), encoding="utf-8")
    print("\n".join(f"{x['step']:<11} {x['filled']:<60} {x['seconds']:>8.2f}s" for x in run.steps))
    print(f"wrote {args.output}: gold.parquet, matches/, rule_kept/, qa.md, review.parquet, state/")


if __name__ == "__main__":
    main()
