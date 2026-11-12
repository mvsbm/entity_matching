[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · **6 Measuring** · [7 Kinds](07-person-or-company.md)

# 6. Measuring honestly, choosing without overfitting

*Challenge C8.*

The headline result is: on test, **48.2% recall (46.2–50.2%) and 0 false merges, with a false-merge rate of at most 0.26%**. This chapter explains every part of that sentence, and why it is a fair number and not a lucky or tuned one.

## Challenge: what exactly do we count?

A system can be judged on its pairs or on its groups, and the two can disagree.

**Pair metrics** judge the decisions themselves. On validation, the second stage accepts 918 pairs, and none is false; 32 of them join two people of one household, counted apart (below).

**Group metrics** judge the final groups, after the pairs from both stages have been joined into entities. A pair counts as *found* if its two records end up in the same group, whether it is accepted directly or joined through other records.

- **Recall:** of all true pairs, the share that end up in one group. On validation, 1,244 of 2,494, so 49.9%.
- **False merges:** pairs of different entities that end up in one group. On validation, 0.
- **Over-merged groups:** groups that mix two or more real entities. On validation, 33, each of them people of one household, since no pair in them is false.

**Why groups are the headline.** A customer experiences the groups, not the pairs. And one false pair can merge two whole groups, creating many false pairs at once.

**In short:** decide on pairs, report on groups.

## Challenge: "0 false merges" doesn't mean "never"

Seeing no false merge among a few thousand pairs doesn't prove the rate is zero. And a recall from 2,494 pairs carries chance variation. Every number needs a range.

**Solution: two intervals.**

**Recall uses the Wilson interval.** For k successes out of n, with z = 1.96 for 95%:

$$\frac{\hat p + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat p(1-\hat p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}, \qquad \hat p = \frac{k}{n}$$

On validation, with k = 1,244 and n = 2,494, this gives **47.9–51.8%**. Unlike the simpler normal approximation, it stays sensible near 0% and 100%.

**Zero events use the rule of three.** If nothing went wrong in n tries, the true rate is at most about 3/n, with 95% confidence. Precisely, it is the largest rate p at which seeing no errors still has a 5% chance:

$$(1 - p)^n = 0.05 \;\Rightarrow\; p = 1 - 0.05^{1/n} \approx \frac{3}{n}$$

On test the groups contain 1,134 true pairs and 45 of one household, and none is false, so the false-merge rate is **at most 0.26%**.

That's why the population is large, with 40,000 entities. A small test set could only promise "at most a few percent".

**In short:** every rate comes with its range, and "zero" comes with its upper bound.

## Challenge: is a change really better?

Allowing names within one edit lifts the rules' validation recall from 11.1% to 11.3%. The two intervals overlap almost completely, so comparing recalls says nothing.

**Solution: compare on the same pairs (a paired sign test).** Run both configurations on the same records and look only at the pairs where they disagree:

- **gains:** true pairs the new version finds and the old one doesn't
- **losses:** true pairs the old version finds and the new one doesn't

If the change made no difference, each disagreement would be a coin flip. The **sign test** asks how surprising the split is.

For a split of k gains and no losses, that probability is 2 × 0.5ᵏ. The CIF ID one-digit-off level gained 7 true pairs out-of-fold and lost none: 2 × 0.5⁷ = **0.0156**. The names-within-one-edit change gained 18 on train and lost 6: p = **0.0227**, a significant gain. On validation it gained 5 and lost 1 (p = 0.22): too few disagreements to tell, which is why choices are made on the larger selection set.

**Why:** pairs both versions agree on carry no information about the difference, and the paired test ignores them. That makes it far more sensitive than two overlapping intervals.

## Challenge: every choice can overfit

We make many choices: thresholds, comparators, candidate generators, model options. If we choose them by looking at a number, that number is no longer an honest estimate. The risk grows with every option tried.

**Solution: separate data, and a rule for every choice.**

**1. Three splits, by entity.** Train is for learning and choosing, validation is for confirming, and test is for reporting once. A person's records never cross splits, nor a household's ([chapter 1](01-entity-resolution-and-our-task.md#where-does-the-truth-come-from)).

**2. Cross-validation inside train.** The probabilistic model is *fitted* on train, so scoring it on train would flatter it. Train's entities are therefore split into three folds. Each fold is scored by a model fitted on the other two, so every score is **out-of-fold**. The rules stage fits nothing, so for it train itself is a fair selection set.

**3. The threshold rule.** On the out-of-fold scores, take the lowest weight that accepts no false pair, with a false-pair rate bound of at most 5%. Then go one step stricter, as a safety margin. A pair of two people of one household is not a false pair here: the family name, the address and the phone are both theirs, so it can score as high as a duplicate, and people decide it, labelled maybe one household ([usage](../usage.md#maybe-one-household)). It is counted apart, in every table's `household` column. For the configuration as written:

| Accept at or above | Pairs accepted (out-of-fold) | False pairs |
|---|---|---|
| 4 bits | 2,970 | 1 |
| 6 bits | 2,753 | 1 |
| **8 bits** | **2,402** | **0**: the lowest safe weight |
| 10 bits | 2,086 | 0: one step stricter, chosen |

Every configuration gets its threshold this way: the configuration as written, each variant, and each Optuna trial. The final configuration's rule gives 6 bits.

A check then confirms that the threshold transfers. Out-of-fold, 0 of 2,569 accepted pairs are false, a rate of at most 0.12%. On validation, 0 of 918 are.

**4. The decision rule (`adopt`).** A change is adopted only if it passes a rule, applied on top of the current choice:

- **"better"**: a significant paired gain on the selection set (more gains than losses, p < 0.05), with no false pair added
- **"cheaper"**: no paired loss on the selection set, and no false pair added
- **"safer"**: the same test as "cheaper", for a change that adds pairs because its gain shows only at scale
- **"chosen"**: the owner's call, for a gain that our 10,000-record sets are too small to show. Recall may move there, but no false pair may be added
- **then, on validation:** "better", "cheaper" and "safer" may not lose more true pairs than they gain; and no kind may add more false pairs than it removes

| Change (second stage) | Out-of-fold gains / losses | Validation | Adopted |
|---|---|---|---|
| term-frequency adjustment off (better) | +33 / −0 | +13 / −0 | yes |
| exact keys only (cheaper) | +0 / −7 | +0 / −2 | no |
| Optuna's suggestion, with its own generators (better) | +79 / −14 | +25 / −4 | yes |
| u for the scores from 1 million random pairs instead of 10 million (cheaper) | +93 / −67 | +61 / −0 | no |
| three compound phone keys instead of the phone (cheaper, for scale) | +0 / −0 | ±0 | yes |
| a reversed sorted pass instead of TF-IDF (cheaper, for scale) | +1 / −0 | ±0 | yes |
| five name keys, so no potential match depends on a sorted window (safer, for scale) | +0 / −0 | ±0 | yes |
| the address only with the phone, the name's first letter or the given name (cheaper, for scale) | +0 / −0 | ±0 | yes |
| no sorted windows (cheaper) | +0 / −0 | ±0 | yes |
| score every pair across two rule clusters (better) | +8 / −0 | ±0 | yes |
| u measured on each scored file (chosen, for scale) | +0 / −700 | +0 / −92 | yes |
| u of the exact levels counted from value counts (chosen, for scale) | +437 / −170 | +0 / −335 | yes |
| a CIF ID one digit off, as a level (better) | +7 / −0 | +4 / −0 | yes |
| its one-deletion key (safer) | +0 / −0 | ±0 | yes |
| the same town, city or prefecture, as address levels (better) | +159 / −344 | +181 / −3 | no |
| the birth date, as a comparison (better) | +49 / −0 | +27 / −0 | yes |
| a birth-date key (safer) | +8 / −0 | +4 / −0 | yes |
| a given name + phone key (safer) | +0 / −0 | ±0 | yes |
| a birth-date one-deletion key, within the prefecture (safer) | +0 / −0 | ±0 | yes |
| a one-edit level counted exactly through one-deletion keys (chosen, for scale) | +0 / −0 | ±0 | yes |
| the fit's own u from 1 million pairs; the scores keep 10 million (cheaper) | +0 / −0 | ±0 | yes |
| the company comparison without its "very close" level (cheaper) | +0 / −0 | ±0 | yes |
| a name must be compared for an automatic merge (chosen, for scale) | +682 / −5 | +494 / −2 | yes |
| a key on the name's reading, its long vowels written one way (safer) | +0 / −0 | ±0 | yes |
| three keys on the name's last three sounds, with the phone, the postal code or the postal area (safer) | +1 / −0 | ±0 | yes |
| the same reading, as a name level (better) | +67 / −0 | +37 / −0 | yes |
| the same last three sounds, as a name level (better) | +15 / −8 | +10 / −6 | no |
| the given name compared on its own (better) | +117 / −897 | +0 / −352 | no |
| the same, or the name's last three sounds where a record has no given name (better) | +0 / −422 | +0 / −154 | no |

Each row is decided on top of the rows above it that were adopted. Optuna's suggestion brings its own list of generators, in place of the list as written.

The "chosen" rows are the owner's calls, made in the open, and on these sets they move recall both ways:
- **u measured on each scored file** loses 700 true pairs out-of-fold and 92 on val. The folds and val hold about 10,000 records, fewer than train, and on a smaller file strangers agree more often. The change removes credit that u from the larger fitting set over-gives there. On a bigger file it adds the credit that train's u withholds, and real files are usually bigger than train.
- **u counted from value counts** gains out-of-fold, +437 / −170, and loses 335 true pairs on val. A sample of 10 million pairs cannot see an agreement rarer than about one in a billion pairs, which an exact name or CIF ID becomes in big files; the exact count is right at every size.
- **A one-edit level counted exactly** moves no true pair here. It is chosen for the same reason: the count is right at every size, where a sample sees almost no CIF ID typo pairs.
- **A name must be compared** sends a pair with no name compared to the review sheet instead of merging it. A household shares an address and a phone, which alone can reach the line. On these sets it gains: +682 / −5 out-of-fold, +494 / −2 on val.

No "chosen" row adds a false pair.

**5. Optuna proposes; the rule decides.** Optuna is a search tool. It tries many combinations of options (60 seeded trials for the rules, scored on train, which a rule doesn't fit to; 30 for the model, scored out-of-fold) and keeps the best trade-offs between recall and false merges. A tie-break, `pick_within_noise`, prefers the cheapest point whose recall is within noise of the best. The suggestion then faces `adopt` like any other change. Both studies are **off by default** (`enabled=False` in `config/experiments.py`). The chosen pipeline keeps the suggestions that passed, because those are written there as changes (`optuna_comparators` for the rules, `optuna_suggestion` for the model). `scripts/choose.py --optuna` searches again, which is worth it after the data or the rules change.

**6. Test is scored once.** A leaderboard records every run. It counts the distinct configurations scored on this population's test, and `scripts/choose.py` stops with an error above 1. The count is 1 for each stage. A newly generated population has a test nobody has seen, so its count starts again. `scripts/choose.py` runs a development round on train and val only, writing to the untracked `data/artifacts/choose/`; `--test` is the round to commit, which scores test and writes `config/final.toml` and `reports/choose.md`.

**Why this solution:** a person choosing by eye always drifts toward the numbers they can see. Rules applied to data the final number never touches remove that drift.

**In short:** learn on train, confirm on validation, report on test once, and let rules make the choices.

## Challenge: does it hold beyond our one dataset?

Every number so far comes from one generated population: one seed, one noise model, one prior. A result that holds only there would be fragile. So `scripts/benchmark.py` re-runs the final configuration, unchanged, on populations generated differently, the way a real file is run (`er.run`, without labels): it fits λ and m on each population's train split, then resolves that population's test split, measuring u on it as a run does. Nothing is re-tuned ([reports/benchmark.md](../../reports/benchmark.md)).

| Scenario | Rules alone | Both stages | 95% interval | False merges | False-merge rate ≤ |
|---|---|---|---|---|---|
| as reported (seed 0) | 9.7% | 45.9% | 43.9–47.9% | 0 | 0.28% |
| another seed (1) | 11.1% | 46.3% | 44.3–48.4% | 0 | 0.29% |
| another seed (2) | 12.1% | 49.3% | 47.2–51.4% | 0 | 0.27% |
| twice as many typos in names, phones and addresses | 8.1% | 33.4% | 31.4–35.4% | 0 | 0.41% |
| emptier fields (fill rates fall to 45%, not 65%) | 7.3% | 41.7% | 39.7–43.7% | 0 | 0.31% |
| prior: the near-certain rules find half the share measured on train (λ × 2) | 9.7% | 49.1% | 47.1–51.1% | 0 | 0.26% |
| prior: they find 1.5 times that share (λ × ⅔) | 9.7% | 45.1% | 43.1–47.1% | 0 | 0.28% |

What the table shows:

- **No scenario has a false merge.** Across the three seeds, recall stays between 45.9% and 49.3%.
- **Typos are the sensitive part.** Twice as many typos cost the final result 12.5 points (45.9% → 33.4%): a typo turns an exact agreement into a close one, worth fewer bits, and pushes more pairs below the line. Emptier fields cost 4.2 points (to 41.7%), and the rules 2.4 (9.7% → 7.3%).
- **A prior off by a factor of two moves recall by a few points, not the false merges.** λ rests on a share measured on train's labels: the true pairs the near-certain rules find (2.3%). A real file has no labels to measure it. If the share were half as large, or 1.5 times as large, every weight would shift by one bit, or by about half a bit. Recall moves from 45.9% to 49.1% or to 45.1%, with no false merge, because the threshold's safety step absorbs the shift.

The cost files of [chapter 3](03-far-too-many-pairs.md#scaling-to-a-million-records), each fitted on itself, are not all clean: the model merges 2 false pairs at 12,532 records, through 1 false link, and 4 at 74,959, through 3, against 0 at 24,955 and 50,116 ([reports/benchmark.md](../../reports/benchmark.md)). Each false link is of 8.2–10.1 bits, against the 8-bit line: near-namesakes, a kana typo apart, sharing an address or a phone. The model expects them: by its own probabilities, 0.84 and 4.38 of its links on those two files are false. Test, scored once, has none, and on every scenario's test split the model expects under one (0.41–0.72). How the cost and the quality behave as the file grows to a million records is in chapter 3.

**In short:** the final configuration holds across seeds, emptier fields and a prior off by a factor of two; more typos cost recall, not false merges. A few near-namesakes do slip through on some larger files, about as many as the model expects.

## Challenge: the tools themselves can fool you

Careful splits are not enough. The pipeline's own tools can produce numbers that look right and are wrong:

- **A cache keyed too loosely** scores a file with another file's name frequencies. `score_fs` clears Splink's cache, and the frequencies are stored with the model.
- **Weights fitted at one size** are wrong at another. λ is rescaled, and u measured, on every scored file.
- **The generator can make impossible twins,** two entities no matcher could tell apart. Each persona is drawn at most once.
- **Two policies on one setting** never settle: if Optuna searched the threshold the threshold rule also sets, the adopt-and-rerun loop would go round for ever. The rule alone sets it.
- **A wall-clock bound** makes a search depend on the machine. Studies are bounded by their number of trials only.
- **A copy that outgrows memory** stops a big run. Every table that grows with the file stays in DuckDB, which spills to disk.

Each has a guard and a check: a test, or a number printed on every run. The full list is in [lessons.md](../lessons.md).

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

**Next:** [7. Person or company →](07-person-or-company.md) · **Back to:** [README](../../README.md) · [1. The task](01-entity-resolution-and-our-task.md)
