[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · **5 Evidence** · [7 Kinds](07-person-or-company.md)

# 5. Uncertain evidence: the Fellegi–Sunter model

*Challenges C4 (look-alikes), C5 (partial evidence), C6 (empty fields) and C7 (pairs vs groups).*

## Challenge: how sure can we be about a pair?

The rules in [chapter 4](04-certain-cases-first-rules.md) leave most true pairs undecided. Here is one of them, from val, a true match with a typo:

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| A | ミッマテルヤ | 20-2 | 3077 | 9991758286659 |
| B | ミッマドウミョオ | 愛知県20-2 | 3077 | 2286801775966 |

The surnames agree, but the given names don't: テルヤ and ドウミョオ, which is evidence against. A's address holds only the street number, but the two records share the address, which is strong evidence. The phone digits agree, which is strong evidence too. The CIF ID differs, which is weak evidence against. We need a way to **add up evidence of different strengths**, for and against, into one score we can act on.

## Solution: evidence in bits

The Fellegi–Sunter model asks two questions about every field.

- **m:** if the two records *are* the same entity, how often does this field look like this?
- **u:** if they are *different* entities, how often does it look like this by chance?

The ratio m / u says how much more likely the observation is under "same" than under "different". Here are the values the method learns for the phone on train:

| Phone observation | m: same entity | u: different entities | Evidence |
|---|---|---|---|
| exactly equal | 0.259 | about 1 in 9,400 | +11.3 bits |
| one digit off | 0.061 | about 1 in 277 | +4.1 bits |
| different | 0.681 | 0.996 | −0.5 bits |

u is rounded to three decimals; the "1 in" values follow from m and the weight. Both can be checked by counting:
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
| address | the same address | +12.76 |
| phone | exactly equal | +11.14 |
| CIF ID | different | −0.03 |
| birth date | missing | 0.00 |
| **total** | | **+6.19** |

The total is from unrounded parts. Back from bits to a probability:

$$p = \frac{2^{w}}{1 + 2^{w}} = \frac{2^{6.19}}{1 + 2^{6.19}} = 98.6\%$$

That clears the method's 6-bit threshold (below) by 0.19 bits. A different CIF ID costs almost nothing: true pairs have different CIF IDs 98.3% of the time (m = 0.983), nearly as often as strangers.

### Why this solution

- **It adds up partial evidence.** A strong agreement can outweigh a weak disagreement, which is exactly what the rules couldn't do.
- **Every decision is explainable.** The table above *is* the explanation. Every pair in a match run's table carries its bits, comparison by comparison (`<comparison>_bits`).
- **It learns without labels,** as the next sections show.
- **It is proven.** Fellegi and Sunter proved the rule optimal when the fields are independent: for a given error rate, no other rule decides more pairs. The model has run in official statistics for decades.

### What it costs: the independence assumption

The sum assumes the fields are **independent**, given whether the pair matches. Some of ours are not. The address code, the address text and the postal code describe one fact: where the record lives. Counting them as three fields would count one agreement three times.

So correlated fields form **one comparison** with ordered levels. The first level that holds wins. The levels and thresholds shown are the method's (`functions.sql`: `gamma_name` and the others):

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

**u is measured on every file we score.** Some fields have more distinct values in a bigger file: there are more addresses and more CIF IDs. Two random records then agree on them less often, so u is smaller. A u measured on train would under-credit those agreements on a bigger file, and over-credit them on a smaller one. Measuring u on the whole file being scored keeps each weight right at any size. The scores and the check on oversized key blocks ([chapter 3](03-far-too-many-pairs.md)) use the same u. It needs no labels, and costs about the same at any size: the fit, with this measurement inside it, takes 2.75 seconds at 13,019 records and 6.03 at a million ([`reports/benchmark.md`](../../reports/benchmark.md)).

**λ, from near-certain rules.** Pairs that agree on CIF ID and name, on CIF ID and company name, or on name, address code and phone are almost surely matches. Counting them, and dividing by the share of true pairs these rules find, gives λ. That share, measured on train's labels at design time, is 2.2% (`[fit] prior_recall` in `config.toml`), used for files without labels. The chance two random records match depends on the file's size, so λ is rescaled for each file. On val, a file of 10,496 records, it is about 1 in 23,000 pairs (−14.5 bits).

**m, by expectation–maximization (EM).** Take the pairs that share a phone number. They are a mix of true pairs and strangers, in unknown proportions. EM alternates two steps until the numbers settle:

1. **Guess the matches:** with the current m, u and λ, compute each pair's probability of being a match.
2. **Update m:** recount each level, weighting every pair by that probability.

It runs once on pairs that share a phone and once on pairs that share an address (`[fit] sessions`). Each run learns the m values of the *other* fields, and a level's m is the median of what the runs learn. A run fits λ and m on a fixed sample of 100,000 records, made of whole postal areas, so the cost doesn't grow with the file. That fit draws its own u sample of 1 million pairs, which feeds only EM; the scores use the u measured on the whole file.

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

**What can go wrong.** A level may never occur in the sample, if its threshold is too strict, or if a lower level can never be reached because the level above it always catches the pair first. Splink then quietly uses default values, which can create strong evidence out of nothing. We use cautious bounds instead. A level no random pair reaches gets u at its 95% upper bound, and a level never seen in training counts 0 bits. The company comparison has no "very close" level for that reason: no pair reaches it, in the sample or in EM, so it would add 0 bits for a second string comparison on every pair.

EM can go wrong the other way too. A level its learning pairs never reach gets an m of almost 0, and so a huge negative weight: a phone one digit off would count as near-proof of two different people, where a typo is the likelier story. So no level weighs less than its comparison's "else" level. And "one digit off" stands for a typo in a value that matches share; where matches never shared the exact value in training (an ID unique to each record), being one digit off just means neighbouring IDs, so it counts 0 bits.

**In short:** counts and random pairs give u, near-certain rules give λ, and EM gives m, with no labels needed.

## Challenge: empty fields

The company comparison above is *missing*: a person has no company name. Some columns are empty for 35% of records, and the birth date is filled for only 15%.

**Solution: an empty field adds 0 bits.** If either record lacks the field, the comparison is skipped.

**Why:** absence is evidence of neither match nor non-match. Treating it as a disagreement would punish records just for being sparse.

## Challenge: some agreements are rarer than others

Sharing the name サトウ says less than sharing a rare name. That was Newcombe's 1959 insight. A **term-frequency adjustment** gives an exact match more bits when the value is rare.

Tested like any other change on cross-validated train, the adjustment loses 33 true pairs out-of-fold and gains none (13 lost on val). So the model has none: a level weighs the same whichever value agrees.

## Challenge: where to draw the line?

A score is not yet a decision, and a run merges nothing by itself: people set a match run's threshold and decide its pairs. The method is designed, and measured, at **6 bits or more**, a probability of about 98.5% (`[lookup] likely_from`, where a lookup calls a candidate likely). On validation, with every rule pair and every pair at or above the threshold taken as a match, the threshold trades recall against false merges like this:

| Taken at or above | Pairs taken | False pairs among them | Recall after grouping |
|---|---|---|---|
| 0 bits | 1,561 | 8 | 59.7% |
| 2 bits | 1,491 | 5 | 58.2% |
| 4 bits | 1,259 | 0 | 51.8% |
| **6 bits** | **1,208** | **0** | **49.9%** |
| 8 bits | 1,166 | 0 | 48.6% |
| 10 bits | 703 | 0 | 28.8% |

*Pairs taken: the pairs the keys list, at or above the threshold, with a name compared (below). Each is scored with the model fitted on train, its u measured on val.*

The 6 is not picked from this table, which would tune it on validation. It comes from the threshold rule applied to train at design time ([chapter 1](01-entity-resolution-and-our-task.md#a-rule-for-every-choice)): the lowest weight with no false pair in cross-validation, plus one safety step.

**The safety step is the review floor.** The pairs between the lowest clean weight and the design threshold, from 4 to 6 bits, are never wrong on cross-validated train, but sit one step below it in case of noise. On val, the 4-bit row above takes 51 more pairs, none of them false, and lifts recall from 49.9% to 51.8%. A lookup shows entities from the review floor by default (`[lookup] at_least`); a match run starts wherever people set it, from 0 bits up (`[score] keep_from`: a run keeps no pair below it) ([decisions](../architecture.md#6--decisions)).

**A name must be compared.** A household shares an address and a phone, and those two alone can reach 6 bits. So the method, as measured, takes a model pair only if a person name or a company name is filled on both sides. A match run's table marks those pairs (`named`), and people judge the others on their evidence, whatever their score.

**The closest non-match**, one of the two pairs of different people with the highest score on val:

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| C | ャマノベタカユキ | 北海道岩見沢市日の出台10-26-24 | 2604 | 8852433827058 |
| D | イナモチタカユキ | 大阪府泉北郡忠岡町 | 2604 | 7587446239261 |

Same phone digits (+11.14). The surnames differ, but the given names agree (タカユキ), worth +7.61. Different addresses (−0.58), and a different CIF ID (−0.03): **+3.64 bits**, below even the review floor. Our example pair's names counted as different, but it shared the address as well as the phone; that is what lifted it to 6.19.

## Challenge: from pairs to groups

Matched pairs must become groups. If people say A–B and B–C match, then A, B and C are one entity.

**Solution: connected components.** Records are points, matched pairs are lines, and every connected set of points is one entity. Each record starts alone, and only people's match decisions draw lines, the rules' pairs and this stage's alike.

**Why, and the risk.** It is the natural reading of "same as", and it lets a record join a group that the rules already started. The risk is a **chain**: one false pair can join two whole groups. A strict threshold, and people deciding each pair, keep chains safe.

A cautious alternative would refuse a merge when the two groups hold different given names, but a typo in a given name looks like a conflict, so it loses true pairs. A run groups by connected components only (`decide.sql`, with `entities_of`), and the benchmark groups the pairs it takes with the same function, so the choice is measured the way it runs.

## On our data

| Split | Recall: rules → + this stage | 95% interval | False merges | False-merge rate at most |
|---|---|---|---|---|
| train | 10.5% → 47.6% | 46.5–48.8% | 0 | 0.09% |
| val | 11.9% → 49.9% | 47.9–51.8% | 0 | 0.24% |
| **test** | 9.6% → **48.2%** | 46.2–50.2% | **0** | 0.26% |

Pairs of two people of one household are counted apart, neither true nor false: 112 on train, 51 on val and 45 on test ([chapter 1](01-entity-resolution-and-our-task.md#a-rule-for-every-choice)).

**In short:** weighing evidence lifts recall from about 10% to about 48%, with no false merge on any split. Most of the rest share too little to clear 6 bits ([data](../data.md#how-hard-it-is)).

## In the code

- `nayose/sql/functions.sql`, 2. The comparisons: `name_score` and `name_level` (`gamma_name` the gate's), `gamma_company`, `gamma_address`, `gamma_phone`, `gamma_cif`, `gamma_birth`, and `levels`, each level's label and kind
- `nayose/sql/fit.sql`: 1. The sample; 2. λ (`fit_prior`, the near-certain rules' pairs); 3. EM's pairs (`em_patterns`, a session a key); 4. u (counted where it can be, the rest sampled, on the sample and on the file); 5. The model (`fit_model`: `model`, each level's m, u and bits; `fit`, λ and its bits at the file's size)
- `nayose/em.py`: `fit` (the model from fit.sql's counts), `learn` (λ, u, then m), `session` (one EM session), `u_bound`, `sensible_m` (the two limits on m), `assemble` (u on the file), `refresh` (an update's u)
- `nayose/config.toml` `[fit]`: `prior_recall`, `sessions`, `fit_rows`, `fit_u_max_pairs`, `u_max_pairs`, `seed`; `[lookup]`: `at_least` (the review floor, 4 bits), `likely_from` (6 bits)
- `nayose/sql/score.sql`: 3. The model's bits (`weights`: the prior's bits, rescaled for a lookup; `weight_of`; `bound_of`); 6. The scores (`scored`: each pair's levels, weight and probability, and `named`, the name check)
- `nayose/sql/match.sql`: a match run's table for people, at the threshold they set (each comparison's level and bits, `named`, `household`)
- `nayose/sql/decide.sql`, 3. The entities: connected components over the pairs people said match (`entities_of`, `nayose/entities.py`)

## Further reading

- R. Linacre, "[An interactive introduction to record linkage](https://robinl.github.io/intro_to_probabilistic_linkage/)." The best intuition for this chapter, from Splink's author.
- I. P. Fellegi and A. B. Sunter, "A theory for record linkage," *Journal of the American Statistical Association* 64(328), 1969.
- W. E. Winkler, "Using the EM algorithm for weight computation in the Fellegi–Sunter model of record linkage," *Proceedings of the Section on Survey Research Methods*, American Statistical Association, 1988.
- Splink documentation: the [waterfall chart](https://moj-analytical-services.github.io/splink/charts/waterfall_chart.html), [match weights](https://moj-analytical-services.github.io/splink/charts/match_weights_chart.html), [term frequency](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html).
- P. Christen, *Data Matching*, Springer, 2012: chapter 6 (classification).

**Next:** [7. Person or company →](07-person-or-company.md)
