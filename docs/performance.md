[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Blocking costs are explained in [chapter 3](guide/03-far-too-many-pairs.md).*

# Performance

Measured in the final clean pass, on an awake machine:

| Step | Time | Note |
|---|---|---|
| one fit on train, nothing cached | 8.5 s | u-sampling of 1e7 pairs is nearly all of it |
| one fit, only name + company u re-sampled | 5.0 s | an Optuna trial: it changes those comparisons' thresholds |
| one fit, all u cached | 0.4 s | m method / term-frequency variants, decisions, re-scoring |
| candidates on val | 0.3 s | nine generators; was 0.56 s with TF-IDF, 0.33 s of it TF-IDF alone |
| "Will it scale?" check | 0.3 s | runs in every Optuna trial; was 52.5 s ([lessons.md](lessons.md#a-check-slower-than-the-trial-it-guarded)) |
| Optuna, 30 trials | 506 s | ≈ 17 s per trial |
| whole probabilistic notebook | ≈ 10.7 min | the deterministic one takes ≈ 2 min, 1.5 of them Optuna |

**Free savings in the code** (identical results, covered by tests/):
- **u cached per comparison** (`FSModel.u_keys`). A comparison's u depends only on itself and the fitting records, and Splink's random sample doesn't depend on which comparisons it scores. So any model that shares a comparison reuses its u.
- **Threshold rule without clustering** (`accept_curve`). The rule reads only accepted and false accepted pairs per weight, so trials and decision variants resolve clusters at the chosen weight only.
- **Run cache.** Identical runs (same config, dataset and threshold) are computed once.

**Tried and rejected by the rule, because it changes results:** u from 1e6 pairs instead of 1e7 (the `u_from_1e6_pairs` decision) would make u-sampling about 6× cheaper. It loses true pairs, though: cross-validated train +10 / −24 (p = 0.024), val −3.

**At a million records** (`scripts/robustness.py --smoke`, one model fitted on train):

| Records | Rules | Probabilistic stage | Peak memory |
|---|---|---|---|
| 75,284 | 1.5 s | 7.4 s | 2.1 GB |
| 999,481 | 18.2 s | 127.0 s | 6.0 GB |

Time grows like N^1.01 from 12,000 to a million records. In the probabilistic stage at 250,000 records, the candidates take 17 s. Two thirds of that is spent outside the generators, mostly in the union of their nine lists (a `"+".join` per pair, in Python). That is linear, so it was left as it is. Why the steps grow linearly, and what had to change for that, is in [chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records).

**What still costs time:** every Optuna trial changes the name comparison's JW thresholds, so its u must be re-sampled per fold.
