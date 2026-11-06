# Choosing how to tell persons from companies

Written by `scripts/choose_kind.py`. Real company names from `data/reference/registry.json` (training: Miyagi and Okayama; test: Fukuoka), written the ways bank records write them, and the personas; the truth is the generator's. Each scenario: 20,000 customers. Judged correct first: the share of companies called company while at most 0.1% of company calls are wrong, and of persons called person while at most 1% of person calls are wrong, each line placed with the truth.

## The scenarios

What a file can't tell about itself, over its plausible range (a Latin hypercube); and, for the combination of `config/pipeline.toml` [kind], the shares it decides within budget.

| scenario | flag_wrong | on_representatives | representative_named_companies | sole_traders | sole_flagged_company | company_dates | companies | persons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 10% | 79% | 19% | 7% | 37% | 35% (founding) | 72.2% | 0.1% |
| 2 | 3% | 21% | 7% | 14% | 31% | 5% (representative) | 76.0% | 93.1% |
| 3 | 6% | 50% | 10% | 4% | 17% | 7% (founding) | 72.9% | 91.1% |
| 4 | 9% | 43% | 14% | 8% | 14% | 22% (representative) | 72.6% | 66.3% |
| 5 | 2% | 58% | 8% | 4% | 24% | 12% (founding) | 74.4% | 97.3% |
| 6 | 8% | 53% | 15% | 9% | 28% | 33% (representative) | 72.9% | 41.0% |
| 7 | 7% | 66% | 9% | 11% | 48% | 53% (founding) | 74.4% | 68.3% |
| 8 | 4% | 33% | 20% | 5% | 46% | 27% (representative) | 70.3% | 3.1% |
| 9 | 7% | 71% | 5% | 3% | 34% | 50% (founding) | 79.9% | 97.5% |
| 10 | 1% | 64% | 17% | 12% | 13% | 20% (representative) | 72.9% | 0.0% |
| 11 | 5% | 29% | 16% | 10% | 22% | 42% (founding) | 72.2% | 89.7% |
| 12 | 5% | 35% | 12% | 14% | 41% | 55% (representative) | 73.2% | 86.3% |

## The search

768 combinations, successive halving:

| scenarios | combinations | seconds |
| --- | --- | --- |
| 3 | 768 | 125 |
| 6 | 192 | 49 |
| 12 | 48 | 55 |

## The finalists on all 12 scenarios (the best 15 of 48)

mean and worst: over the scenarios, of the two sides' shares averaged.

| legal | ngram | training | combiner | signals | mean | worst | companies_mean | companies_worst | persons_mean | persons_worst |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal | 67.8% | 35.1% | 74.3% | 70.2% | 61.4% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal | 67.8% | 35.1% | 74.3% | 70.2% | 61.4% | 0.0% |
| bank table | 1–3 | public | gbdt2 | flag, birth, birth_year, legal, known_name | 67.6% | 36.2% | 73.9% | 70.3% | 61.2% | 0.0% |
| bank table | 1–3 | public | gbdt2 | flag, birth_year, legal, known_name | 67.6% | 36.2% | 73.9% | 70.3% | 61.2% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal, known_name | 67.5% | 35.1% | 74.3% | 70.2% | 60.6% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal, known_name | 67.5% | 35.1% | 74.3% | 70.2% | 60.6% | 0.0% |
| bank table | 1–3 | public | gbdt2 | flag, birth, birth_year, legal | 67.4% | 36.2% | 73.7% | 70.3% | 61.2% | 0.0% |
| bank table | 1–3 | public | gbdt2 | flag, birth_year, legal | 67.4% | 36.2% | 73.7% | 70.3% | 61.2% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth, legal, known_name | 67.1% | 35.1% | 74.2% | 70.2% | 60.1% | 0.0% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal, known_name | 67.0% | 35.5% | 74.6% | 70.9% | 59.4% | 0.0% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal, known_name | 67.0% | 35.5% | 74.6% | 70.9% | 59.4% | 0.0% |
| bank table | 1–3 | public + the file's legal-form records | gbdt2 | flag, birth, legal | 67.0% | 35.1% | 74.2% | 70.2% | 59.7% | 0.0% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth, birth_year, legal | 66.7% | 35.4% | 74.2% | 70.9% | 59.2% | 0.0% |
| bank table | 1–4 | public + the file's legal-form records | gbdt2 | flag, birth_year, legal | 66.7% | 35.4% | 74.2% | 70.9% | 59.2% | 0.0% |
| bank table | 1–4 | public + the file's legal-form records | gbdt3 | flag, birth, birth_year, legal, known_name | 66.5% | 35.6% | 73.3% | 68.2% | 59.6% | 0.1% |

