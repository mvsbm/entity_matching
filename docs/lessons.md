[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. A short summary is in [chapter 6](guide/06-measuring-and-choosing.md#challenge-the-tools-themselves-can-fool-you).*

# Pitfalls and what guards against them

Each entry names a way an entity-resolution pipeline like this one goes wrong, and how it would show (**Pitfall**); why it happens (**Why**); what this pipeline does against it (**Guard**); and the test or report that keeps it so (**Check**). They are worth reading before trusting any entity-resolution number, ours included.

## Scores that depend on what was scored before
- **Pitfall:** a cache keyed too loosely makes a file's scores depend on which file was scored before it on the same connection. It shows as train and cross-validation disagreeing with val and test, or a change gaining far more on one set than on another.
- **Why:** Splink keeps term-frequency tables in a cache on the DuckDB connection, keyed by name alone. With one shared connection, every file after the first is scored with the first file's name frequencies, and a name missing from that stale table gets no adjustment at all.
- **Guard:** `score_fs` clears Splink's cache before scoring, and term frequencies come from the fitting records, stored in the model. The pipeline's own caches are keyed by everything they read: the u cache (`er.match.scored_sample`) by the comparison and a fingerprint of the values it reads.
- **Check:** `tests/` scores one set after another on a shared connection and compares the result with a fresh connection, for the model and for the rules. Another test checks that one u sample serves the same records in any order, as a frame or as a table.

## Weights fitted at one file size, used at another
- **Pitfall:** a model fitted on one file and applied to a bigger or a smaller one weighs the evidence wrongly. It shows as recall that drifts with the file's size at a fixed threshold, or as a change that loses on small selection sets and gains on big files.
- **Why:** the prior λ is a per-pair rate. True pairs grow with the number of records N, pairs with N², so a prior fitted on 30,000 records is off by log2 of the size ratio on another file. u has the same problem for fields whose number of distinct values grows with the file, such as the address and the CIF ID: two random records agree on them less often in a bigger file. A u from 30,000 records under-credits an agreement on them by about log2(N / 30,000) bits on a bigger file, 5 bits at a million, and over-credits it on a smaller one. Fields with a fixed set of values, such as the phone digits or a surname, are not affected. And a sample of 10 million pairs cannot see an agreement rarer than about one in a billion pairs, which an exact name or CIF ID becomes in a big file.
- **Guard:** `score_fs` rescales λ to the scored file's size (`scaled_prior`). The fit ends by measuring u on the whole file (`scored_u`): the leading exact levels from value counts, a one-edit level right after them through one-deletion keys, the rest from 10 million random pairs. The scores and the gate on oversized blocks both use these u. Measuring u on the scored file is a "chosen" decision: on the 10,000-record selection sets it removes credit that the larger fitting set's u over-gives there, so it loses 60 true pairs out-of-fold and 12 on val, with no false pair added. Counting the exact levels gains 47 and loses 5 out-of-fold.
- **Check:** tests pad the scored set and check that the weight moves by exactly the change in the prior's odds, and that u comes from the scored file while m stays as fitted. [`reports/benchmark.md`](../reports/benchmark.md) reports recall at every file size, and [`reports/choose.md`](../reports/choose.md) each decision's paired counts.

## A generator that makes impossible twins
- **Pitfall:** synthetic data holds pairs no matcher could separate, which count as false merges that are no fault of the matcher. They show as false pairs that cluster in one over-merged entity, or as a threshold that fails to transfer from cross-validation to val.
- **Why:** drawing personas with replacement makes entities with the same name and prefecture. When two of them also draw the same address, they differ only in CIF ID and phone. Real data wouldn't contain such a pair.
- **Guard:** the generator draws each persona at most once, and refuses a population larger than the persona file. Same-name pairs come only from the persona file itself.
- **Check:** `reports/choose.md` prints the transfer check every round: at 8 bits, 0 false of 2,368 accepted pairs out-of-fold, and 0 of 765 on val. False pairs that cluster into one over-merged entity are a sign of one cause, not several.

## Levels without an estimate
- **Pitfall:** Splink fills a level it could not estimate with default m and u values, which can produce strong weights out of nothing. It shows as Splink warning "u values not fully trained" or "level not observed".
- **Why:** a lower level can be unreachable, when its threshold sits above the level before it ("JW low" above "JW high"), or a threshold can be so strict that no random pair reaches it.
- **Guard:** a level no sampled pair reached gets u at its 95% upper bound, so its weight is a lower bound on the evidence. A level never seen in training gets m = u, worth 0 bits. The model lists such levels (`er.filled`). A level that is never reached is left out: the company comparison has no "JW high" level, and the search skips a tuned level the model doesn't have.
- **Check:** a test builds a shadowed level and checks that it carries 0 bits.

## Two policies that set one parameter
- **Pitfall:** two procedures that both choose the same setting make the adopt-and-rerun loop go round for ever. It shows as a search suggesting an adopted configuration again, and that suggestion passing the decision rule again.
- **Why:** if Optuna searches the acceptance threshold while the threshold rule re-sets each adopted configuration's threshold to its own choice, any point with a lower threshold beats the choice again.
- **Guard:** one policy everywhere. Every configuration, whether the pipeline as written, a decision variant or an Optuna trial, takes its threshold from the threshold rule (`config/pipeline.toml` `[threshold]`), and Optuna does not search it.
- **Check:** the search spaces in `config/experiments.py` hold no threshold, each trial takes the rule's (`FSChooser.threshold_of`), and a test checks the rule's pick.

## A search option that does nothing
- **Pitfall:** a search option built on top of the current choice can be a no-op, so the search spends trials on it and learns nothing. It shows as an option whose two values give identical trials.
- **Why:** trials are built from `FINAL`'s model. With term frequency off in `FINAL`, a trial's "term frequency on" has no keys to turn back on; with a level dropped by a decision, a threshold for it has nothing to tune.
- **Guard:** "on" restores the keys from the pipeline as written, and a trial tunes only the levels the model has.
- **Check:** none automated: `FSChooser.search` in `er/select.py` builds each trial, in one place.

## A wall-clock bound on a search
- **Pitfall:** a search bounded by time gives results that depend on the machine. It shows as studies that run fewer trials than asked.
- **Why:** Optuna's `timeout` counts wall-clock time, and a laptop asleep with the lid closed uses it up. The notebook's own timers pause during sleep, so they hide it.
- **Guard:** studies are bounded by `n_trials` only, and seeded, so a study always runs the same trials.
- **Check:** `Tune` and `FSTune` (`er/config.py`) have no timeout to set.

## String similarity on bytes, not characters
- **Pitfall:** a string function that compares bytes scores Japanese names wrongly, and nothing fails. It shows only when a known pair's score is checked by hand.
- **Why:** DuckDB's `jaro_winkler_similarity`, `jaccard` and `damerau_levenshtein` compare UTF-8 bytes, and katakana takes 3 bytes per character. That scores サトウヒロシ / サトウタカシ at 0.897 instead of 0.844.
- **Guard:** `er.strings` registers character-level versions (`cl_*`, on rapidfuzz), and every rule and Fellegi–Sunter level uses them.
- **Check:** `connect()` checks them on every start, and so does `tests/`.

## Keys whose pairs grow with the square of the file
- **Pitfall:** a key or a rule that is cheap on a small file explodes on a big one. Nothing shows on a 10,000-record file; it shows only when each step is priced by its complexity and its growth projected to larger files.
- **Why:** a key with a fixed set of values makes chance pairs that grow like N². The last four phone digits take only 10,000 values: the phone key alone projects to 49.8 pairs per record at a million records, against a budget of 5 ([`reports/choose.md`](../reports/choose.md)). TF-IDF compares each unresolved record with every record, up to 10⁶ comparisons per record there. Rule F2, joined on the phone alone, has the same problem.
- **Guard:** three compound phone keys instead of the phone, a sorted pass on the reversed name instead of TF-IDF, and F2 joined on the phone plus the start of the address. Each passed the decision rule with no true pair lost ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).
- **Check:** `scripts/choose.py` stops if `FINAL` would go over budget at `target_rows` (its "Cost of FINAL" and "Will it scale?" tables), and Optuna prunes trials that would. Every run's `budget` step counts each key's pairs before any join: it stops only if the normal blocks would not fit in memory and the temp disk, and checks oversized blocks on a sample.

## A window that shrinks as the file grows
- **Pitfall:** a sorted neighbourhood finds fewer of the close pairs as the file grows, so a potential match found on a small file is lost on a big one. The decisions don't show it: they ask which true pairs the model accepts, not which could reach the threshold at every size.
- **Why:** a sorted neighbourhood compares each record with the next three in name order. The more records, the more sort between two similar names.
- **Guard:** keys, whose reach does not depend on the file size: the exact person and company names, one-deletion keys on the company name and, within the postal area, on the person name, and given name + postal code. No potential match depends on a window, on train or at a million records ([chapter 3](guide/03-far-too-many-pairs.md#keeping-every-potential-match)).
- **Check:** `scripts/choose.py` counts the potential matches that share no key (`window_only`), at train's size and at `target_rows`, and stops if any is left: 0 of 3,036 on train, 0 of 2,960 at a million records. A label-free check lists the agreement patterns that can reach the threshold with no guaranteed key, with the model's estimate of their share of matches: at most 11.9% at a million.

## Two rule clusters that are never compared
- **Pitfall:** when the rules split one entity into two clusters, a second stage that looks only at records the rules left alone never scores a pair between them. It shows as potential matches both stages miss that are on no candidate list.
- **Why:** candidates are generated for the records the rules left alone, and an accepted pair must touch one.
- **Guard:** `FSSpec.bridge` scores every pair across two rule clusters, and `scripts/choose.py` decides it every round, as "better". On these sets it finds no extra true pair (+0 / −0 out-of-fold and on val), so `FINAL` leaves it off.
- **Check:** tests check that a bridging stage joins two clusters, and that with the whole file as the query, generators list pairs between any two records not already in one cluster. The decision is in `reports/choose.md`.

## A projection that assumes too much
- **Pitfall:** a projection of a key's pairs to a bigger file understates the keys that matter most, so a key over budget passes the design check.
- **Why:** projecting from how fast distinct values grow on record samples (α ≈ 2 − β) assumes every value is equally common, and a record sample splits each entity's duplicates apart, so true pairs shrink as fast as chance pairs. Neither holds here. A power law fitted to the pair counts of small subsamples fails too: chance pairs (×N²) only begin to dominate past the sizes it was fitted on. The address is shared by households and drawn from a fixed pool, so it is the key such a projection understates most.
- **Guard:** `grown_pairs` counts, on train, the pairs of one entity (T, which grow like N) and the chance pairs between entities (C, which grow like N²), and projects each: P(n) = T·n/N + C·n(n − 1)/(N(N − 1)). It is the exact expectation of keeping a share of the entities. The address key alone projects to 5.4 pairs per record at a million records, over the budget of 5, so the address is used only with the phone, the name's first letter or the given name (`bounded_address_keys`, adopted with no true pair lost). Household pairs count as chance, the safe direction.
- **Check:** budgets are per record (`max_pairs_per_record`), so a budget means the same at any size; a test checks the projection on a key with a fixed pool of values and on one without.

## Linear work done one pair at a time in Python
- **Pitfall:** a step that is linear, but runs Python code once per pair or per record, becomes most of the work. It shows as a step whose time grows far faster than its pairs, or as a check that costs more than the trial it guards.
- **Why:** per-element Python is slow: joining the generators' names with `"+".join` once per pair, a lambda per pair and generator to report each generator's reach, an `isin` filter of every record when every record is a query, `np.isin` on arrays of Python strings to select sampled entities.
- **Guard:** a pair's generators are one bit each, combined by `bit_or` in SQL, then named once per distinct combination; a regex over those names reports each generator's reach; `query=None` skips the filter. The scale check samples nothing: `grown_pairs` computes the expectation with group-bys, once per round, and each Optuna trial reads its generators' rows from it. Where whole entities must be kept, they are ranked once (`entity_rank`) and kept below a cut-off.
- **Check:** every run's `steps.json`, and [`reports/benchmark.md`](../reports/benchmark.md), report each step's time at every file size.

## A copy that outgrows memory
- **Pitfall:** an intermediate table copied into pandas with more columns than needed outgrows memory on a big file. It shows as a run that stalls deep in swap.
- **Why:** reading Splink's predictions into pandas with every matching column of both records, only to keep the ids, the weights and the gammas, makes a copy that grows with the candidates times the columns.
- **Guard:** DuckDB selects the needed columns before anything reaches pandas, and the predictions table is dropped once read. Every table of size N or C is a DuckDB table (`er.run`), which spills past `[compute]` `memory_limit` to `.tmp/` under the folder a run starts in, unless `temp_directory` says otherwise. A run's capacity counts the spill room DuckDB allows: 90% of the free disk by default. DuckDB keeps what the limit allows, so the peak under a large limit says little: test the smallest limit that completes, not the peak.
- **Check:** every run's `steps.json` records the peak memory after each step, and `reports/benchmark.md` reports it at every file size: 6.23 GB at a million records under an 8 GB limit, Python included.

## An answer that depends on the file's order
- **Pitfall:** an output column depends on the order of the records in the file. It shows as identical clusters but a different `resolved_by` after the file is shuffled.
- **Why:** naming, for a record the probabilistic stage reached, the first rule in the file that touched it.
- **Guard:** a record keeps the rule that resolved it in the previous stage, or else is named after the model, whatever the order.
- **Check:** a test runs the same records in two orders and requires identical gold, every column; it also checks that an increment never splits a stored cluster. Another requires the engine `scripts/choose.py` measures with (`er.pipeline`) and the one `nayose` runs (`er.run`) to give identical gold.

## Two spellings of "nothing"
- **Pitfall:** a blank that isn't treated as missing. A name that still holds a full-width space never equals the same name without it, and two values emptied by normalization agree at "exact" and fall into one block. It shows by reading the code or the values, not in the numbers.
- **Why:** pandas' Arrow-backed strings run regexes with RE2, whose `\s` matches ASCII whitespace only, so ホンエ　ヨシツグ keeps its full-width space and never equals ホンエヨシツグ. And an empty string is a value: a company name that is only a legal form becomes an empty string.
- **Guard:** the patterns name the full-width space; a blank input value is missing, so it can't win a fallback; a value that normalization empties is missing too.
- **Check:** a test standardizes blank, space-only and legal-form-only values.

## A run folder that holds two runs
- **Pitfall:** a full run written into a folder that holds an earlier run keeps some of the earlier files, and an increment stopped between its writes leaves gold and the stored records disagreeing, with no way to retry. It shows as more stored records than the input holds.
- **Why:** a full run that overwrites only the files it writes itself, and an increment that replaces its files one by one.
- **Guard:** a full run refuses a folder that holds a run unless `--overwrite`, and a folder takes one writer at a time (`run_lock`). Every file is written under a temporary name; once all are complete, the renames they need are saved, then done, and the next increment finishes any left undone.
- **Check:** tests re-run into a used folder, stop an increment halfway through its renames, and hold a folder's lock while another run tries it.

## An increment that counts its own batch twice
- **Pitfall:** an increment that reads the stored records through a glob sees its own batch twice once it has written its part. It shows as u counted on the run's records disagreeing with the u the increment scored with; the QA report's fill rates weigh the batch twice, and a review row touching a new record can appear twice.
- **Why:** a view over a glob of `state/records/` includes the part the increment just wrote, and the QA report runs after the write.
- **Guard:** an increment reads the stored parts it found when it started, by name, not by glob.
- **Check:** a test compares the increment's exact u with u counted on its records after the write.

## Re-measuring u on every increment
- **Pitfall:** measuring u again on every increment, whatever has changed, takes most of an increment's time and only redraws the noise. It shows as a small batch costing nearly as much as a full fit.
- **Why:** a small batch barely moves u. Until the drift is larger than a sampled level's own sampling error, a new sample is no closer to the truth.
- **Guard:** before its rules, an increment counts the exact and the one-edit levels again on all records (`refreshed_u`). A comparison's sampled u are measured again only once the drift of its exact level exceeds the sampling error of its most precise sampled level, 1/(ln 2·√hits) bits. The CIF ID, phone and birth date comparisons are counted in full, so they need no sample.
- **Check:** a test checks that an increment samples exactly the comparisons whose drift exceeds their error, and each run's `state/scoring.json` keeps the last check, drift and error, per comparison.

## A placeholder value that passes the budget
- **Pitfall:** a dummy value, such as a phone `0000` on many records, makes huge blocks that add work for nothing. Spread over compound keys, its blocks stay under the cap per key, so a per-key budget lets it through. It shows as candidates that jump with no gain in matches.
- **Why:** a budget that caps each key's pairs per record can't tell a placeholder from a real shared value. A block's share of true matches falls as it grows, and a placeholder's block holds none.
- **Guard:** a block of 64 or more records (more pairs than `[budget] sample_pairs`, 2,000) is left out of its generator's join and checked first: about 2,000 of its pairs are scored with the model and the file's u, and the block is joined only if one reaches the review floor (6 bits, one grid step below the threshold). No hit in 2,000 pairs bounds a block's yield under 0.15%. A rule doesn't trust a key value held by such a block. Skipped blocks are named in the summary and in `qa.md`.
- **Check:** tests put a dummy phone on 100 records (skipped), 70 copies of one record (kept and joined), and one customer ID and name on 70 records (no rule merges them).

## A report that carries records off the machine
- **Pitfall:** a run report sent to someone for help carries records with it: the value of a placeholder phone, a customer ID on thousands of records, the IDs of the largest clusters. It shows only by reading the report.
- **Why:** the notes that make a run's problems clear quote the values behind them, and a report built from them inherits the values.
- **Guard:** `report.txt` is built only from field and column names, counts, shares, times and the model's parameters. A note that quotes a value is kept apart (`Run.examples`) and goes to the terminal and `qa.md` only.
- **Check:** a test puts a placeholder phone and a customer ID with one name on many records, so the run has notes quoting them, and checks that the report holds no kana or kanji, no record ID and no customer ID.

## A legal-form list that misses how banks write it
- **Pitfall:** a list of legal forms in full (株式会社, カブシキガイシャ) and one abbreviation misses most of how bank records write them: カ)〇〇 at the front, 〇〇(カ at the end, イ) for 医療法人, ザイ) for a 財団法人, and readings with small kana written large (カブシキガイシヤ). It shows as companies that look like persons to every later step, and company names that keep their legal form when compared.
- **Why:** bank systems store names in half-width katakana under the Zengin rules: no small kana, and each legal form abbreviated, at a position that depends on where the form stands in the name.
- **Guard:** `[locale]` `legal_forms` holds every form's reading and the middle abbreviations ((カ)); `legal_front` and `legal_end` hold the abbreviations by where banks may put them. `config.legal_pattern` adds each reading with small kana written large, longest first, so 医療法人社団 isn't cut to 医療法人.
- **Check:** a test strips every form at its positions, keeps a front-only one at the end, and leaves the generator's names losing exactly the forms the generator writes; `reports/choose_kind.md` shows what the bank table is worth against the generator's forms alone.

## A signal true only in the generator
- **Pitfall:** a generator that fills birth dates for persons only makes "a birth date is filled" look like proof of a person, and a classifier leans on it. In a real file a company's record can hold a date there too: its founding date, or its representative's birth date. It shows as companies called persons, confidently.
- **Why:** the generator's choices become the model's evidence. A signal that exists only by construction is learned as if it were real.
- **Guard:** `scripts/choose_kind.py` gives companies a date on 0–60% of their records, a founding year or the representative's birth date, and judges every combination across that range. The combiner reads the birth year, which still tells a founding year from most birth years, not only whether a date is filled.
- **Check:** `reports/choose_kind.md`: each signal's worth, with and without, across the scenarios.

## A seeded generator that draws in a set's order
- **Pitfall:** a generator seeded for reproducible data draws its random numbers while looping over a Python set. It shows as a benchmark whose baseline row moves between two runs of the same code.
- **Why:** Python hashes strings differently in every process, so a set of entity IDs iterates in a different order each time, and the same draws land on different entities: which companies sit at their representative's address, in `er.generate.kind_problems`, would change from run to run.
- **Guard:** every draw follows a fixed order: the entities' own order (`pd.unique`), never a set's.
- **Check:** a test generates the person-or-company problems in two processes with different `PYTHONHASHSEED` and requires identical records.

## A model judged that isn't the one that runs
- **Pitfall:** a script that chooses between configurations builds its own copy of a training set. Its verdict then holds for a model no run uses. It shows as a ranking that moves when the copy is replaced by the real one.
- **Why:** a copy with another seed, or the same names written another way (each persona written once and duplicated, where the run writes each twice), trains another model, and the ranking of the 48 finalists moves with it by many places.
- **Guard:** `scripts/choose_kind.py` trains its public name model on `er.generate.kind_training_names`, as `er.generate.train_name_model` does, and judges by `[kind]`'s own budgets.
- **Check:** `reports/choose_kind.md`, written from the run's own training names.

## Measurements run into a folder that keeps people's work
- **Pitfall:** a benchmark resolves its baseline into a run folder that an earlier, labelled run used. The baseline then carries that run's answers. It shows as a baseline better than it is.
- **Why:** a full run keeps people's answers across `--overwrite`, as it must for real work. Three ways of routing resolved into one folder hand each the answers of the labelled run before it: about 3,000 truth answers, most of them exactly the flag's errors, would correct the flag-alone baseline.
- **Guard:** each routing gets a fresh folder of its own.
- **Check:** `reports/benchmark.md`, written with fresh folders.

## A measuring draw taken from what review left
- **Pitfall:** records sent to people because they look wrong are a biased sample, and so is a draw taken from the records left after them, or one stratified to hold more of the records the engine is surest of. Placing a line or measuring an error rate on any of them misjudges it. It shows as a line that holds on the answers and breaks on the file.
- **Why:** the records sent to decide are those where the engine and the flag disagree, where the errors gather; taking them out of the measuring draw leaves the easy records. A stratified draw puts more of the surest records above each line than the file has there, so the error above it looks smaller than it is.
- **Guard:** `kind.kind_review_sheet` draws the measuring rows first, at random from every record with a name, then the records to decide from the rest. `kind.classifier` places the lines and measures the flag on the measuring answers only, and fits the combiner on all of them.
- **Check:** a test checks the sheet's two kinds of rows and their reasons; the benchmark's "Person or company" section counts the wrong calls on every record.

## A line placed at zero errors on a few hundred labels
- **Pitfall:** "no labelled error above the line" on a few hundred labels says little about a 0.1% error rate: a sample with 100 companies in it passes a line that lets one call in a hundred go wrong. It shows as a line that holds on the labels and breaks on the file, in some files and not in others.
- **Why:** no error in n draws bounds the rate only near 3/n.
- **Guard:** the company line is two grid steps stricter than the first clean one on a measuring draw of 2,000 records at random, and three on fewer answers: on 1,000, two steps broke the budget in 4 of 60 trials. The person line asks for a wrong share within its budget at 95% confidence: a share of at most half the budget, measured on as few as 30 answers, broke the budget in 4 of 60 trials.
- **Check:** `reports/choose_kind.md`, placing the lines: in how many of the 12 scenarios each number of answers and each rule breaks the budget.

## An increment that drops the review queue
- **Pitfall:** pairs waiting for a decision vanish when the next run writes a new review sheet, though they are still open.
- **Why:** a run keeps no scores, so a sheet written from an increment's own scores holds only the pairs its batch made.
- **Guard:** an increment keeps the previous sheet's rows that nobody gave back and whose records are still apart, with any decision typed in, and adds its own.
- **Check:** a test decides one pair, runs an increment, and checks that the others are still on the sheet and the decided one is not.

## A nearly empty field that stops the fit
- **Pitfall:** a field filled on very few records makes the fit stop with a long traceback from Splink.
- **Why:** the fit learns m from pairs that share a phone, and from pairs that share an address. If no two records of its sample share an address, Splink refuses a learning rule with no pairs.
- **Guard:** a rule that finds no pair is skipped, and the summary names it; the field still counts where it is filled. With no rule left, the run stops with two lines saying what to fix.
- **Check:** a test empties the address and then the phone too.

## An engine upgrade that changes the API
- **Pitfall:** a new major version of the database changes its Python API. It shows as a run that hangs on its second query, or fails on `fetchone`.
- **Why:** in DuckDB 2.0 a relation has no `fetchone`, and an `execute()` whose rows are not all fetched holds the connection. The connection-level `fetch_record_batch` is gone, and the `x -> …` lambda syntax is deprecated.
- **Guard:** every query fetches its rows (`.fetchall()`), the chunked reader has a cursor of its own, and lambdas are written `lambda x: …`.
- **Check:** `requirements.txt` pins DuckDB, and `tests/` runs every generator and a whole run on it.

## Reference data traps
- **Pitfall:** reference data that looks complete but isn't. It shows as odd names among the generated companies, or prefectures missing from the generated addresses.
- **Why:** Wikidata's transitive `company` tree, for Japanese companies with kana, holds mostly dissolved municipalities. yubinbango writes prefecture codes without the leading zero (`1`, not `01`), so a join on two-digit codes silently drops the nine prefectures coded 01–09.
- **Guard:** only direct company types give real companies, and the prefecture codes are zero-padded.
- **Check:** [data.md](data.md) records what each reference file holds, down to the towns in all 47 prefectures.

## Test that informs a choice
- **Pitfall:** scoring test while developing turns it into another selection set, and its numbers stop being unbiased. Nothing in the numbers shows it.
- **Why:** every look at test before the choices are final is a chance for a choice to follow it.
- **Guard:** choices are made on train and confirmed on val, by rule. A leaderboard records every run and counts the distinct configurations scored on each population's test; `scripts/choose.py` stops above 1 per stage. `scripts/choose.py --no-test` runs a development round with test left unseen, and a newly generated population starts its count afresh. A deliberate clean pass on the same population first archives the leaderboard (`data/artifacts/experiments/archive/`).
- **Check:** a test counts test evaluations per population, and [`reports/choose.md`](../reports/choose.md) ends with the count: 1 for each stage.
