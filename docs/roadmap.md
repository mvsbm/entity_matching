[← README](../README.md) · [Architecture](architecture.md)

# Roadmap

This page lists the plans, in order. The other docs describe the code as it is. Each step keeps the results
identical, so `tests/test_parity.py`'s digests stay unchanged. Each step also quotes BigQuery's cost before and after,
in both bytes billed and work, from `scripts/estimate_cost.py`.

## 1 · BigQuery parity on the sandbox

No job has run on BigQuery yet. Every result is proven on DuckDB. Once the DevOps team provides staging's sandbox
dataset (`deploy/terraform/`, whose tables expire in a day), the tests' population runs through both engines, and
every job's tables are compared by digest, as `tests/test_parity.py` compares them here. The same runs calibrate
`scripts/estimate_cost.py` against BigQuery's own bytes billed and slot time. After that comes the scale rehearsal,
1M → 10M → 100M generated records with time and bytes billed at each size, before the first real build.

## 2 · Lookups on BigQuery

`nayose.lookup` runs on BigQuery as here, its statements writing temporary tables alone. `deploy/run.py` gets a
`lookup` job that writes the answer, which holds a record's values, to the run's table `looked_up`, and prints only
that it did, so no value reaches Jenkins' log. The parity step proves it equal to the lookups here, and measures how
much of the key index a lookup's keys read.
