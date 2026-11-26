"""Write the files a first test of nayose in the BigQuery console needs (docs/console.md), synthetic records only:

    .venv/bin/python scripts/console_files.py                                   # data/console/, for YOUR_PROJECT.nayose
    .venv/bin/python scripts/console_files.py OUT --dataset PROJECT.DATASET     # for your own names

- deploy.sql and name_weights.parquet: deploy/deploy.py --sql, with nayose/mapping.sql reading the table TABLE of the
  dataset (synthetic_records), not the table input;
- synthetic_first.parquet: a generated population's records, for a build, every column the mapping reads among them
  (a column the generator doesn't fill is empty), as text;
- synthetic_batch.parquet: the 5% held back from it, for an update.
With --sql-only, the two deploy files alone: what data/console/'s must equal (tests/test_deploy.py).
"""
import argparse
import hashlib
import importlib.util
import os
import re
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # this checkout's nayose and design

import nayose
from design.generate import generate, load_reference, load_spec

DATASET, TABLE = "YOUR_PROJECT.nayose", "synthetic_records"  # data/console/'s: docs/console.md replaces the dataset


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("out", nargs="?", type=Path, default=ROOT / "data" / "console")
    p.add_argument("--dataset", default=DATASET, help="PROJECT.DATASET nayose is installed in")
    p.add_argument("--table", default=TABLE, help="the table of the dataset the records are uploaded to")
    p.add_argument("--entities", type=int, default=10_000)
    p.add_argument("--sql-only", action="store_true", help="deploy.sql and name_weights.parquet alone")
    a = p.parse_args(argv)
    if os.environ.get("NAYOSE_CONFIG"):
        p.error("NAYOSE_CONFIG is set: these files hold nayose/config.toml's values; unset it")
    if a.out == ROOT / "data" / "console" and (a.dataset, a.table) != (DATASET, TABLE):
        p.error(f"give OUT for your own names: data/console holds {DATASET}'s files, which the repository keeps")
    read = (nayose.HERE / "mapping.sql").read_text(encoding="utf-8")
    mapping, n = re.subn(r"\bFROM\s+input\b", f"FROM `{a.dataset}.{a.table}`", read, flags=re.I)
    assert n and not re.search(r"\binput\b", re.sub(r"--[^\n]*", "", mapping)), "mapping.sql reads input otherwise"
    spec = importlib.util.spec_from_file_location("deploy", ROOT / "deploy" / "deploy.py")
    deploy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deploy)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "mapping.sql").write_text(mapping, encoding="utf-8", newline="\n")
        deploy.main([a.dataset, "--mapping", str(Path(tmp) / "mapping.sql"), "--sql", str(a.out)])
    if a.sql_only:
        return 0
    population = replace(load_spec(ROOT / "config" / "generator.toml")[0], entities=a.entities)
    records = generate(population, *load_reference(ROOT / "data" / "reference")).df
    records = records.reindex(columns=nayose.config()["input"]["columns"]).astype("string")
    later = records["CONT_ID"].map(lambda x: int(hashlib.md5(x.encode()).hexdigest(), 16) % 100 < 5)
    records[~later].to_parquet(a.out / "synthetic_first.parquet", index=False)
    records[later].to_parquet(a.out / "synthetic_batch.parquet", index=False)
    print(f"wrote {a.out}: deploy.sql, name_weights.parquet, synthetic_first.parquet ({(~later).sum():,} records), "
          f"synthetic_batch.parquet ({later.sum():,})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
