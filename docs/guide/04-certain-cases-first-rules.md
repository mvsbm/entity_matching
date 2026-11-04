[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · **4 Rules** · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Measuring](06-measuring-and-choosing.md)

# 4. Certain cases first: rules

*Challenges C1 (variants) and C4 (look-alikes), for the clear cases.*

## Challenge: some pairs are obvious, but no single field is safe

Many duplicates are easy. Two records with the same CIF ID and the same full name are almost surely one person. A computer should settle these cheaply, explainably and without mistakes.

The trap is that any **single** field is shared by many different people. On train, for each field alone we counted how many true pairs agree on it, and how many pairs of *different* entities agree on it too:

| Field alone | True pairs that agree | Pairs of different entities that agree |
|---|---|---|
| last 4 phone digits | 74.5% | 45,506 |
| postal code | 70.8% | 41,868 |
| address code | 56.4% | 10,671 |
| address | 41.5% | 7,724 |
| given name | 48.0% | 117,118 |
| full name | 42.5% | 230 |
| CIF ID | 45.2% | 0 |

The phone is the most common agreement among true pairs, and also among strangers. A rule on any one of these fields would merge thousands of different people.

## Solution: rules that need two or three fields to agree

A **rule** is a short list of conditions that must *all* hold. Requiring two or three fields at once removes the look-alikes, because strangers rarely agree on several fields together:

| Fields that must agree | True pairs that agree | Pairs of different entities that agree |
|---|---|---|
| CIF ID + full name | 19.2% | 0 |
| CIF ID + phone | 33.2% | 0 |
| full name + address code + phone | 19.9% | 0 |
| address code + phone | 42.9% | 0 |
| phone + postal code | 53.6% | 4 |

Each rule finds only some true pairs, but rules are combined: a pair is accepted if **any one** rule holds.

The CIF ID is a special case. In our synthetic data, it is never shared by two entities, so it would be safe on its own. Real systems reuse and mistype CIF IDs, so our rules don't rely on that.

### Two stages: exact, then fuzzy

**Exact rules** ask for exact agreement, for example *CIF ID and full name*. There are five:

| Rule | Fields that must be equal |
|---|---|
| X1 | CIF ID + full name |
| X2 | CIF ID + company name |
| X3 | CIF ID + phone |
| X4 | full name + address code + phone |
| X5 | company name + address code + phone |

**Fuzzy rules** allow one field to be *close* instead of equal, using the similarity functions from [chapter 2](02-the-same-fact-written-differently.md). For example, rule F1 needs *the name close, plus the same address code and the same phone*. There are seven, including one for a surname change after marriage: same given name, address code and phone.

The close-enough tests were chosen by rule ([chapter 6](06-measuring-and-choosing.md)):

| Field | Counts as close when |
|---|---|
| person name | folded names are at most 2 edits apart (Levenshtein) |
| company name | their character sets overlap by at least 77% (Jaccard) |
| address | normalized addresses have Jaro–Winkler ≥ 0.91 |
| phone | at most one digit wrong or two digits swapped (Damerau–Levenshtein ≤ 1) |

The stages run in order, as a **cascade**. Fuzzy rules only add pairs that touch a record the exact rules left unresolved, so the clear cases are settled first.

### Why this solution

- **Rules are cheap.** Each rule is one database join on its exact fields, then a fuzzy check on the few pairs that join. On train, the 12 rules as written look at 24,635 pairs in total, out of 454 million.
- **Rules are easy to audit.** Every accepted pair carries the name of the rule that accepted it.
- **On our data, rules make no mistakes.** That makes them the safe first tier ([chapter 1](01-entity-resolution-and-our-task.md#how-is-it-done-in-practice)).

## On our data

| Split | Recall | 95% interval | False merges | False-merge rate at most |
|---|---|---|---|---|
| train | 69.2% | 68.1–70.3% | 0 | 0.06% |
| val | 69.3% (exact rules alone: 52.2%) | 67.4–71.2% | 0 | 0.19% |
| **test** | **71.1%** | 69.2–72.9% | **0** | 0.18% |

The exact rules find about half of the true pairs. The fuzzy rules lift that to about 70%. No split has a single false merge.

**Variants we tested.** Each was compared with the rules as written, on the same validation pairs:

| Change | True pairs gained / lost | Verdict |
|---|---|---|
| no kana folding before Jaro–Winkler | +1 / −53 | worse: folding matters |
| folded names must be equal, not close | +0 / −60 | worse: typos need tolerance |
| refuse a merge if two given names conflict | +0 / −210 | worse: given-name typos look like conflicts |
| names within 1 edit (Levenshtein) | +6 / −0 | adopted, then superseded by the next row |
| Optuna's comparators (the table above) | +12 / −0 | adopted |

**In short:** rules settle 70% of duplicates for almost nothing, and never wrongly.

## What it costs: where rules stop

Back to the pair from [chapter 1](01-entity-resolution-and-our-task.md):

| | Name | Address | Phone | CIF ID |
|---|---|---|---|---|
| A | マツモトヒサオ | 福島県福島市吉倉4-11 | 0599 | 5227073594045 |
| B | マツモトヒサウ | 福島県福島市吉倉4-11 | 0499 | 5912064752971 |

Every rule needs the full name, the phone or the CIF ID to agree exactly. Here all three differ: the name by one kana, the phone by one digit, the CIF ID entirely. So no rule fires, although a person would match these at a glance.

About 30% of duplicates are like this, with small differences in two or more fields at once. Rules can't weigh one strong agreement against two weak differences. That needs a model of evidence, which is the next chapter.

**In short:** all-or-nothing conditions can't add up partial evidence.

## In the code

- `notebooks/deterministic_matching.ipynb`: `SPEC` (the rules), `CHANGES` and `DECISIONS`; the cells for the design analysis, A/B tests, decisions and output
- `er/config.py`: `Rule`, `Stage`, `RulesSpec`, `Comparator`
- `er/match.py`: `rule_edges` (one Splink join per rule)
- `er/pipeline.py`: `run_rules`, `preflight`, `cascade`
- all tables: [results.md](../results.md)

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 6 (classification), on rule-based matching.
- [Splink documentation](https://moj-analytical-services.github.io/splink/): `deterministic_link` runs each of our rules.

**Next:** [5. Uncertain evidence: Fellegi–Sunter →](05-uncertain-evidence-fellegi-sunter.md)
