[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · **4 Rules** · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Measuring](06-measuring-and-choosing.md)

# 4. Certain cases first: rules

*Challenges C1 (variants) and C4 (look-alikes), for the clear cases.*

## Challenge: some pairs are obvious, but no single field is safe

Many duplicates are easy. Two records with the same CIF ID and the same full name are almost surely one person. A computer should settle these cheaply, explainably and without mistakes.

The trap is that any **single** field is shared by many different people. On train, for each field alone we counted how many true pairs agree on it, and how many pairs of *different* entities agree on it too:

| Field alone | True pairs that agree | Pairs of different entities that agree |
|---|---|---|
| last 4 phone digits | 33.2% | 45,079 |
| postal code | 35.6% | 33,413 |
| address code | 27.1% | 4,787 |
| address | 10.6% | 20,142 |
| given name | 32.2% | 84,380 |
| full name | 19.6% | 150 |
| CIF ID | 2.3% | 0 |

The postal code and the phone are the most common agreements among true pairs, and among strangers too. The given name is shared by the most strangers of all. A rule on any one of these fields would merge thousands of different people.

## Solution: rules that need two or three fields to agree

A **rule** is a short list of conditions that must *all* hold. Requiring two or three fields at once removes the look-alikes, because strangers rarely agree on several fields together:

| Fields that must agree | True pairs that agree | Pairs of different entities that agree |
|---|---|---|
| CIF ID + full name | 0.35% | 0 |
| CIF ID + phone | 0.78% | 0 |
| full name + address code + phone | 1.98% | 0 |
| address code + phone | 8.84% | 1 |
| phone + postal code | 11.5% | 4 |

Few true pairs agree on several fields at once, because a duplicate often has a new phone, a new address or a typo. Each rule finds only some true pairs, but rules are combined: a pair is accepted if **any one** rule holds.

The CIF ID is a special case. In our synthetic data, it is never shared by two entities, so it would be safe on its own, but only 2.3% of true pairs share it. Real systems reuse and mistype CIF IDs, so our rules don't rely on it alone.

### Two stages: exact, then fuzzy

**Exact rules** ask for exact agreement, for example *CIF ID and full name*. There are five:

| Rule | Fields that must be equal |
|---|---|
| X1 | CIF ID + full name |
| X2 | CIF ID + company name |
| X3 | CIF ID + phone |
| X4 | full name + address code + phone |
| X5 | company name + address code + phone |

**Fuzzy rules** allow one or two fields to be *close* instead of equal, using the similarity functions from [chapter 2](02-the-same-fact-written-differently.md). For example, rule F1 needs *the name close, plus the same address code and the same phone*. There are seven, including one for a surname change after marriage: same given name, address code and phone.

The close-enough tests are chosen by rule ([chapter 6](06-measuring-and-choosing.md)), and are in `config/final.toml`:

| Field | Counts as close when |
|---|---|
| person name | folded names are at most 2 edits apart, a swap of two neighbours counting as one (Damerau–Levenshtein ≤ 2) |
| company name | names, with the legal form removed and kana folded, are at most 1 edit apart (Levenshtein ≤ 1) |
| address | normalized addresses have Jaro–Winkler ≥ 0.9 |
| phone | at most one digit wrong (Hamming ≤ 1) |

**How a rule runs.** Each rule is one plain SQL join on its exact fields. Its fuzzy conditions are then checked only on the pairs that join, and two equal values pass without calling the string function at all. Rule F2 (name and address close, same phone) also joins on the first three characters of the normalized address, where the city starts, so it does not pair everyone who shares four phone digits. A pair found by several rules belongs to the first in order. In a run, a rule also leaves out any key value held by 64 records or more: one customer ID on thousands of records is not one customer's.

