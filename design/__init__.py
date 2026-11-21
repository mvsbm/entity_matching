"""Design time: what is chosen once, on labelled synthetic data, and committed through a pull request; never run by a
production job. It reads the engine (er) and writes config/final.toml and reports/.

generate     synthetic records from real names, companies and addresses, with the truth
experiments  the variants scripts/choose.py tries on config/pipeline.toml, and the order it decides them in
select       scripts/choose.py's two stages: the rules, then the Fellegi–Sunter model, each change judged in turn
pipeline     the design-time analyses those stages run: candidates against the truth, thresholds, what scales
evaluate     pair and cluster metrics, the paired test and the bounds the decisions rest on
tune         the comparator searches (Optuna)
sample       records drawn by hash and every pair they could make, scored as a run scores
probe, gap   the matches no key lists, counted without labels and measured against the truth (scripts/benchmark.py)
"""
