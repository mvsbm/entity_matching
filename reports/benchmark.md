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

## Cost: files of growing size (time grows like N^0.4)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample of the file inside it (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12532 | 8.0 | 0.72 | 0.15 | 0.1 | 7.16 | 0.06 | 0.22 | 0.23 | 0.02 | 0.04 | 0.4573 | 2 | 0.48% | 985 | 0.84 | 1 |
| 24955 | 8.9 | 0.86 | 0.24 | 0.17 | 7.66 | 0.09 | 0.33 | 0.33 | 0.04 | 0.07 | 0.4598 | 0 | 0.12% | 1832 | 1.03 | 0 |
| 50116 | 10.0 | 0.93 | 0.43 | 0.29 | 7.68 | 0.14 | 0.57 | 0.69 | 0.04 | 0.13 | 0.4467 | 0 | 0.06% | 3705 | 2.48 | 0 |
| 74959 | 11.0 | 1.08 | 0.63 | 0.43 | 7.91 | 0.2 | 0.8 | 0.74 | 0.06 | 0.19 | 0.4422 | 4 | 0.12% | 5383 | 4.38 | 3 |
| 1000338 | 43.0 | 5.85 | 6.89 | 1.93 | 9.24 | 2.23 | 6.24 | 15.22 | 0.27 | 0.93 | — | — | — | 38787 | 30.11 | — |
