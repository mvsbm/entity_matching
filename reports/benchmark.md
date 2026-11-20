# Benchmark

Written by `scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB`: `config/final.toml` through `er.run`, the run without labels on DuckDB tables, on generated populations. Nothing is re-tuned.

## Quality: scenarios

Each population's test split, with λ and m fitted on its train split without labels and u measured on the test split, as a run does. `false_merges` are pairs of records in one cluster that are two entities; `false_links` are the model's links between two entities, and `expected_false` the false links the model expects among its own (the sum of 1 − match probability), which a run reports without labels. `gap_at_line` and `probe_missed` estimate, without labels, the matches no key lists, with their 95% intervals: the gap pairs a sample of records with every record that shares a value or a near one (`er.gap`); the probe samples pairs within a phone or a postal area (`er.probe`). They run here, where the keys are chosen, not in a run.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most | household_merges | model_links | expected_false | false_links | gap_at_line | probe_missed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.096 | 0.4817 | 0.462–0.502 | 0 | 0.26% | 45 | 882 | 1.1 | 0 | 0 (0–3) | 0 (0–6) |
| seed 1 | 0.1095 | 0.4861 | 0.466–0.507 | 0 | 0.27% | 49 | 858 | 0.91 | 0 | 1 (0–3) | 1 (0–6) |
| seed 2 | 0.1035 | 0.5062 | 0.486–0.526 | 0 | 0.25% | 55 | 928 | 1.06 | 0 | 2 (0–5) | 2 (0–8) |
| typos doubled | 0.0921 | 0.4307 | 0.411–0.451 | 0 | 0.29% | 23 | 777 | 1.48 | 0 | 1 (0–3) | 0 (0–6) |
| fields emptier (last column 45% filled) | 0.0786 | 0.4439 | 0.424–0.464 | 0 | 0.29% | 21 | 829 | 1.11 | 0 | 0 (0–3) | 0 (0–6) |
| prior_recall halved (λ ×2) | 0.096 | 0.4975 | 0.477–0.518 | 0 | 0.26% | 47 | 920 | 0.98 | 0 | 0 (0–3) | 0 (0–6) |
| prior_recall ×1.5 (λ ×⅔) | 0.096 | 0.4771 | 0.457–0.497 | 0 | 0.27% | 27 | 862 | 1.27 | 0 | 0 (0–3) | 0 (0–6) |

## Person or company: end to end

Populations with one name column for every kind (`er.generate.kind_problems`): real company names from the registry, held out of the name model's training and written as banks write them; companies with records under their representative's name, the representative a person of the file (half at that person's address and phone); sole traders named like a shop; company dates; and a flag good, medium or poor. Each resolved three ways: names routed by the truth (the flag replaced by it, taken as it is); by the flag alone; by the kind step (a written legal form, or a name the model is sure of, never a person's against a company flag; else the flag). This section: `scripts/benchmark.py`'s `kinds(20_000)` alone, measured again on 2026-11-20; the others are from the command above. `person_company_clusters` hold a true person and a true company; `sure_*` is the share of true companies called 2 and of true persons called 1; `wrong_*` the records called 2 that are persons and called 1 that are companies.

| flag | routed_by | recall | false_merges | person_company_clusters | pairs_to_decide | sure_companies | wrong_companies | sure_persons | wrong_persons | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| good (1% wrong at random, 20% on representatives) | the truth | 0.5018 | 5 | 0 | 285 | 100.0% | 0 | 100.0% | 0 | 4.3 |
| good (1% wrong at random, 20% on representatives) | the flag alone | 0.4911 | 38 | 27 | 297 | 97.9% | 306 | 98.5% | 102 | 4.3 |
| good (1% wrong at random, 20% on representatives) | the kind step | 0.4899 | 33 | 26 | 306 | 98.7% | 554 | 97.4% | 63 | 3.2 |
| medium (3%, 50%) | the truth | 0.5018 | 5 | 0 | 285 | 100.0% | 0 | 100.0% | 0 | 2.9 |
| medium (3%, 50%) | the flag alone | 0.4718 | 79 | 61 | 284 | 94.8% | 886 | 95.8% | 256 | 4.7 |
| medium (3%, 50%) | the kind step | 0.4728 | 73 | 59 | 291 | 96.9% | 1091 | 94.8% | 153 | 3.2 |
| poor (10%, 80%) | the truth | 0.5018 | 5 | 0 | 285 | 100.0% | 0 | 100.0% | 0 | 2.9 |
| poor (10%, 80%) | the flag alone | 0.4046 | 121 | 93 | 371 | 86.9% | 2533 | 87.9% | 644 | 4.9 |
| poor (10%, 80%) | the kind step | 0.4146 | 111 | 86 | 353 | 93.6% | 2690 | 87.2% | 314 | 3.3 |

## Cost: files of growing size (time grows like N^0.58)

Each file is resolved by `nayose resolve records` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample of the file inside it (10,000,000 pairs) grow far slower than the file (the fit's sample is fixed; only u's exact counts read every record), so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | report | write | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13019 | 2.3 | 0.63 | 0.34 | 0.1 | 1.38 | 0.06 | 0.2 | 0.02 | 0.02 | 0.16 | 0.05 | 0.4843 | 2 | 0.44% | 1122 | 1.67 | 1 |
| 25947 | 3.0 | 0.71 | 0.56 | 0.17 | 1.51 | 0.09 | 0.32 | 0.03 | 0.02 | 0.18 | 0.09 | 0.4927 | 0 | 0.10% | 2148 | 2.28 | 0 |
| 52115 | 4.1 | 0.89 | 0.97 | 0.3 | 1.71 | 0.15 | 0.58 | 0.04 | 0.04 | 0.2 | 0.16 | 0.4784 | 2 | 0.11% | 4301 | 4.76 | 2 |
| 77926 | 5.5 | 1.02 | 1.4 | 0.43 | 2.01 | 0.22 | 0.83 | 0.05 | 0.06 | 0.22 | 0.24 | 0.4777 | 6 | 0.14% | 6345 | 7.62 | 5 |
| 1039995 | 27.2 | 7.21 | 6.63 | 2.05 | 3.54 | 2.09 | 10.38 | 0.23 | 0.24 | 0.7 | 1.29 | — | — | — | 55222 | 223.43 | — |
