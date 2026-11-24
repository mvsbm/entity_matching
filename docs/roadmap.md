[← README](../README.md) · [Architecture](architecture.md)

# Roadmap

This page lists the plans, in order. The other docs describe the code as it is. Each step keeps the results
identical, so `tests/test_parity.py`'s digests stay unchanged. Each step also quotes BigQuery's cost before and after,
in both bytes billed and work, from `scripts/estimate_cost.py`.

## 1 · A key index that persists

`score.sql` makes every record's keys again for each batch, an `O(N·L)` scan, and a lookup makes them again too, an
`O(N·G)` scan. The plan is to keep the keys as a table of the run, clustered by key on BigQuery. A batch then adds its
own keys and joins on them alone, so the keys' part of an update costs `O(Δ·b)` and a lookup's costs `O(G·b)`. This is
the index the on-demand lookups need at a billion records.

## 2 · BigQuery parity on the sandbox

No job has run on BigQuery yet. Every result is proven on DuckDB. Once the DevOps team provides staging's sandbox
dataset (`deploy/terraform/`, whose tables expire in a day), the tests' population runs through both engines, and
every job's tables are compared by digest, as `tests/test_parity.py` compares them here. The same runs calibrate
`scripts/estimate_cost.py` against BigQuery's own bytes billed and slot time. After that comes the scale rehearsal,
1M → 10M → 100M generated records with time and bytes billed at each size, before the first real build.

## 3 · Lookups on BigQuery

A lookup is an update of the record asked about, rolled back. BigQuery takes no DDL in a transaction, so the deploy
makes no lookup procedure (`JOBS` in `nayose/engines.py`). On BigQuery, a lookup will run in a session of its own,
over clones of the run's tables, and the session ends without writing anything back. It comes with the parity step,
which proves it equal to the lookups here.
