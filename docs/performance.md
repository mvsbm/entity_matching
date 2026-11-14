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
| 1 | load: read in chunks, check the fields, standardize the chunks in parallel processes, and tell persons from companies | `Run.load`, `er.standardize.prepare`, `er.kind` | O(N·L) | N | 10.73 s |
| 2 | budget: every rule's and generator's pairs, exactly, before any join | `Run.budget`, `er.candidates.estimate` | O(N) per rule and generator, a group-by | N | 1.96 s |
| 3 | fit: λ, and m by EM, on a sample of whole postal areas (EM's own u from 10⁶ pairs); then u measured on this file: value counts for the leading exact levels, position, swap and deletion keys for a one-edit level after them (so cif, phone and birth are counted exactly), S pairs for name, company and address | `Run.fit`, `er.match.train_fs`, `exact_u`, `scored_sample`, `assemble_u` | O(n + S·K + P_em·K) + O(N + S·K) | **constant**, plus N | 9.40 s |
| 4 | rules: one plain SQL join per rule (the first rule wins a pair), fuzzy checks on the joined pairs only, then the cascade's clusters | `Run.rules`, `er.match.rule_edges`, `er.cluster.merge` | O(N + Σ P_r·L²) + O(E·d + N) | N; ≤ 0.14 pairs per record per rule at 1M | 2.57 s |
| 5 | candidates: every generator as one SQL join or window, keeping only the pairs that can reach 0 (step 6's bound) or a rule found, merged by bitmask, only pairs touching a record the rules left alone; oversized blocks checked on a sample scored with the file's u | `Run.candidates`, `er.candidates.candidates` | O(N·L + Σ P_g) | N; ≤ 1.75 pairs per record per key at 1M, 3 per sorted window | 6.53 s |
| 6 | score: every candidate that can reach 0 points, with the u the fit measured; a bound settles the rest below 0 unscored, as nothing reads them (below) | `Run.score`, `er.match.score_fs`, `bound_sql` | O(C·K_c + C₀·K·L²) | C | 16.05 s |
| 7 | cluster: accept at the threshold, connected components with the rules' pairs (each rule cluster one node), gold | `Run.cluster`, `er.cluster.merge` | O(C + E·d + N) | N | 0.34 s |
| 7b | probe: a hash-stable draw of the records in each `[probe]` group, each paired with its group and scored: the matches no key lists ([below](#the-probe-the-matches-no-key-lists)) | `Run.probe`, `er.probe.missed` | O(N + P·K + L) | N; P about `[probe] pairs` a group | 3.52 s |
| 8 | write: gold, matches, the rules' pairs and the state for increments, as Parquet | `Run.write` | O(N + C) | N | 1.07 s |
| 9 | report: qa.md, report.txt and the review sheet, built before the write and landing with it | `Run.report` | O(review pairs) + O(N) | N | 0.78 s |
| | **total** | | | | **53.0 s** |

**Pairs that can't reach 0 points.** Nothing reads a candidate's score below 0: `scored/` keeps 0 points and up, and the line, the trust steps and review all start there. So a pair is scored only when its bound reaches 0: the prior, each comparison whose tests are equality, Hamming or one edit at its own level, and each other at the best level the pair may land in (`bound_tests`): DuckDB settles each level's test where it can in C++, a name or a company name in katakana by Jaro–Winkler on its one-byte copy, and only a test it can't settle (text outside katakana and ASCII, an edit distance past one) counts as passing. 0 where its fields are missing. Each test is computed once: the outcomes index a table of the bounds they allow, since DuckDB computes an expression as often as it is written. A pair a rule found is scored whatever its bound. A full run's candidates step already leaves the rest out as its keys list them (below); an increment's are counted (`unscored`, one row "below 0" in report.txt's SCORES and the score chart) and never compared by name, company or address: on a file whose address and phone are mostly empty, that is nearly every candidate. Every score written is the same to the last bit. The gate on oversized blocks and the probe do the same at their own floors, the review floor and the line. K_c is the comparisons settled first, C₀ the candidates whose bound reaches 0.

At a million records, scoring the candidates (16.05 s) and the fit (9.40 s) take nearly half the time. The fit costs
nearly the same at any size: it learns on n records, and its u sample of the file is S pairs for each of name, company
and address, whatever the file's size; cif, phone and birth are counted exactly, in O(N). The score grows with the
candidates.

**An increment** (`Run.increment`, `nayose add records`): a batch of Δ new records joins a written run.

| Step | Cost | What it touches |
|---|---|---|
| load | O(Δ·L), plus one O(N) copy | the batch; a record already in the run is set aside. The stored records and the batch then form one table, which every later step reads |
| fit | O(N) + O(S·K_stale) | the stored model, with u settled before the rules: the exact and one-edit u counted again on all the records (group-bys, and the distinct values' position, swap and deletion keys); a comparison's sampled u measured again only once the drift of its exact u exceeds its sampling error (`er.match.refreshed_u`) |
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
- **Names scored in DuckDB** (`er.kind.NameModel.logit`): every distinct name's character n-grams in one query, once
  however often the name repeats, joined to the model's weights and summed in term order, so every run gives the same
  bits. The same sums as scikit-learn's vectorizer, which builds the n-grams one name at a time in Python.
- **Each distinct value prepared once** (`er.standardize.normalize`): every step reads one value alone, so a column's
  distinct values go through the steps and the column is made of them; 25 to 40 times faster on a column that repeats
  (phones, postal codes, common names), and done value by value where most values are distinct.
- **The budget's counts read again** (`er.candidates.candidates`, `known`): each generator's pairs and blocks are
  counted once, by the budget, and step 4 reads them, not the records.
- **One u sample per set of records** (`er.match.scored_sample`, `SCORED_U`). A comparison's u depends only on
  itself, the sample size, the seed (`FSModel.u_keys`) and the values it reads, since Splink picks the sampled pairs by
  a hash of the record ID. So the cache is keyed by the comparison and a fingerprint of those values, a frame and a
  table with the same rows alike: within one process, a model's variants and `choose.py`'s repeats of train share one
  sample. A workspace keeps it too (`u_sampled.json`, keyed besides by the code and Splink's and DuckDB's versions), so
  a rerun or a trial of a method comparing the same way reads it and draws no sample: 250,000 records' fit from 12.5 s
  to 3.6 s. cif, phone and birth need none: their levels are counted (`exact_u`, once per fit).
- **The u sample counted in one pass** (`er.match.sample_u`). The records and pairs are drawn as Splink draws them (a
  hash of the ID and the seed), and every comparison's levels are counted in one pass over the pairs, where Splink's
  estimate joins them again for each comparison, chunk by chunk: the same counts, so the same u to the last bit. The
  pairs are written first as row numbers, 16 bytes a pair (160 MB for 10 million): the drawn records fill one row
  group, and DuckDB would compare pairs read from it on one thread. Streamed into the counts, the compared values
  never sit in memory. The fit's two samples of 250,000 records, 11.2 s to 3.5 s with the edit distances below.
- **Scores in one query** (`er.match.predict_sql`). Splink's predict SQL as Splink writes it: each level's condition
  in order, its weight the same `float8` literal, summed in the same order, so the same scores to the last bit (tests
  compare them with Splink's), without the two copies of the records Splink makes first and its SQL built per call.
  Scoring 250,000 records 4.8 s to 2.6 s, the probe's draws 5.1 s to 3.0 s. A model with term frequencies is scored
  by Splink.
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
- **Edit distances in DuckDB** (`er.config.Comparator.test`). On ASCII values DuckDB's Levenshtein and
  Damerau–Levenshtein are rapidfuzz's (both unrestricted; tests compare them). Other text gets a copy at load with each
  character one ASCII byte by its code point (`one_byte_hash`); two characters may share a byte but never the reverse,
  so the copies are never farther apart than the values, and a pair past the threshold there can't pass. Python
  checks only the pairs left: of 10 million sampled address pairs, 36,645 instead of 2.3 million. Records
  prepared without the copy are bounded by the bytes instead: one character edited is at most 4 bytes edited.
- **The oversized blocks' samples scored a slice at a time, in DuckDB** (`Run._gate`, `Run._scored`), not all at once
  through pandas: thousands of placeholder blocks no longer need their every sampled pair compared in one call.
- **A rule's untrusted values tested before its join** (in WHERE, not ON): a placeholder's block is no longer joined
  and compared in full before it is left out.
- **Each candidate pair listed once**: a key's join over the query keeps one order of a pair of two queried records
  instead of both and a DISTINCT; the union's parts are freed as soon as it is made.
- **Scoring in slices** (`Run.score_pairs`, 5 million pairs at a time). A pair's score depends on it alone, so the
  slices score as the whole would; each slice says how far scoring is (pairs scored, and those at the model's line so
  far), and bounds the step's memory. Each slice joins every record again, about 0.75 s at a million records: 9.3
  million pairs in slices of a million took 13.8 s, in slices of 5 million 8.8 s, for 0.2 GB more at the peak.
- **The trust sheet's links joined once** (`er.report.trust_sheet`). Every question the sheet asks (does a range
  hold a link, how many people decided, the next range's sample, the spot-checks) reads the links from the lowest step
  or the line up, written once to a table, not joined again from every scored pair each time: the report on a million
  records 11.9 s to 5.5 s, on 250,000 3.4 s to 2.1 s.
- **Chunks standardized in parallel** (`Run.load`, `run.ahead`). Every step reads one record, or one chunk's
  values, so the chunks are cleaned in worker processes, spawned on every system (as many as DuckDB's threads, at most
  one per chunk, the CPUs, and 61 on Windows), one chunk queued beyond them, and taken back in order: the same records;
  an error in one cancels those not started. Each chunk is sent with the cleaning settings, and the person/company model
  is rebuilt from its terms and weights in the worker, on one thread. A script that
  runs a load keeps its work under `if __name__ == "__main__":`, as the scripts here do: each worker imports it first.
- **Pairs that can't reach 0 never stored** (`Run._reaching`, `er.match.reaching_sql`). Each generator's pairs pass
  step 6's bound as they are listed, 10 million at a time, before they are stored; generators that list fewer wait
  and pass it together (`er.candidates._bound`), since the bound reads a pair alone and each pass joins the records
  again: on 500,000 generated records the candidates step 4.4 s to 3.1 s, an increment of 100,000 into 400,000 4.3 s
  to 3.1 s. First a rough test on a hash of each column (`rough_sql`): it reads only whether values are missing or
  equal, each comparison at the best weight that leaves, so it costs a few integers a pair and never drops a pair the
  bound keeps: on those records with 85% of addresses and 70% of phones blanked and customer IDs in sequence (59
  million pairs listed by `cif_deletions`), with the pass above, the candidates step 25.5 s to 17.9 s. Then a looser test on a few
  columns (the cheap comparisons and the name, the others at their best level or 0, `first_bound`), then the whole
  bound on the few left. Score scores the same pairs. Each listed pair leaves a 64-bit hash first, 8 bytes, so the
  gate reads the pairs other keys listed as it would every pair, and the counts mean what they did: `candidates` the
  distinct pairs listed (`stored`, those kept), each generator's pairs as listed, `unscored` those below 0. On a
  generated file of 1.3 million records with sparse addresses and sequential customer IDs, 112 million candidates
  were 33,700 stored and the step 61 s instead of 593 s. Larger passes spill: 33 million pairs through the joins took
  ten times what 10 million did. Design time (`er.pipeline.run_fs`) stores every pair, so the keys' metrics count
  them all (`Run.reaching_only`).
- **A key's oversized blocks left out before its join**, on both sides, not from its pairs after.
- **The gap's sample bounded once** (`er.sample.discover`): every atom's drawn pairs are listed first, then pass the
  bound together, 10 million at a time, not one pass per atom; each pass joins the records again.
- **PassJoin's candidates as value IDs** (`Records.near_values`): the segment join keeps each candidate as two
  integers, and only those cross into Python, with each value's text once, for rapidfuzz to check: no pandas string
  for each of tens of millions of candidate pairs of names. With the bound above, the gap step on 500,000 generated
  records 21.5 s to 6.3 s (within two edits of a name, 12.4 s to 1.9 s), on train 4.9 s to 1.3 s.
- **EM's sessions per key without Splink's checks** (`train_fs`): each session's linker skips Splink's settings
  validation, which only logs warnings the fit hides, and takes the prior the first linker estimated on the same
  records, not counted again. A fit on 1,000 records one session per key, 2.9 s to 2.3 s; on 128,000, 6.2 s to 5.4 s.
  With the gap's sample above, `nayose try sample` on 500,000 generated records 107 s to 67 s.
- **One edit on ASCII without an edit table** (`Comparator.test`): the same length, the Hamming distance; a length
  one apart, Levenshtein (an insertion or a deletion either way). Only a Damerau pair two substitutions apart is
  tested by Damerau–Levenshtein.
- **A one-edit level's u counted by keys** (`exact_u`): a substitution apart, two values share exactly one "value
  without its i-th character, at i"; a swap of neighbours apart, one "the two in order, at i"; so each key's records
  pair (Σn)² − Σn² over 2 ways. A length one apart is a join of the longer's deletions on the shorter values (for
  Hamming, which pads, the longer without its last). O(U·L²), the distinct values grouped once: no pair is listed,
  where sequential IDs listed tens of millions.
- **EM on agreement-pattern counts** (`train_fs`): with no term frequencies, each iteration reads the count of each
  agreement pattern, a few hundred rows, not every pair in EM's blocks, as Splink does when told. The same updates,
  summed in another order: weights within 10⁻⁹ bits, unless that order moves the change past `em_convergence` and EM
  stops an iteration sooner or later, which leaves a level's weight as far from the other order's as one iteration
  moves it. On that generated file's sample, 505 s to 25 s.
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
