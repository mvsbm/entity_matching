[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Blocking costs are explained in [chapter 3](guide/03-far-too-many-pairs.md).*

# Performance

## End to end: the cost of every step

**Notation:**

| Symbol | Meaning |
|---|---|
| N | records in the scored file |
| n | records in the fitting set (train, about 30,000; fixed) |
| L | characters in a name or address (about 7 and 15) |
| P_r | pairs inside rule r's key blocks |
| P_g | pairs inside generator g's key blocks |
| C | candidate pairs, the union of all P_g |
| K | comparisons in the model (5) |
| E | accepted pairs |
| d | diameter of the largest cluster |
| S | sampled random pairs for u (10⁷) |
| F | folds (3) |
| D | decision variants (8) |
| T | Optuna trials |

"Grows like" is measured on generated files from 12,000 to 75,000 records, or from entity subsamples of train (`scale_check`).

**Every production run, per file** (`run_rules`, then `run_fs`). The times are measured on 999,481 records.

| # | Step | Code | Cost | Grows like | At 1M |
|---|---|---|---|---|---|
| 1 | load and standardize | `er.io.load`, `er.standardize.prepare` | O(N·L) | N | seconds |
| 2 | count each rule's work before joining | `er.pipeline.preflight` | O(N) per rule, a group-by | N | < 1 s |
| 3 | rules: one hash join per rule, fuzzy checks on the joined pairs only | `er.match.rule_edges` | O(N + P_r · L²) per rule | N^0.98 to N^1.04 per rule | ≤ 0.13 million pairs per rule |
| 4 | rules: clustering | `er.resolve` (connected components) | O((N + E)·d) | N | |
| | **rules, total** | | | | **17.5 s** |
| 5 | candidates: exact and compound keys | `er.candidates.generate` | O(N + P_g) per key | N^0.98 to N^1.58 | 0.1 to 4.0 million pairs per key |
| 6 | candidates: one-deletion keys | same | O(N·L + P_g) | N^1.01 to N^1.44 | ≤ 0.23 million |
| 7 | candidates: sorted neighbourhood (3 passes) | same | O(N log N + N·w) per pass | N | 3 million per pass, at most |
| 8 | merge the lists, drop pairs inside one rule cluster | `er.candidates.candidates` | O(Σ P_g), a vectorized group-by | N | |
| 9 | u, re-sampled on the scored file | `er.match.with_scored_u` | O(S·K) + O(N), a fingerprint | **constant** | about 8 s |
| 10 | score the candidates | `er.match.score_fs` (Splink, DuckDB) | O(C·K·L²) | as C | |
| 11 | accept at the threshold, then cluster | `er.pipeline.cascade` | O(C) + O((N + E)·d) | N | |
| | **probabilistic stage, total** | | | | **96.4 s** |

Once, before any file is scored, the model is **fitted on train**. That costs the same whatever the production size:

| Step | Cost | Measured |
|---|---|---|
| u by random sampling | O(S·K) | 8.9 s (nearly all of a fit) |
| λ from the near-certain rules | O(n + P_prior) | < 1 s |
| m by EM, on the phone and address blocks | O(iterations · P_em · K) | < 1 s |

**Choosing the configuration** happens in the notebooks only, on train and val:

| Step | Cost |
|---|---|
| threshold rule on out-of-fold scores | O(F · (fit + run on n/F records)) |
| decisions | O(D · (F + 1) · run) |
| A/B on val | O(variants · run) |
| Optuna (off by default) | O(T · F · run) |
| coverage check (`window_only`) | O(n + P + T_true · K), plus two u samples |
| evaluation | O(N + true pairs) |

**In total**, a production file costs O(N log N + C·K·L²), with C growing about linearly in N. On top of that come a fixed ~8 s for u and a fit of fixed size. Two places can still grow faster than the file: a key whose blocks keep growing with N, such as a household address or a common company name, and the sorted windows' N log N sort. Both are measured, and projected to `budget.target_rows`, by `scale_check` before every run.

## Measured in the final clean pass

On an awake machine:

| Step | Time | Note |
|---|---|---|
| one fit on train, nothing cached | 8.9 s | u-sampling of 10⁷ pairs is nearly all of it |
| one fit, all u cached | 0.4 s | m method / term-frequency variants, decisions, re-scoring |
| u on a scored file | ≈ 8 s, once per file and comparison | cached in `er.match.SCORED_U` |
| candidates on val | 0.1 s | 14 generators, 51,484 pairs |

**Where each notebook's time goes** (every code cell, in order):

| Notebook | Cells | Total | The largest cells |
|---|---|---|---|
| `dataset_generation` | 5 | 2.8 s | generate and check the population, 2.3 s |
| `deterministic_matching` | 11 | 26 s | decisions 16 s · A/B 4.4 s · output 2.2 s; Optuna and Pareto are off |
| `probabilistic_matching` | 14 | 220 s | decisions 97 s · A/B 34 s · threshold 33 s · output 20 s · "Will it scale?" 17 s · training 9 s · candidates on train 6 s; Optuna and Pareto are off |

u-sampling now runs once per scored file (each fold, val, train, test, and the coverage check's two samples), so it accounts for most of the decision, output and "Will it scale?" time. `scripts/export_pdfs.py` runs all three notebooks and prints them in 4.3 minutes. With Optuna it took 13; turning a study back on (`enabled=True`) adds about 1.5 minutes (deterministic) and at least 8.5 minutes (probabilistic).

**Free savings in the code** (identical results, covered by tests/):
- **u cached per comparison** (`FSModel.u_keys`). A comparison's u depends only on itself and the records it is sampled on, and Splink's random sample doesn't depend on which comparisons it scores. So any model that shares a comparison reuses its u, from the fit (`U` in the notebook) or from a scored file (`SCORED_U`).
- **Threshold rule without clustering** (`accept_curve`). The rule reads only accepted and false accepted pairs per weight, so decision variants resolve clusters at the chosen weight only.
- **Run cache.** Identical runs (same config, dataset and threshold) are computed once.
- **Merged lists by bitmask.** A pair's generators are one bit each, summed in C, then named once per combination. At 250,000 records the probabilistic stage takes 15 s instead of 59 s ([lessons.md](lessons.md#merging-the-candidate-lists-was-most-of-the-work)).

**Tried and rejected by the rule, because it changes results:** u from 10⁶ pairs instead of 10⁷ (the `u_from_1e6_pairs` decision) would make u-sampling about 6× cheaper. It loses true pairs, though: cross-validated train +10 / −24 (p = 0.024), val −3.

**At a million records** (`scripts/robustness.py --smoke`, one model fitted on train, ~6 minutes in all):

| Records | Rules | Probabilistic stage | Peak memory |
|---|---|---|---|
| 75,284 | 1.5 s | 12.0 s | 2.2 GB |
| 999,481 | 17.5 s | 96.4 s | 7.5 GB |

From 75,000 to a million records, 13 times the records take 8 times as long in the probabilistic stage, because the ~8 s u-sample is fixed. Why the steps grow linearly, and what had to change for that, is in [chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records).
