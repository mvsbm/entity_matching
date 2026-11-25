[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Blocking costs are explained in [chapter 3](guide/03-far-too-many-pairs.md).*

# Performance

What a run costs, and how each figure is measured. BigQuery bills in one of two ways: on-demand bills the bytes a query reads, and capacity bills the slot time it uses. Locally, the cost is wall clock.

## Notation

| Symbol | Meaning |
|---|---|
| N | the run's records |
| Δ | the records in a batch (a build: Δ = N) |
| n | the records the model is fitted on (`[fit] fit_records`, 100,000; fixed) |
| S | the pairs u is sampled on (`u_max_pairs`, about 10⁷ on the file; `fit_u_max_pairs`, 10⁶ on the sample) |
| L | the characters in a name or an address |
| K | the comparisons in the model (6) |
| b | the records in one key block |
| G | the keys a record has (one a generator, and L + 1 a deletion generator: 22 generators, 4 of them deletion ones) |
| ΣP | the pairs inside every generator's blocks, before they are deduplicated |
| C, C_Δ | the candidate pairs; those touching the batch |
| P_em | the pairs in EM's blocks (equal phone, equal address) within the sample |
| D | people's decisions |
| P, F | the pairs a match table holds; the fields it shows of each record |

## End to end: the cost of every step

| Job or stage | SQL | Grows like | Why |
|---|---|---|---|
| records | `records.sql` | O(Δ·L) + O(N) | each record of the batch is read and standardized; placeholders are counted over the whole run |
| fit (a build) | `fit.sql`, `em.py` | O(n + P_em·K) + O(N + S·K) | EM learns on a fixed sample. u is counted exactly for the equality and one-edit levels (by value counts, never pair by pair) and sampled for the rest |
| score | `score.sql` | O(Δ·L + N·L) + O(Δ·b + C_Δ·K·L²) | the batch's keys, and those of the records made again, join the key index; the index is scanned for the blocks the batch's keys name; then those blocks are joined and their pairs compared |
| decide | `decide.sql` | O(D + N) | connected components over the match decisions; then every record placed |
| match | `match.sql` | O(C + P·F) | a scan of the scored pairs; those kept are joined to their records |
| lookup | `lookup.sql` | O(G) + O(G·b + C·K·L²) | the record's keys made alone; the key index read by them; the record scored against its blocks' records alone |
| report | `report.sql` | O(N·F) + O(C) | each field's fill; the batch's pairs by band |

A build is O(N·L + n + S·K + ΣP + C·K·L²): linear in N while each generator's pairs per record stay flat as the file grows (report.txt's BLOCKS shows them). An update's expensive work grows with its batch. Its O(N) part is scans: the run's records for the placeholders, and the key index for the blocks its keys name.

## Measuring BigQuery's cost on DuckDB

`python scripts/estimate_cost.py FILE [FILE …]` builds each file on DuckDB, then runs a match at `keep_from`, recording every statement's plan:

```
billed   = Σ over statements, Σ over the tables t each scans: max(10 MB, Σ over the columns c it reads of t: bytes(c))
bytes(c) = Σ over t's rows: 2 + its UTF-8 length (a string), 8 (a number), 1 (a boolean), 0 (NULL)
dollars  = billed / 2⁴⁰ × p                p = $6.25 per TiB (PRICE_PER_TIB: the US multi-region list price)
rows     = Σ over statements: every plan operator's rows out   (DuckDB's total_intermediate_rows)
calls    = Σ over statements: JavaScript calls, every cl_* but cl_levenshtein (counted in the twins, row by row)
x(10⁹)   = x₂ · (10⁹ / n₂)^b, per statement, summed per stage  b = ln(x₂ / x₁) / ln(n₂ / n₁), from the two largest files
```

- **Bytes billed:** each scan's table and columns (its projections and filters) come from DuckDB's plan. A `WHERE` or a `LIMIT` cuts nothing, as on BigQuery, and an `UPDATE` bills every column of its table.
- **Slot work:** BigQuery's slot time is not measured here. Rows and calls stand in for it, reported apart: each call is a JavaScript call on BigQuery, the costliest work per row. `cl_levenshtein` is BigQuery's own `EDIT_DISTANCE`, so it isn't counted.
- **Too low where:** a scan that DuckDB proves empty from its statistics is never planned, so it isn't counted; BigQuery would bill it at least 10 MB. DuckDB's plans are not BigQuery's.

## A build at a million records

Billed, rows and calls: `scripts/estimate_cost.py` on 1M generated records. Wall clock: `scripts/benchmark.py`'s build of 1,039,995 generated records on a 10-thread laptop, an 8 GB memory limit.

