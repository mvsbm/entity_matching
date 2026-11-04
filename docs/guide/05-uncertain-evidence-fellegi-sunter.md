[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · **5 Evidence** · [6 Measuring](06-measuring-and-choosing.md)

# 5. Uncertain evidence: the Fellegi–Sunter model

*Challenges C4 (look-alikes), C5 (partial evidence), C6 (empty fields) and C7 (pairs vs groups).*

## Challenge: how sure can we be about a pair?

The rules in [chapter 4](04-certain-cases-first-rules.md) could not decide this pair:

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| A | マツモトヒサオ | 福島県福島市吉倉4-11 | 0599 | 5227073594045 |
| B | マツモトヒサウ | 福島県福島市吉倉4-11 | 0499 | 5912064752971 |

The address agrees, which is strong evidence. The name and the phone almost agree, which is weaker evidence. The CIF ID differs, which is weak evidence against. We need a way to **add up evidence of different strengths**, for and against, into one score we can act on.

## Solution: evidence in bits

The Fellegi–Sunter model asks two questions about every field.

- **m:** if the two records *are* the same entity, how often does this field look like this?
- **u:** if they are *different* entities, how often does it look like this by chance?

The ratio m / u says how much more likely the observation is under "same" than under "different". Here are the values learned for the phone, from the training cell:

| Phone observation | m: same entity | u: different entities | Evidence |
|---|---|---|---|
| exactly equal | 0.746 | 1 in 7,984 | +12.5 bits |
| one digit off | 0.081 | 1 in 279 | +4.5 bits |
| different | 0.173 | 0.996 | −2.5 bits |

Both u values can be checked by counting:
- **Exactly equal:** two strangers share a random last four digits about 1 time in 10,000.
- **One digit off:** each number has 36 neighbours that differ in exactly one digit, and 36 in 10,000 is about 1 in 278.
- **m is not 1:** a true pair has a *different* phone 17% of the time, because people own several phones.

**From ratios to bits.** For a pair whose fields land in observations γ₁, γ₂, …, Bayes' rule in odds form says:

$$\underbrace{\frac{P(\text{same} \mid \gamma)}{P(\text{different} \mid \gamma)}}_{\text{odds after looking}} \;=\; \underbrace{\frac{\lambda}{1-\lambda}}_{\text{odds before looking}} \;\times\; \prod_{k} \frac{m_k(\gamma_k)}{u_k(\gamma_k)}$$

Here λ is the chance that two random records are the same entity. Taking log₂ of both sides turns the product into a sum, which gives the **match weight**:

$$w \;=\; \log_2\frac{\lambda}{1-\lambda} \;+\; \sum_k \log_2\frac{m_k}{u_k}$$

Each term is a number of **bits**, and each bit doubles the odds. So +10 bits multiply the odds by about 1,000.

**The example pair, field by field.** These numbers come from the notebook's "Why a pair matches" cell:

| Evidence | Observation | Bits |
|---|---|---|
| before looking | two random records match about 1 in 32,000 | −14.98 |
| name | close (Jaro–Winkler 0.943 after folding, at least 0.75) | +3.98 |
| company | missing (a person has no company name) | 0.00 |
| address | the same | +14.01 |
| phone | one digit off | +4.50 |
| CIF ID | different | −0.90 |
| **total** | | **+6.61** |

Back from bits to a probability:

$$p = \frac{2^{w}}{1 + 2^{w}} = \frac{2^{6.61}}{1 + 2^{6.61}} = 99.0\%$$

### Why this solution

- **It adds up partial evidence.** A strong agreement can outweigh a weak disagreement, which is exactly what the rules couldn't do.
- **Every decision is explainable.** The table above *is* the explanation. Any accepted pair can be printed this way.
- **It learns without labels,** as the next sections show.
- **It is proven.** Fellegi and Sunter proved the rule optimal when the fields are independent: for a given error rate, no other rule decides more pairs. The model has run in official statistics for decades.

### What it costs: the independence assumption

The sum assumes the fields are **independent**, given whether the pair matches. Some of ours are not. The address code, the address text and the postal code describe one fact: where the record lives. Counting them as three fields would count one agreement three times.

So correlated fields form **one comparison** with ordered levels. The first level that holds wins. The thresholds shown are the final ones:

| Comparison | Levels, strongest first |
|---|---|
| name | exact · exact after folding · very close (Jaro–Winkler ≥ 0.95) · same given name · close (≥ 0.75) · else |
| company | exact · very close · close · else |
| address | same address code or address · address within 2 edits · same postal code · else |
| phone | exact · one digit off · else |
| CIF ID | exact · else |

The "same given name" level catches a surname change after marriage.

**In short:** every field adds evidence in bits; correlated fields share one comparison.

## Challenge: learning m, u and λ without labels

In production, nobody tells us which pairs match. Each parameter must come from the records themselves.

**u, from random pairs.** Almost every random pair of records is two different entities. So we draw 10 million random pairs and count how often each level occurs. That count estimates u.

**λ, from near-certain rules.** Pairs that agree on CIF ID and name are almost surely matches. Counting them, and assuming these rules find about half of all true pairs, gives λ. On train it is about 1 in 97,000 pairs. The chance two random records match depends on the file's size, so λ is rescaled for each file. On validation it is 1 in 32,000.

**m, by expectation–maximization (EM).** Take the pairs that share a phone number. They are a mix of true pairs and strangers, in unknown proportions. EM alternates two steps until the numbers settle:

1. **Guess the matches:** with the current m, u and λ, compute each pair's probability of being a match.
2. **Update m:** recount each level, weighting every pair by that probability.

It runs once on pairs that share a phone and once on pairs that share an address. Each run learns the m values of the *other* fields.

**Does EM get it right?** Our synthetic data has labels, so we can check. Trained on the same records, EM and the labels learn almost the same weights. This is the configuration as written, where "very close" starts at 0.92:

| Level | EM | From labels |
|---|---|---|
| name exact | +15.57 | +15.57 |
| name very close | +11.37 | +11.38 |
| same address | +14.02 | +14.01 |
| phone exact | +12.54 | +12.54 |
| CIF ID different | −0.90 | −0.92 |

**What can go wrong.** A level may never occur in the sample, if its threshold is too strict, or if a lower level can never be reached because the level above it always catches the pair first. Splink then quietly uses default values, which can create strong evidence out of nothing. We use cautious bounds instead. A level no random pair reached gets u at its 95% upper bound, and a level never seen in training counts 0 bits. ([lessons](../lessons.md))

**In short:** random pairs give u, near-certain rules give λ, and EM gives m, with no labels needed.

## Challenge: empty fields

The company comparison above is *missing*: a person has no company name. Some columns are empty for 35% of records.

**Solution: an empty field adds 0 bits.** If either record lacks the field, the comparison is skipped.

**Why:** absence is evidence of neither match nor non-match. Treating it as a disagreement would punish records just for being sparse.

## Challenge: some agreements are rarer than others

Sharing the name サトウ says less than sharing a rare name. That was Newcombe's 1959 insight. A **term-frequency adjustment** gives an exact match more bits when the value is rare.

We tested it, and cross-validated train decided. Switching it off found 15 more true pairs and lost none, so it is off.

The adjustment carries a subtle trap. Frequencies must come from the training records and stay fixed when scoring, or a score would depend on which file is being scored. A cache bug once caused exactly that ([lessons](../lessons.md)).

## Challenge: where to draw the line?

A score is not yet a decision. We accept a pair at **6 bits or more**, a probability of about 98.5%. On validation, the line trades recall against false merges like this:

| Accept at or above | Pairs accepted | False pairs among them | Recall after grouping |
|---|---|---|---|
| 0 bits | 531 | 5 | 93.7% |
| 2 bits | 519 | 2 | 93.4% |
| 4 bits | 491 | 0 | 92.4% |
| **6 bits** | **471** | **0** | **91.5%** |
| 8 bits | 423 | 0 | 89.4% |

The line was not picked from this table, which would tune it on validation. It comes from a rule applied to train ([chapter 6](06-measuring-and-choosing.md)): the lowest weight with no false pair in cross-validation, plus one safety step.

**The closest non-match**, just below the line:

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| C | セルシスカブシキガイシャ (a company) | 東京都多摩市連光寺5-18-5 | 8813 | 2754477213332 |
| D | ヤマモトカヨ (a person) | 東京都多摩市連光寺5-18-5 | 6813 | 4590715084681 |

Same address (+14.01), phone one digit off (+4.50), different CIF ID (−0.90). That's the same evidence as our true pair, except the name. A company and a person have no name to compare, so the total is **+2.64 bits: rejected**. The four bits between a match and a non-match come from the name.

## Challenge: from pairs to groups

Accepted pairs must become groups. If A–B and B–C are accepted, then A, B and C are one entity.

**Solution: connected components.** Records are points, accepted pairs are lines, and every connected set of points is one entity. The pairs from the rules and from this stage are grouped together.

**Why, and the risk.** It is the natural reading of "same as", and it lets a record join a group that the rules already started. The risk is a **chain**: one false pair can join two whole groups. The strict 6-bit line is what keeps chains safe.

We also tested the cautious alternative: refuse a merge when the two groups hold different given names. It lost 258 true pairs on validation, because a typo in a given name looks like a conflict.

## On our data

| Split | Recall: rules → + this stage | 95% interval | False merges | False-merge rate at most |
|---|---|---|---|---|
| train | 69.2% → 89.3% | 88.5–90.0% | 0 | 0.05% |
| val | 69.3% → 91.5% | 90.2–92.6% | 0 | 0.15% |
| **test** | 71.1% → **90.2%** | 88.9–91.3% | **0** | 0.14% |

**In short:** weighing evidence lifts recall from about 70% to about 90%, with no false merges.

## In the code

- `er/match.py`:
  - `train_fs`: learns λ, u and m
  - `score_fs`: scores candidate pairs
  - `waterfall`: the field-by-field table
  - `scaled_prior`: rescales λ to the scored file's size
- `er/resolve.py`: `connected_components`, `constrained`
- `notebooks/probabilistic_matching.ipynb`: `SPEC.model` (the comparisons and levels), the Training cell (EM against labels), "Why a pair matches", the Threshold cell
- every table: [results.md](../results.md)

## Further reading

- R. Linacre, "[An interactive introduction to record linkage](https://robinl.github.io/intro_to_probabilistic_linkage/)." The best intuition for this chapter, from Splink's author.
- I. P. Fellegi and A. B. Sunter, "A theory for record linkage," *Journal of the American Statistical Association* 64(328), 1969.
- W. E. Winkler, "Using the EM algorithm for weight computation in the Fellegi–Sunter model of record linkage," *Proceedings of the Section on Survey Research Methods*, American Statistical Association, 1988.
- Splink documentation: the [waterfall chart](https://moj-analytical-services.github.io/splink/charts/waterfall_chart.html), [match weights](https://moj-analytical-services.github.io/splink/charts/match_weights_chart.html), [term frequency](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html).
- P. Christen, *Data Matching*, Springer, 2012: chapter 6 (classification).

**Next:** [6. Measuring honestly, choosing without overfitting →](06-measuring-and-choosing.md)
