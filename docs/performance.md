[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Blocking costs are explained in [chapter 3](guide/03-far-too-many-pairs.md).*

# Performance

Measured in the final clean pass, on an awake machine:

| Step | Time | Note |
|---|---|---|
| one fit on train, nothing cached | 8.9 s | u-sampling of 1e7 pairs is nearly all of it |
| one fit, only name + company u re-sampled | 5.0 s | an Optuna trial: it changes those comparisons' thresholds |
| one fit, all u cached | 0.4 s | m method / term-frequency variants, decisions, re-scoring |
| candidates on val | 0.5 s | 14 generators, 51,484 pairs |
| "Will it scale?" check | 0.5 s | projections looked up from the Candidates cell, plus `window_only`; Optuna trials only look them up |
| Optuna, 30 trials | 518 s | ≈ 17 s per trial |

**Where each notebook's time goes** (every code cell, in order; the cells are described in the notebooks' introductions):

| Notebook | Cells | Total | The largest cells |
|---|---|---|---|
| `dataset_generation` | 5 | 2.8 s | generate and check the population, 2.2 s |
| `deterministic_matching` | 11 | 123 s | Optuna 91 s · decisions 16 s · Pareto 6 s · A/B 4.5 s; the other seven 5 s together |
| `probabilistic_matching` | 14 | 660 s | Optuna 518 s · decisions 61 s · threshold 32 s · A/B 25 s · training 9 s · candidates on train 6 s; the other eight 9 s together |

Optuna takes about three quarters of the matching notebooks' time (608 of 782 s). Everything else runs in about 3 minutes. `scripts/export_pdfs.py` runs all three and prints them in 13 minutes.

**Free savings in the code** (identical results, covered by tests/):
- **u cached per comparison** (`FSModel.u_keys`). A comparison's u depends only on itself and the fitting records, and Splink's random sample doesn't depend on which comparisons it scores. So any model that shares a comparison reuses its u.
- **Threshold rule without clustering** (`accept_curve`). The rule reads only accepted and false accepted pairs per weight, so trials and decision variants resolve clusters at the chosen weight only.
- **Run cache.** Identical runs (same config, dataset and threshold) are computed once.

**Tried and rejected by the rule, because it changes results:** u from 1e6 pairs instead of 1e7 (the `u_from_1e6_pairs` decision) would make u-sampling about 6× cheaper. It loses true pairs, though: cross-validated train +10 / −24 (p = 0.024), val −3.

**At a million records** (`scripts/robustness.py --smoke`, one model fitted on train):

| Records | Rules | Probabilistic stage | Peak memory |
|---|---|---|---|
| 75,284 | 1.5 s | 4.0 s | 2.3 GB |
| 999,481 | 19.2 s | 98.4 s | 6.9 GB |

Time grows like N^1.06 from 12,000 to a million records. Merging the generators' lists once took most of the probabilistic stage: a `"+".join` per pair, in Python. Now a pair's generators are one bit each, summed in C. At 250,000 records the stage takes 15 s instead of 59 s, with identical results ([lessons.md](lessons.md#merging-the-candidate-lists-was-most-of-the-work)). Why the steps grow linearly, and what had to change for that, is in [chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records).

**What still costs time:** every Optuna trial changes the name comparison's JW thresholds, so its u must be re-sampled per fold.
