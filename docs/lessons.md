[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. A short summary is in [chapter 6](guide/06-measuring-and-choosing.md#challenge-the-tools-themselves-can-fool-you).*

# Lessons: how this pipeline fooled us, and what now guards against it

Each entry gives the symptom that gave it away, the cause, the fix, and what keeps it fixed. They are worth reading before trusting any entity-resolution number, ours included.

## Scores depended on what had been scored before
- **Symptom:** recall on train and in cross-validation sat about 10 points below val and test. Turning term frequency off gained 560 true pairs in cross-validation but only 26 on val.
- **Cause:** Splink keeps term-frequency tables in a cache on the DuckDB connection, keyed by the column name alone. With one shared connection, every dataset after the first was scored with the first dataset's name frequencies. Names missing from that stale table got no adjustment at all.
- **Fix:** `score_fs` clears the cache before scoring, and term frequencies now come from the fitting records, stored in the model.
- **Guard:** `tests/` scores one set after another on a shared connection and compares the result with a fresh connection.

## Scores depended on the size of the scored set
- **Symptom:** none visible yet. It would have shown on a much bigger file.
- **Cause:** the prior λ is a per-pair rate. True pairs grow with the number of records N, pairs with N². A model fitted on 30,000 records and applied to 10,000 or to 1,000,000 uses the wrong prior by log2 of the size ratio. Term frequencies computed on the scored set have the same problem.
- **Fix:** `score_fs` rescales λ to the scored set's size (`scaled_prior`), so cross-validation folds, val, test and any real file are all scored on one scale.
- **Guard:** a test pads the scored set and checks that the weight moves by exactly the change in the prior's odds.

## The size rescaling was only half done
- **Symptom:** at a fixed threshold, recall falls as the scored file grows: 89.9% at 12,000 records, 87.6% at 75,000 (the scale runs, now `scripts/benchmark.py`).
- **Cause:** λ is rescaled to the scored file's size, but u stays as measured on train. For fields whose number of distinct values grows with the file, such as the address and the CIF ID, the chance that two random records agree also shrinks like 1/N. Train's u then under-credits an agreement on them by about log2(N / 30,000) bits: 1.3 bits at 75,000 records, 5 bits at a million. On the 10,000-record val and test files it over-credits them by about 1.6 bits instead. Fields with a fixed set of values, such as the phone digits or a surname, are not affected.
- **Fix:** re-sample u on each scored file (`FSModel.u_from_scored`). It needs no labels and costs the same 10 million random pairs whatever the size. At 75,000 records it lifts recall from 87.6% to 88.7%, with the same false pairs.
- **How it was decided:** by the owner, as a "chosen" decision. Since the standardization fixes it gains on the selection sets too (+63 / −0 true pairs out-of-fold, +20 / −0 on val); the rest of this entry is the first decision's evidence. The rule's selection sets have about 10,000 records, where the change only removes credit u from train had over-given: −27 true pairs out-of-fold, −8 on val, no false pair added either way. The gain shows on bigger files, and real files are usually bigger than train.
- **Guard:** a test checks that u comes from the scored file, and `scripts/benchmark.py` reports recall at every file size.

## Three false positives that were one clone
- **Symptom:** the check that the threshold transfers failed. Cross-validated train had 0 false pairs out of 784 accepted; val had 3 out of 300.
- **Cause:** all three were one event. Two entities with the same full name lived at the same address and differed only in CIF and phone. The generator drew personas with replacement, which made about 8,500 pairs of entities with the same name and prefecture. Two of them also drew the same address. No matcher can separate such a pair, and real data wouldn't contain it.
- **Fix:** the generator draws each persona at most once. Same-name pairs now come only from the persona file itself (3,872 personas share a full name).
- **Guard:** the evaluation cell prints the transfer check on every run. False pairs that cluster into one over-merged entity are a sign of one cause, not several.

## Levels without an estimate fell back to Splink's defaults
- **Symptom:** Splink warned "u values not fully trained" and "level not observed" during the Optuna studies.
- **Cause:** some trials placed a "JW low" threshold above "JW high", which leaves the lower level unreachable, or used thresholds so strict that no random pair reached them. Splink then filled in default m and u values, and those can produce strong weights out of nothing.
- **Fix:** a level no sampled pair reached gets u at its 95% upper bound, so its weight is a lower bound on the evidence. A level never seen in training gets m = u, worth 0 bits. The training cell lists such levels.
- **Guard:** a test builds a shadowed level and checks that it carries 0 bits.

## Optuna and the threshold rule pulled in opposite directions
- **Symptom:** after we adopted Optuna's suggestion, the next study suggested the same configuration again, and it passed the decision rule again.
- **Cause:** Optuna searched the acceptance threshold directly and settled on 3.5. The threshold rule then re-set the adopted configuration's threshold to its own choice: the lowest weight with no false pairs plus one safety step, which came to 6. Any point with a lower threshold beat `FINAL` again, so the loop could never converge.
- **Fix:** one policy everywhere. Every configuration, whether the pipeline as written, a decision variant or an Optuna trial, takes its threshold from the threshold rule (`config/pipeline.toml` `[threshold]`), and Optuna no longer searches it.

## A search option that did nothing
- **Cause:** trials were built from `FINAL`'s model. Once `FINAL` had term frequency off, a trial's "term frequency on" had no keys to turn back on.
- **Fix:** "on" now restores the keys from the pipeline as written.

## A wall-clock timeout made results depend on the laptop
- **Symptom:** studies ran 3–37 trials instead of 30 or 60.
- **Cause:** Optuna's `timeout` counts wall-clock time, and a laptop asleep with the lid closed uses it up. The notebook's own timers pause during sleep, so they hid it.
- **Fix:** studies are bounded by `n_trials` only, so a seeded study always runs the same trials.

## String similarity on bytes, not characters
- **Cause:** DuckDB's `jaro_winkler_similarity`, `jaccard` and `damerau_levenshtein` compare UTF-8 bytes, and katakana takes 3 bytes per character. That scores サトウヒロシ / サトウタカシ at 0.897 instead of 0.844.
- **Fix:** `er.strings` registers character-level versions (`cl_*`), and every rule and Fellegi–Sunter level uses them.
- **Guard:** `connect()` checks them on every start, and so does `tests/`.

## Two steps grew with the square of the file
- **Symptom:** none at 10,000 records, where every step took under a second. It showed only when each step was priced by its complexity and its growth measured on larger generated files.
- **Cause:** the phone key and rule F2 joined on the last four phone digits, which take only 10,000 values, so chance pairs grow like N². TF-IDF compared each unresolved record with every record. At a million records: 39 million pairs, 55.8 million pairs and 6.4 × 10¹¹ operations.
- **Fix:** three compound phone keys, a sorted pass on the reversed name instead of TF-IDF, and F2 joined on the phone plus the start of the address. Each passed the decision rule with no true pair lost ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).
- **Guard:** `scripts/choose.py` stops if `FINAL` would go over budget at `target_rows` (its cost and "will it scale" steps), Optuna prunes trials that would, and every run's `budget` step stops before any join if a rule or generator is over budget on the actual file.

## A window that shrinks as the file grows
- **Symptom:** none in the decisions, which lost no pair the model accepts. It showed when we asked a stricter question: which true pairs *could* reach the threshold, and does a list hold them at every file size?
- **Cause:** a sorted neighbourhood compares each record with the next three in name order. The more records, the more sort between two similar names: the window held 85.8% of the name-close true pairs at 12,000 records, and 60.9% at 75,000. Some potential matches shared no exact key, so only the window found them: 61 on train, 27 of them still potential at a million records.
- **Fix:** keys, whose reach does not depend on the file size. They are the exact person and company names, one-deletion keys on the company name and, within the postal area, on the person name, and given name + postal code. Now no potential match depends on a window, on any split, up to a million records ([chapter 3](guide/03-far-too-many-pairs.md#keeping-every-potential-match)).
- **Guard:** `scripts/choose.py` counts the potential matches that share no key (`window_only`), at train's size and at `target_rows`, and stops if any is left.

## Two rule clusters were never compared
- **Symptom:** in the scale runs, most potential matches that both stages missed were on no candidate list: 28 of 30 at 50,000 records, and 14 of 14 at 75,000.
- **Cause:** the second stage generated candidates only for records the rules left alone. When the rules split one entity into two clusters, no pair between them was ever scored.
- **Fix:** the second stage scores every pair across two clusters (`FSSpec.bridge`). Pairs inside one cluster are dropped before the union, so the list grows by only 7%. It passed the decision rule as "better": +12 / −0 true pairs on cross-validated train, +4 / −0 on val, no false pair added.
- **Guard:** a test checks that, with the whole file as the query, generators list pairs between any two records.

## A projection that assumed too much
- **Cause:** the design projected each key from how fast its distinct values grow on record samples (α ≈ 2 − β). That formula assumes every value is equally common, and a record sample splits each entity's duplicates apart, so true pairs shrink as fast as chance pairs. Neither holds here.
- **First fix:** keep or drop whole entities, and fit a power law to the pair counts themselves.
- **Then:** the power law understated the keys that matter most. Fitted on the smallest three subsamples, it predicted the address key's pairs on a file four times bigger 37% too low, because chance pairs (×N²) only begin to dominate past the sizes it was fitted on. It put the address key at 1.5 million pairs at a million records, inside the budget; the address is shared by households and drawn from a fixed pool.
- **Fix:** `grown_pairs` counts, on train, the pairs of one entity (T, which grow like N) and the chance pairs between entities (C, which grow like N²), and projects each: P(n) = T·n/N + C·n(n − 1)/(N(N − 1)). It is the exact expectation of keeping a share of the entities, and lands within ±5% on that same test. The address key then projects to 12.8 pairs per record at a million records, over the budget of 5, so the address alone was replaced by the address with the phone, the name's first letter or the given name (`bounded_address_keys`, adopted with no true pair lost). Household pairs count as chance, the safe direction.
- **Guard:** budgets are per record (`max_pairs_per_record`), so a budget means the same at any size; a test checks the projection on a key with a fixed pool of values and on one without.

## A check slower than the trial it guarded
- **Symptom:** the scale check took 52.5 s. Optuna, which runs it in every trial, took 41 minutes instead of 8.
- **Cause:** `np.isin` on arrays of Python strings, to select the sampled entities.
- **Fix:** rank the entities once and keep those below a cut-off: 0.30 s. The study went from 2,455 s to 506 s.

## The first million-record run ran out of memory
- **Symptom:** the first million-record scale run stalled at 27 GB on a 16 GB laptop, deep in swap.
- **Cause:** `score_fs` read Splink's predictions into pandas with every matching column of both records, only to keep the ids, the weights and the gammas. At 250,000 records that copy added 4.8 GB to the peak. At a million it would have needed about 19 GB.
- **Fix:** DuckDB selects the needed columns before anything reaches pandas, and the predictions table is dropped once read. At 250,000 records the step now adds 1.1 GB, with identical results.
- **Since:** every table of size N or C is a DuckDB table (`er.run`), which spills past `[compute]` `memory_limit`. A million records peak at 4.45 GB.
- **Guard:** every run's `steps.json` records the peak memory after each step, and `scripts/benchmark.py` reports it at every file size.

## Merging the candidate lists was most of the work
- **Symptom:** with the five name keys and bridging, the million-record run's probabilistic stage went from 127 s to 228 s, though only 7% more pairs were scored.
- **Cause:** three per-pair Python loops, each linear and each slow. Merging the generators' lists joined their names with `"+".join`, once per pair: 55% of the stage at 250,000 records. Reporting each generator's reach ran a lambda per pair and generator. With every record a query, each generator still filtered all records through an `isin`.
- **Fix:** a pair's generators are one bit each, combined by `bit_or` in SQL, then named once per distinct combination. A regex over those names reports each generator's reach. `query=None` skips the filter. At 250,000 records the stage takes 15 s instead of 59 s, with identical results.
- **Guard:** every run's `steps.json`, and `scripts/benchmark.py`, report each step's time at every file size.

## Who resolved a record depended on the file's order
- **Symptom:** the run without labels reproduced the labelled clusters exactly, but `resolved_by` differed on 318 train records, 81 val and 117 test.
- **Cause:** for a record the probabilistic stage reached, gold named the first rule in the file that touched it, so shuffling the file changed the answer.
- **Fix:** a record keeps the rule that resolved it in the previous stage, or else is named after the model, whatever the order.
- **Guard:** a test runs the same records in two orders and requires identical gold, every column; it also checks that an increment never splits a stored cluster. Another requires the engine `scripts/choose.py` measures with (`er.pipeline`) and the one `scripts/resolve.py` runs (`er.run`) to give identical gold.

## Two spellings of "nothing"
- **Symptom:** found by reading the code, not in the numbers: after `strip_spaces`, 614 of train's 23,848 person names (2.6%) still held a full-width space, so ホンエ　ヨシツグ never equalled ホンエヨシツグ. And a company name that was only a legal form became an empty string.
- **Cause:** pandas' Arrow-backed strings run regexes with RE2, whose `\s` matches ASCII whitespace only. And an empty string is a value: two records whose company name had been emptied agreed at "exact", and fell into one block.
- **Fix:** the patterns name the full-width space; a blank input value is missing, so it can't win a fallback; a value that normalization empties is missing too.
- **Guard:** a test standardizes blank, space-only and legal-form-only values.

## A run folder could hold two runs
- **Symptom:** a full run written into a folder that held an earlier run and its increment kept the increment's files: 598 stored records for 501. And an increment stopped between its writes left gold and the stored records disagreeing, with no way to retry.
- **Cause:** a full run overwrote only the files it writes itself, and an increment replaced its files one by one.
- **Fix:** a full run refuses a folder that holds a run unless `--overwrite`. Every file is written under a temporary name; once all are complete, the renames they need are saved, then done, and the next increment finishes any left undone.
- **Guard:** tests re-run into a used folder, and stop an increment halfway through its renames.

## DuckDB 2.0 changed under us
- **Symptom:** a run hung on its second query, or failed on `fetchone`.
- **Cause:** in DuckDB 2.0 a relation has no `fetchone`, and an `execute()` whose rows are not all fetched holds the connection. The connection-level `fetch_record_batch` is gone, and the `x -> …` lambda syntax is deprecated.
- **Fix:** every query fetches its rows (`.fetchall()`), the chunked reader has a cursor of its own, and lambdas are written `lambda x: …`.
- **Guard:** `requirements.txt` pins DuckDB, and `tests/` runs every generator and a whole run on it.

## Reference data traps
- **Wikidata's class tree:** 13,766 of the 16k "Japanese companies" with kana in the transitive `company` tree are dissolved municipalities. Only direct company types give real companies.
- **yubinbango prefecture codes** are written without the leading zero (`1`, not `01`). That silently dropped 9 prefectures until the codes were zero-padded.

## Test was seen during development
Earlier versions of the pipeline, with the stale cache and the persona clones, were scored on test. The fixes came from symptoms found on train and val, never from test numbers. The leaderboard now holds one clean pass of the final code, which scored test once per stage. The development runs are archived in `data/artifacts/experiments/archive/`.
