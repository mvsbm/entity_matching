[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · [3 Pairs](03-far-too-many-pairs.md) · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Measuring](06-measuring-and-choosing.md) · **7 Kinds**

# 7. Person or company

*A file of customers holds persons and companies. Each record, and each customer, gets its kind; and a person is never merged with a company by a guess.*

## Challenge: the file says which, but not reliably

A customer file usually carries a flag, 1 for a person and 2 for a company. It is right most of the time, and nobody knows how often it is wrong. Telling the kinds apart matters twice: as an answer of its own, and for matching, where a company merged into a person's records is a false merge of the worst kind.

What makes it hard, each built into the generator (`er.generate.kind_problems`) so it can be measured:

- **One name column for both kinds.** A person's name and a company's name arrive in the same column.
- **Legal forms written the bank's way.** カブシキガイシャ in full, カ)ヤマダショウジ in front, ヤマダショウジ(カ at the end, イ) for 医療法人, or left out.
- **Companies under their representative's name.** Some of a company's records carry a person's name: its representative, who may have records of their own, sometimes at the same address and phone.
- **Sole traders** are legally persons, and named like a shop: ヨシヤスショウテン.
- **Companies with a date** in the birth-date column: a founding date, or the representative's birth date.
- **The flag** is wrong at random, and more often on exactly these cases.

None of these rates is known for a given file. So the choice must hold across their whole plausible range, not at one guess.

## Solution: a name model, a combiner, a line per side, and people where the signals disagree

1. **A legal form says company.** Written where banks write one (the readings, and the bank abbreviations at the front or the end), a legal form makes a company near certain.
2. **The name says where a record leans.** A logistic regression on the name's character 1–3-grams, legal forms and spaces removed, trained once on public data: the registry's real company readings and the personas' names. It needs no label from the file. It learns what company stems look like: …ショウテン, …クリニック, …コウギョウ.
3. **People's answers weigh the rest.** A combiner, gradient-boosted trees of depth 2, weighs the name's score, the file's flag, the birth year and the legal form, fitted on people's answers. It learns how far to trust this file's flag.
4. **Correct first: a line per side.** Each record gets 2 company or 1 person only above that side's line, else 0 not sure. The company line: the lowest with no answer of a person above it, then two grid steps stricter. The person line: the lowest where the answers above it are wrong at most half of 1%.
5. **Disagreements wait for people.** Where the engine leans one way and the flag says the other, the record is held back from matching: its name goes to neither the person side nor the company side. Everywhere else the name goes to the side it leans to, and a pair of a person and a company has no name compared, so the model's name check (`[model] needs`, [chapter 5](05-uncertain-evidence-fellegi-sunter.md)) leaves it to people.
6. **People see why.** `kind_review.parquet` lists the held records and the flag's likely errors (why = decide), and a random draw that measures the flag and the engine (why = measure). Each row says in words what the engine, the name alone and the flag say. People answer 1, 2 or 0; their answers stand for their records.

A customer's kind follows from its records: 2 if any record surely is a company, 1 if none leans company and one surely is a person, else 0.

### Why this solution

- **The flag alone isn't enough, and neither is the name.** The flag is wrong where the cases are hard; the name can't see a company under a person's name. The combiner uses both, weighted by this file's answers.
- **No labels needed to start.** Without answers the engine calls a company only where a legal form is written, and never surely a person. The name model is trained on public data, so a run works on day one, and gets better as people answer.
- **The measuring draw is random.** Records sent to people because they look wrong would make every error rate look worse than it is. A draw stratified to hold more of the surest records puts more of them above each line than the file has, so the error measured above the line is not the file's. On the scenarios the two draws trade places by size (below); only the random draw measures the file as it is.
- **Held back, not guessed.** A company sent to the person side can merge into its representative's own records. Holding the disagreements back costs some recall until people answer, and spares those merges.

## How we know: every combination, across the unknowns

`scripts/choose_kind.py` ([reports/choose_kind.md](../../reports/choose_kind.md)) builds test populations of 20,000 customers from real company names (the registry's, trained on two prefectures and tested on a third) and the personas, with the problems above at rates drawn over their plausible range: 12 scenarios. It tries 768 combinations of the ideas (legal forms, the name model's n-grams and training, every subset of five signals, three combiners) by successive halving, and judges each correct first: the share of companies called company while at most 0.1% of company calls are wrong, and of persons called person while at most 1% are wrong.

| Idea | Best mean over the 12 scenarios |
|---|---|
| the bank table (against the generator's forms alone) | 67.6% (the generator's forms: not among the 48 finalists) |
| n-grams 1–3 (against 1–4) | 67.6% (67.2%) |
| trees of depth 2 (against depth 3; logistic regression) | 67.6% (66.0%; not among the finalists) |
| the birth year (against without it) | 67.6% (66.8%) |
| a dictionary of known surnames and given names | 67.6% with it, 67.3% without |
| training also on the file's own legal-form records | 67.6% (66.8% on public data only) |

