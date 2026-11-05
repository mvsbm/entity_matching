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

## Cost: files of growing size (time grows like N^0.2)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample inside `score` (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12392 | 17.1 | 0.57 | 0.11 | 0.05 | 8.67 | 0.23 | 0.13 | 7.84 | 0.03 | 0.03 | 0.8885 | 0 | 0.12% |
| 24944 | 18.9 | 0.66 | 0.18 | 0.08 | 9.38 | 0.3 | 0.22 | 8.59 | 0.04 | 0.06 | 0.894 | 3 | 0.16% |
| 50215 | 18.4 | 0.78 | 0.33 | 0.14 | 8.52 | 0.39 | 0.39 | 8.47 | 0.07 | 0.12 | 0.8944 | 1 | 0.05% |
| 75284 | 19.3 | 0.97 | 0.48 | 0.2 | 8.31 | 0.49 | 0.55 | 8.96 | 0.09 | 0.18 | 0.8902 | 5 | 0.07% |
| 999481 | 39.8 | 5.5 | 5.49 | 0.86 | 7.3 | 3.31 | 3.0 | 18.52 | 0.38 | 0.92 | — | — | — |