The stages run in order, as a **cascade**. Fuzzy rules only add pairs that touch a record the exact rules left unresolved, so the clear cases are settled first. The probabilistic stage follows the same rule: its pairs must touch a record the rules left alone, so it can add a record to a rule cluster, but does not join two rule clusters. Joining them is one of the changes tested, and finds no extra true pair on these sets ([chapter 6](06-measuring-and-choosing.md#challenge-every-choice-can-overfit)).

### Why this solution

- **Rules are cheap.** Each rule is one database join on its exact fields, then a fuzzy check on the few pairs that join. On train, the 12 chosen rules look at 3,710 pairs in total, out of 453 million.
- **Rules are easy to audit.** Every accepted pair carries the name of the rule that accepted it.
- **On our data, rules make no mistakes.** That makes them the safe first tier ([chapter 1](01-entity-resolution-and-our-task.md#how-is-it-done-in-practice)).

## On our data

| Split | Recall | 95% interval | False merges | False-merge rate at most |
|---|---|---|---|---|
| train | 10.7% | 10.0–11.5% | 0 | 0.40% |
| val | 9.7% (exact rules alone: 3.0%) | 8.5–11.0% | 0 | 1.38% |
| **test** | **9.7%** | 8.6–11.0% | **0** | 1.31% |

The exact rules find 3% of the true pairs. The fuzzy rules lift that to about 10%. No split has a single false merge. The numbers are low by design: the synthetic duplicates rarely agree exactly, as real ones don't ([data](../data.md#how-hard-it-is)).

**Variants we tested.** Each is compared with the rules as written, on the same validation pairs:

| Change | True pairs gained / lost | Verdict |
|---|---|---|
| no kana folding before Jaro–Winkler | +0 / −41 | worse: folding matters |
| folded names must be equal, not close | +0 / −22 | worse: typos need tolerance |
| refuse a merge if two given names conflict | +0 / −42 | worse: given-name typos look like conflicts |
| names within 1 edit (Levenshtein) | +6 / −2 | adopted on train (+17 / −4), then superseded by the last row |
| F2 with an exact address, or joined on the phone and the address's first three characters | +0 / −0 each | adopted as cheaper: on the phone alone, F2's pairs grow with the square of the file |
| Optuna's comparators (the table above) | +21 / −1 | adopted (on train, on top of the adopted rows above: +33 / −0) |

**In short:** rules settle about one true pair in ten for almost nothing, and never wrongly.

## What it costs: where rules stop

Back to the pair from [chapter 1](01-entity-resolution-and-our-task.md):

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| A | マツモトヒサオ | 福島県福島市吉倉4-11 | 0599 | 5227073594045 |
| B | マツモトヒサウ | 福島県福島市吉倉4-11 | 0499 | 5912064752971 |

Every rule needs the name, the phone or the CIF ID to agree exactly. Here all three differ: the name by one kana, the phone by one digit, the CIF ID entirely. So no rule fires, although a person would match these at a glance.

Most true pairs are like this: on train, the rules miss 6,177 of them, about nine in ten, most with differences in two or more fields at once. Rules can't weigh one strong agreement against two weak differences. That needs a model of evidence, which is the next chapter.

**In short:** all-or-nothing conditions can't add up partial evidence.

## In the code

- `config/pipeline.toml` `[rules]`: the rules, in logical fields; `config/experiments.py`: `rules_changes` and `RULES_DECISIONS`
- `er/select.py`: `RulesChooser` (the design analysis, A/B tests, decisions, cost and output), run by `scripts/choose.py`; its tables are in [`reports/choose.md`](../../reports/choose.md)
- `notebooks/demo.ipynb`, section 5: each rule's pairs on a small file
- `er/config.py`: `Rule`, `Stage` (`Stage.sql`: a fuzzy condition lets equal values through without the string function), `RulesSpec`, `Comparator`
- `er/match.py`: `rule_edges` (one SQL join per rule, the first rule wins a pair; for `choose.py`, full runs and increments alike)
- `er/pipeline.py`: `run_rules`, `preflight`, `cascade`; `er/run.py`: `Run.rules` (each stored cluster merged as one node, `Run._merge`)
- all tables: [results.md](../results.md)

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 6 (classification), on rule-based matching.
- [Splink documentation](https://moj-analytical-services.github.io/splink/): `deterministic_link` would give the same pairs, but joins every column of both records back first; a plain join is 1.35× faster at a million records.

**Next:** [5. Uncertain evidence: Fellegi–Sunter →](05-uncertain-evidence-fellegi-sunter.md)
