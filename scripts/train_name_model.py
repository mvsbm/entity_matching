"""Train the person-or-company name model and write config/kind_names.npz, which every run loads (er.kind.name_model).

    .venv/bin/python scripts/train_name_model.py      # a few seconds

Public data only: data/reference/'s personas and registry companies, written the ways config/generator.toml says bank
records write them (er.generate.train_name_model). Run it, and commit the file, after changing data/reference/,
config/generator.toml's kana_confusions or branches, the legal forms or kana folding in config/settings.toml, [kind]
ngram, or the training code: a test fails until the file is what training builds, and a run refuses a file trained
under other settings.
"""
import argparse

from er.config import load_pipeline
from er.generate import train_name_model
from er.kind import NAME_MODEL, name_key
from er.settings import load_settings


def main() -> None:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                            epilog=__doc__.split("\n\n", 1)[1]).parse_args()
    s = load_settings()
    spec = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns).kind
    train_name_model(s, spec).save(s.root / NAME_MODEL, name_key(s, spec))
    print(f"wrote {NAME_MODEL}")


if __name__ == "__main__":
    main()
