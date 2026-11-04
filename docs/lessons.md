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
- **Symptom:** none visible yet. It would have shown at production size.
- **Cause:** the prior λ is a per-pair rate. True pairs grow with the number of records N, pairs with N². A model fitted on 30,000 records and applied to 10,000 or to 1,000,000 uses the wrong prior by log2 of the size ratio. Term frequencies computed on the scored set have the same problem.
- **Fix:** `score_fs` rescales λ to the scored set's size (`scaled_prior`), so cross-validation folds, val, test and production are all scored on one scale.
- **Guard:** a test pads the scored set and checks that the weight moves by exactly the change in the prior's odds.

## The size rescaling is only half done (open)
- **Symptom:** at a fixed threshold, recall falls as the scored file grows: 89.8% at 12,000 records, 87.5% at 75,000 (`scripts/robustness.py`).
- **Cause:** λ is rescaled to the scored file's size, but u stays as measured on train. For fields whose number of distinct values grows with the file, such as the address and the CIF ID, the chance that two random records agree also shrinks like 1/N. Train's u then under-credits an agreement on them by about log2(N / 30,000) bits: 1.3 bits at 75,000 records, 5 bits at a million. On the 10,000-record val and test files it over-credits them by about 1.6 bits instead. Fields with a fixed set of values, such as the phone digits or a surname, are not affected.
- **Measured fix:** re-sample u on the scored file. It needs no labels and costs the same 10 million random pairs whatever the size. At 75,000 records it recovers recall from 87.5% to 88.6%, with the same false pairs (the `recall_u_from_file` column of the robustness report).
- **Status:** not adopted yet. It changes every reported number, so it needs its own clean pass through the decision rule, with the threshold re-chosen.

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
- **Fix:** one policy everywhere. Every configuration, whether `SPEC`, a decision variant or an Optuna trial, takes its threshold from `THRESHOLD_RULE`, and Optuna no longer searches it.

## A search option that did nothing
- **Cause:** trials were built from `FINAL`'s model. Once `FINAL` had term frequency off, a trial's "term frequency on" had no keys to turn back on.
- **Fix:** "on" now restores the keys from `SPEC`.

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
- **Guard:** the "Will it scale?" cell in each notebook stops the run if `FINAL` would go over budget at a million records, and Optuna prunes trials that would.

## A projection that assumed too much
- **Cause:** the design projected each key from how fast its distinct values grow on record samples (α ≈ 2 − β). That formula assumes every value is equally common, and a record sample splits each entity's duplicates apart, so true pairs shrink as fast as chance pairs. Neither holds here.
- **Fix:** `grown_pairs` keeps or drops whole entities and fits the pair counts themselves. It overstates the growth of keys that households share (α 1.58 for the address, against 1.01 on generated files), which is the safe direction.

## A check slower than the trial it guarded
- **Symptom:** the scale check took 52.5 s. Optuna, which runs it in every trial, took 41 minutes instead of 8.
- **Cause:** `np.isin` on arrays of Python strings, to select the sampled entities.
- **Fix:** rank the entities once and keep those below a cut-off: 0.30 s. The study went from 2,455 s to 506 s.

## The first million-record run ran out of memory
- **Symptom:** the robustness script's million-record run stalled at 27 GB on a 16 GB laptop, deep in swap.
- **Cause:** `score_fs` read Splink's predictions into pandas with every matching column of both records, only to keep the ids, the weights and the gammas. At 250,000 records that copy added 4.8 GB to the peak. At a million it would have needed about 19 GB.
- **Fix:** DuckDB selects the needed columns before anything reaches pandas, and the predictions table is dropped once read. At 250,000 records the step now adds 1.1 GB, with identical results.
- **Guard:** the cost table of `scripts/robustness.py --smoke` reports the peak memory at each file size.

## Reference data traps
- **Wikidata's class tree:** 13,766 of the 16k "Japanese companies" with kana in the transitive `company` tree are dissolved municipalities. Only direct company types give real companies.
- **yubinbango prefecture codes** are written without the leading zero (`1`, not `01`). That silently dropped 9 prefectures until the codes were zero-padded.

## Test was seen during development
Earlier versions of the pipeline, with the stale cache and the persona clones, were scored on test. The fixes came from symptoms found on train and val, never from test numbers. The leaderboard now holds one clean pass of the final code, which scored test once per stage. The development runs are archived in `data/artifacts/experiments/archive/`.
