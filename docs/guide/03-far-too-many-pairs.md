[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · **3 Pairs** · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Measuring](06-measuring-and-choosing.md)

# 3. Far too many pairs

*Challenge C3.*

## Challenge: comparing everything is impossible

To find every duplicate, we would compare every record with every other one. The number of pairs grows with the square of the file size:

| Records | Pairs to compare |
|---|---|
| 9,966 (our validation file) | 49,655,595 |
| 1,000,000 (a large file) | 499,999,500,000 (5 × 10¹¹) |

Only 2,215 of the 50 million validation pairs are true duplicates. Comparing all of them would waste almost all the work, and at a million records it would not finish in reasonable time.

## Solution: compare only promising pairs

The standard answer is **blocking**: compare two records only if they already share something. We generate a short list of **candidate pairs** in three ways, then score only those. A fourth way serves only while choosing.

**Key blocks.** Records that agree exactly on a key, such as the last four phone digits, form a block, and only pairs inside a block are compared. A block of k records holds k(k−1)/2 pairs, so the work for a key is:

$$P = \sum_{\text{blocks}} \binom{k}{2}$$

A key can combine fields, such as the phone and the prefecture. The configuration offers 17 keys, built from the phone, the address, the address code, the CIF ID, the folded names, the postal code, the prefecture and the birth date.

