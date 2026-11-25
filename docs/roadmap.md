[← README](../README.md) · [Architecture](architecture.md)

# Roadmap

This page lists the plans, in order. The other docs describe the code as it is. Each step keeps the results
identical, so `tests/test_parity.py`'s digests stay unchanged. Each step also quotes BigQuery's cost before and after,
in both bytes billed and work, from `scripts/estimate_cost.py`.

## 1 · BigQuery at scale, in staging

Every job has run on a BigQuery sandbox (`deploy/bigquery_check.py`, [operations](operations.md#checking-on-a-bigquery-sandbox)):
each table it keeps, each lookup's answer and each function are the same as DuckDB's, and report.txt is read from
the job's temporary report_ tables after its procedure. A sandbox refuses DML and stores 10 GiB in its life, so
the rest waits for staging, where billing is on: DML as BigQuery runs it, and the scale rehearsal, 1M → 10M → 100M
generated records with time and bytes billed at each size, before the first real build. The same runs measure how
much of the key index a lookup's keys read.

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