The name model it judges is the run's own: trained on `er.generate.kind_training_names`, as `er.kind.name_model` trains it. The pipeline's combination, public training only so the name model is trained once, comes 25th of 48 at 65.5%, 2.1 points below the best, which also trains on the file's own legal-form records and adds the dictionary of names. On the company side it decides 74.0% of companies on average and 70.5% in the worst scenario. On the person side, 57.0% on average, and from 0.0% to 97.5% by scenario: it falls to nothing where many companies have records under their representative's name and the flag is wrong on them (15–20% of companies, the flag wrong on 33–79% of those records). Those records are a person's name, flagged person: no signal in them says company.

**Sole traders.** Counted as individuals, the person side decides 57.0% of persons; counted as businesses on their trade-name records, 7.8%; on every record, 0.1%. A sole trader is legally a person, which is also what the flag means.

**Placing the lines from answers.** With 2,000 answers at random and the company line two steps stricter, the company side kept its budget in every scenario (the worst wrong share: 0.02% of company calls); the person side broke its 1% in 2 of 12 (worst 1.67%). Stratified the same 2,000 (a third leaning company, a third leaning person), neither broke it (0.04%, 0.86%); at 500 and 1,000 answers its worst person error was the higher one (2.86% and 1.49%, against 1.36% and 0.54% at random), and at 1,000 the random draw kept the person budget everywhere. No draw and size keeps both budgets in every scenario: the person line is measured, not guaranteed.

## On a whole run

`scripts/benchmark.py` runs the whole pipeline on generated populations of 20,000 customers with all of the above, one name column for both kinds, and a flag good (wrong on 1% of records at random, on 20% of the representative-named ones), medium (3%, 50%) or poor (10%, 80%). The company names come from the registry's companies held out of the name model's training; the persons come from every persona, half of them in its training. Each population is resolved three ways: names routed by the truth, by the flag alone, and by the kind step with people answering its review sheet (here, with the truth) ([reports/benchmark.md](../../reports/benchmark.md)):

| Flag | Routed by | Recall | False merges | Person–company clusters | Persons called 2 | Companies called 1 | Persons called 1 |
|---|---|---|---|---|---|---|---|
| any | the truth | 46.2% | 1 | 0 | 0 | 0 | 98.5% |
| good | the flag alone | 45.5% | 21 | 20 | 304 | 83 | 97.0% |
| good | the kind step | 46.8% | 20 | 19 | 0 | 40 | 98.3% |
| medium | the flag alone | 44.2% | 62 | 54 | 832 | 244 | 94.4% |
| medium | the kind step | 46.5% | 53 | 46 | 0 | 0 | 12.1% |
| poor | the flag alone | 39.0% | 84 | 72 | 2,362 | 571 | 86.7% |
| poor | the kind step | 41.4% | 75 | 63 | 0 | 0 | 11.5% |

- **Recall** is 1.2–2.4 points higher by the kind step than by the flag alone.
- **No person is called a company** by the kind step; the flag alone calls 304 to 2,362. It also calls fewer companies persons: 0 to 40, against 83 to 571.
- **False merges** are fewer than the flag's on every flag: 20, 53 and 75 against 21, 62 and 84. Routed by the truth there is one, between two persons: the others come from names sent to the wrong side. A company record under its representative's name, at the representative's address and phone and flagged person, goes to the person side by either route, and can merge into the representative's own records.
- **Few persons are surely persons** where the flag is medium or poor: 12.1% and 11.5%. The person line, placed on the 2,000 answers drawn to measure, sits high there, so most persons stay 0, not sure. A record that is not sure still sends its name to the side it leans to, unless it is held back, so matching uses it; only its kind waits for more answers. With a good flag, 98.3%.

## What it can't do

- **A company record that is its representative's twin.** Under the representative's name, at the representative's address and phone, flagged person: every column matches the person's own record. Neither the engine nor people looking at the record can tell; another column could (an account type, a corporate number).
- **The person side is measured, not guaranteed.** Where many companies hide under their representatives' names behind a wrong flag, the person line finds no level within its budget and calls nobody a sure person. The run says so ("person never").

## In the code

- `er/kind.py`: `legal`, `text`, `NameModel` (scored in DuckDB), `name_model` (trained once, cached), `Classifier.classify`, `lines`, `classifier` (people's answers), `merge_answers`, `kind_review_sheet`
- `er/standardize.py`: `legal_pattern`, and `prepare`, which scores each chunk and routes the name fields
- `er/run.py`: `Run.load` (the classifier), `Run._gold` (a customer's kind), `qa` (the summary's kind lines)
- `er/settings.py`: `shared_name`, the settings for one name column
- `er/generate.py`: `name_model_split`, `kind_problems`, `bank_name`, `kind_training_names`
- `scripts/choose_kind.py`: the choice above; `scripts/benchmark.py`: `kinds`, the whole run; `scripts/resolve.py`: `--kind-labels` and `kind_review.parquet`
- every table: [results.md](../results.md#person-or-company)

## Further reading

- J. H. Friedman, "Greedy function approximation: a gradient boosting machine," *Annals of Statistics* 29(5), 2001.
- G. Ke et al., "LightGBM: a highly efficient gradient boosting decision tree," *NeurIPS*, 2017. The histogram trees scikit-learn's `HistGradientBoostingClassifier` follows.
- B. D. Jovanovic and P. S. Levy, "A look at the rule of three," *The American Statistician* 51(2), 1997. Why no error in n draws bounds a rate only near 3/n.

**Back to:** [README](../../README.md) · [1. The task](01-entity-resolution-and-our-task.md)
