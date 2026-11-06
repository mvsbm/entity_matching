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
| 3 | 768 | 128 |
| 6 | 192 | 51 |
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

The pipeline's combination: answers drawn at random or stratified, the combiner fitted on them, the lines placed on their out-of-fold probabilities (`er.kind.lines`: the company rule as below; the person line where the answers' wrong share is at most half of 1%), then the wrong calls on every other record: the mean share decided, the worst wrong share, and in how many of the 12 scenarios the wrong share broke its budget.

| answers | drawn | company_rule | companies | company_wrong_worst | company_over_budget | persons | person_wrong_worst | person_over_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 500 | random | no error above, then 1 step stricter | 65.40% | 0.29% | 1 | 27.46% | 1.36% | 2 |
| 500 | random | no error above, then 2 steps stricter | 60.27% | 0.12% | 1 | 27.46% | 1.36% | 2 |
| 500 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 1 step stricter | 68.59% | 0.57% | 2 | 8.84% | 2.86% | 1 |
| 500 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 63.56% | 0.60% | 2 | 8.84% | 2.86% | 1 |
| 1000 | random | no error above, then 1 step stricter | 68.17% | 0.81% | 4 | 14.96% | 0.54% | 0 |
| 1000 | random | no error above, then 2 steps stricter | 64.64% | 0.17% | 2 | 14.96% | 0.54% | 0 |
| 1000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 1 step stricter | 62.34% | 0.04% | 0 | 19.32% | 1.49% | 1 |
| 1000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 56.65% | 0.02% | 0 | 19.32% | 1.49% | 1 |
| 2000 | random | no error above, then 1 step stricter | 66.76% | 0.31% | 2 | 22.25% | 1.67% | 2 |
| 2000 | random | no error above, then 2 steps stricter | 64.74% | 0.02% | 0 | 22.25% | 1.67% | 2 |
| 2000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 1 step stricter | 70.88% | 0.04% | 0 | 23.91% | 0.86% | 0 |
| 2000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 68.03% | 0.04% | 0 | 23.91% | 0.86% | 0 |
