# Benchmark

Written by `scripts/benchmark.py`: `config/final.toml` through `er.run`, the run without labels on DuckDB tables, on generated populations. Nothing is re-tuned.

## Quality: scenarios

Each population's test split, with λ, u and m fitted on its train split without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.0971 | 0.4591 | 0.439–0.479 | 0 | 0.28% |
| seed 1 | 0.1108 | 0.463 | 0.443–0.484 | 0 | 0.29% |
| seed 2 | 0.1206 | 0.4929 | 0.472–0.514 | 0 | 0.27% |
| typos doubled | 0.0812 | 0.3338 | 0.314–0.354 | 0 | 0.41% |
| fields emptier (last column 45% filled) | 0.0727 | 0.4172 | 0.397–0.437 | 0 | 0.31% |
| prior_recall halved (λ ×2) | 0.0971 | 0.4908 | 0.471–0.511 | 0 | 0.26% |
| prior_recall ×1.5 (λ ×⅔) | 0.0971 | 0.4506 | 0.431–0.471 | 0 | 0.28% |

## Cost: files of growing size (time grows like N^0.4)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample of the file inside it (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12532 | 8.0 | 0.73 | 0.15 | 0.11 | 7.19 | 0.06 | 0.22 | 0.23 | 0.03 | 0.04 | 0.4573 | 2 | 0.48% |
| 24955 | 9.0 | 0.85 | 0.26 | 0.17 | 7.63 | 0.09 | 0.34 | 0.38 | 0.04 | 0.07 | 0.4598 | 0 | 0.12% |
| 50116 | 9.9 | 0.94 | 0.43 | 0.3 | 7.75 | 0.14 | 0.58 | 0.51 | 0.05 | 0.13 | 0.4467 | 0 | 0.06% |
| 74959 | 11.0 | 1.07 | 0.61 | 0.44 | 7.89 | 0.2 | 0.83 | 0.74 | 0.06 | 0.19 | 0.4422 | 4 | 0.12% |
| 1000338 | 42.9 | 6.23 | 6.95 | 1.82 | 9.18 | 2.29 | 6.24 | 15.35 | 0.27 | 0.81 | — | — | — |
