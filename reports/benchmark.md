# Benchmark

Written by `scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB`: the method (`nayose/sql/`, `nayose/config.toml`) through nayose's build, the run without labels on DuckDB, on generated populations. Nothing is re-tuned. A run merges nothing by itself; each is measured at the method's design threshold (6 points), as people would take a match run there whole: every rule pair, and the model's pairs at it or above with a name compared, joined by transitive closure.

## Quality: scenarios

Each population's test split, with λ and m fitted on its train split without labels and u measured on the test split, as a run does. `false_merges` are pairs of records in one cluster that are two entities; `false_links` are the model's links between two entities, and `expected_false` the false links the model expects among its own (the sum of 1 − match probability), known without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most | household_merges | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.096 | 0.4817 | 0.462–0.502 | 0 | 0.26% | 45 | 1111 | 1.03 | 0 |
| seed 1 | 0.1095 | 0.4861 | 0.466–0.507 | 0 | 0.27% | 49 | 1115 | 0.94 | 0 |
| seed 2 | 0.1035 | 0.5053 | 0.485–0.526 | 0 | 0.25% | 55 | 1171 | 1.1 | 0 |
| typos doubled | 0.0921 | 0.4307 | 0.411–0.451 | 0 | 0.29% | 23 | 996 | 1.52 | 0 |
| fields emptier (last column 45% filled) | 0.0786 | 0.4439 | 0.424–0.464 | 0 | 0.29% | 22 | 1016 | 1.02 | 0 |
| prior_recall halved (λ ×2) | 0.096 | 0.4975 | 0.477–0.518 | 0 | 0.26% | 47 | 1150 | 0.94 | 0 |
| prior_recall ×1.5 (λ ×⅔) | 0.096 | 0.4771 | 0.457–0.497 | 0 | 0.27% | 27 | 1091 | 1.17 | 0 |

## Person or company: end to end

Populations with one name column for every kind (`design.generate.kind_problems`): real company names from the registry, held out of the name model's training and written as banks write them; companies with records under their representative's name, the representative a person of the file (half at that person's address and phone); sole traders named like a shop; company dates; and a flag good, medium or poor. Each resolved three ways: names routed by the truth (the flag replaced by it, taken as it is); by the flag alone; by the kind step (a written legal form, or a name the model is sure of, never a person's against a company flag; else the flag). `person_company_clusters` hold a true person and a true company; `sure_*` is the share of true companies called 2 and of true persons called 1; `wrong_*` the records called 2 that are persons and called 1 that are companies.

| flag | routed_by | recall | false_merges | person_company_clusters | sure_companies | wrong_companies | sure_persons | wrong_persons | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| good (1% wrong at random, 20% on representatives) | the truth | 0.5018 | 5 | 0 | 100.0% | 0 | 100.0% | 0 | 5.0 |
| good (1% wrong at random, 20% on representatives) | the flag alone | 0.4911 | 38 | 27 | 97.9% | 306 | 98.5% | 102 | 5.0 |
| good (1% wrong at random, 20% on representatives) | the kind step | 0.4899 | 33 | 26 | 98.7% | 554 | 97.4% | 63 | 5.1 |
| medium (3%, 50%) | the truth | 0.5018 | 5 | 0 | 100.0% | 0 | 100.0% | 0 | 5.1 |
| medium (3%, 50%) | the flag alone | 0.4712 | 79 | 61 | 94.8% | 886 | 95.8% | 256 | 5.1 |
| medium (3%, 50%) | the kind step | 0.4723 | 73 | 59 | 96.9% | 1091 | 94.8% | 153 | 5.0 |
| poor (10%, 80%) | the truth | 0.5018 | 5 | 0 | 100.0% | 0 | 100.0% | 0 | 5.0 |
| poor (10%, 80%) | the flag alone | 0.4046 | 121 | 93 | 86.9% | 2533 | 87.9% | 644 | 5.2 |
| poor (10%, 80%) | the kind step | 0.4146 | 111 | 86 | 93.6% | 2690 | 87.2% | 314 | 5.0 |

## Cost: files of growing size (time grows like N^0.37)

Each file is resolved by `python -m nayose build` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Each stage's seconds: its own column. `fit` (on 100,000 records) and the u sample of the file inside it (10,000,000 pairs) grow far slower than the file (the fit's sample is fixed; only u's exact counts read every record), so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | records s | fit s | score s | decide s | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13019 | 5.1 | 1.29 | 0.73 | 3.84 | 0.52 | 0.05 | 0.4843 | 2 | 0.44% | 1414 | 1.62 | 1 |
| 25947 | 5.5 | 1.52 | 1.18 | 3.76 | 0.54 | 0.05 | 0.492 | 0 | 0.11% | 2782 | 2.34 | 0 |
| 52115 | 7.0 | 1.93 | 2.0 | 3.98 | 0.94 | 0.06 | 0.4784 | 2 | 0.11% | 5570 | 4.9 | 2 |
| 77926 | 7.1 | 2.04 | 2.77 | 3.36 | 0.88 | 0.06 | 0.4747 | 6 | 0.14% | 8155 | 8.25 | 5 |
| 1039995 | 24.1 | 6.4 | 9.41 | 5.48 | 9.02 | 0.18 | — | — | — | 69727 | 56.85 | — |
