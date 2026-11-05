[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · **6 Measuring**

# 6. Measuring honestly, choosing without overfitting

*Challenge C8.*

The headline result is: on test, **89.9% recall (88.6–91.1%) and 0 false merges, with a false-merge rate of at most 0.14%**. This chapter explains every part of that sentence, and why it is a fair number and not a lucky or tuned one.

## Challenge: what exactly do we count?

A system can be judged on its pairs or on its groups, and the two can disagree.

**Pair metrics** judge the decisions themselves. On validation, the second stage accepted 460 pairs, and all 460 were true.

**Group metrics** judge the final groups, after the pairs from both stages have been joined into entities. A pair counts as *found* if its two records end up in the same group, whether it was accepted directly or joined through other records.

- **Recall:** of all true pairs, the share that end up in one group. On validation, 2,034 of 2,227, so 91.3%.
- **False merges:** pairs of different entities that end up in one group. On validation, 0.
- **Over-merged groups:** groups that mix two or more real entities. On validation, 0.

**Why groups are the headline.** A customer experiences the groups, not the pairs. And one false pair can merge two whole groups, creating many false pairs at once.

**In short:** decide on pairs, report on groups.

## Challenge: "0 false merges" doesn't mean "never"

Seeing no false merge among a few thousand pairs doesn't prove the rate is zero. And a recall from 2,227 pairs carries chance variation. Every number needs a range.

**Solution: two intervals.**

**Recall uses the Wilson interval.** For k successes out of n, with z = 1.96 for 95%:

$$\frac{\hat p + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat p(1-\hat p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}, \qquad \hat p = \frac{k}{n}$$

On validation, with k = 2,034 and n = 2,227, this gives **90.1–92.4%**. Unlike the simpler normal approximation, it stays sensible near 0% and 100%.

**Zero events use the rule of three.** If nothing went wrong in n tries, the true rate is at most about 3/n, with 95% confidence. Precisely, it is the largest rate p at which seeing no errors still has a 5% chance:

$$(1 - p)^n = 0.05 \;\Rightarrow\; p = 1 - 0.05^{1/n} \approx \frac{3}{n}$$

On test the groups contain 2,126 predicted pairs and none is false, so the false-merge rate is **at most 0.14%**.

That's why the population is large, with 40,000 entities. A small test set could only promise "at most a few percent".

**In short:** every rate comes with its range, and "zero" comes with its upper bound.

## Challenge: is a change really better?

Allowing names within one edit lifts the rules' validation recall from 68.8% to 69.1%. The two intervals overlap almost completely, so comparing recalls says nothing.

**Solution: compare on the same pairs (a paired sign test).** Run both configurations on the same records and look only at the pairs where they disagree:

- **gains:** true pairs the new version finds and the old one doesn't
- **losses:** true pairs the old version finds and the new one doesn't

If the change made no difference, each disagreement would be a coin flip. The **sign test** asks how surprising the split is.

For example, the names-within-one-edit change gained 6 true pairs on validation and lost none. Under a fair coin, a 6–0 split has a probability of 2 × 0.5⁶ = **0.031**.

**Why:** pairs both versions agree on carry no information about the difference, and the paired test ignores them. That makes it far more sensitive than two overlapping intervals.

## Challenge: every choice can overfit

We make many choices: thresholds, comparators, candidate generators, model options. If we choose them by looking at a number, that number is no longer an honest estimate. The risk grows with every option tried.

**Solution: separate data, and a rule for every choice.**

**1. Three splits, by entity.** Train is for learning and choosing, validation is for confirming, and test is for reporting once. A person's records never cross splits ([chapter 1](01-entity-resolution-and-our-task.md#where-does-the-truth-come-from)).

**2. Cross-validation inside train.** The probabilistic model is *fitted* on train, so scoring it on train would flatter it. Train's entities are therefore split into three folds. Each fold is scored by a model fitted on the other two, so every score is **out-of-fold**. The rules stage fits nothing, so for it train itself is a fair selection set.

**3. The threshold rule.** On the out-of-fold scores, take the lowest weight that accepts no false pair, with a false-pair rate bound of at most 5%. Then go one step stricter, as a safety margin. For the configuration as written:

| Accept at or above | Pairs accepted (out-of-fold) | False pairs |
|---|---|---|
| 2 bits | 1,609 | 14 |
| 4 bits | 1,507 | 1 |
| **6 bits** | **1,392** | **0**: the lowest safe weight |
| 8 bits | 1,241 | 0: one step stricter, chosen |

Every configuration gets its threshold this way: the configuration as written, each variant, and each Optuna trial. The final configuration's rule gives 6 bits.

A check then confirms that the threshold transfers. Out-of-fold, 0 of 1,386 accepted pairs are false, a rate of at most 0.22%. On validation, 0 of 460 are.

**4. The decision rule (`adopt`).** A change is adopted only if it passes a rule, applied on top of the current choice:

- **"better"**: a significant paired gain on the selection set (p < 0.05), with no false pair added
- **"cheaper"**: no paired loss on the selection set
- **"safer"**: the same test as "cheaper", for a change that adds pairs because its gain shows only at scale
- **"chosen"**: the owner's call, for a gain that our 10,000-record sets are too small to show. Recall may move there, but no false pair may be added
- **both:** no paired loss on validation

| Change (second stage) | Out-of-fold gains / losses | Validation | Adopted |
|---|---|---|---|
| term-frequency adjustment off | +15 / −0 | +2 / −0 | yes |
| exact keys only (cheaper) | +0 / −3 | ±0 | no |
| Optuna's suggestion | +172 / −0 | +43 / −0 | yes |
| u from 1 million random pairs instead of 10 million (cheaper) | +9 / −26 | +0 / −1 | no |
| three compound phone keys instead of the phone (cheaper, for scale) | +0 / −0 | ±0 | yes |
| a reversed sorted pass instead of TF-IDF (cheaper, for scale) | +1 / −0 | ±0 | yes |
| five name keys, so no potential match depends on a sorted window (safer, for scale) | +1 / −0 | ±0 | yes |
| the address only with the phone, the name's first letter or the given name (cheaper, for scale) | +0 / −0 | ±0 | yes |
| no sorted windows (cheaper) | +0 / −3 | +0 / −1 | no |
| score every pair across two rule clusters | +12 / −0 | +4 / −0 | yes |
| u re-sampled on each scored file (chosen, for scale) | +63 / −0 | +20 / −0 | yes |
| u of the exact levels counted from value counts (chosen, for scale) | +0 / −122 | +0 / −27 | yes |

The "chosen" rows are the owner's calls, made in the open. u measured on each scored file gains on these sets too. Counting u exactly for the exact levels does not: it loses 122 true pairs out-of-fold and 27 on val, with no false pair added either way. A sample of 10 million pairs cannot see an agreement rarer than about one in a billion pairs, which an exact name or CIF ID becomes in big files, so the sample over-credits it there; the exact count is right at every size, and the owner chose that over the higher number on 10,000-record files.

**5. Optuna proposes; the rule decides.** Optuna is a search tool. It tries many combinations of options (30 seeded trials, scored out-of-fold) and keeps the best trade-offs between recall and false merges. A tie-break, `pick_within_noise`, prefers the cheapest point whose recall is within noise of the best. The suggestion then faces `adopt` like any other change. After one adoption, later searches found nothing that passed (most recently +0 / −12 out-of-fold), so the search has converged. Both studies are now **off by default** (`enabled=False` in `config/experiments.py`). `FINAL` keeps the suggestions that were adopted, because those are written as changes there. Turning the studies back on (`scripts/choose.py --optuna`) costs about 10 minutes, and is worth it after the data or the rules change.

**6. Test is scored once.** A leaderboard records every run. It counts the distinct configurations scored on test, and `scripts/choose.py` stops with an error above 1. The count is 1 for each stage.

**Why this solution:** a person choosing by eye always drifts toward the numbers they can see. Rules applied to data the final number never touches remove that drift.

**In short:** learn on train, confirm on validation, report on test once, and let rules make the choices.

## Challenge: does it hold beyond our one dataset?

Every number so far comes from one generated population: one seed, one noise model, one assumed prior. A result that holds only there would be fragile. So `scripts/benchmark.py` re-runs the final configuration, unchanged, on populations generated differently, the way a real file is run (`er.run`, without labels): it fits λ, u and m on each population's train split, then resolves that population's test split. Nothing is re-tuned ([reports/benchmark.md](../../reports/benchmark.md), measured before the standardization fixes in [lessons.md](../lessons.md#two-spellings-of-nothing)).

| Scenario | Rules alone | Both stages | 95% interval | False merges | False-merge rate ≤ |
|---|---|---|---|---|---|
| as reported (seed 0) | 71.1% | 89.9% | 88.6–91.1% | 0 | 0.14% |
| another seed (1) | 70.3% | 90.7% | 89.5–91.8% | 0 | 0.14% |
| another seed (2) | 66.9% | 88.8% | 87.4–90.0% | 0 | 0.15% |
| twice as many typos in names, phones and addresses | 67.4% | 88.8% | 87.4–90.0% | 0 | 0.15% |
| emptier fields (fill rates fall to 45%, not 65%) | 62.8% | 88.5% | 87.2–89.7% | 0 | 0.14% |
| prior: the near-certain rules find 25% of true pairs, not 50% (λ × 2) | 71.1% | 91.5% | 90.3–92.5% | 0 | 0.14% |
| prior: they find 75% (λ × ⅔) | 71.1% | 89.1% | 87.8–90.3% | 0 | 0.14% |

What the table shows:

- **The final result moves by about a point.** Across seeds and noise, recall stays between 88.5% and 90.7%, and no scenario has a false merge.
- **The rules are the sensitive part.** They need exact agreements, so emptier fields cost them 8 points (71.1% → 62.8%). The second stage recovers most of that, and the final result loses 1.4 points.
- **A prior off by a factor of two barely matters.** λ rests on an assumption: that the near-certain rules find half of all true pairs. If they found a quarter, or three quarters, every weight would shift by one bit, or by about half a bit. Recall moves by +1.6 or −0.8 points, with no false merge, because the threshold's safety step absorbs the shift.

How the cost and the quality behave as the file grows to a million records is in [chapter 3](03-far-too-many-pairs.md#scaling-to-a-million-records).

**In short:** the final configurations hold across seeds, more noise, emptier fields and a prior off by a factor of two.

## Challenge: the tools themselves can fool you

Even with careful splits, the pipeline once reported numbers that were wrong. We found each problem from a symptom on train or validation:

- **A stale cache.** It scored files with another file's name frequencies, so train and validation disagreed by 10 points.
- **Cloned personas.** Three "false merges" turned out to be one impossible twin made by the generator.
- **Two policies in conflict.** Optuna searched the threshold that the threshold rule also set, so the adopt-and-rerun loop never settled.
- **A wall-clock timeout.** The sleeping laptop made the search results depend on the machine.
- **A copy that outgrew the laptop.** At a million records, a full copy of the model's predictions needed more memory than the machine had.

Each now has a guard: a test or a check printed on every run. The full stories are in [lessons.md](../lessons.md).

**In short:** distrust a surprising number until its cause is found.

## In the code

- `er/evaluate.py`: `wilson`, `fp_upper` (the zero-event bound), `paired_test` (the sign test), `adopt`, `cluster_metrics`, `edge_metrics`
- `er/pipeline.py`: `entity_folds`, `cross_validate_fs`, `cv_threshold_curve`, `accept_curve`, `select_threshold`
- `er/config.py`: `ThresholdRule`
- `er/tune.py`: `pick_within_noise`, `new_study`
- `er/io.py`: `append_leaderboard`, `test_evaluations` and `assert_test_scored_once` (the test counter)
- `er/select.py`: `RulesChooser` and `FSChooser`, every step of the choice, run by `scripts/choose.py` ([reports/choose.md](../../reports/choose.md)); `config/experiments.py`: the changes and the order they are decided in
- `scripts/benchmark.py`: the scenarios above, and the cost run of [chapter 3](03-far-too-many-pairs.md#scaling-to-a-million-records)
- every table: [results.md](../results.md)

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 7 (evaluation of matching quality and complexity).
- E. B. Wilson, "Probable inference, the law of succession, and statistical inference," *Journal of the American Statistical Association* 22(158), 1927.
- C. J. Clopper and E. S. Pearson, "The use of confidence or fiducial limits illustrated in the case of the binomial," *Biometrika* 26(4), 1934.
- D. Menestrina, S. E. Whang and H. Garcia-Molina, "Evaluating entity resolution results," *PVLDB* 3(1), 2010. On group metrics such as B-cubed.

**Back to:** [README](../../README.md) · [1. The task](01-entity-resolution-and-our-task.md)
