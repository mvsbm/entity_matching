# Benchmark

Written by `scripts/benchmark.py`: `config/final.toml` through `er.run`, the run without labels on DuckDB tables, on generated populations. Nothing is re-tuned.

## Quality: scenarios

Each population's test split, with λ, u and m fitted on its train split without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.7111 | 0.8994 | 0.887–0.911 | 0 | 0.14% |
| seed 1 | 0.7034 | 0.9069 | 0.895–0.918 | 0 | 0.14% |
| seed 2 | 0.67 | 0.8886 | 0.875–0.901 | 0 | 0.15% |
| typos doubled | 0.6743 | 0.8867 | 0.873–0.899 | 0 | 0.15% |
| fields emptier (last column 45% filled) | 0.6279 | 0.8829 | 0.869–0.895 | 0 | 0.14% |
| prior_recall 0.25 (λ ×2) | 0.7111 | 0.9147 | 0.903–0.925 | 0 | 0.14% |
| prior_recall 0.75 (λ ×⅔) | 0.7111 | 0.8901 | 0.877–0.902 | 0 | 0.14% |

## Cost: files of growing size (time grows like N^0.21)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample inside `score` (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12392 | 17.9 | 0.57 | 0.12 | 0.07 | 9.01 | 0.24 | 0.12 | 8.24 | 0.03 | 0.03 | 0.8885 | 0 | 0.12% |
| 24944 | 19.1 | 0.66 | 0.22 | 0.08 | 9.42 | 0.32 | 0.21 | 8.77 | 0.05 | 0.07 | 0.894 | 3 | 0.16% |
| 50215 | 19.6 | 0.78 | 0.34 | 0.15 | 8.97 | 0.42 | 0.38 | 9.14 | 0.07 | 0.13 | 0.8944 | 1 | 0.05% |
| 75284 | 20.4 | 0.97 | 0.5 | 0.21 | 8.76 | 0.53 | 0.52 | 9.59 | 0.1 | 0.19 | 0.8902 | 5 | 0.07% |
| 999481 | 44.1 | 3.81 | 5.7 | 0.99 | 7.75 | 3.52 | 3.37 | 20.68 | 0.53 | 1.53 | — | — | — |
