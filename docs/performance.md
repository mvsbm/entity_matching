[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Blocking costs are explained in [chapter 3](guide/03-far-too-many-pairs.md).*

# Performance

## End to end: the cost of every step

**Notation:**

| Symbol | Meaning |
|---|---|
| N | records in the file |
| Δ | records in an increment's batch |
| n | records the model is fitted on (`fit_rows`, 30,000; fixed) |
| L | characters in a name or address |
| P_r, P_g | pairs inside rule r's or generator g's key blocks |
| b | records in one key block |
| C | candidate pairs, the union of all P_g; C_Δ, those touching the batch |
| K | comparisons in the model (6) |
| S | random pairs sampled for u on the file (10⁷; fixed), for each comparison not counted exactly; the fit's own sample, for EM, is 10⁶ |
| P_em | pairs in EM's blocks (equal phone, equal address) within the fitting sample |
| E | accepted pairs |
| d | diameter of the largest cluster: Splink's connected components take up to d rounds |
| F, D, T | folds (3), decision variants (5 for the rules, 23 for the model), Optuna trials |

**A full run** (`er.run.Run.full`, which `nayose resolve records` calls), with the times measured on 1,000,338 generated records by
`scripts/benchmark.py`, in a process of its own under an 8 GB DuckDB memory limit (peak 6.64 GB, Python included). The reader
reads the file before these steps, about 15 s a million records from CSV, 7 s from Parquet ([below](#reading-a-file-as-it-comes)):

| # | Step | Code | Cost | Grows like | At 1M |
|---|---|---|---|---|---|
| 1 | load: read in chunks, check the fields, standardize each chunk, and tell persons from companies | `Run.load`, `er.standardize.prepare`, `er.kind` | O(N·L) | N | 10.73 s |
| 2 | budget: every rule's and generator's pairs, exactly, before any join | `Run.budget`, `er.candidates.estimate` | O(N) per rule and generator, a group-by | N | 1.96 s |
| 3 | fit: λ, and m by EM, on a sample of whole postal areas (EM's own u from 10⁶ pairs); then u measured on this file: value counts for the leading exact levels, one-deletion keys for a one-edit level after them (so cif, phone and birth are counted exactly), S pairs for name, company and address | `Run.fit`, `er.match.train_fs`, `exact_u`, `scored_sample`, `assemble_u` | O(n + S·K + P_em·K) + O(N + S·K) | **constant**, plus N | 9.40 s |
| 4 | rules: one plain SQL join per rule (the first rule wins a pair), fuzzy checks on the joined pairs only, then the cascade's clusters | `Run.rules`, `er.match.rule_edges`, `er.cluster.merge` | O(N + Σ P_r·L²) + O(E·d + N) | N; ≤ 0.14 pairs per record per rule at 1M | 2.57 s |
| 5 | candidates: every generator as one SQL join or window, merged by bitmask, only pairs touching a record the rules left alone; oversized blocks checked on a sample scored with the file's u | `Run.candidates`, `er.candidates.candidates` | O(N·L + Σ P_g) | N; ≤ 1.75 pairs per record per key at 1M, 3 per sorted window | 6.53 s |
| 6 | score: every candidate, with the u the fit measured | `Run.score`, `er.match.score_fs` | O(C·K·L²) | C | 16.05 s |
| 7 | cluster: accept at the threshold, connected components with the rules' pairs (each rule cluster one node), gold | `Run.cluster`, `er.cluster.merge` | O(C + E·d + N) | N | 0.34 s |
| 7b | probe: a hash-stable draw of the records in each `[probe]` group, each paired with its group and scored: the matches no key lists ([below](#the-probe-the-matches-no-key-lists)) | `Run.probe`, `er.probe.missed` | O(N + P·K + L) | N; P about `[probe] pairs` a group | 3.52 s |
| 8 | write: gold, matches, the rules' pairs and the state for increments, as Parquet | `Run.write` | O(N + C) | N | 1.07 s |
| 9 | report: qa.md, report.txt and the review sheet, built before the write and landing with it | `Run.report` | O(review pairs) + O(N) | N | 0.78 s |
| | **total** | | | | **53.0 s** |

At a million records, scoring the candidates (16.05 s) and the fit (9.40 s) take nearly half the time. The fit costs
nearly the same at any size: it learns on n records, and its u sample of the file is S pairs for each of name, company
and address, whatever the file's size; cif, phone and birth are counted exactly, in O(N). The score grows with the
candidates.

**An increment** (`Run.increment`, `nayose add records`): a batch of Δ new records joins a written run.

| Step | Cost | What it touches |
|---|---|---|
| load | O(Δ·L), plus one O(N) copy | the batch; a record already in the run is set aside. The stored records and the batch then form one table, which every later step reads |
| fit | O(N) + O(S·K_stale) | the stored model, with u settled before the rules: the exact and one-edit u counted again on all the records (group-bys, and the distinct values' one-deletion keys); a comparison's sampled u measured again only once the drift of its exact u exceeds its sampling error (`er.match.refreshed_u`) |
| rules | O(Δ·Σ b) + a scan of the stored records | each rule joins the batch against all records; the cascade merges into the stored clusters, each cluster one node |
| candidates | O(Δ·Σ b) + a scan | every generator, with the batch as the query; deletion keys and the budget only for the blocks the batch's keys reach |
| score | O(C_Δ·K·L²) | only the pairs touching the batch |
| cluster | O(C_Δ + touched clusters) | the stored clusters, with the new pairs merged in |
| write | O(Δ + C_Δ) appended, O(N) rewritten | new Parquet parts for records, rule pairs and matches; gold and the rules' clusters rewritten. Every file is staged under a temporary name and renamed into place only once all are complete, so an interrupted increment leaves the run as it was, or is finished by the next one |

So a full run costs **O(N·L + Σ P + C·K·L² + E·d)**, plus the fit and the u sample, whose sizes are fixed. It
is linear in N when every key's pairs per record stay flat as the file grows, which `budget` checks exactly on each
file and `scale_check` projects to `budget.target_rows` while choosing (below). An increment costs
**O(Δ·(L + Σ b) + C_Δ·K·L²)**, plus sequential scans and rewrites of the stored columns, the exact u counts, and a u
sample only for a comparison that has drifted. Its expensive work grows with the batch, not with the file. A full run
re-fits the model.

**People's decisions** (`Run.decide`, `nayose apply decisions`) cost **O(D + touched clusters)** for D
decisions, plus O(N) to rewrite gold: each `match` pair merges two stored clusters, each one node, and nothing is scored.

**Measured:** into the million-record run, an increment of 1,000 records takes about 4 s, with a peak of 2.25 GB.

**A lookup** (`index.look_up`, `nayose match record`): one record against the run's index costs
**O(G·(log N + b) + C·K·L²)**, N only inside log N: each of its keys reads a few row groups of its table, sorted by the
key's hash, and a sorted window's place is a bisect in every 1,024th key. **A search** (`index.search`, `nayose search
records`) costs **O(F·(log N + 2,000) + 500·K·L²)**: each value given read by its start from its column's sorted table,
at most 2,000 records listed and 500 scored. Building the index (`index.build`, `nayose build index`) costs
**O(N·(G + R + D·L + F) + N log N)**: every key and searched value of every record, sorted, read from the run's own
files. Keeping it up to date after an increment, decisions or merging conditions (`index.update`) costs
**O(Δ·(G + R + D·L + F) + N)** for Δ records added, the N one pass over two columns for the entities that moved.
**Measured** on a million generated records ([reports/benchmark_lookup.md](../reports/benchmark_lookup.md)): built in
about 7 s, 0.85 GB on disk; with the index kept open, a lookup at p50 about 100 ms and p95 about 125 ms, a search at p50
about 70 ms and p95 about 115 ms; 1,000 records added, the index up to date in 0.3 s, against 7 s to build it again. The
pairs and weights equal to an increment of that record alone on every record checked, and the index kept up to date
answering every lookup and search as one built again.

**Memory.** Records, pairs, scores and clusters are DuckDB tables. Past `memory_limit` (config/settings.toml `[compute]`,
or `--compute memory_limit=8GB` on a command), DuckDB spills them to `temp_directory`: by default a folder of the
person's own, readable only by them, in the system's temporary folder. The budget counts the room DuckDB may spill to: 90% of that disk's free space, DuckDB's
own cap (`max_temp_directory_size`). Python holds one chunk of `load` (200,000 records), the fitting sample (n records)
and small summaries. DuckDB keeps in memory what fits under its limit and spills the rest, so the 6.64 GB peak at a
million records shows what it chose to keep under 8 GB. The deletion-key tables hold only the IDs and the key columns.

## The cost checks before a run

| Check | When | Cost | What it stops |
|---|---|---|---|
| `budget` | every run, on the actual file | O(N) per rule and generator | only a run whose normal blocks would not fit in memory and the room DuckDB may spill to. Oversized blocks (64+ records) are checked on a sample instead: at most `sample_pairs` scored pairs each, never more than joining them would cost |
| `scale_check` | `scripts/choose.py`, on train | O(N) per key | a key whose pairs, projected to `target_rows`, exceed `max_pairs_per_record` × N: the guard against keys that grow by many normal blocks, which the sample check doesn't catch |
| `window_only` | `scripts/choose.py`, on train | O(N + P + P_true·K), P_true true pairs, plus two u samples | a true pair that could reach the threshold but shares no key, at train's size or at `target_rows` |
| `pattern_coverage` | `scripts/choose.py` and every run's QA report | O(Π levels), a few thousand patterns | reported, not stopped: patterns that can reach the threshold with no guaranteed key |

`scale_check` splits a key's pairs P on train into T pairs of one entity and C chance pairs between entities. A
bigger population of the same kind has proportionally more duplicated entities, so T grows like N, and two entities
share a value with the same probability at any size, so C grows like N²: P(n) = T·n/N + C·n(n − 1)/(N(N − 1)). That is
the expectation of keeping a share of the entities, computed instead of sampled. Pairs between members of one
household count as chance, the safe side ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).

## Choosing the configuration

`scripts/choose.py`, once, on the labelled synthetic train and val (Optuna off):

| Step | Cost |
|---|---|
| rules: design analyses, A/B, decisions, cost, evaluation, output | O(D · run) on train and val |
| candidates on train: every generator's reach | O(N·L + Σ P_g) |
| training: EM against labels | O(n + S·K + P_em·K), twice |
| threshold rule on out-of-fold scores | O(F · (fit + run on n/F records)) |
| A/B on val | O(variants · run) |
| decisions | O(D · (F + 1) · run) |
| will it scale: `scale_check`, `window_only`, `pattern_coverage` | O(N) per key + O(N + P + P_true·K) + O(Π levels) |
| output: train, val and test through the chosen pipeline | O(3 · run) |
| gold: train, val and test resolved by `er.run` into `data/medallion/gold/<dataset>/` | O(3 · full run), with train's model |
| Optuna (off by default) | O(T · F · run) |

`reports/choose.md` times some of it: the training, 7.5 s by EM and 0.3 s from labels; the threshold rule's 3-fold
cross-validation, 27.5 s; and `FINAL` on each dataset, 2.0 s on train, 0.9 s on val, 6.7 s on test. u is sampled
once per set of records and comparison (each fold, val, train, test, and the coverage check's two samples), and only
for the comparisons not counted exactly. `notebooks/demo.ipynb` runs every step of a full run and an increment on
3,758 records; `scripts/export_pdfs.py` prints it as a PDF.

`scripts/choose_kind.py` chooses how persons and companies are told apart: 768 combinations on 12 generated scenarios
of 20,000 customers each, by successive halving. `reports/choose_kind.md` times the search: 125 s for every combination
on 3 scenarios, 49 s for the best quarter on 6, 55 s for the best quarter of those on 12. Each scenario's name models are
trained once and its signals computed once; a combination fits only its combiner, on 1,000 records.

**Work the code skips** (identical results, covered by tests/):
- **Names scored in DuckDB** (`er.kind.NameModel.logit`): every name's distinct character n-grams in one query,
  joined to the model's weights and summed in term order, so every run gives the same bits. The same sums as
  scikit-learn's vectorizer, which builds the n-grams one name at a time in Python.
- **One u sample per set of records** (`er.match.scored_sample`, `SCORED_U`). A comparison's u depends only on
  itself, the sample size, the seed (`FSModel.u_keys`) and the values it reads, since Splink picks the sampled pairs by
  a hash of the record ID. So the cache is keyed by the comparison and a fingerprint of those values, a frame and a
  table with the same rows alike: within one process, a model's variants and `choose.py`'s repeats of train share one
  sample. The cache lives in the process: two runs of `nayose` each draw their own. cif, phone and birth need none: their levels are counted (`exact_u`, once per fit).
- **Rules in plain SQL** (`er.match.rule_edges`): one equi-join per rule, for `choose.py`, full runs and increments
  alike. A fuzzy condition lets equal values through without calling the string function. Splink's
  `deterministic_link` would join every column of both records back first.
- **Deletion keys unnested once** per candidates call (`Records.variants`), into a table that the count, the join and
  the oversized blocks' sample all read. A full run joins it in one pass; an increment keeps only the blocks its batch
  reaches.
- **Clusters merged, not rebuilt** (`er.cluster.merge`). A full run merges its pairs into the rule clusters as an increment
  does, each cluster one node, so connected components run over the clusters the pairs touch, not over every record.
- **An increment's records in one table**: the stored parts and the batch are read once, into `records`, which every
  later step reads.
- **String functions on one thread per DuckDB call** (`er.strings.udf`). DuckDB already calls them on all its threads,
  so a thread pool per call costs more than it saves: the rules call Damerau–Levenshtein about 20 values at a time, and
  on a million records a pool per call made the rules take 15 s instead of 4 s. Running the functions in worker
  processes instead was slower (the fit 21 s instead of 12 s): a value takes 0.2 to 1 µs to compare, and passing a batch
  to another process costs more than that.
- **A comparison told its threshold** (`cl_<function>_cut`). Every condition asks whether a pair is within a threshold
  (a Jaro–Winkler of 0.9 or more, an edit distance of 2 or less), so the function is given it and stops once the answer
  is known (rapidfuzz's `score_cutoff`): the same pairs pass and fail, with the same score where they pass, and an edit
  distance on long values is no longer worked out in full. On addresses of about 150 characters, the fit's 10 million
  sampled pairs take a third of the time.
- **A linker reads only the columns it compares** (`match.narrowed`, `match.read_by`). Splink carries every column of its
  input through its joins, two copies per pair; a wide file's other columns (80 of them, long text) made scoring a
  million records 428 s instead of 63 s. Each linker gets the ID and the columns its levels, blocking rules and term
  frequencies read; one it reads and lacks still fails loudly. The fit's sample is read the same way.
- **An edit distance tested on the lengths first.** A Levenshtein, Damerau–Levenshtein or Hamming distance is never
  less than the lengths' difference, so `abs(length(a) - length(b)) <= t` goes before the Python call: the same pairs
  pass, and on long values most pairs never reach Python.
- **The oversized blocks' samples scored a slice at a time, in DuckDB** (`Run._gate`, `Run._scored`), not all at once
  through pandas: thousands of placeholder blocks no longer need their every sampled pair compared in one call.
- **A rule's untrusted values tested before its join** (in WHERE, not ON): a placeholder's block is no longer joined
  and compared in full before it is left out.
- **Each candidate pair listed once**: a key's join over the query keeps one order of a pair of two queried records
  instead of both and a DISTINCT; the union's parts are freed as soon as it is made.
- **Scoring in slices** (`Run.score_pairs`, a million pairs at a time). A pair's score depends on it alone, so the slices
  score as the whole would; each slice says how far scoring is (pairs scored, and those at the model's line so far), and
  the step's peak memory is one slice's, not every pair's. Each slice costs about 0.3 s of setting up.
- **Threshold rule without clustering** (`accept_curve`). The rule reads only accepted and false accepted pairs per
  weight, so decision variants resolve clusters at the chosen weight only.
- **Run cache.** Identical runs (same configuration, dataset and threshold) are computed once, in both stages.
- **Merged lists by bitmask.** A pair's generators are one bit each, combined with `bit_or` in SQL, then named once
  per combination ([lessons.md](lessons.md#linear-work-done-one-pair-at-a-time-in-python)).

**Rejected by the rule, because they change results:** u from 10⁶ pairs instead of 10⁷ for the scores
(`u_from_1e6_pairs`) would make u-sampling about 6× cheaper, but loses true pairs: cross-validated train +1 / −8
(p = 0.0391), val −1. The fit's own sample, which feeds only EM, does use 10⁶ pairs (`fit_u_from_1e6_pairs`): no pair
moves on train or val. Dropping the three sorted windows (`no_sorted_windows`) would remove 9 pairs per record at a
million records, 3 per window, but loses 1 true pair on val.

## Files of growing size

`scripts/benchmark.py`: each generated file resolved by `nayose resolve records` in a process of its own, the model fitted
on the file itself, without labels ([reports/benchmark.md](../reports/benchmark.md)):

| Records | Seconds | Peak memory | fit | score | everything else |
|---|---|---|---|---|---|
| 12,532 | 8.9 | 0.96 GB | 7.26 | 0.26 | 1.38 |
| 24,955 | 10.7 | 1.08 GB | 7.81 | 0.38 | 2.51 |
| 50,116 | 13.1 | 1.44 GB | 7.85 | 0.76 | 4.49 |
| 74,959 | 15.4 | 1.66 GB | 8.03 | 1.16 | 6.21 |
| 1,000,338 | 53.0 | 6.64 GB | 9.40 | 16.05 | 27.55 |

Over these sizes, time grows like N^0.42. `fit` costs nearly the same at every size, 7.26 s at 12,532 records and 9.40 s
at a million: it learns on 30,000 records, its u sample of the file is 10⁷ pairs for each of name, company and address
whatever the file's size, and cif, phone and birth are counted exactly. So it is nearly all of a small file's time.
Everything else goes from 6.21 s at 74,959 records to 27.55 s at a million: 13 times the records, 4.4 times the time,
since the probe scores about `[probe] pairs` in each group once a group has that many, as the postal area does
already at 74,959 records (3.04 s there, 3.52 s at a million). Scoring the candidates, `score`, grows from 1.16 s to 16.05 s, the largest
step at a million records.

## Reading a file as it comes

`scripts/benchmark_intake.py`: the reader (`er.intake`, before every run) on a generated file of 1,000,338 records × 25
columns written as CSV, clean and damaged ([reports/benchmark_intake.md](../reports/benchmark_intake.md)):

| File | Seconds | Read back | Changed, never damaged |
|---|---|---|---|
| clean UTF-8 CSV | 14.8 | every value | 0 |
| damaged CSV, every proposal accepted | 26.8 | each kind of damage: 100.0% of its values | 0 |

The damaged file holds values in CP932 (10% of rows) and EUC-JP (2%), zero-width characters and NULs, placeholders,
spreadsheet numbers, names garbled upstream and unquoted commas inside addresses. Most values take the fast path: ASCII
as it is, UTF-8 that reads as Japanese text decoded once; only the others are tried in every encoding and judged, so a
damaged file costs about twice a clean one. A Parquet file is read by column: the first chunk learns each column from
its values one by one (a text column's first 50,000; past them, UTF-8 values tell nothing), then each chunk's values
that reading keeps as they are are settled in Arrow, the rest read one by one as in a CSV; the same file, byte for
byte, in about half the time (7.1 s against 14.8 s on the million records as Parquet).

## The probe: the matches no key lists

At the end of a full run, `Run.probe` scores about `[probe] pairs` (a million) pairs in each of its groups, drawn at
random among the pairs that share a phone or a postal area. On a million records it scored 989,900 of the 50,094,600
pairs that share a phone and 1,026,781 of the 894,794,914 that share a postal area, in 3.5 s for both: 7% of the run.