## What each idea is worth

The best mean among the finalists with the idea, and without it.

| idea | best_mean |
| --- | --- |
| legal: bank table | 67.8% |
| legal: generator's forms | not among the finalists |
| ngram: 1–3 | 67.8% |
| ngram: 1–4 | 67.0% |
| training: public | 67.6% |
| training: public + the file's legal-form records | 67.8% |
| combiner: gbdt2 | 67.8% |
| combiner: gbdt3 | 66.5% |
| combiner: lr | not among the finalists |
| signal flag: with | 67.8% |
| signal flag: without | — |
| signal birth: with | 67.8% |
| signal birth: without | 67.8% |
| signal birth_year: with | 67.8% |
| signal birth_year: without | 67.1% |
| signal legal: with | 67.8% |
| signal legal: without | — |
| signal known_name: with | 67.6% |
| signal known_name: without | 67.8% |

## The pipeline's combination

`config/pipeline.toml` [kind]: the bank table, n-grams 1–3, trained once on public data, gradient-boosted trees of depth 2 on the flag, the birth year and the legal form. Rank 8 of 48: mean 67.4% (worst 36.2%), against 67.8% for the best (bank table, 1–3, public + the file's legal-form records, gbdt2: flag, birth_year, legal).

## Counting sole traders

The pipeline's combination, each way of counting them.

| policy | companies_mean | companies_worst | persons_mean | persons_worst |
| --- | --- | --- | --- | --- |
| individuals | 73.7% | 70.3% | 61.2% | 0.0% |
| by record (a trade-name record a business) | 75.1% | 68.0% | 7.5% | 0.0% |
| businesses (every record) | 71.1% | 62.0% | 0.1% | 0.0% |

## Placing the lines from people's answers

The pipeline's combination: answers drawn at random or stratified, the combiner fitted on them, the lines placed on their out-of-fold probabilities (`er.kind.lines`: the company rule as below; the person line where the answers' wrong share is at most half of 1%), then the wrong calls on every other record: the mean share decided, the worst wrong share, and in how many of the 12 scenarios the wrong share broke its budget.

| answers | drawn | company_rule | companies | company_wrong_worst | company_over_budget | persons | person_wrong_worst | person_over_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 500 | random | no error above, then 1 step stricter | 64.82% | 0.19% | 1 | 22.26% | 1.28% | 2 |
| 500 | random | no error above, then 2 steps stricter | 59.80% | 0.06% | 0 | 22.26% | 1.28% | 2 |
| 500 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 1 step stricter | 60.72% | 0.83% | 2 | 19.11% | 1.12% | 1 |
| 500 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 56.82% | 0.84% | 2 | 19.11% | 1.12% | 1 |
| 1000 | random | no error above, then 1 step stricter | 67.46% | 0.27% | 5 | 15.50% | 0.65% | 0 |
| 1000 | random | no error above, then 2 steps stricter | 62.72% | 0.10% | 0 | 15.50% | 0.65% | 0 |
| 1000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 1 step stricter | 70.94% | 0.08% | 0 | 18.76% | 1.20% | 1 |
| 1000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 68.38% | 0.02% | 0 | 18.76% | 1.20% | 1 |
| 2000 | random | no error above, then 1 step stricter | 66.80% | 0.25% | 2 | 20.72% | 0.95% | 0 |
| 2000 | random | no error above, then 2 steps stricter | 64.69% | 0.04% | 0 | 20.72% | 0.95% | 0 |
| 2000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 1 step stricter | 69.31% | 0.13% | 1 | 21.39% | 3.30% | 1 |
| 2000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 64.14% | 0.13% | 1 | 21.39% | 3.30% | 1 |
