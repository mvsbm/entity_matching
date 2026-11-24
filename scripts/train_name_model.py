"""Train the person-or-company name model and write config/kind_names.npz, which every run reads (nayose's records.sql).

    .venv/bin/python scripts/train_name_model.py      # a few seconds

Public data only: data/reference/'s personas and registry companies, written the ways config/generator.toml says bank
records write them (design.generate.train_name_model). Run it, and commit the file, after changing data/reference/,
config/generator.toml's kana_confusions or branches, nayose/config.toml's legal forms, kana folding or [records] ngram,
or the training code.
"""
import argparse
import os
from pathlib import Path

import numpy as np

from design.generate import train_name_model

ROOT = Path(__file__).resolve().parents[1]
NAME_MODEL = ROOT / "config" / "kind_names.npz"


def main() -> None:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                            epilog=__doc__.split("\n\n", 1)[1]).parse_args()
    m = train_name_model(ROOT / "data" / "reference", ROOT / "config" / "generator.toml")
    tmp = NAME_MODEL.with_name(f"kind_names.{os.getpid()}.tmp.npz")  # complete before it replaces the old file: a run may be reading it
    np.savez_compressed(tmp, terms=np.array(m["terms"]), coef=m["coef"], intercept=m["intercept"], ngram=m["ngram"])
    os.replace(tmp, NAME_MODEL)
    print(f"wrote {NAME_MODEL.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