| Stage | Billed | Rows | JavaScript calls | Wall clock |
|---|---|---|---|---|
| records | 2,144 MB | 302M | 0 | 9.4 s |
| fit | 1,167 MB | 517M | 0.41M | 5.5 s |
| score | 4,684 MB | 640M | 1.11M | 9.0 s |
| decide (the build's) | 161 MB | 15M | 0 | 0.18 s |
| **build** | **8,156 MB** | **1,474M** | **1.52M** | **24.1 s** |
| match at `keep_from` | 199 MB | 4.1M | 205k | 0.6 s, as its own job |

```
dollars(build) = 8,156 × 10⁶ B / 2⁴⁰ × $6.25 = 0.0074 TiB × $6.25 ≈ $0.05
dollars(match) =    199 × 10⁶ B / 2⁴⁰ × $6.25 = 0.0002 TiB × $6.25 ≈ $0.001
```

These use the US list price; the region's price differs (`asia-northeast1` is the Terraform default). Score bills over half of the build's bytes. For each stage, the estimator lists the five costliest statements, by their shares of bytes, rows and calls together.

- **At 1B records** (each statement's a·N^b, b from 200k and 1M): records 1.2 TiB, fit 0.3 TiB, decide and match under 0.1 TiB. Score's projection, 5,487 TiB, is no estimate: a phone generator's blocks grow with the square of the file only until the gate caps them at 64 records, which no power law fitted between 200k and 1M sees.
- **On BigQuery itself:** not measured yet: it needs the sandbox dataset

## An update, a decision, a lookup

| Job | Records | Wall clock |
|---|---|---|
| update | a batch of 10,161 onto 189,839 | 4.3 s |
| decide, as its own job | a run of 1M | 0.6 s |
| lookup, as its own job | 200k | 1.2 s |

A lookup reads the key index by its keys, and the records it touches by ID. Of an oversized block it reads the gate's sample alone (65 records), so it reads at most about 65 records a block key whatever the run's size (a rule key's records it reads whole): at 1M, 69 at the median and 160 at p99; at 1B, without the sample, a lookup would read whole blocks of thousands. 1.3 s at 1,039,995 records as a job of its own, the run read in place, read-only. On BigQuery, 48 statements for a stored record and 78 for typed values: Python's statements call the functions the deploy made, never making them again. Each is billed at least 10 MB a table it reads: about 0.4 GB, whatever the run's size, plus the index's blocks its keys fall in (`scripts/estimate_cost.py` can't tell those from the whole index, 1.7 GB at 1M). `scripts/estimate_cost.py` doesn't measure an update's bytes.

## Memory and disk

The run's tables are DuckDB's. Past `memory_limit` (`--compute memory_limit=8GB`), DuckDB spills to `temp_directory`. Python holds only small results: the fit's counts, the model and report.txt's numbers. Peak memory and `run.duckdb`'s size at 1M: 6.4 GB and 1.14 GB at 1,039,995 records, 0.75 GB of it the key index (`every_key`, `rule_keys`: 43.5M rows; about 1.7 TB at 1B in BigQuery's bytes). For files of growing size, `scripts/benchmark.py` builds each one in a process of its own and writes `reports/benchmark.md`: [reports/benchmark.md](../reports/benchmark.md): a build grows like N^0.35 between 13,019 and 1,039,995 records, 5.1 s to 24.1 s, 1.29 GB to 6.4 GB at peak. A small file's build is mostly the fit's u sample, about ten million pairs at any size.

## Each generator's worth

`python scripts/generator_quality.py RUN [--truth TRUTH.parquet] [--points 6]` counts, for each generator of a build's run,
the pairs its keys list (candidates), the matches among them (6 points or more with a name compared, or a rule's), and
the matches it alone finds, which no other generator or rule does. It then names the generators that can go together
losing no match, and what they cost: their index rows and the candidates only they list. Counts alone, so a run on real
records can be read anywhere. On 1M generated records, 9 of the 22 generators can go together: 19% of `every_key`'s
rows and 25% of the candidates.

## What keeps the cost down

Every speed-up keeps every table the same: `tests/test_parity.py` holds each job's tables to recorded digests (`tests/fixtures/`).

- **A fitting sample of fixed size:** whole postal areas by hash, so households stay together, and the fit's cost doesn't grow with the file.
- **u counted, not sampled, where it can be:** equality and one edit come from how many records hold each value, never from listing pairs, and a sample would miss an agreement rarer than one pair in a billion.
- **Only the columns compared are read:** fit and score read records through `fit.sql`'s view `compared`, so only those columns are billed.
- **Oversized blocks checked first:** a block of `oversized` (64) records or more is listed only if a sample of its pairs holds one at `search_floor` or more. A rule leaves out a value held that often.
- **Placeholders read as missing,** so a dummy phone's block never forms.
- **A bound before the comparisons:** a pair is compared in full only if the most points its equalities allow reach `keep_from`; every rule pair is compared whatever its bound.
- **Cheap tests before a comparison call:** an edit distance is never less than the two lengths' difference, nor less than the distance between the values' `one_byte_hash` copies. A Jaro–Winkler is never more than the lengths and the common start allow (`jaro_winkler_most`), nor, for two katakana names, more than the letters both hold allow (`name_jw_most`, from each record's letter bits). Those are tested first, so many pairs never reach the JavaScript (or, on DuckDB, rapidfuzz).
- **On DuckDB, its own functions** where both strings are one byte per character, and a comparison told its threshold stops once the answer is known (`cl_*_cut`). BigQuery computes it in full.
- **Each distinct name scored once** by the name model, however many records share it.
- **A row a function reads comes from a narrow table:** `compared`, or a match's own columns. BigQuery may bill a row passed whole as every column of its table (`records` has 37), so `tests/test_sql.py` refuses a row of `records` passed to a function.
- **An update touches its batch:** only the pairs touching it are scored, with the model the build left (the fit doesn't run), and a batch that brings no new placeholder reads no record to make again: a 1% update at 1M bills about 3,460 MB, makes 35,584 comparison calls and takes 3.4 s on DuckDB. A statement an update needn't run says so (`-- when:`), and isn't run, since BigQuery bills a statement's scans whatever it returns.
