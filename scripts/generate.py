"""Write a synthetic population: config/generator.toml's spec, generated from the reference data, checked, then split
by entity into config/generator.toml [split]'s datasets (records as they arrive, in the bronze layer, and labels for
evaluation), as Parquet.

    .venv/bin/python scripts/generate.py                                   # data/medallion/bronze/<dataset>.parquet, data/labels/<dataset>.parquet
    .venv/bin/python scripts/generate.py --entities 20000 --seed 3 --out data/artifacts/s3  # another population, unsplit
"""
import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from design.generate import check, generate, load_reference, load_spec, profile, split_by_entity

ROOT = Path(__file__).resolve().parents[1]
BRONZE, LABELS = ROOT / "data" / "medallion" / "bronze", ROOT / "data" / "labels"  # records as they arrive; their entities


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--entities", type=int, help="entities to generate (default: the spec's)")
    parser.add_argument("--seed", type=int, help="random seed (default: the spec's)")
    parser.add_argument("--out", type=Path, help="write one unsplit records.parquet and labels.parquet here instead")
    args = parser.parse_args()

    spec, split = load_spec(ROOT / "config" / "generator.toml")
    spec = replace(spec, **{k: v for k, v in (("entities", args.entities), ("seed", args.seed)) if v is not None})
    g = generate(spec, *load_reference(ROOT / "data" / "reference"))
    check(spec, g)
    entities = g.truth.groupby("ENTITY_ID").size()
    print(f"{len(g.df):,} records · {len(entities):,} entities · {(entities > 1).mean():.1%} duplicated · typos {g.typos}")
    hard = profile(g)
    print(f"how hard: of {int(hard['true pairs']):,} true pairs, " +
          " · ".join(f"{k} {v:.1%}" for k, v in hard.drop("true pairs").items()))

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        g.df.to_parquet(args.out / "records.parquet", index=False)
        g.truth.to_parquet(args.out / "labels.parquet", index=False)
        print(f"wrote {args.out}/records.parquet and labels.parquet")
        return
    of = split_by_entity(g.truth, split)
    BRONZE.mkdir(parents=True, exist_ok=True)
    LABELS.mkdir(parents=True, exist_ok=True)
    for name in split.shares:
        g.df[of == name].to_parquet(BRONZE / f"{name}.parquet", index=False)
        g.truth[of == name].to_parquet(LABELS / f"{name}.parquet", index=False)
    print(pd.DataFrame({"records": of.value_counts(), "entities": g.truth.groupby(of)["ENTITY_ID"].nunique()}).reindex(list(split.shares)))


if __name__ == "__main__":
    main()
