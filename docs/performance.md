[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Blocking costs are explained in [chapter 3](guide/03-far-too-many-pairs.md).*

# Performance

## End to end: the cost of every step

**Notation:**

| Symbol | Meaning |
|---|---|
| N | records in the file |
| Δ | records in an increment's batch |
| n | records the model is fitted on (`fit_rows`, 100,000; fixed) |
| L | characters in a name or address |
| P_r, P_g | pairs inside rule r's or generator g's key blocks |
| b | records in one key block |
| C | candidate pairs, the union of all P_g; C_Δ, those touching the batch |
| K | comparisons in the model (6) |
| S | random pairs sampled for u on the file (10⁷; fixed), for each comparison not counted exactly; the fit's own sample, for EM, is 10⁶ |
| P_em | pairs in EM's blocks (equal phone, equal address) within the fitting sample |
| E | the rules' pairs |

**A full run** (`jobs.build.build`, which `python -m er build` calls), with the times measured on 1,039,995 generated records by
`scripts/benchmark.py`, in a process of its own under an 8 GB DuckDB memory limit (peak 7.3 GB, Python included). The reader
reads the file before these steps, about 3.3 s a million records ([below](#reading-a-file-as-it-comes)); the lookup index is
built after them, 3.2 s ([below](#a-lookup)):

| # | Step | Code | Cost | Grows like | At 1M |
|---|---|---|---|---|---|
| 1 | load: read in chunks, check the fields, standardize the chunks in parallel processes, and tell persons from companies | `steps.load.load`, `er.standardize.prepare`, `er.kind` | O(N·L) | N | 5.30 s |
| 2 | budget: every rule's and generator's pairs, exactly, before any join | `steps.budget.budget`, `er.candidates.estimate` | O(N) per rule and generator, a group-by | N | 1.96 s |
| 3 | fit: λ, and m by EM, on a sample of whole postal areas (EM's own u from 10⁶ pairs); then u measured on this file: value counts for the leading exact levels, position, swap and deletion keys for a one-edit level after them (so cif, phone and birth are counted exactly), S pairs for name, company and address | `steps.fit.fit`, `er.match.train_fs`, `exact_u`, `scored_sample`, `assemble_u` | O(n + S·K + P_em·K) + O(N + S·K) | **constant**, plus N | 4.33 s |
| 4 | rules: one plain SQL join per rule (the first rule wins a pair), fuzzy checks on the joined pairs only | `steps.rules.rules`, `er.match.rule_edges` | O(N + Σ P_r·L²) | N; ≤ 0.14 pairs per record per rule at 1M | 2.11 s |
| 5 | candidates: every generator as one SQL join or window, keeping only the pairs that can reach 0 (step 6's bound) or a rule found, merged by bitmask; oversized blocks checked on a sample scored with the file's u | `steps.candidates.candidates`, `er.candidates.candidates` | O(N·L + Σ P_g) | N; ≤ 1.75 pairs per record per key at 1M | 10.74 s |
| 6 | score: every candidate that can reach 0 points, with the u the fit measured; a bound settles the rest below 0 unscored, as nothing reads them (below) | `steps.score.score`, `er.match.score_fs`, `bound_sql` | O(C·K_c + C₀·K·L²) | C | 0.25 s |
| 7 | cluster: gold, the entities people's decisions make: each record its own, connected components over the match pairs; nothing merges by itself | `steps.cluster.cluster`, `er.cluster.merge` | O(D + N), for D decisions | N | 0.14 s |
| 8 | write: gold, the rules' pairs, the scored pairs and the state for increments, as Parquet | `steps.write.write` | O(N + C) | N | 1.14 s |
| 9 | report: report.txt, built before the write and landing with it | `steps.report.report` | O(C + N) | N | 0.27 s |
| | **total** | | | | **26.2 s** |

**Pairs that can't reach 0 points.** Nothing reads a candidate's score below the floor: `scored/` keeps 0 points and up (or `[threshold] keep_from`), and a match run's threshold starts there. So a pair is scored only when its bound reaches the floor: the prior, each comparison whose tests are equality, Hamming or one edit at its own level, and each other at the best level the pair may land in (`bound_tests`): DuckDB settles each level's test where it can in C++, a name or a company name in katakana by Jaro–Winkler on its one-byte copy, and only a test it can't settle (text outside katakana and ASCII, an edit distance past one) counts as passing. 0 where its fields are missing. Each test is computed once: the outcomes index a table of the bounds they allow, since DuckDB computes an expression as often as it is written. A pair a rule found is scored whatever its bound. A full run's candidates step already leaves the rest out as its keys list them (below); an increment's are counted (`unscored`, one row "below 0" in report.txt's SCORES and the score chart) and never compared by name, company or address: on a file whose address and phone are mostly empty, that is nearly every candidate. Every score written is the same to the last bit. The gate on oversized blocks does the same at its own floor, the review floor. K_c is the comparisons settled first, C₀ the candidates whose bound reaches 0.

At a million records, the candidates (10.74 s) and the load (5.30 s) take more than half the time. The fit grows
far slower than the file: it learns on n records, and its u sample of the file is S pairs for each of name, company
and address, whatever the file's size; cif, phone and birth are counted exactly, in O(N). The score grows with the
candidates, and is small because the candidates step lists only the pairs that can reach 0.

**An increment** (`jobs.update.update`, `python -m er update`): a batch of Δ new records joins a written run.

| Step | Cost | What it touches |
|---|---|---|
| load | O(Δ·L), plus one O(N) copy | the batch; a record already in the run is set aside. The stored records and the batch then form one table, which every later step reads |
| fit | O(N) + O(S·K_stale) | the stored model, with u settled before the rules: the exact and one-edit u counted again on all the records (group-bys, and the distinct values' position, swap and deletion keys); a comparison's sampled u measured again only once the drift of its exact u exceeds its sampling error (`er.match.refreshed_u`) |
| rules | O(Δ·Σ b) + a scan of the stored records | each rule joins the batch against all records |
| candidates | O(Δ·Σ b) + a scan | every generator, with the batch as the query; deletion keys and the budget only for the blocks the batch's keys reach |
| score | O(C_Δ·K·L²) | only the pairs touching the batch |
| cluster | O(D + N) | the stored entities and each new record alone, joined by people's match decisions |
| write | O(Δ + C_Δ) appended, O(N) rewritten | new Parquet parts for records, rule pairs and scored pairs; gold rewritten. Every file is staged under a temporary name and renamed into place only once all are complete, so an interrupted increment leaves the run as it was, or is finished by the next one |
| index | O(Δ·(G + R + D·L) + N) | the lookup index brought up to date ([below](#a-lookup)) |

So a full run costs **O(N·L + Σ P + C·K·L² + E·log E + D)**, plus the fit and the u sample, whose sizes are fixed. It
is linear in N when every key's pairs per record stay flat as the file grows, which `budget` checks exactly on each
file; projected to a million records on labelled train, every key of the method stays under 5 pairs per record (below). An increment costs
**O(Δ·(L + Σ b) + C_Δ·K·L²)**, plus sequential scans and rewrites of the stored columns, the exact u counts, and a u
sample only for a comparison that has drifted. Its expensive work grows with the batch, not with the file. A full run
re-fits the model.

**A match run** (`jobs.match.match`, `python -m er match`) costs **O(C)** to read `scored/`, plus **O(P·F)** to join
the P pairs at the threshold to their records' F fields. Nothing is scored.

**People's decisions** (`jobs.decide.decide`, `python -m er decide`) cost **O(D + N)** for D decisions: the entities
made again from every pair's latest decision, from single records, and gold rewritten. Nothing is scored. The index is
then brought up to date, as after an increment.

**Measured:** an increment of 1,000 records into a run of 999,000 generated records (the parity runs' 1M file less
1,000 drawn at random), in a process of its own: 4.0 s of steps, 5.4 s wall clock, a peak of
4.19 GB under DuckDB's default memory limit.

**Memory.** Records, pairs, scores and clusters are DuckDB tables. Past `memory_limit` (config/settings.toml `[compute]`,
or `--compute memory_limit=8GB` on a job), DuckDB spills them to `temp_directory`: by default a folder of the
person's own, readable only by them, in the system's temporary folder. The budget counts the room DuckDB may spill to: 90% of that disk's free space, DuckDB's
own cap (`max_temp_directory_size`). Python holds one chunk of `load` (200,000 records), the fitting sample (n records)
and small summaries. DuckDB keeps in memory what fits under its limit and spills the rest, so the 7.1 GB peak at a
million records ([below](#files-of-growing-size)) shows what it chose to keep under 8 GB. The deletion-key tables hold only the IDs and the key columns.

### A lookup

`jobs.index.look_up`, `python -m er lookup`: one record against the run's index costs
**O(G·(log N + b) + C·K·L²)**, N only inside log N: each of its keys reads a few row groups of its table, sorted by the
key's hash. Building the index (`jobs.index.build`, the last step of `build`) costs
**O(N·(G + R + D·L) + N log N)**: every key of every record, sorted, read from the run's own
files. Keeping it up to date after an increment or decisions (`jobs.index.update`) costs
**O(Δ·(G + R + D·L) + N)** for Δ records added, the N one pass over two columns for the entities that moved.
**Measured** at design time on 1,039,995 generated records: built in
3.2 s, 840 MB on disk; with the index kept open, a lookup at p50 83 ms, p95 91 ms and at most 197 ms; 1,000 records added, the index up to date in 0.2 s, against 3.1 s to build it again. The
pairs and weights equal to an increment of that record alone on every record checked, and the index kept up to date
answering every lookup as one built again.

## The cost checks before a run

| Check | When | Cost | What it stops |
|---|---|---|---|
| `budget` | every run, on the actual file | O(N) per rule and generator | only a run whose normal blocks would not fit in memory and the room DuckDB may spill to. Oversized blocks (64+ records) are checked on a sample instead: at most `sample_pairs` scored pairs each, never more than joining them would cost |
| `pattern_coverage` | every run, in report.txt (PATTERNS WITHOUT A KEY) | O(Π levels), a few thousand patterns | reported, not stopped: patterns that can reach the threshold with no guaranteed key |

The keys themselves are chosen on labelled train to stay under 5 pairs per record projected to a million
records: the guard against keys that grow by many normal blocks, which the sample check doesn't catch. A key's pairs P on train split into T pairs of one entity and C chance pairs between entities. A
bigger population of the same kind has proportionally more duplicated entities, so T grows like N, and two entities
share a value with the same probability at any size, so C grows like N²: P(n) = T·n/N + C·n(n − 1)/(N(N − 1)). That is
the expectation of keeping a share of the entities, computed instead of sampled. Pairs between members of one
household count as chance, the safe side ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).

## Work the code skips

Identical results, covered by tests/:
- **Names scored in DuckDB** (`er.kind.NameModel.logit`): every distinct name's character n-grams in one query, once
  however often the name repeats, joined to the model's weights and summed in term order, so every run gives the same
  bits. The same sums as scikit-learn's vectorizer, which builds the n-grams one name at a time in Python.
- **Each distinct value prepared once** (`er.standardize.normalize`): every step reads one value alone, so a column's
  distinct values go through the steps and the column is made of them; 25 to 40 times faster on a column that repeats
  (phones, postal codes, common names), and done value by value where most values are distinct.
- **The u sample counted in one pass** (`er.match.sample_u`). The records and pairs are drawn as Splink draws them (a
  hash of the ID and the seed: the portable one, `config.hashed`), and every comparison's levels are counted in one pass
  over the pairs, where Splink's estimate joins them again for each comparison, chunk by chunk: on the same pairs, the
  same counts, so the same u to the last bit. The
  pairs are written first as row numbers, 16 bytes a pair (160 MB for 10 million): the drawn records fill one row
  group, and DuckDB would compare pairs read from it on one thread. Streamed into the counts, the compared values
  never sit in memory. The fit's two samples of 250,000 records, 11.2 s to 3.5 s with the edit distances below.
- **Scores in one query** (`er.match.predict_sql`). Splink 5.0's predict SQL as Splink writes it: each level's condition
  in order, its weight the same `float8` literal, summed in the same order, so the same scores to the last bit (tests
  compare them with the scores recorded from Splink 5.0), without the two copies of the records Splink makes first and
  its SQL built per call. Scoring 250,000 records 4.8 s to 2.6 s.
- **Rules in plain SQL** (`er.match.rule_edges`): one equi-join per rule, for full runs and increments
  alike. A fuzzy condition lets equal values through without calling the string function. Splink's
  `deterministic_link` would join every column of both records back first.
- **Deletion keys unnested once** per candidates call (`Records.variants`), into a table that the count, the join and
  the oversized blocks' sample all read. A full run joins it in one pass; an increment keeps only the blocks its batch
  reaches.
- **Clusters merged, not rebuilt** (`er.cluster.merge`). The rules' stages merge their pairs into the clusters before
  them, and an increment into the stored ones, each cluster one node, so connected components run over the clusters the
  pairs touch, not over every record.
- **An increment's records in one table**: the stored parts and the batch are read once, into `records`, which every
  later step reads.
- **String functions on one thread per DuckDB call** (`er/engine/duckdb.py`, its `udf`). DuckDB already calls them on all its threads,
  so a thread pool per call costs more than it saves: the rules call Damerau–Levenshtein about 20 values at a time, and
  on a million records a pool per call made the rules take 15 s instead of 4 s. Running the functions in worker
  processes instead was slower (the fit 21 s instead of 12 s): a value takes 0.2 to 1 µs to compare, and passing a batch
  to another process costs more than that.
- **A comparison told its threshold** (`cl_<function>_cut`). Every condition asks whether a pair is within a threshold
  (a Jaro–Winkler of 0.9 or more, an edit distance of 2 or less), so the function is given it and stops once the answer
  is known (rapidfuzz's `score_cutoff`): the same pairs pass and fail, with the same score where they pass, and an edit
  distance on long values is not worked out in full. On addresses of about 150 characters, the fit's 10 million
  sampled pairs take a third of the time.
- **A model reads only the columns it compares** (`match.narrowed`, `match.read_by`). Every column carried through
  the scoring joins is copied twice per pair; a wide file's other columns (80 of them, long text) made scoring a
  million records 428 s instead of 63 s. Scoring gets the ID and the columns its levels and blocking rules read; one it
  reads and lacks still fails loudly. The fit's sample is read the same way.
- **An edit distance tested on the lengths first.** A Levenshtein, Damerau–Levenshtein or Hamming distance is never
  less than the lengths' difference, so `abs(length(a) - length(b)) <= t` goes before the Python call: the same pairs
  pass, and on long values most pairs never reach Python.
- **Edit distances in DuckDB** (`er.config.Comparator.test`). On ASCII values DuckDB's Levenshtein and
  Damerau–Levenshtein are rapidfuzz's (both unrestricted; tests compare them). Other text gets a copy at load with each
  character one ASCII byte by its code point (`one_byte_hash`); two characters may share a byte but never the reverse,
  so the copies are never farther apart than the values, and a pair past the threshold there can't pass. Python
  checks only the pairs left: of 10 million sampled address pairs, 36,645 instead of 2.3 million. Records
  prepared without the copy are bounded by the bytes instead: one character edited is at most 4 bytes edited.
- **The oversized blocks' samples scored a slice at a time, in DuckDB** (`steps.candidates._Gate`), not all at once
  through pandas: thousands of placeholder blocks never need their every sampled pair compared in one call.
- **A rule's untrusted values tested before its join** (in WHERE, not ON): a placeholder's block is left out before
  it is joined and compared in full.
- **Each candidate pair listed once**: a key's join over the query keeps one order of a pair of two queried records
  instead of both and a DISTINCT; the union's parts are freed as soon as it is made.
- **Scoring in slices** (`steps.score.SCORE_PAIRS`, 5 million pairs at a time). A pair's score depends on it alone, so the
  slices score as the whole would, and a slice bounds the step's memory. Each slice joins every record again, about 0.75 s at a million records: 9.3
  million pairs in slices of a million took 13.8 s, in slices of 5 million 8.8 s, for 0.2 GB more at the peak.
- **Chunks standardized in parallel** (`steps.load.load`, `steps.load.ahead`). Every step reads one record, or one chunk's
  values, so the chunks are cleaned in worker processes, spawned on every system (as many as DuckDB's threads, at most
  one per chunk, the CPUs, and 61 on Windows), one chunk queued beyond them, and taken back in order: the same records;
  an error in one cancels those not started. Each chunk is sent with the cleaning settings, and the person/company model
  is rebuilt from its terms and weights in the worker, on one thread. A script that
  runs a load keeps its work under `if __name__ == "__main__":`, as the scripts here do: each worker imports it first.
- **Pairs that can't reach 0 never stored** (`steps.candidates.reaching`, `er.match.reaching_sql`). Each generator's pairs pass
  step 6's bound as they are listed, 10 million at a time, before they are stored; generators that list fewer wait
  and pass it together (`er.candidates._bound`), since the bound reads a pair alone and each pass joins the records
  again: on 500,000 generated records the candidates step 4.4 s to 3.1 s, an increment of 100,000 into 400,000 4.3 s
  to 3.1 s. First a rough test on a hash of each column (`rough_sql`): it reads only whether values are missing or
  equal, each comparison at the best weight that leaves, so it costs a few integers a pair and never drops a pair the
  bound keeps: on those records with 85% of addresses and 70% of phones blanked and customer IDs in sequence (59
  million pairs listed by `cif_deletions`), with the pass above, the candidates step 25.5 s to 17.9 s. Then a looser test on a few
  columns (the cheap comparisons and the name, the others at their best level or 0, `first_bound`), then the whole
  bound on the few left. Score scores the same pairs. Each listed pair leaves a 60-bit hash first (`config.hashed`), 8 bytes, so the
  gate reads the pairs other keys listed as it would every pair, and the counts mean what they did: `candidates` the
  distinct pairs listed (`stored`, those kept), each generator's pairs as listed, `unscored` those below 0. On a
  generated file of 1.3 million records with sparse addresses and sequential customer IDs, 112 million candidates
  were 33,700 stored and the step 61 s instead of 593 s. Larger passes spill: 33 million pairs through the joins took
  ten times what 10 million did. With `reaching_only` off, `jobs.build.build` stores every pair, so design time's metrics of the keys count
  them all.
- **A key's oversized blocks left out before its join**, on both sides, not from its pairs after.
- **Records read as Parquet only** (`er.intake`): every column read as text, by column in Arrow, with no delimiter,
  quoting or encoding to work out. On the parity runs' generated 1,000,000-record Parquet file, the reader 3.81 s to
  3.25 s (the median of three runs), the file it reads the same to the byte (its SHA-256); the full run with it 27.1 s
  to 26.2 s, wall clock; every result the same to the last bit, on train, val, 200,000 and 1,000,000 records, an
  increment and 30 lookups.
- **A chain made from its prefix's column** (`er.standardize.prepare`): a normalization chain whose chain without its
  last step was already made (`address`, then `address` and `first3`) applies only that step to it, when that step
  makes nothing of an empty value, as every built-in step does. On addresses of about 100 characters, the address
  normalized once a chunk, not twice: a chunk of 200,000 records 6.0 s to 4.3 s.
- **A fit sample of 100,000 records** (`fit_rows`). The fit's sample costs little against the u measured on the
  file: on 1,039,995 generated records the fit step takes 3.3 s on 30,000 records and 3.7 s on 100,000; on 500,355
  records of 80 columns, addresses of about 100 characters and long notes, 3.0 s and 3.8 s.
- **One edit on ASCII without an edit table** (`Comparator.test`): the same length, the Hamming distance; a length
  one apart, Levenshtein (an insertion or a deletion either way). Only a Damerau pair two substitutions apart is
  tested by Damerau–Levenshtein.
- **A one-edit level's u counted by keys** (`exact_u`): a substitution apart, two values share exactly one "value
  without its i-th character, at i"; a swap of neighbours apart, one "the two in order, at i"; so each key's records
  pair (Σn)² − Σn² over 2 ways. A length one apart is a join of the longer's deletions on the shorter values (for
  Hamming, which pads, the longer without its last). O(U·L²), the distinct values grouped once: no pair is listed,
  where sequential IDs listed tens of millions.
- **EM on agreement-pattern counts, in Python** (`er.fit.session`): each session counts its pairs' agreement
  patterns in one query, a few hundred rows, and runs its rounds over those counts in Python, never over every pair
  in its blocks: the prior counted once, no table cache or settings check per session.
- **Merged lists by bitmask.** A pair's generators are one bit each, combined with `bit_or` in SQL, then named once
  per combination.

**Not used, because it changes results** (measured at design time on labelled train and val): u from 10⁶ pairs
instead of 10⁷ for the scores would make u-sampling about 6× cheaper, but loses true pairs: cross-validated train
+1 / −8 (p = 0.0391), val −1. The fit's own sample, which feeds only EM, does use 10⁶ pairs: no pair moves on train or
val.

## Files of growing size

`scripts/benchmark.py`: each generated file resolved by `python -m er build` in a process of its own, the model fitted
on the file itself, without labels ([reports/benchmark.md](../reports/benchmark.md)):

| Records | Seconds | Peak memory | fit | score | everything else |
|---|---|---|---|---|---|
| 13,019 | 2.3 | 0.60 GB | 1.49 | 0.02 | 0.79 |
| 25,947 | 2.8 | 0.68 GB | 1.58 | 0.03 | 1.19 |
| 52,115 | 3.9 | 0.90 GB | 1.86 | 0.04 | 2.00 |
| 77,926 | 5.1 | 1.10 GB | 2.23 | 0.05 | 2.82 |
| 1,039,995 | 26.2 | 7.26 GB | 4.33 | 0.25 | 21.62 |

Over these sizes, time grows like N^0.57. `fit` grows far slower than the file, 1.49 s at 13,019 records and 4.33 s
at a million: it learns on 100,000 records (`fit_rows`), its u sample of the file is 10⁷ pairs for each of name, company and address
whatever the file's size, and cif, phone and birth are counted exactly. So it is most of a small file's time.
Everything else goes from 2.82 s at 77,926 records to 21.62 s at a million: 13 times the records, 7.7 times the time.
The candidates step is the largest at a million records, 10.74 s, from 0.76 s at 77,926; scoring stays under a
quarter of a second at every size, since the candidates step lists only the pairs that can reach 0.

## Reading a file as it comes

Measured at design time: the reader (`er.intake`, before every job) on a generated file of 1,039,995 records × 25
columns as Parquet, every column text, a clean copy and a damaged one:

| File | Seconds | Read back | Changed, never damaged |
|---|---|---|---|
| clean | 3.4 | every value | 0 |
| damaged | 3.9 | each kind of damage: 100.0% of its values | 0 |

The damaged copy holds 84,895 values with a zero-width character and a NUL, 84,222 NULL placeholders, 10,094 numbers
a spreadsheet wrote (5851.0) and 83,148 values written as lists (["…"]). Most values take the fast path: each chunk's
values that reading keeps as they are (plain ASCII, Japanese UTF-8 with nothing to fix) are settled in Arrow, by
column, and only the rest are read one by one, so the damaged copy costs about 15% more than the clean one. Which
columns hold numbers is learned from the first chunk (a column's first 50,000 values).
Plain ASCII is told by Arrow's byte tests (printable, not empty, no space at either end), not by a regular expression,
and a bracket found by RE2, which finds a single character far faster than Arrow's substring search: on a file of
500,000 records × 80 columns, some of 1,500 characters, the reader 37 s to 20 s.
