"""Choose the configuration on the labelled synthetic datasets, both stages in order, and write what was chosen.

    .venv/bin/python scripts/choose.py              # a development round: train and val only, test left unseen
    .venv/bin/python scripts/choose.py --test       # the round to commit: design analyses, A/B, threshold rule, decisions, checks, test once
    .venv/bin/python scripts/choose.py --optuna     # also run both Optuna searches (off by default; about 10 minutes)

Starts from config/pipeline.toml and config/experiments.py. Writes (a development round writes the first two to the
untracked data/artifacts/choose/ instead, so it changes no committed file):
- reports/choose.md: every table of the run (the docs cite it)
- config/final.toml: the chosen pipeline, in the pipeline.toml format, which nayose runs
- data/medallion/gold/<dataset>/: each dataset resolved by er.run, as nayose would, with train's fitted model
- data/artifacts: the leaderboard and the fitted models (data/artifacts/models/*_final.json)
Test is scored once per stage; the run stops if the leaderboard shows test scored with another configuration.
"""
import argparse
import time
from dataclasses import replace

from er.config import dump_pipeline, load_pipeline
from er.io import markdown
from er.run import Run
from er.select import FSChooser, RulesChooser
from er.settings import load_experiments, load_settings
from er.strings import connect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--optuna", action="store_true", help="also run both Optuna searches")
    parser.add_argument("--test", action="store_true", help="the round to commit: also scores test, once per stage, and writes "
                        "config/final.toml and reports/choose.md (without it: train and val only, into data/artifacts/choose/)")
    args = parser.parse_args()

    s = load_settings()
    if not args.test:  # every report and leaderboard row comes from train and val; test stays unseen for the round to commit
        s = replace(s, data=replace(s.data, datasets=tuple(d for d in s.data.datasets if d != "test")))
    report_file, final_file = ((s.root / "reports" / "choose.md", s.root / "config" / "final.toml") if args.test
                               else (s.paths["artifacts"] / "choose" / "choose.md", s.paths["artifacts"] / "choose" / "final.toml"))
    report_file.parent.mkdir(parents=True, exist_ok=True)
    p = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    x = load_experiments(s.root)
    _, db = connect()
    report = ["# Choosing the configuration", "",
              "Written by `scripts/choose.py` from `config/pipeline.toml` and `config/experiments.py`, on the labelled synthetic "
              "datasets. " + ("Test is scored once per stage, at the end of each." if args.test else
                                 "A development round: train and val only, test left unseen."), ""]

    def section(title: str, steps) -> None:
        report.extend([f"## {title}", ""])
        for step in steps:
            t = time.perf_counter()
            for heading, text, table in step():
                report.extend([f"### {heading}", ""] + ([text, ""] if text else []) + ([markdown(table), ""] if table is not None else []))
            report_file.write_text("\n".join(report), encoding="utf-8")  # after every step: a step that stops keeps the tables before it
            print(f"{title}: {step.__name__} ({time.perf_counter() - t:.1f}s)", flush=True)

    rules = RulesChooser(p.rules, p, s, db, x.rules_changes(p), x.RULES_DECISIONS,
                         replace(x.rules_tune(s.paths["optuna"]), enabled=args.optuna))
    section("Stage 1: rules", [rules.design, rules.ab, rules.decide, rules.cost, rules.evaluate, rules.output, rules.search])
    fs = FSChooser(p.fs, p, rules.final, s, db, x.fs_changes(p), x.FS_DECISIONS, replace(x.fs_tune(s.paths["optuna"]), enabled=args.optuna))
    section("Stage 2: Fellegi–Sunter", [fs.candidates_on_train, fs.training, fs.threshold, fs.ab, fs.decide, fs.will_it_scale,
                                         fs.evaluate, fs.why, fs.output, fs.search])

    header = ("# The chosen pipeline: config/pipeline.toml with config/experiments.py's adopted changes, written by "
              "scripts/choose.py.\n# Adopted: rules " + ", ".join(rules.adopted) + "; Fellegi–Sunter " + ", ".join(fs.adopted) +
              ".\n# nayose runs it. It can be edited by hand; scripts/choose.py overwrites it.")
    final = replace(p, rules=rules.final, fs=fs.final)
    dump_pipeline(final, s.chains, final_file, header)
    model = fs.fit(fs.final, fs.train_records, fs.train_truth, "train")
    for dataset in s.data.datasets:  # the gold layer, written by the code nayose runs
        Run(final, s, model=model).full(s.data.bronze_dir / f"{dataset}.parquet", s.data.gold_dir / dataset, overwrite=True)
    print(f"wrote {report_file}, {final_file} and {s.data.gold_dir}/<dataset>/")


if __name__ == "__main__":
    main()
