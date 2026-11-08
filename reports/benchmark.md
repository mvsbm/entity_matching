# Benchmark

Written by `scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB`: `config/final.toml` through `er.run`, the run without labels on DuckDB tables, on generated populations. Nothing is re-tuned.

## Quality: scenarios

Each population's test split, with λ and m fitted on its train split without labels and u measured on the test split, as a run does. `false_merges` are pairs of records in one cluster that are two entities; `false_links` are the model's links between two entities, and `expected_false` the false links the model expects among its own (the sum of 1 − match probability), which a run reports without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.0971 | 0.4591 | 0.439–0.479 | 0 | 0.28% | 798 | 0.54 | 0 |
| seed 1 | 0.1108 | 0.463 | 0.443–0.484 | 0 | 0.29% | 753 | 0.49 | 0 |
| seed 2 | 0.1206 | 0.4929 | 0.472–0.514 | 0 | 0.27% | 801 | 0.63 | 0 |
| typos doubled | 0.0812 | 0.3338 | 0.314–0.354 | 0 | 0.41% | 540 | 0.41 | 0 |
| fields emptier (last column 45% filled) | 0.0727 | 0.4172 | 0.397–0.437 | 0 | 0.31% | 767 | 0.68 | 0 |
| prior_recall halved (λ ×2) | 0.0971 | 0.4908 | 0.471–0.511 | 0 | 0.26% | 869 | 0.5 | 0 |
| prior_recall ×1.5 (λ ×⅔) | 0.0971 | 0.4506 | 0.431–0.471 | 0 | 0.28% | 776 | 0.72 | 0 |

## Person or company: end to end

Populations with one name column for every kind (`er.generate.kind_problems`): real company names from the registry, held out of the name model's training and written as banks write them; companies with records under their representative's name, the representative a person of the file (half at that person's address and phone); sole traders named like a shop; company dates; and a flag good, medium or poor. Each resolved three ways: names routed by the truth (the flag replaced by it, taken as it is); by the flag alone; by the kind step, people answering its review sheet (here, with the truth). `person_company_clusters` hold a true person and a true company; `sure_*` is the share of true companies called 2 and of true persons called 1; `wrong_*` the records called 2 that are persons and called 1 that are companies.

| flag | routed_by | recall | false_merges | person_company_clusters | pairs_to_decide | sure_companies | wrong_companies | sure_persons | wrong_persons | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| good (1% wrong at random, 20% on representatives) | the truth | 0.4618 | 1 | 0 | 573 | 83.7% | 0 | 98.5% | 0 | 7.4 |
| good (1% wrong at random, 20% on representatives) | the flag alone | 0.4553 | 21 | 20 | 532 | 82.0% | 304 | 97.0% | 83 | 7.3 |
| good (1% wrong at random, 20% on representatives) | the kind step, 2,000 labels | 0.4677 | 20 | 19 | 513 | 64.5% | 0 | 98.3% | 40 | 7.7 |
| medium (3%, 50%) | the truth | 0.4618 | 1 | 0 | 573 | 83.7% | 0 | 98.5% | 0 | 3.7 |
| medium (3%, 50%) | the flag alone | 0.4417 | 62 | 54 | 500 | 78.8% | 832 | 94.4% | 244 | 7.2 |
| medium (3%, 50%) | the kind step, 2,000 labels | 0.4652 | 53 | 46 | 483 | 63.9% | 0 | 12.1% | 0 | 7.7 |
| poor (10%, 80%) | the truth | 0.4618 | 1 | 0 | 573 | 83.7% | 0 | 98.5% | 0 | 3.8 |
| poor (10%, 80%) | the flag alone | 0.3899 | 84 | 72 | 528 | 72.1% | 2362 | 86.7% | 571 | 7.3 |
| poor (10%, 80%) | the kind step, 2,000 labels | 0.4142 | 75 | 63 | 530 | 63.7% | 0 | 11.5% | 0 | 7.6 |

## Cost: files of growing size (time grows like N^0.42)

Each file is resolved by `nayose resolve records` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample of the file inside it (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | probe | report | write | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12532 | 8.9 | 0.96 | 0.23 | 0.11 | 7.26 | 0.14 | 0.23 | 0.26 | 0.03 | 0.47 | 0.16 | 0.05 | 0.4573 | 2 | 0.48% | 985 | 0.84 | 1 |
| 24955 | 10.7 | 1.08 | 0.39 | 0.17 | 7.81 | 0.18 | 0.34 | 0.38 | 0.04 | 1.12 | 0.19 | 0.09 | 0.4598 | 0 | 0.12% | 1832 | 1.03 | 0 |
| 50116 | 13.1 | 1.44 | 0.69 | 0.3 | 7.85 | 0.25 | 0.58 | 0.76 | 0.06 | 2.28 | 0.21 | 0.17 | 0.4467 | 0 | 0.06% | 3705 | 2.48 | 0 |
| 74959 | 15.4 | 1.66 | 0.96 | 0.45 | 8.03 | 0.36 | 0.85 | 1.16 | 0.08 | 3.04 | 0.24 | 0.24 | 0.4422 | 4 | 0.12% | 5383 | 4.38 | 3 |
| 1000338 | 53.0 | 6.64 | 10.73 | 1.96 | 9.4 | 2.57 | 6.53 | 16.05 | 0.34 | 3.52 | 0.78 | 1.07 | — | — | — | 38786 | 30.11 | — |
