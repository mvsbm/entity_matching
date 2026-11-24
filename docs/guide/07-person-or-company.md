[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · **7 Kinds**

# 7. Person or company

*A file of customers holds persons and companies. Each record, and each customer, gets its kind; and a person is never merged with a company by a guess.*

## Challenge: the file says which, but not reliably

A customer file usually carries a flag, 1 for a person and 2 for a company. It is right most of the time, and nobody knows how often it is wrong. Telling the kinds apart matters twice: as an answer of its own, and for matching, where a company merged into a person's records is a false merge of the worst kind.

What makes it hard, each built into the generator (`design.generate.kind_problems`) so it can be measured:

- **One name column for both kinds.** A person's name and a company's name arrive in the same column.
- **Legal forms written the bank's way.** カブシキガイシャ in full, カ)ヤマダショウジ in front, ヤマダショウジ(カ at the end, イ) for 医療法人, or left out.
- **Companies under their representative's name.** Some of a company's records carry a person's name: its representative, who may have records of their own, sometimes at the same address and phone.
- **Sole traders** are legally persons, and named like a shop: ヨシヤスショウテン.
- **Companies with a date** in the birth-date column: a founding date, or the representative's birth date.
- **The flag** is wrong at random, and more often on exactly these cases.

None of these rates is known for a given file. So the choice must hold across their whole plausible range, not at one guess.

## Solution: a legal form, a name model, and the flag where neither is sure

1. **A legal form says company.** Written where banks write one (the readings, and the bank abbreviations at the front or the end), a legal form makes a company near certain.
2. **The name says where a record leans.** A logistic regression on the name's character 1–3-grams, legal forms and spaces removed, trained once on public data: the registry's real company readings and the personas' names. It needs no label from the file. It learns what company stems look like: …ショウテン, …クリニック, …コウギョウ.
3. **Correct first: sure, or the flag.** The engine calls 2 company where a legal form is written, and 2 company or 1 person where the name model is at least `[kind] name_line` (99%) sure, but never 1 person against a company flag: a company's records under its representative's name read as a person's; otherwise the file's flag decides, and with no flag the record is 0, not sure. `[kind] trust_flag = true` takes the flag as it is.
4. **Disagreements are flagged, not held.** Where the engine is sure and the flag says the other kind, the record is flagged and matched as the engine says. Each name goes to the side of its kind, and a pair of a person and a company has no name compared, so the model's name check (`[model] needs`, [chapter 5](05-uncertain-evidence-fellegi-sunter.md)) leaves it to people.
5. **The flag's owners see where it is likely wrong.** `gold.parquet` marks each flagged record (`kind_flagged`), and `report.txt` counts them.

A customer's kind follows from its records: 2 if any record is a company, 1 if none leans company and one is a person, else 0.

### Why this solution

- **The flag alone isn't enough, and neither is the name.** The flag is wrong where the cases are hard; the name can't see a company under a person's name. The engine takes the name where it is sure, and the flag elsewhere.
- **No labels needed.** The name model is trained on public data and the legal forms are the banks' own, so a run works on day one, on nothing but the file.
- **Held back, not guessed.** A company sent to the person side can merge into its representative's own records. Holding a person–company pair back for people costs some recall until they decide it, and spares those merges.

## How we know: every combination, across the unknowns

The ideas are measured at design time on test populations of 20,000 customers from real company names (the registry's, trained on two prefectures and tested on a third) and the personas, with the problems above at rates drawn over their plausible range: 12 scenarios. 768 combinations of the ideas (legal forms, the name model's n-grams and training, every subset of five signals, three combiners) go through successive halving, each judged correct first: the share of companies called company while at most 0.1% of company calls are wrong, and of persons called person while at most 1% are wrong.

| Idea | Best mean over the 12 scenarios |
|---|---|
| the bank table (against the generator's forms alone) | 67.6% (the generator's forms: not among the 48 finalists) |
| n-grams 1–3 (against 1–4) | 67.6% (67.2%) |
| trees of depth 2 (against depth 3; logistic regression) | 67.6% (66.0%; not among the finalists) |
| the birth year (against without it) | 67.6% (66.8%) |
| a dictionary of known surnames and given names | 67.6% with it, 67.3% without |
| training also on the file's own legal-form records | 67.6% (66.8% on public data only) |

The name model judged is the run's own: trained on `design.generate.kind_training_names`, as `scripts/train_name_model.py` trains it. The pipeline's combination, the run's name model (public training only, so it is trained once) under the study's trees of depth 2, comes 25th of 48 at 65.5%, 2.1 points below the best, which also trains on the file's own legal-form records and adds the dictionary of names. On the company side it decides 74.0% of companies on average and 70.5% in the worst scenario. On the person side, 57.0% on average, and from 0.0% to 97.5% by scenario: it falls to nothing where many companies have records under their representative's name and the flag is wrong on them (15–20% of companies, the flag wrong on 33–79% of those records). Those records are a person's name, flagged person: no signal in them says company.

**Sole traders.** Counted as individuals, the person side decides 57.0% of persons; counted as businesses on their trade-name records, 7.8%; on every record, 0.1%. A sole trader is legally a person, which is also what the flag means.

## On a whole run

`scripts/benchmark.py` runs the whole pipeline on generated populations of 20,000 customers with all of the above, one name column for both kinds, and a flag good (wrong on 1% of records at random, on 20% of the representative-named ones), medium (3%, 50%) or poor (10%, 80%). The company names come from the registry's companies held out of the name model's training; the persons come from every persona, half of them in its training. Each population is resolved three ways: names routed by the truth, by the flag alone, and by the kind step ([reports/benchmark.md](../../reports/benchmark.md)):

| Flag | Routed by | Recall | False merges | Person–company clusters | Persons called 2 | Companies called 1 | Persons called 1 |
|---|---|---|---|---|---|---|---|
| any | the truth | 50.2% | 5 | 0 | 0 | 0 | 100.0% |
| good | the flag alone | 49.1% | 38 | 27 | 306 | 102 | 98.5% |
| good | the kind step | 49.0% | 33 | 26 | 554 | 63 | 97.4% |
| medium | the flag alone | 47.1% | 79 | 61 | 886 | 256 | 95.8% |
| medium | the kind step | 47.2% | 73 | 59 | 1,091 | 153 | 94.8% |
| poor | the flag alone | 40.5% | 121 | 93 | 2,533 | 644 | 87.9% |
| poor | the kind step | 41.5% | 111 | 86 | 2,690 | 314 | 87.2% |

- **False merges** are fewer than the flag's on every flag: 33, 73 and 111 against 38, 79 and 121. Routed by the truth there are 5: the others come from names sent to the wrong side. A name that reads as a person's never overrides a company flag, so a company's records under its representative's name stay on the company side while the flag says company.
- **Wrong kinds:** companies called persons are fewer than the flag's on every flag: 63, 153 and 314 against 102, 256 and 644. Persons called companies are more: 554, 1,091 and 2,690 against 306, 886 and 2,533, where a name the model is sure is a company's overrides a person flag.
- **Recall** is within 0.2 points of the flag alone's against a good or medium flag, and 1.0 point higher against a poor one.
- **Nearly every record has a kind:** 87.2–97.4% of persons and 93.6–98.7% of companies.

## What it can't do

- **A company record that is its representative's twin.** Under the representative's name, at the representative's address and phone, flagged person: every column matches the person's own record. Neither the engine nor people looking at the record can tell; another column could (an account type, a corporate number).
- **A person the flag wrongly calls a company stays a company.** A name that reads as a person's never overrides a company flag, so the flag's mistake stands there; it costs fewer merges than the engine's person call costs on companies under their representative's name.

## In the code

- `er/kind.py`: `legal`, `text`, `NameModel` (scored in DuckDB), `name_model` (loads `config/kind_names.npz`, trained by `scripts/train_name_model.py`), `Classifier.classify`, `classifier`
- `er/standardize.py`: `legal_pattern`, and `prepare`, which scores each chunk and routes the name fields
- `er/steps/load.py`: `steps.load.load` (the classifier); `er/steps/cluster.py`: `steps.cluster._gold`, `steps.cluster.customer_kinds` (a customer's kind); `er/report.py`: `qa` (the summary's kind lines)
- `er/settings.py`: `shared_name`, the settings for one name column
- `design/generate.py`: `name_model_split`, `kind_problems`, `bank_name`, `kind_training_names`
- `scripts/benchmark.py`: `kinds`, the whole run

## Further reading

- J. H. Friedman, "Greedy function approximation: a gradient boosting machine," *Annals of Statistics* 29(5), 2001.
- G. Ke et al., "LightGBM: a highly efficient gradient boosting decision tree," *NeurIPS*, 2017. The histogram trees scikit-learn's `HistGradientBoostingClassifier` follows.
- B. D. Jovanovic and P. S. Levy, "A look at the rule of three," *The American Statistician* 51(2), 1997. Why no error in n draws bounds a rate only near 3/n.

**Back to:** [README](../../README.md) · [1. The task](01-entity-resolution-and-our-task.md)
