# Choosing how to tell persons from companies

Written by `scripts/choose_kind.py`. Real company names from `data/reference/registry.json` (training: Miyagi and Okayama; test: Fukuoka), written the ways bank records write them, and the personas; the truth is the generator's. Each scenario: 20,000 customers. Judged correct first: the share of companies called company while at most 0.1% of company calls are wrong, and of persons called person while at most 1% of person calls are wrong, each line placed with the truth.

## The scenarios

What a file can't tell about itself, over its plausible range (a Latin hypercube); and, for the combination of `config/pipeline.toml` [kind], the shares it decides within budget.

| scenario | flag_wrong | on_representatives | representative_named_companies | sole_traders | sole_flagged_company | company_dates | companies | persons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 10% | 79% | 19% | 7% | 37% | 35% (founding) | 72.5% | 0.1% |
| 2 | 3% | 21% | 7% | 14% | 31% | 5% (representative) | 76.0% | 94.9% |
| 3 | 6% | 50% | 10% | 4% | 17% | 7% (founding) | 72.3% | 92.8% |
| 4 | 9% | 43% | 14% | 8% | 14% | 22% (representative) | 72.7% | 70.8% |
| 5 | 2% | 58% | 8% | 4% | 24% | 12% (founding) | 74.4% | 97.5% |
| 6 | 8% | 53% | 15% | 9% | 28% | 33% (representative) | 72.9% | 0.2% |
| 7 | 7% | 66% | 9% | 11% | 48% | 53% (founding) | 74.9% | 52.7% |
| 8 | 4% | 33% | 20% | 5% | 46% | 27% (representative) | 70.5% | 0.2% |
| 9 | 7% | 71% | 5% | 3% | 34% | 50% (founding) | 82.0% | 97.1% |
| 10 | 1% | 64% | 17% | 12% | 13% | 20% (representative) | 74.5% | 0.0% |
| 11 | 5% | 29% | 16% | 10% | 22% | 42% (founding) | 72.7% | 90.0% |
| 12 | 5% | 35% | 12% | 14% | 41% | 55% (representative) | 73.2% | 87.4% |

## The search

768 combinations, successive halving:

| scenarios | combinations | seconds |
| --- | --- | --- |
| 3 | 768 | 131 |
| 6 | 192 | 53 |
| 12 | 48 | 54 |

## The finalists on all 12 scenarios (the best 15 of 48)

mean and worst: over the scenarios, of the two sides' shares averaged.

| legal | ngram | training | combiner | signals | mean | worst | companies_mean | companies_worst | persons_mean | persons_worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal, known_name | 67.6% | 35.6% | 74.6% | 70.2% | 60.6% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal, known_name | 67.6% | 35.6% | 74.6% | 70.2% | 60.6% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal | 67.3% | 35.1% | 74.3% | 70.3% | 60.2% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal | 67.3% | 35.1% | 74.3% | 70.3% | 60.2% | 0.0% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal | 67.2% | 35.5% | 74.2% | 70.6% | 60.3% | 0.1% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal | 67.2% | 35.5% | 74.2% | 70.6% | 60.3% | 0.1% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal, known_name | 67.1% | 35.5% | 74.4% | 70.6% | 59.8% | 0.0% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal, known_name | 67.1% | 35.5% | 74.4% | 70.6% | 59.8% | 0.0% |
| bank table | 1–4 | public | gbdt2 | flag, birth, legal, known_name | 66.8% | 35.7% | 74.7% | 71.5% | 58.9% | 0.0% |
| bank table | 1–4 | public | gbdt2 | flag, birth_year, legal, known_name | 66.7% | 35.1% | 74.5% | 70.3% | 59.0% | 0.0% |
| bank table | 1–4 | public | gbdt2 | flag, birth, birth_year, legal, known_name | 66.7% | 35.1% | 74.5% | 70.3% | 59.0% | 0.0% |
| bank table | 1–4 | public | gbdt2 | flag, birth, birth_year, legal | 66.5% | 35.1% | 74.3% | 70.3% | 58.7% | 0.0% |
| bank table | 1–4 | public | gbdt2 | flag, birth_year, legal | 66.5% | 35.1% | 74.3% | 70.3% | 58.7% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth, legal, known_name | 66.2% | 35.4% | 74.0% | 70.0% | 58.3% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt3 | flag, birth, birth_year, legal | 66.0% | 35.8% | 73.7% | 70.6% | 58.3% | 0.0% |

## What each idea is worth

The best mean among the finalists with the idea, and without it.

| idea | best_mean |
| --- | --- |
| legal: bank table | 67.6% |
| legal: generator's forms | not among the finalists |
| ngram: 1–3 | 67.6% |
| ngram: 1–4 | 67.2% |
| training: public | 66.8% |
| training: public + the file's legal-form records | 67.6% |
| combiner: gbdt2 | 67.6% |
| combiner: gbdt3 | 66.0% |
| combiner: lr | not among the finalists |
| signal flag: with | 67.6% |
| signal flag: without | — |
| signal birth: with | 67.6% |
| signal birth: without | 67.6% |
| signal birth_year: with | 67.6% |
| signal birth_year: without | 66.8% |
| signal legal: with | 67.6% |
| signal legal: without | — |
| signal known_name: with | 67.6% |
| signal known_name: without | 67.3% |

## The pipeline's combination

