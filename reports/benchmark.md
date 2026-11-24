# Benchmark

Written by `scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB`: `config/pipeline.toml` through `jobs.build.build`, the run without labels on DuckDB tables, on generated populations. Nothing is re-tuned.

## Quality: scenarios

Each population's test split, with λ and m fitted on its train split without labels and u measured on the test split, as a run does. `false_merges` are pairs of records in one cluster that are two entities; `false_links` are the model's links between two entities, and `expected_false` the false links the model expects among its own (the sum of 1 − match probability), which a run reports without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most | household_merges | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.096 | 0.4817 | 0.462–0.502 | 0 | 0.26% | 45 | 882 | 1.02 | 0 |
| seed 1 | 0.1095 | 0.4861 | 0.466–0.507 | 0 | 0.27% | 49 | 858 | 0.91 | 0 |
| seed 2 | 0.1035 | 0.5053 | 0.485–0.526 | 0 | 0.25% | 55 | 926 | 1.08 | 0 |
| typos doubled | 0.0921 | 0.4307 | 0.411–0.451 | 0 | 0.29% | 23 | 777 | 1.51 | 0 |
| fields emptier (last column 45% filled) | 0.0786 | 0.4439 | 0.424–0.464 | 0 | 0.29% | 22 | 830 | 1.0 | 0 |
| prior_recall halved (λ ×2) | 0.096 | 0.4975 | 0.477–0.518 | 0 | 0.26% | 47 | 920 | 0.93 | 0 |
| prior_recall ×1.5 (λ ×⅔) | 0.096 | 0.4771 | 0.457–0.497 | 0 | 0.27% | 27 | 862 | 1.15 | 0 |

## Person or company: end to end

Populations with one name column for every kind (`design.generate.kind_problems`): real company names from the registry, held out of the name model's training and written as banks write them; companies with records under their representative's name, the representative a person of the file (half at that person's address and phone); sole traders named like a shop; company dates; and a flag good, medium or poor. Each resolved three ways: names routed by the truth (the flag replaced by it, taken as it is); by the flag alone; by the kind step (a written legal form, or a name the model is sure of, never a person's against a company flag; else the flag). `person_company_clusters` hold a true person and a true company; `sure_*` is the share of true companies called 2 and of true persons called 1; `wrong_*` the records called 2 that are persons and called 1 that are companies.

| flag | routed_by | recall | false_merges | person_company_clusters | pairs_to_decide | sure_companies | wrong_companies | sure_persons | wrong_persons | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| good (1% wrong at random, 20% on representatives) | the truth | 0.5018 | 5 | 0 | 302 | 100.0% | 0 | 100.0% | 0 | 3.0 |
| good (1% wrong at random, 20% on representatives) | the flag alone | 0.4911 | 38 | 27 | 298 | 97.9% | 306 | 98.5% | 102 | 1.9 |
| good (1% wrong at random, 20% on representatives) | the kind step | 0.4899 | 33 | 26 | 306 | 98.7% | 554 | 97.4% | 63 | 1.9 |
| medium (3%, 50%) | the truth | 0.5018 | 5 | 0 | 302 | 100.0% | 0 | 100.0% | 0 | 1.5 |
| medium (3%, 50%) | the flag alone | 0.4712 | 79 | 61 | 287 | 94.8% | 886 | 95.8% | 256 | 3.0 |
| medium (3%, 50%) | the kind step | 0.4723 | 73 | 59 | 294 | 96.9% | 1091 | 94.8% | 153 | 1.9 |
| poor (10%, 80%) | the truth | 0.5018 | 5 | 0 | 302 | 100.0% | 0 | 100.0% | 0 | 1.5 |
| poor (10%, 80%) | the flag alone | 0.4046 | 121 | 93 | 387 | 86.9% | 2533 | 87.9% | 644 | 3.6 |
| poor (10%, 80%) | the kind step | 0.4146 | 111 | 86 | 374 | 93.6% | 2690 | 87.2% | 314 | 2.0 |

## Cost: files of growing size (time grows like N^0.57)

Each file is resolved by `python -m er build` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 100,000 records) and the u sample of the file inside it (10,000,000 pairs) grow far slower than the file (the fit's sample is fixed; only u's exact counts read every record), so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | report | write | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13019 | 2.4 | 0.61 | 0.3 | 0.11 | 1.5 | 0.06 | 0.22 | 0.02 | 0.02 | 0.16 | 0.05 | 0.4843 | 2 | 0.44% | 1122 | 1.61 | 1 |
| 25947 | 3.0 | 0.68 | 0.49 | 0.17 | 1.57 | 0.09 | 0.36 | 0.03 | 0.03 | 0.18 | 0.09 | 0.492 | 0 | 0.11% | 2144 | 2.33 | 0 |
| 52115 | 4.2 | 0.85 | 0.8 | 0.3 | 1.86 | 0.15 | 0.65 | 0.04 | 0.04 | 0.2 | 0.17 | 0.4784 | 2 | 0.11% | 4301 | 4.82 | 2 |
| 77926 | 5.5 | 0.99 | 1.14 | 0.44 | 2.22 | 0.21 | 0.95 | 0.05 | 0.06 | 0.23 | 0.24 | 0.4747 | 6 | 0.14% | 6287 | 8.07 | 5 |
| 1039995 | 27.3 | 7.51 | 5.41 | 2.05 | 4.04 | 1.96 | 11.36 | 0.23 | 0.22 | 0.81 | 1.18 | — | — | — | 44065 | 54.54 | — |
