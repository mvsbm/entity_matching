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
1M → 10M → 100M generated records with time and bytes billed at each size, before the first real build. The same
step proves the BigQuery `lookup` job equal to the lookups here, and measures how much of the key index a
lookup's keys read. It also shows report.txt read from the job's temporary report_ tables after its procedure ends:
BigQuery's docs give a procedure's temporary tables to its caller and keep a session's for the session, but no test
here can show it.

## 2 · BigQuery's pricing and storage, measured

Each of these is kept only where the sandbox shows the bill falling, every table the same:

- **The pricing model.** Each job is run on demand (bytes billed) and on capacity (slot time, `total_slot_ms`), and
  each job's cost is worked out under both. The jobs scan much and compute little a row, which is the case where
  slot time costs less.
- **Pruning for small batches.** An update's batch keys passed to the clustered key index as a parameter, as a
  lookup's are, where the batch is small enough to.
- **Search indexes** on `records.id`, `gold.id` and the key index's `key`, for the lookups.
- **Storage.** Physical (compressed) storage billing, with two days of time travel: each update adds to the key index
  and rewrites the fit's tables, and time travel keeps every version it replaces.