`config/pipeline.toml` [kind]: the bank table, n-grams 1–3, trained once on public data, gradient-boosted trees of depth 2 on the flag, the birth year and the legal form. Rank 25 of 48: mean 65.5% (worst 35.3%), against 67.6% for the best (bank table, 1–3, public + the file's legal-form records, gbdt2: flag, birth, birth_year, legal, known_name).

## Counting sole traders

The pipeline's combination, each way of counting them.

| policy | companies_mean | companies_worst | persons_mean | persons_worst |
| --- | --- | --- | --- | --- |
| individuals | 74.0% | 70.5% | 57.0% | 0.0% |
| by record (a trade-name record a business) | 72.7% | 48.6% | 7.8% | 0.0% |
| businesses (every record) | 69.8% | 52.4% | 0.1% | 0.0% |

## Placing the lines from people's answers

The pipeline's combination and the best: answers drawn at random, 5 draws per scenario (60 trials), the combiner fitted on them, each line placed on their out-of-fold probabilities by each rule below. Then the calls on every other record: the mean share decided, the worst wrong share, and in how many trials the wrong share broke its budget (1% for person calls, 0.1% for company calls).

### The person line

- a: the lowest line whose answers above it are 30 or more and at most half the budget wrong
- b: the lowest line whose 95% one-sided upper bound (Clopper–Pearson) on the wrong share above it is within the budget
- c: the company's rule: the lowest line with no wrong answer above it, then margin_steps stricter

| combination | answers | person_rule | persons | person_wrong_worst | person_over_budget |
| --- | --- | --- | --- | --- | --- |
| the pipeline's | 500 | a | 26.36% | 3.15% | 8 |
| the pipeline's | 500 | b | 4.47% | 0.95% | 0 |
| the pipeline's | 500 | c | 5.13% | 2.06% | 4 |
| the pipeline's | 1000 | a | 22.27% | 1.54% | 8 |
| the pipeline's | 1000 | b | 10.50% | 1.19% | 2 |
| the pipeline's | 1000 | c | 2.52% | 1.62% | 3 |
| the pipeline's | 2000 | a | 25.34% | 1.23% | 4 |
| the pipeline's | 2000 | b | 19.81% | 1.23% | 2 |
| the pipeline's | 2000 | c | 2.05% | 0.56% | 0 |
| the pipeline's | 4000 | a | 20.57% | 1.51% | 2 |
| the pipeline's | 4000 | b | 29.84% | 1.14% | 2 |
| the pipeline's | 4000 | c | 0.01% | 0.00% | 0 |
| the best | 500 | a | 29.87% | 2.91% | 13 |
| the best | 500 | b | 4.42% | 1.14% | 1 |
| the best | 500 | c | 4.89% | 5.62% | 6 |
| the best | 1000 | a | 26.38% | 2.69% | 10 |
| the best | 1000 | b | 7.27% | 1.02% | 1 |
| the best | 1000 | c | 1.59% | 1.17% | 1 |
| the best | 2000 | a | 24.13% | 1.20% | 3 |
| the best | 2000 | b | 22.03% | 1.20% | 2 |
| the best | 2000 | c | 0.47% | 0.28% | 0 |
| the best | 4000 | a | 22.43% | 1.85% | 4 |
| the best | 4000 | b | 29.82% | 1.00% | 1 |
| the best | 4000 | c | 0.01% | 0.00% | 0 |

### The company line

The lowest grid line with no labelled person above it, then this many grid steps stricter (`margin_steps`).

| combination | answers | company_rule | companies | company_wrong_worst | company_over_budget |
| --- | --- | --- | --- | --- | --- |
| the pipeline's | 500 | 2 steps | 61.79% | 3.13% | 10 |
| the pipeline's | 500 | 3 steps | 52.13% | 1.45% | 7 |
| the pipeline's | 500 | 4 steps | 35.02% | 1.41% | 2 |
| the pipeline's | 500 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 52.13% | 1.45% | 7 |
| the pipeline's | 1000 | 2 steps | 66.77% | 0.41% | 4 |
| the pipeline's | 1000 | 3 steps | 57.97% | 0.14% | 1 |
| the pipeline's | 1000 | 4 steps | 40.48% | 0.27% | 1 |
| the pipeline's | 1000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 57.97% | 0.14% | 1 |
| the pipeline's | 2000 | 2 steps | 66.74% | 0.12% | 1 |
| the pipeline's | 2000 | 3 steps | 59.29% | 0.08% | 0 |
| the pipeline's | 2000 | 4 steps | 46.14% | 0.15% | 1 |
| the pipeline's | 2000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 66.74% | 0.12% | 1 |
| the pipeline's | 4000 | 2 steps | 67.69% | 0.04% | 0 |
| the pipeline's | 4000 | 3 steps | 62.03% | 0.03% | 0 |
| the pipeline's | 4000 | 4 steps | 50.68% | 0.09% | 0 |
| the pipeline's | 4000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 67.69% | 0.04% | 0 |
| the best | 500 | 2 steps | 61.42% | 3.01% | 11 |
| the best | 500 | 3 steps | 49.53% | 1.46% | 6 |
| the best | 500 | 4 steps | 35.09% | 1.37% | 3 |
| the best | 500 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 49.53% | 1.46% | 6 |
| the best | 1000 | 2 steps | 65.47% | 0.80% | 3 |
| the best | 1000 | 3 steps | 54.68% | 0.32% | 2 |
| the best | 1000 | 4 steps | 36.66% | 0.14% | 1 |
| the best | 1000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 54.68% | 0.32% | 2 |
| the best | 2000 | 2 steps | 67.06% | 0.13% | 1 |
| the best | 2000 | 3 steps | 59.52% | 0.06% | 0 |
| the best | 2000 | 4 steps | 45.54% | 0.12% | 1 |
| the best | 2000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 67.06% | 0.13% | 1 |
| the best | 4000 | 2 steps | 67.64% | 0.02% | 0 |
| the best | 4000 | 3 steps | 61.91% | 0.03% | 0 |
| the best | 4000 | 4 steps | 50.94% | 0.05% | 0 |
| the best | 4000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 67.64% | 0.02% | 0 |
