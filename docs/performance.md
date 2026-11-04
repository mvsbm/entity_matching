[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Blocking costs are explained in [chapter 3](guide/03-far-too-many-pairs.md).*

# Performance

Measured in the final clean pass, on an awake machine:

| Step | Time | Note |
|---|---|---|
| one fit on train, nothing cached | 8.1 s | u-sampling of 1e7 pairs is nearly all of it |
| one fit, only name + company u re-sampled | 5.0 s | an Optuna trial: it changes those comparisons' thresholds |
| one fit, all u cached | 0.4 s | m method / term-frequency variants, decisions, re-scoring |
| candidates on val | 0.56 s | person TF-IDF 0.33 s of it |
| Optuna, 30 trials | 518 s | ≈ 17 s per trial (was ≈ 27 s) |
| whole probabilistic notebook | ≈ 10.7 min | was ≈ 15 min; the deterministic one takes ≈ 1.3 min |

**Free savings in the code** (identical results, covered by tests/):
- **u cached per comparison** (`FSModel.u_keys`). A comparison's u depends only on itself and the fitting records, and Splink's random sample doesn't depend on which comparisons it scores. So any model that shares a comparison reuses its u.
- **Threshold rule without clustering** (`accept_curve`). The rule reads only accepted and false accepted pairs per weight, so trials and decision variants resolve clusters at the chosen weight only.
- **Run cache.** Identical runs (same config, dataset and threshold) are computed once.

**Tried and rejected by the rule, because it changes results:** u from 1e6 pairs instead of 1e7 (the `u_from_1e6_pairs` decision) would make u-sampling about 6× cheaper. It loses true pairs, though: cross-validated train +10 / −24 (p = 0.024), val −3.

**What still costs time:** every Optuna trial changes the name comparison's JW thresholds, so its u must be re-sampled per fold.
