"""Write a synthetic population: config/generator.toml's spec, generated from the reference data, checked, then split
by entity into the datasets of config/settings.toml (silver records, and labels for evaluation), as Parquet.

    .venv/bin/python scripts/generate.py                                   # data/medallion/silver/<dataset>.parquet, data/labels/<dataset>.parquet
    .venv/bin/python scripts/generate.py --entities 20000 --seed 3 --out data/synthetic/s3   # another population, unsplit
"""
import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from er.generate import check, generate, load_reference, load_spec, split_by_entity
from er.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--entities", type=int, help="entities to generate (default: the spec's)")
    parser.add_argument("--seed", type=int, help="random seed (default: the spec's)")
    parser.add_argument("--out", type=Path, help="write one unsplit records.parquet and labels.parquet here instead")
    args = parser.parse_args()

    s = load_settings()
    spec, split = load_spec(s.root / "config" / "generator.toml")
    spec = replace(spec, **{k: v for k, v in (("entities", args.entities), ("seed", args.seed)) if v is not None})
    g = generate(spec, *load_reference(s.paths["reference"]))
    check(spec, g)
    entities = g.truth.groupby("ENTITY_ID").size()
    print(f"{len(g.df):,} records · {len(entities):,} entities · {(entities > 1).mean():.1%} duplicated · typos {g.typos}")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        g.df.to_parquet(args.out / "records.parquet", index=False)
        g.truth.to_parquet(args.out / "labels.parquet", index=False)
        print(f"wrote {args.out}/records.parquet and labels.parquet")
        return
    assert set(split.shares) == set(s.data.datasets), "config/generator.toml [split] must name config/settings.toml's datasets"
    of = split_by_entity(g.truth, split)
    s.data.silver_dir.mkdir(parents=True, exist_ok=True)
    s.data.labels_dir.mkdir(parents=True, exist_ok=True)
    for name in split.shares:
        g.df[of == name].to_parquet(s.data.silver_dir / f"{name}.parquet", index=False)
        g.truth[of == name].to_parquet(s.data.labels_dir / f"{name}.parquet", index=False)
    print(pd.DataFrame({"records": of.value_counts(), "entities": g.truth.groupby(of)["ENTITY_ID"].nunique()}).reindex(list(split.shares)))


if __name__ == "__main__":
    main()
