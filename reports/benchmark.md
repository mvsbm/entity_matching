# Benchmark

> Measured before the standardization fixes of 2026-11-05 (full-width spaces, blank values), which changed the matching results; run `scripts/benchmark.py` again to refresh it.

Written by `scripts/benchmark.py`: `config/final.toml` through `er.run`, the run without labels on DuckDB tables, on generated populations. Nothing is re-tuned.

## Quality: scenarios

Each population's test split, with λ, u and m fitted on its train split without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.7106 | 0.899 | 0.886–0.911 | 0 | 0.14% |
| seed 1 | 0.7029 | 0.9069 | 0.895–0.918 | 0 | 0.14% |
| seed 2 | 0.6691 | 0.8877 | 0.874–0.900 | 0 | 0.15% |
| typos doubled | 0.6738 | 0.8881 | 0.874–0.900 | 0 | 0.15% |
| fields emptier (last column 45% filled) | 0.6275 | 0.885 | 0.872–0.897 | 0 | 0.14% |
| prior_recall 0.25 (λ ×2) | 0.7106 | 0.9147 | 0.903–0.925 | 0 | 0.14% |
| prior_recall 0.75 (λ ×⅔) | 0.7106 | 0.8914 | 0.878–0.903 | 0 | 0.14% |

## Cost: files of growing size (time grows like N^0.18)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample inside `score` (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12392 | 19.1 | 0.58 | 0.11 | 0.05 | 9.68 | 0.25 | 0.14 | 8.79 | 0.03 | 0.03 | 0.8888 | 0 | 0.12% |
| 24944 | 19.0 | 0.67 | 0.18 | 0.08 | 9.55 | 0.3 | 0.23 | 8.57 | 0.04 | 0.06 | 0.8955 | 3 | 0.16% |
| 50215 | 18.8 | 0.78 | 0.32 | 0.14 | 8.61 | 0.4 | 0.4 | 8.78 | 0.06 | 0.12 | 0.8929 | 1 | 0.05% |
| 75284 | 19.7 | 0.96 | 0.46 | 0.2 | 8.53 | 0.5 | 0.56 | 9.17 | 0.09 | 0.18 | 0.8902 | 5 | 0.07% |
| 999481 | 40.6 | 4.45 | 5.26 | 0.86 | 7.45 | 3.33 | 3.15 | 18.94 | 0.43 | 1.13 | — | — | — |
