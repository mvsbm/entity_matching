# Benchmark

Written by `scripts/benchmark.py`: `config/final.toml` through `er.run`, the run without labels on DuckDB tables, on generated populations. Nothing is re-tuned.

## Quality: scenarios

Each population's test split, with λ, u and m fitted on its train split without labels. `false_merges` are pairs of records in one cluster that are two entities; `false_links` are the model's links between two entities, and `expected_false` the false links the model expects among its own (the sum of 1 − match probability), which a run reports without labels.

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
| good (1% wrong at random, 20% on representatives) | the truth | 0.4704 | 0 | 0 | 517 | 83.7% | 0 | 98.5% | 0 | 6.1 |
| good (1% wrong at random, 20% on representatives) | the flag alone | 0.4578 | 15 | 15 | 520 | 82.5% | 223 | 97.4% | 58 | 6.1 |
| good (1% wrong at random, 20% on representatives) | the kind step, 2,000 labels | 0.4679 | 12 | 12 | 504 | 65.1% | 0 | 98.4% | 23 | 6.6 |
| medium (3%, 50%) | the truth | 0.4704 | 0 | 0 | 517 | 83.7% | 0 | 98.5% | 0 | 2.6 |
| medium (3%, 50%) | the flag alone | 0.4426 | 45 | 40 | 509 | 79.8% | 642 | 95.3% | 192 | 6.1 |
| medium (3%, 50%) | the kind step, 2,000 labels | 0.4634 | 44 | 39 | 484 | 65.8% | 0 | 97.2% | 79 | 6.4 |
| poor (10%, 80%) | the truth | 0.4704 | 0 | 0 | 517 | 83.7% | 0 | 98.5% | 0 | 2.6 |
| poor (10%, 80%) | the flag alone | 0.401 | 79 | 68 | 511 | 74.0% | 2014 | 88.5% | 478 | 5.9 |
| poor (10%, 80%) | the kind step, 2,000 labels | 0.4145 | 77 | 66 | 512 | 65.1% | 0 | 73.9% | 97 | 6.3 |

## Cost: files of growing size (time grows like N^0.42)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample of the file inside it (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12532 | 8.3 | 0.8 | 0.22 | 0.11 | 7.38 | 0.06 | 0.22 | 0.24 | 0.03 | 0.04 | 0.4573 | 2 | 0.48% | 985 | 0.84 | 1 |
| 24955 | 9.3 | 0.91 | 0.39 | 0.17 | 7.8 | 0.09 | 0.36 | 0.35 | 0.04 | 0.08 | 0.4598 | 0 | 0.12% | 1832 | 1.03 | 0 |
| 50116 | 10.5 | 1.01 | 0.66 | 0.31 | 7.86 | 0.14 | 0.6 | 0.71 | 0.06 | 0.14 | 0.4467 | 0 | 0.06% | 3705 | 2.48 | 0 |
| 74959 | 11.6 | 1.17 | 0.96 | 0.44 | 8.1 | 0.21 | 0.83 | 0.78 | 0.07 | 0.21 | 0.4422 | 4 | 0.12% | 5383 | 4.38 | 3 |
| 1000338 | 48.6 | 6.07 | 11.08 | 1.91 | 9.52 | 2.39 | 6.61 | 15.82 | 0.37 | 0.88 | — | — | — | 38786 | 30.11 | — |