**One-deletion keys.** Each record also emits its value with each single character deleted, so two values one edit apart always share a key ([below](#keeping-every-potential-match)).

**Sorted neighbourhood.** Sort all records by a key, such as the folded name, and compare each record with the next three (a window of 4). A typo near the end of a name keeps the record close in the sorted order, so the pair is still found.

**TF-IDF neighbours,** while choosing only. Cut each name into overlapping pieces of 2–3 characters, give rare pieces more weight, and compare each record with its 5 most similar names (a cosine similarity of at least 0.5). This finds typos anywhere in a name, even in the first character. It is also the one generator that compares every record with every other, so the chosen pipeline leaves it out ([below](#scaling-to-a-million-records)).

**Only pairs the rules have not settled.** The rules in [chapter 4](04-certain-cases-first-rules.md) settle the clear cases first. A generator lists only pairs that touch a record the rules left alone. A pair between two of their clusters is not listed ([below](#keeping-every-potential-match)).

### Why this solution

- **Keys cost almost nothing.** A database hash join finds all pairs in a block in about O(N + P) time. One-deletion keys cost O(N·L + P), for values of L characters.
- **The kinds catch different typos.** Keys need an exact agreement. One-deletion keys survive one typo anywhere. Sorted neighbourhood survives late typos, and sorting the reversed name too survives early ones.
- **Every key is measured before use.** Before any join, a run counts P for every key. A block of 64 or more records sharing one value is checked on a sample of about 2,000 of its pairs first. The sample is scored as the candidates will be, with the model and the u measured on the file, and the block is joined in full only if a sampled pair reaches 6 bits, the review floor. A big block holds few true matches, and a placeholder's block (a dummy phone) holds none. While choosing, `scripts/choose.py` also projects every key to the target size, which keeps out keys that grow by many normal blocks ([below](#how-the-configuration-keeps-it-that-way)).

## How do we know a candidate list is good?

Two numbers, which pull in opposite directions:

- **Completeness:** the share of the true duplicates the list contains. A pair that is not on the list can never be found later.
- **Reduction ratio:** the share of all pairs we skip.

On train, for the 6,177 true pairs the rules missed. Each generator is listed with the pairs it makes, and the share of the missed pairs on the list so far:

| Generators, added one by one | Pairs they make | Missed pairs on the list |
|---|---|---|
| phone | 46,675 | 27.0% |
| + address, address code, CIF ID | 11,607 | 48.5% |
| + folded person and company names | 4,397 | 79.5% |
| + sorted neighbourhood (person, company) | 85,502 | 84.3% |
| + TF-IDF (person, company) | 30,897 | 86.1% |
| + the scalable generators and the birth date (below) | 83,154 | 88.8% |

The folded names find the most for the pairs they make; the sorted windows make the most pairs. The chosen pipeline (`config/final.toml`) keeps 21 of these 26 generators. It leaves out the phone, the address and the address code alone, which grow with the square of the file, and TF-IDF, which compares every name with every other (next sections). On validation it lists **50,923 candidates holding 86.1% of the 2,000 true pairs the rules missed**, while still skipping 99.90% of all pairs. On train, every true pair that could reach the threshold shares one of its keys, at train's size and at a million records ([below](#keeping-every-potential-match)), so the pairs it leaves out lack the evidence to be accepted.

**In short:** a few cheap keys find most duplicates; the extra generators buy the last few points.

## What it costs: keys that grow with the square

The phone key is useful but dangerous. The last four digits have only 10,000 possible values, so unrelated people collide by chance. With N records spread over 10,000 values, the chance collisions alone are about:

$$P \approx \frac{N^2}{2 \times 10{,}000}$$

On train (30,103 records) that gives about 45,300 chance pairs, and the count finds 45,079 pairs of different entities sharing a phone. Another 2,296 are true duplicates: 33.2% of train's 6,920 true pairs share a phone. Together they make the 47,375 pairs that `estimate` counts in the phone blocks.

At a million records, the same formula gives **50 million** chance pairs from the phone key alone. That's why every key is projected to the target size before it is used.

Two more costs:

- **A missed candidate is lost for good.** On val, 13.9% of the true pairs the rules missed are on no list, and the second stage can never find them. On train, every true pair that could reach the threshold shares a key, so the pairs left out are those without the evidence to be accepted.
- **Sorted neighbourhood fails on early typos.** A wrong first character moves a record far away in the sorted order. A second pass on the reversed name finds those, unless the name has typos at both ends.

**In short:** blocking sets the ceiling on recall, and keys with few values blow up at scale.

## Scaling to a million records

The labelled files hold 10,000 to 30,000 records, and the pipeline must run on files of a million records and more. So every step is priced by its time complexity, and every key by how its pairs grow with the file.

### Where the work grows faster than the file

For each key, `scale_check` splits its pairs on train into pairs of one entity, which grow like N, and chance pairs between two entities, which grow like N². It projects both to a million records and reports a **growth exponent** α, with work ∝ N^α. At α = 1 the work is linear: ten times the records, ten times the work. At α = 2 it is quadratic: ten times the records, a hundred times the work. The times are from a whole run on 1,000,338 records ([below](#measured-a-whole-run-up-to-a-million-records)).

| Step | Cost | Grows like | At a million records |
|---|---|---|---|
| load and standardize | O(N·L) | N | 6.89 s |
| fit | O(n + S·K + P_em·K) + O(N + S·K) | a fixed sample, plus O(N) counts | 9.24 s |
| rules | O(N + ΣP_r·L²) + O(E·d + N) | N^1.0 to N^1.16 per rule | ≤ 0.14 million pairs per rule; 2.23 s |
| **rule F2, joined on the phone alone** | O(N + P) | **N^1.95** | **50 million pairs**, the phone key's blocks |
| key: **phone alone** | O(N + P) | **N^1.95** | **50 million pairs**, nearly all by chance |
| keys: **address alone, address code alone** | O(N + P) | **N^1.84, N^1.72** | **5.4 and 5.3 pairs per record**, over the budget of 5 |
| the chosen keys and one-deletion keys | O(N + P), O(N·L + P) | N^1.0 to N^1.82 | ≤ 1.7 million pairs each |
| sorted neighbourhood | O(N log N + N·w) | N | 3 million pairs per pass |
| **TF-IDF neighbours** | O(N·L + U·N·q) | **N^2.0** | **10¹² similarities** |
| candidates | O(N·L + ΣP_g) | as ΣP_g | 6.24 s |
| score | O(C·K·L²) | as C | 15.22 s |
| cluster | O(C + E·d + N) | N | 0.27 s |

*N records · n = 30,000 records in the fit's sample · S = 10⁷ pairs sampled for u · K comparisons (6) · P_em pairs in EM's blocks · L characters in a value · P_r, P_g pairs in a rule's or a generator's blocks · w the window · U records queried, q n-grams per name · C candidates · E accepted pairs · d the largest cluster's diameter. Every symbol and step: [performance](../performance.md#end-to-end-the-cost-of-every-step).*

Everything is near-linear except two kinds of step:

1. **A key with a fixed pool of values.** The last four phone digits take only 10,000 values, however large the file. Chance collisions grow like N²/(2 × 10,000), while true duplicates grow only like N. Both the phone key and rule F2 on the phone rest on it. Addresses are such a pool too: households share them, and a country has only so many.
2. **All-against-all similarity.** TF-IDF compares each record the rules left alone with every record, so its work grows like N².

The chosen keys still grow faster than N in part, but from a far smaller constant: the largest, phone + name initial, projects to 1.7 pairs per record.

### The fixes

Every fix passes the decision rule that judges every other change ([chapter 6](06-measuring-and-choosing.md)). A change adopted because it is *cheaper* may lose no true pair on cross-validated train or on val, and may add no false pair.

**Fix 1: the phone key becomes three compound keys.** A true duplicate that shares its phone digits almost always shares something coarse as well. A chance collision rarely does. So instead of the phone alone, we block on:

- phone + prefecture,
- phone + postal area (the first 3 digits of the postal code),
- phone + name initial (the first character of the person name, else the company name, folded, legal form removed).

Each key splits the 10,000 phone values into hundreds of thousands of combinations or more. At a million records, the phone key alone projects to 50 million pairs; the three compound keys to 3.0 million together, each under the budget of 5 per record.

*Decision:* 0 true pairs gained or lost, on cross-validated train and on val. **Adopted.** These keys still grow faster than N (α = 1.47, 1.09 and 1.46), from a much smaller constant. The check below would flag them first if files grew well past a million.

**Fix 2: TF-IDF becomes a second sorted pass.** TF-IDF earns its place by finding typos near the start of a name, which a sorted order misses. Drop the ト from サトウヒロシ, and サウヒロシ sorts far away, among the names that begin with サウ. Sorted by the **reversed** name, the two stay close (シロヒウサ, シロヒウトサ), because they end alike. Two sorted passes cost O(N log N) each, against TF-IDF's N².

*Decision:* +1 true pair and 0 lost on cross-validated train; +4 and 0 on val. **Adopted.**

**Fix 3: rule F2 joins on more than the phone.** F2 accepts a pair with a similar name, a similar address (Jaro–Winkler 0.9 or more) and the same phone. With the address fuzzy, the phone is its only exact key, so a join on the phone alone would inherit the phone's N² growth. So F2 joins on the phone and the first three characters of the normalized address (the start of the city, such as 福島市), and checks the name and the address on the joined pairs:

| F2 joins on | Pairs at a million records | Train: true pairs lost | Val: lost | Adopted |
|---|---|---|---|---|
| phone alone | 50 million | — | — | over budget |
| phone + first 3 characters of the normalized address | 0.14 million | 0 | 0 | **yes** |

An exact address would defeat F2's purpose, which is address typos. The first three characters survive typos later in the address.

**Fix 4: fit on a fixed-size sample, then measure u on the file.** The fit takes a fixed sample of 30,000 records, made of whole postal areas, so a household's records stay together. On it, λ (the chance that two random records are the same entity) comes from near-certain rules, and m from EM. The fit's own u sample, 10⁶ pairs, feeds only EM. Then u, how often two different entities agree on a field by chance, is measured on the whole file:

- **Counted** for the leading exact levels, from value counts.
- **Counted** for a one-edit level right after them on the same column: the CIF ID, the phone and the birth date "one digit off". The distinct values are joined on their one-deletion keys, so these three comparisons need no sample at all.
- **Sampled** for the other levels of the name, the company and the address, from 10⁷ random pairs, every one of them used.

The gate on oversized blocks and the scores both use these u. The fit costs O(n + S·K + P_em·K) and u on the file O(N + S·K): fixed, apart from the O(N) counts. Each u sample is kept per comparison and the values it reads (`er.match.scored_sample`), so a file no bigger than the fit's sample is sampled once. Cross-validation and Optuna run on train only. A run fits on the file it resolves (or takes `scripts/choose.py`'s model, fitted on train, with `--model`), then scores the whole file, with λ rescaled to the file's size ([chapter 5](05-uncertain-evidence-fellegi-sunter.md)). An increment keeps the stored model and refreshes u before its rules: the counted levels are counted again, and a sampled comparison is sampled again only once its drift outgrows its sampling error.

**Not chosen:**

- **A cap on how common an n-gram may be in TF-IDF.** It is linear, but the share of typo pairs it keeps falls as the file grows. The loss would keep growing with the file.
- **TF-IDF as an exact sparse matrix product.** Cheaper, and still N².
- **TF-IDF within each prefecture.** It misses people who moved, and records without a prefecture.

### Keeping every potential match

The fixes above are judged by the pairs the chosen pipeline accepts. A stricter test asks about the pairs it *could* accept. Call a true pair a **potential match** if its fields, once compared, would reach the 8-bit threshold. Blocking must keep every potential match, at every file size. A pair that falls short with all its evidence counted can never be accepted, whatever list it is on.

What counts as potential depends on the file size. λ shrinks as the file grows, so the same evidence earns fewer bits: about log2(N / 30,000) fewer than on train. u moves too, because u is measured on each scored file ([chapter 5](05-uncertain-evidence-fellegi-sunter.md#challenge-learning-m-u-and-λ-without-labels)): on fields whose values grow with the file, strangers agree less often, so an agreement earns more. That makes every size testable on the training file. Score its true pairs once, then move λ to the target size, and u by the growth measured between half and all of train's entities. The pairs still at 8 bits or more are the potential matches at that size.

**Challenge: a sorted window reaches less as the file grows.** A sorted neighbourhood compares each record with the next three in name order. In a bigger file, more records sort between two similar names, so fewer true pairs fall inside the window. The window needed grows with the file: a fixed window loses pairs, and a growing one costs N². Most of these pairs share another key anyway: an address, a CIF ID, a phone. A potential match that shares none is left to the window, and so to the file's size.

**Solution: keys, whose reach does not depend on the file size.** Two records share a key or they don't, however many records lie between them. Five name keys cover the pairs a window would otherwise have to find:

| Key | What it guarantees | Pairs at a million records |
|---|---|---|
| person name, exact (folded) | every pair with the same name | 0.61 million |
| company name, exact | every pair with the same company name | 0.35 million |
| company name, one-deletion keys | every pair of company names one edit apart | 0.84 million |
| person name, one-deletion keys within the postal area | every pair of names one edit apart in one postal area | 0.08 million |
| given name + postal code | a surname change at the same postal code | 0.06 million |

With them, **no potential match on train depends on a window**: 0 of 3,036 at train's size, and 0 of 2,960 at a million records. Without the windows, val loses 1 true pair (cross-validated train: none gained or lost), so the windows stay.

**One-deletion keys.** Each record emits its value, and the value with each single character deleted. サトウヒロシ gives サトウヒロシ, トウヒロシ, サウヒロシ, サトヒロシ, サトウロシ, サトウヒシ and サトウヒロ. Two names one edit apart always share one of these keys:

- **A substituted character** (サトウヒロシ, サトウヒロミ): deleting it from both gives サトウヒロ.
- **A dropped character** (サトウヒロシ, サトヒロシ): the shorter name is itself a deletion of the longer.
- **Two neighbours swapped** (サトウ, サウト): deleting the ウ from both gives サト.

A name of L characters emits L + 1 keys, so the work is O(N·L + P). Spelling correctors such as SymSpell use the same idea, called symmetric deletion. The keys are unnested once, into one table that the count, the join and the sample check of big blocks all read; an increment keeps only the blocks its batch reaches. The chosen pipeline uses them for company names, for person names within the postal area, for the CIF ID and for the birth date within the prefecture. The same idea counts u for the "one digit off" levels (Fix 4).

**Why within the postal area?** Many short names differ from another person's by one kana. On their own, the person-name deletion keys would pair them across the whole country. Within the postal area they grow like N^1.01. A potential match whose names are one edit apart but whose postal areas differ needs strong evidence from another field, and that field has a key of its own. The coverage check below confirms this on train.

**Two rule clusters of one entity.** The rules sometimes split one entity into two clusters. Candidates must touch a record the rules left alone, so no pair between two such clusters is scored. Scoring every pair across two clusters (`[model] bridge`) is an option. A false pair there would merge both clusters, so it must pass as *better*, with a significant gain. It gains no true pair on cross-validated train or on val, so it is not adopted.

| Change | Kind | Cross-validated train | Val | Adopted |
|---|---|---|---|---|
| the five name keys | safer | +1 / −0 true pairs, no false pair added | +0 / −0 | yes |
| the address only with another field (next) | cheaper | +0 / −0, no false pair added | +0 / −0 | yes |
| no sorted windows | cheaper | +0 / −0 | +0 / −1 | no |
| score every pair across two clusters | better | +0 / −0 | +0 / −0 | no |

"Safer" is the cheaper test for a change that adds pairs: it may lose no true pair and add no false one. Its gain shows at scale, and the coverage check below measures it.

**Challenge: an address alone grows with the square.** A key's pairs are of two kinds. Pairs of one entity grow like N: a bigger population of the same kind has proportionally more duplicated entities. Chance pairs between two entities grow like N², whenever the key's values come from a pool that doesn't grow with the file, because two entities then share a value with the same probability at any size. Addresses are such a pool: households share them, and a country has only so many. On train, 4,828 of the address key's 5,507 pairs join two different entities, and projected that way they reach **5.4 pairs per record at a million records**, over the budget of 5. The address code makes 5.3.

**Solution: the address only with one more field.** A true pair that shares an address almost always shares something else with it: the phone digits, the name's first letter, or, after a marriage, the given name. Two households at one address rarely do. So the address and the address code are each combined with the phone and with the name's first letter, and the address code with the given name:

| Key | Pairs per record at a million records |
|---|---|
| address alone, address code alone | 5.4 and 5.3 |
| address + phone, address code + phone | 0.01 and 0.02 |
| address + the name's first letter, address code + the name's first letter | 0.23 and 0.28 |
| given name + address code | 0.03 |

With these five keys, every potential match on train still shares a key, at its size and at a million records. The decision rule adopted them as cheaper: no true pair lost or false pair added, on cross-validated train or on val.

### How the configuration keeps it that way

`scripts/choose.py` projects every key and rule of the chosen pipeline to `budget.target_rows` (a million records) and stops if one would exceed the budget of 5 pairs per record (`er.pipeline.scale_check`). It needs only the training file. For each key it counts the pairs of one entity, P_same, and the chance pairs, P_chance, and projects each by its own law: P(n) = P_same·n/N + P_chance·n(n − 1)/(N(N − 1)). That is what keeping a share of the entities would give on average, computed instead of sampled. Pairs between two members of a household count as chance, the safe side. Optuna trials that fail the check are pruned.

For the chosen pipeline, the largest projection of a key is phone + name initial, at 1.7 pairs per record; each sorted window makes 3 per record by construction. The check also counts the potential matches on train that share no key, at train's size and at a million records (`window_only`), and stops if any is left. Here: 0 of 3,036, and 0 of 2,960.

Without labels, a run can check only the patterns: every combination of comparison levels that could reach the threshold must imply a shared key (`pattern_coverage`, in every run's QA report). A Jaro–Winkler level implies none, so a pattern built on close names counts as uncovered even when another key, in practice, joins it. For the chosen pipeline at a million records, 226 patterns are uncovered, and the model puts their share of matches at 11.9% at most. The largest pair a close company name with the same address or the same phone. On labelled train, every potential match shares a key (above).

### Measured: a whole run, up to a million records

`scripts/benchmark.py` generates files of growing size and resolves each with `scripts/resolve.py`, in a process of its own, as a real run: on DuckDB tables, fitted on the file itself, without labels, under an 8 GB memory limit ([reports/benchmark.md](../../reports/benchmark.md)):

| Records | Fit | Rules | Candidates | Score | Total | Peak memory |
|---|---|---|---|---|---|---|
| 12,532 | 7.16 s | 0.06 s | 0.22 s | 0.23 s | 8.0 s | 0.72 GB |
| 24,955 | 7.66 s | 0.09 s | 0.33 s | 0.33 s | 8.9 s | 0.86 GB |
| 50,116 | 7.68 s | 0.14 s | 0.57 s | 0.69 s | 10.0 s | 0.93 GB |
| 74,959 | 7.91 s | 0.20 s | 0.80 s | 0.74 s | 11.0 s | 1.08 GB |
| **1,000,338** | **9.24 s** | **2.23 s** | **6.24 s** | **15.22 s** | **43.0 s** | **5.85 GB** |

A million records take 43.0 seconds. The fit, on a fixed sample, and the u sample of the file inside it, 10 million pairs, cost about the same at any size, so at these sizes the total grows far slower than the file. Without them, the work grows about linearly with it. Peak memory is the process's, Python included: 5.85 GB at a million records, under the 8 GB limit. The cost of every step, for a full run and for an increment, is in [performance.md](../performance.md).

Three choices keep a million records within bounds:

- **DuckDB reads only what a step needs.** The scores stay in DuckDB, which reads only the columns used. Copied into pandas with every compared field of both records, they would not fit ([lessons.md](../lessons.md#a-copy-that-outgrows-memory)).
- **The lists merge in SQL.** Each generator sets one bit, and one query ORs them, so no Python code runs once per pair ([lessons.md](../lessons.md#linear-work-done-one-pair-at-a-time-in-python)).
- **Tables spill to disk.** Every table of size N or C is a DuckDB table, which spills to disk past the memory limit: to `.tmp/` under the folder a run starts in, unless `[compute] temp_directory` says otherwise. A run counts the room DuckDB may spill to (90% of the free disk) in its capacity. pandas holds only one chunk of the file at a time, and small summaries.

The generator has 60,000 distinct personas. Beyond that it must reuse them, which creates clones no matcher can tell apart, so the million-record row measures cost only.

### Quality as the file grows

Up to 75,000 records, every entity is still a distinct persona, so quality can be measured too. Each file is fitted on itself, without labels:

| Records | Recall | False merges | False-merge rate ≤ |
|---|---|---|---|
| 12,532 | 45.7% | 2 | 0.48% |
| 24,955 | 46.0% | 0 | 0.12% |
| 50,116 | 44.7% | 0 | 0.06% |
| 74,959 | 44.2% | 4 | 0.12% |

On train, every true pair that could reach the threshold shares a key, at its size and at a million records. Two things change as the file grows:

- **False pairs appear.** A bigger file holds more pairs of different entities that look alike. The run joined 2 false pairs at 12,532 records, through 1 false link, and 4 at 74,959, through 3. Each is a model link between 8.2 and 10.1 bits (the threshold is 8), between near-namesakes with a kana typo who share an address or a phone. The model expects them: the sum of 1 − match probability over its links, which every run reports without labels, is 0.84 at 12,532 records, 4.38 at 74,959, and 30.11 of 38,787 links at a million. The bound on the false-merge rate is 0.48% at 12,532 records, above the 0.28% reported for test, and 0.06–0.12% at the larger sizes.
- **Recall stays within two points,** between 44.2% and 46.0%. u is measured on each scored file, so an agreement on a field whose values grow with the file, such as the address or the CIF ID, earns the credit it has at that size ([lessons.md](../lessons.md#weights-fitted-at-one-file-size-used-at-another)). On the labelled splits, which are no bigger than train, this choice costs true pairs: 60 on cross-validated train and 12 on val (`u_from_scored_file`, adopted as "chosen", [chapter 6](06-measuring-and-choosing.md)).

**In short:** two kinds of step grow with the square of the file: keys whose values come from a fixed pool (the phone digits, the address), and all-against-all similarity. Compound keys, a reversed sorted pass and a narrower F2 join keep both in check. A sorted window reaches fewer pairs as the file grows, so five more keys make sure no potential match depends on one. A million records take 43.0 seconds, with peak memory 5.85 GB under an 8 GB limit, on DuckDB tables that spill to disk past it.

## In the code

- `er/config.py`: the generator types `KeyBlocker`, `SortedNeighbourhood`, `TfidfNeighbours`, `DeletionKeys` (one-deletion keys); `er/candidates.py`: each as SQL (`pairs_sql`), `candidates` (merge by bits), `estimate` (the count before any join)
- `er/pipeline.py`: `grown_pairs` (a key's pairs of one entity and by chance, each projected by its own law), `scale_check` (every key and rule projected to `target_rows`), `window_only` (the potential matches no key reaches), `pattern_coverage` (the same question without labels) and `cascade`'s `bridge` (a stage that may join two clusters)
- `er/config.py`: `Budget` (`max_pairs_per_record`, `max_block_size`, `target_rows`, `sample_pairs`); `FSSpec.bridge` (score every pair across two clusters)
- `er/match.py`: `exact_u` (u counted: the leading exact levels, and a one-edit level after them through one-deletion keys), `scored_sample` (u sampled, kept per comparison and the values it reads), `assemble_u`, `refreshed_u` (an increment's u)
- `config/pipeline.toml`: every generator, in logical fields; `config/settings.toml`: the fields behind the compound keys (`any_name`, the postal area) and the normalizers `initial`, `first3`, `reverse`
- `config/experiments.py`: the key changes and their decisions (`compound_phone_keys`, `sorted_names_for_tfidf`, `name_keys`, `bounded_address_keys`, `no_sorted_windows`, `bridge_rule_clusters`), and the u changes (`u_exact_by_counts`, `u_near_by_keys`, `fit_u_from_1e6_pairs`)
- `er/select.py`: `FSChooser.candidates_on_train` prints the generator table above; `will_it_scale` stops `scripts/choose.py` if the chosen pipeline would go over budget at `target_rows`, or would leave a potential match to a window; `RulesChooser.cost` does the same for the rules
- `er/run.py`: `Run.budget`, the exact count on the file before any join; `Run.fit`, the fit and then u on the file; `Run.capacity`, the memory limit plus the spill room; `er/candidates.py`: `oversized`, `sample_sql`, `_gate`, the sample check of big blocks; `scripts/benchmark.py`: whole runs on generated files from 12,500 to a million records

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 4 (indexing).
- P. Christen, "A survey of indexing techniques for scalable record linkage and deduplication," *IEEE Transactions on Knowledge and Data Engineering* 24(9), 2012.
- G. Papadakis et al., "[Blocking and filtering techniques for entity resolution: a survey](https://arxiv.org/abs/1905.06167)," *ACM Computing Surveys* 53(2), 2020.

**Next:** [4. Certain cases first: rules →](04-certain-cases-first-rules.md)
