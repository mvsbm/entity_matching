[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · **5 Evidence** · [6 Measuring](06-measuring-and-choosing.md) · [7 Kinds](07-person-or-company.md)

# 5. Uncertain evidence: the Fellegi–Sunter model

*Challenges C4 (look-alikes), C5 (partial evidence), C6 (empty fields) and C7 (pairs vs groups).*

## Challenge: how sure can we be about a pair?

The rules in [chapter 4](04-certain-cases-first-rules.md) leave most true pairs undecided. Here is one of them, from val ([`reports/choose.md`](../../reports/choose.md), "An accepted true match with a typo"):

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| A | ミッマテルヤ | 20-2 | 3077 | 9991758286659 |
| B | ミッマドウミョオ | 愛知県20-2 | 3077 | 2286801775966 |

The surnames agree, but the given names don't: テルヤ and ドウミョオ, which is evidence against. A's address holds only the street number, but the two records share the address, which is strong evidence. The phone digits agree, which is strong evidence too. The CIF ID differs, which is weak evidence against. We need a way to **add up evidence of different strengths**, for and against, into one score we can act on.

## Solution: evidence in bits

The Fellegi–Sunter model asks two questions about every field.

- **m:** if the two records *are* the same entity, how often does this field look like this?
- **u:** if they are *different* entities, how often does it look like this by chance?

The ratio m / u says how much more likely the observation is under "same" than under "different". Here are the values learned for the phone, on train ([`reports/choose.md`](../../reports/choose.md), "Training on train"):

| Phone observation | m: same entity | u: different entities | Evidence |
|---|---|---|---|
| exactly equal | 0.261 | about 1 in 9,600 | +11.3 bits |
| one digit off | 0.062 | about 1 in 280 | +4.1 bits |
| different | 0.677 | 0.996 | −0.6 bits |

The report rounds u to three decimals; the "1 in" values follow from m and the weight. Both can be checked by counting:
- **Exactly equal:** two strangers share a random last four digits about 1 time in 10,000.
- **One digit off:** each number has 36 neighbours that differ in exactly one digit, and 36 in 10,000 is about 1 in 278.
- **m is not 1:** a true pair has a *different* phone two times in three, because people change phones and own several.

**From ratios to bits.** For a pair whose fields land in observations γ₁, γ₂, …, Bayes' rule in odds form says:

$$\underbrace{\frac{P(\text{same} \mid \gamma)}{P(\text{different} \mid \gamma)}}_{\text{odds after looking}} \;=\; \underbrace{\frac{\lambda}{1-\lambda}}_{\text{odds before looking}} \;\times\; \prod_{k} \frac{m_k(\gamma_k)}{u_k(\gamma_k)}$$

Here λ is the chance that two random records are the same entity. Taking log₂ of both sides turns the product into a sum, which gives the **match weight**:

$$w \;=\; \log_2\frac{\lambda}{1-\lambda} \;+\; \sum_k \log_2\frac{m_k}{u_k}$$

Each term is a number of **bits**, and each bit doubles the odds. So +10 bits multiply the odds by about 1,000.

**The example pair, field by field,** scored on val, with u measured on val's own records:

| Evidence | Observation | Bits |
|---|---|---|
| before looking | two random records match about 1 in 23,000 | −14.49 |
| name | different | −3.19 |
| company | missing (a person has no company name) | 0.00 |
| address | the same address | +12.77 |
| phone | exactly equal | +11.14 |
| CIF ID | different | −0.03 |
| birth date | missing | 0.00 |
| **total** | | **+6.19** |

The total is the report's, from unrounded parts. Back from bits to a probability:

$$p = \frac{2^{w}}{1 + 2^{w}} = \frac{2^{6.19}}{1 + 2^{6.19}} = 98.6\%$$

That clears the 6-bit line (below) by 0.19 bits, so the model accepts the pair. A different CIF ID costs almost nothing: true pairs have different CIF IDs 98.5% of the time (m = 0.985), nearly as often as strangers.

### Why this solution

- **It adds up partial evidence.** A strong agreement can outweigh a weak disagreement, which is exactly what the rules couldn't do.
- **Every decision is explainable.** The table above *is* the explanation. Any accepted pair can be printed this way.
- **It learns without labels,** as the next sections show.
- **It is proven.** Fellegi and Sunter proved the rule optimal when the fields are independent: for a given error rate, no other rule decides more pairs. The model has run in official statistics for decades.

### What it costs: the independence assumption

The sum assumes the fields are **independent**, given whether the pair matches. Some of ours are not. The address code, the address text and the postal code describe one fact: where the record lives. Counting them as three fields would count one agreement three times.

So correlated fields form **one comparison** with ordered levels. The first level that holds wins. The levels and thresholds shown are the final ones (`config/final.toml`):

| Comparison | Levels, strongest first |
|---|---|
| name | exact · exact after folding · same reading · very close (Jaro–Winkler ≥ 0.95 after folding) · same given name · close (≥ 0.75) · else |
| company | exact (legal form removed, kana folded) · close (Jaro–Winkler ≥ 0.8) · else |
| address | same address code or address · address within 2 edits · same postal code · else |
| phone | exact · one digit off · else |
| CIF ID | exact · one edit off (a digit wrong, added or dropped, or two neighbours swapped) · else |
| birth date | exact · one edit off (a digit wrong, added or dropped, or two neighbours swapped) · else |

The "same reading" level catches a long vowel written another way (サトウ and サトオ). The "same given name" level catches a surname change after marriage.

**In short:** every field adds evidence in bits; correlated fields share one comparison.

## Challenge: learning m, u and λ without labels

In a real file, nobody tells us which pairs match. Each parameter must come from the records themselves.

**u, from counts and from random pairs.** Almost every random pair of records is two different entities, so u is how often random pairs land at each level. Where it can, u is counted exactly:
- **The leading exact levels** of each comparison (an exact name, the same address, the same CIF ID): from how often each value occurs.
- **A one-edit level right after them on the same column** (the CIF ID, phone or birth date one digit off): through one-deletion keys, since two values one edit apart always share a key. The CIF ID, phone and birth date comparisons then need no sample at all.

The other levels (a close name, a nearby address) come from 10 million random pairs, every one of them scored. Counting matters because a sample of 10 million pairs cannot see an agreement rarer than about one in a billion pairs, which an exact name or CIF ID becomes in a big file.

**u is measured on every file we score.** Some fields have more distinct values in a bigger file: there are more addresses and more CIF IDs. Two random records then agree on them less often, so u is smaller. A u measured on train would under-credit those agreements on a bigger file, and over-credit them on a smaller one. Measuring u on the whole file being scored keeps each weight right at any size. The scores and the check on oversized key blocks ([chapter 3](03-far-too-many-pairs.md)) use the same u. It needs no labels, and costs about the same at any size: the fit, with this measurement inside it, takes 7.4 seconds at 12,532 records and 9.3 at a million ([`reports/benchmark.md`](../../reports/benchmark.md)).

**λ, from near-certain rules.** Pairs that agree on CIF ID and name, on CIF ID and company name, or on name, address code and phone are almost surely matches. Counting them, and dividing by the share of true pairs these rules find, gives λ. That share is measured on train's labels by `scripts/choose.py`: 2.2%, kept in `config/final.toml` for files without labels. The chance two random records match depends on the file's size, so λ is rescaled for each file. On val, a file of 10,496 records, it is about 1 in 23,000 pairs (−14.5 bits).

**m, by expectation–maximization (EM).** Take the pairs that share a phone number. They are a mix of true pairs and strangers, in unknown proportions. EM alternates two steps until the numbers settle:

1. **Guess the matches:** with the current m, u and λ, compute each pair's probability of being a match.
2. **Update m:** recount each level, weighting every pair by that probability.

It runs once on pairs that share a phone and once on pairs that share an address. Each run learns the m values of the *other* fields. A run fits λ and m on a fixed sample of 30,000 records, made of whole postal areas, so the cost doesn't grow with the file. That fit draws its own u sample of 1 million pairs, which feeds only EM; the scores use the u measured on the whole file.

**Does EM get it right?** Our synthetic data has labels, so we can check. Trained on the same records, EM and the labels learn close weights. This is the configuration as written, where "very close" starts at 0.92:

| Level | EM | From labels |
|---|---|---|
| name exact | +15.55 | +15.79 |
| name very close | +11.50 | +11.48 |
| same address | +13.35 | +13.65 |
| phone exact | +11.30 | +11.64 |
| CIF ID different | −0.02 | −0.03 |
| company different | −2.71 | −1.51 |
| name different | −2.67 | −4.39 |

The largest gap, about 1.7 bits, is a different name.

**What can go wrong.** A level may never occur in the sample, if its threshold is too strict, or if a lower level can never be reached because the level above it always catches the pair first. Splink then quietly uses default values, which can create strong evidence out of nothing. We use cautious bounds instead. A level no random pair reaches gets u at its 95% upper bound, and a level never seen in training counts 0 bits ([lessons](../lessons.md)). The company comparison has no "very close" level for that reason: no pair reaches it, in the sample or in EM, so it would add 0 bits for a second string comparison on every pair.

EM can go wrong the other way too. A level its learning pairs never reach gets an m of almost 0, and so a huge negative weight: a phone one digit off would count as near-proof of two different people, where a typo is the likelier story. So no level weighs less than its comparison's "else" level. And "one digit off" stands for a typo in a value that matches share; where matches never shared the exact value in training (an ID unique to each record), being one digit off just means neighbouring IDs, so it counts 0 bits.

**In short:** counts and random pairs give u, near-certain rules give λ, and EM gives m, with no labels needed.

## Challenge: empty fields

The company comparison above is *missing*: a person has no company name. Some columns are empty for 35% of records, and the birth date is filled for only 15%.

**Solution: an empty field adds 0 bits.** If either record lacks the field, the comparison is skipped.

**Why:** absence is evidence of neither match nor non-match. Treating it as a disagreement would punish records just for being sparse.

## Challenge: some agreements are rarer than others

Sharing the name サトウ says less than sharing a rare name. That was Newcombe's 1959 insight. A **term-frequency adjustment** gives an exact match more bits when the value is rare.

It is tested like any other change, and cross-validated train decides. Switching it off finds 33 more true pairs out-of-fold and loses none (13 more on val), so it is off.

The adjustment carries a subtle trap. Frequencies must come from the training records and stay fixed when scoring, or a score would depend on which file is being scored. Splink caches them on the database connection by column name, so `score_fs` clears that cache and uses the frequencies stored with the model ([lessons](../lessons.md)).

## Challenge: where to draw the line?

A score is not yet a decision. We accept a pair at **6 bits or more**, a probability of about 98.5%. On validation, the line trades recall against false merges like this:

| Accept at or above | Pairs accepted | False pairs among them | Recall after grouping |
|---|---|---|---|
| 0 bits | 1,263 | 8 | 59.7% |
| 2 bits | 1,195 | 5 | 58.2% |
| 4 bits | 973 | 0 | 52.0% |
| **6 bits** | **918** | **0** | **49.9%** |
| 8 bits | 877 | 0 | 48.6% |
| 10 bits | 416 | 0 | 28.8% |

The line is not picked from this table, which would tune it on validation. It comes from a rule applied to train ([chapter 6](06-measuring-and-choosing.md)): the lowest weight with no false pair in cross-validation, plus one safety step.

**The safety step goes to people.** The pairs between the lowest clean weight and the line, from 4 to 6 bits, are never wrong on cross-validated train, but are held back in case of noise. Every run lists them in `review.parquet` for people to decide ([usage](../usage.md#6--review-and-decide)). On val, the 4-bit row above accepts 55 more pairs, none of them false, and takes recall from 49.9% to 52.0%. The automatic line stays where the rule put it.

**A name must be compared.** A household shares an address and a phone, and those two alone can reach the line. So a pair is merged automatically only if a person name or a company name is filled on both sides. Without one, the pair goes on the review sheet (`why` = decide), whatever its score.

**The closest non-match**, the rejected pair of different people with the highest score on val:

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| C | ャマノベタカユキ | 北海道岩見沢市日の出台10-26-24 | 2604 | 8852433827058 |
| D | イナモチタカユキ | 大阪府泉北郡忠岡町 | 2604 | 7587446239261 |

Same phone digits (+11.14). The surnames differ, but the given names agree (タカユキ), worth +7.62. Different addresses (−0.58), and a different CIF ID (−0.03): **+3.66 bits, rejected**, below even the review band. Our example pair's names counted as different, but it shared the address as well as the phone; that is what lifted it to 6.19.

## Challenge: from pairs to groups

Accepted pairs must become groups. If A–B and B–C are accepted, then A, B and C are one entity.

**Solution: connected components.** Records are points, accepted pairs are lines, and every connected set of points is one entity. The pairs from the rules and from this stage are grouped together.

**Why, and the risk.** It is the natural reading of "same as", and it lets a record join a group that the rules already started. The risk is a **chain**: one false pair can join two whole groups. The strict 6-bit line is what keeps chains safe.

A cautious alternative would refuse a merge when the two groups hold different given names, but a typo in a given name looks like a conflict, so it loses true pairs. A run groups by connected components only (`er.cluster.merge`), and design time measures the run itself, so the choice is measured the way it runs.

## On our data

| Split | Recall: rules → + this stage | 95% interval | False merges | False-merge rate at most |
|---|---|---|---|---|
| train | 10.5% → 47.7% | 46.5–48.8% | 0 | 0.09% |
| val | 11.9% → 49.9% | 47.9–51.8% | 0 | 0.24% |
| **test** | 9.6% → **48.2%** | 46.2–50.2% | **0** | 0.26% |

Pairs of two people of one household are counted apart, neither true nor false: 112 on train, 51 on val and 45 on test ([chapter 6](06-measuring-and-choosing.md#challenge-every-choice-can-overfit)).

**In short:** weighing evidence lifts recall from about 10% to about 48%, with no false merge on any split. Most of the rest share too little to clear 6 bits ([data](../data.md#how-hard-it-is)).

## In the code

- `er/match.py`:
  - `train_fs`: learns λ, u and m
  - `exact_u`, `scored_u`: u counted exactly where it can be, the rest sampled, on the scored file
  - `score_fs`: scores candidate pairs
  - `waterfall`: the field-by-field table
  - `scaled_prior`: rescales λ to the scored file's size
- `er/cluster.py`: `merge`, the run's clustering
- `config/pipeline.toml` `[model]`: the comparisons and levels; `er/select.py`: `FSChooser.training` (EM against labels), `why`, `threshold`, run by `scripts/choose.py`
- `er/run.py`: `Run.fit` (the fit, then u on the whole file) and `Run.score`, the same model without labels on any file; `er/match.py`: `named_sql`, the name check; `notebooks/demo.ipynb`, sections 5 and 8–11, draws each step
- every table: [results.md](../results.md)

## Further reading

- R. Linacre, "[An interactive introduction to record linkage](https://robinl.github.io/intro_to_probabilistic_linkage/)." The best intuition for this chapter, from Splink's author.
- I. P. Fellegi and A. B. Sunter, "A theory for record linkage," *Journal of the American Statistical Association* 64(328), 1969.
- W. E. Winkler, "Using the EM algorithm for weight computation in the Fellegi–Sunter model of record linkage," *Proceedings of the Section on Survey Research Methods*, American Statistical Association, 1988.
- Splink documentation: the [waterfall chart](https://moj-analytical-services.github.io/splink/charts/waterfall_chart.html), [match weights](https://moj-analytical-services.github.io/splink/charts/match_weights_chart.html), [term frequency](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html).
- P. Christen, *Data Matching*, Springer, 2012: chapter 6 (classification).

**Next:** [6. Measuring honestly, choosing without overfitting →](06-measuring-and-choosing.md)
