[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · **3 Pairs** · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Kinds](06-person-or-company.md)

# 3. Far too many pairs

*Challenge C3.*

## Challenge: comparing everything is impossible

To find every duplicate, we would compare every record with every other one. The number of pairs grows with the square of the file size:

| Records | Pairs to compare |
|---|---|
| 10,496 (our validation file) | 55,077,760 |
| 1,000,000 (a large file) | 499,999,500,000 (5 × 10¹¹) |

Only 2,494 of the 55 million validation pairs are true duplicates. Comparing all of them would waste almost all the work, and at a million records it would not finish in reasonable time.

## Solution: compare only promising pairs

The standard answer is **blocking**: compare two records only if they already share something. We generate a short list of **candidate pairs** in two ways, then score only those.

**Key blocks.** Records that agree exactly on a key, such as the last four phone digits, form a block, and only pairs inside a block are compared. A block of k records holds k(k−1)/2 pairs, so the work for a generator is:

$$P = \sum_{\text{blocks}} \binom{k}{2}$$

A generator's key can combine fields, such as the phone and the prefecture. `score.sql` writes 18 generators of such keys, built from the phone, the address, the address code, the CIF ID, the folded names and their readings, the postal code, the prefecture and the birth date.

**One-deletion keys.** Each record also emits its value with each single character deleted, so two values one edit apart always share a key ([below](#keeping-every-potential-match)). `score.sql` writes four generators of them. Together they are the 22 **candidate generators**, each written once and chosen by name in `config.toml` `[score] generators`.

**Two more, measured at design time and left out.** A **sorted neighbourhood** sorts all records by a value, such as the folded name, and compares each record with the next three (a window of 4): a typo near the end of a name keeps the record close in the sorted order. Its reach shrinks as the file grows ([below](#keeping-every-potential-match)). **TF-IDF neighbours** cut each name into overlapping pieces of 2–3 characters, give rare pieces more weight, and compare each record with its 5 most similar names (a cosine similarity of at least 0.5): this finds typos anywhere in a name, even in the first character. It compares every record with every other ([below](#scaling-to-a-million-records)).

**The rules' pairs too.** A pair a rule finds ([chapter 4](04-certain-cases-first-rules.md)) is listed and scored like any other: nothing is settled before people decide it.

### Why this solution

- **Keys cost almost nothing.** A database hash join finds all pairs in a block in about O(N + P) time. One-deletion keys cost O(N·L + P), for values of L characters.
- **The two catch different typos.** Keys need an exact agreement. One-deletion keys survive one typo anywhere.
- **Every block is measured before use.** Before any join, a run counts the records of every block its batch reaches. A block of 64 or more records sharing one value (`[score] oversized`) is checked on a sample of its pairs first: 64 of its new records against 64 of all its records, chosen by hash, about 2,000 pairs in a build. The sample is scored as the candidates will be, with the model and the u measured on the file, and the block's pairs are all listed only if a sampled pair reaches 0 points, the search floor (`[score] search_floor`): below the 4 points people review, so a pair a better model would lift is already found. A big block holds few true matches, and a placeholder's block (a dummy phone) holds none. At design time every generator of the method is also projected to a million records, which keeps out generators that grow by many normal blocks ([below](#how-the-configuration-keeps-it-that-way)).

## How do we know a candidate list is good?

Two numbers, which pull in opposite directions:

- **Completeness:** the share of the true duplicates the list contains. A pair that is not on the list can never be found later.
- **Reduction ratio:** the share of all pairs we skip.

Measured at design time on train, for the 6,355 true pairs the rules missed. Each generator is listed with the pairs it makes, and the share of the missed pairs on the list so far:

| Generators, added one by one | Pairs they make | Missed pairs on the list |
|---|---|---|
| phone | 50,939 | 27.0% |
| + address, address code, CIF ID | 13,098 | 48.2% |
| + folded person and company names | 4,492 | 79.5% |
| + sorted neighbourhood (person, company) | 88,858 | 84.3% |
| + TF-IDF (person, company) | 33,126 | 86.1% |
| + the scalable generators, the name's reading and last sounds, and the birth date (below) | 96,672 | 89.2% |

The folded names find the most for the pairs they make; the sorted windows make the most pairs. The method lists pairs by 22 of these 30 generators, all of which make keys. It leaves out the phone, the address and the address code alone, which grow with the square of the file, TF-IDF, which compares every name with every other, and the sorted windows, whose reach shrinks as the file grows (next sections). On validation it lists **2,869 candidates holding 79.6% of the 2,198 true pairs the rules missed**, while skipping 99.995% of all pairs. On train, every true pair that could reach the threshold shares one of its keys, at train's size and at a million records ([below](#keeping-every-potential-match)), so the pairs it leaves out lack the evidence to reach the threshold.

**In short:** a few cheap generators find most duplicates; the extra ones buy the last few percentage points.

## What it costs: generators that grow with the square

The phone generator is useful but dangerous. The last four digits have only 10,000 possible values, so unrelated people collide by chance. With N records spread over 10,000 values, the chance collisions alone are about:

$$P \approx \frac{N^2}{2 \times 10{,}000}$$

On train (31,226 records) that gives about 48,800 chance pairs, and the count finds 49,342 pairs of different entities sharing a phone. Another 2,359 are true duplicates: 33.2% of train's 7,102 true pairs share a phone. Together they make the 51,701 pairs in the phone's blocks.

At a million records, the same formula gives **50 million** chance pairs from the phone generator alone. That's why every generator is projected to the target size before it is used.

**A missed candidate is lost for good.** On val, 20.4% of the true pairs the rules missed are on no list, and the second stage can never find them. On train, every true pair that could reach the threshold shares a key, so the pairs left out are those without the evidence to reach it.

**In short:** blocking sets the ceiling on recall, and generators whose keys take few values blow up at scale.

## Scaling to a million records

The labelled files hold 10,000 to 30,000 records, and the method must run on files of a million records and more. So every step is priced by its time complexity, and every generator by how its pairs grow with the file.

### Where the work grows faster than the file

Each generator's pairs on train split into pairs of one entity, P_same, which grow like N, and chance pairs between two entities, P_chance, which grow like N². Their mix gives a **growth exponent** at train's size, α = (P_same + 2·P_chance) / (P_same + P_chance), with work ∝ N^α. At α = 1 the work is linear: ten times the records, ten times the work. At α = 2 it is quadratic: ten times the records, a hundred times the work. A run has four stages, each a SQL file; the rules, the keys and the scores are parts of the third. The times are from a whole build on 1,039,995 records ([below](#measured-a-whole-run-up-to-a-million-records)).

| Step | Cost | Grows like | At a million records |
|---|---|---|---|
| `records.sql`: read, standardize, persons and companies | O(N·L) | N | 9.83 s |
| `fit.sql`: the model on its sample, then u on the file | O(n + S·K + P_em·K) + O(N + S·K) | a fixed sample, plus O(N) counts | 6.03 s |
| `score.sql`, whole: the rules, the keys, the gate and the scores | O(N·L + ΣP_r·L² + ΣP_g + C·K·L²) | as ΣP_g and C | 14.83 s |
| · the rules | O(N + ΣP_r·L²) | N^1.0 to N^1.21 per rule | ≤ 0.18 million pairs per rule |
| · **rule F2, joined on the phone alone** | O(N + P) | **N^1.95** | **50 million pairs**, the phone generator's blocks |
| · generator: **phone alone** | O(N + P) | **N^1.95** | **50 million pairs**, nearly all by chance |
| · generators: **address alone, address code alone** | O(N + P) | **N^1.85, N^1.74** | **5.8 and 5.7 pairs per record**, over the budget of 5 |
| · the chosen generators, exact and one-deletion | O(N + P), O(N·L + P) | N^1.0 to N^1.83 | ≤ 2.1 million pairs each |
| · **TF-IDF neighbours** | O(N·L + U·N·q) | **N^2.0** | **10¹² similarities** |
| · the scores | O(C·K·L²) | as C | |
| `decide.sql`: the entities people's decisions make | O(D + N) | N | 0.18 s |

*N records · n = 100,000 records in the fit's sample · S = 10⁷ pairs sampled for u · K comparisons (6) · P_em pairs in EM's blocks · L characters in a value · P_r, P_g pairs in a rule's or a generator's blocks · U records queried, q n-grams per name · C candidates · D people's decisions. The rows in bold are left out of the method. Every symbol and step: [performance](../performance.md#end-to-end-the-cost-of-every-step).*

Everything is near-linear except two sorts of step:

1. **A generator with a fixed pool of values.** The last four phone digits take only 10,000 values, however large the file. Chance collisions grow like N²/(2 × 10,000), while true duplicates grow only like N. Both the phone generator and rule F2 on the phone rest on it. Addresses are such a pool too: households share them, and a country has only so many.
2. **All-against-all similarity.** TF-IDF compares each record with every record, so its work grows like N².

The chosen generators still grow faster than N in part, but from a far smaller constant: the largest, phone + name initial, projects to 2.1 pairs per record.

### The fixes

Every fix passes the decision rule ([chapter 1](01-entity-resolution-and-our-task.md#a-rule-for-every-choice)), measured at design time on labelled synthetic data. A change adopted because it is *cheaper* may lose no true pair on cross-validated train or on val, and may add no false pair.

**Fix 1: the phone generator becomes three compound generators.** A true duplicate that shares its phone digits almost always shares something coarse as well. A chance collision rarely does. So instead of the phone alone, we block on:

- phone + prefecture,
- phone + postal area (the first 3 digits of the postal code),
- phone + name initial (the first character of the person name, else the company name, folded, legal form removed).

Each generator splits the 10,000 phone values into hundreds of thousands of combinations or more. At a million records, the phone generator alone projects to 50 million pairs; the three compound generators to 3.6 million together, each under the budget of 5 per record.

*Decision:* 0 true pairs gained or lost, on cross-validated train and on val. **Adopted.** These generators still grow faster than N (α = 1.52, 1.17 and 1.52), from a much smaller constant. The check below would flag them first if files grew well past a million.

**Fix 2: rule F2 joins on more than the phone.** F2 pairs two records with a similar name, a similar address (Jaro–Winkler 0.9 or more) and the same phone. With the address fuzzy, the phone is its only exact key, so a join on the phone alone would inherit the phone's N² growth. So F2 joins on the phone and the first three characters of the normalized address (the start of the city, such as 福島市), and checks the name and the address on the joined pairs:

| F2 joins on | Pairs at a million records | Train: true pairs lost | Val: lost | Adopted |
|---|---|---|---|---|
| phone alone | 50 million | — | — | over budget |
| phone + first 3 characters of the normalized address | 0.18 million | 0 | 0 | **yes** |

An exact address would defeat F2's purpose, which is address typos. The first three characters survive typos later in the address.

**Fix 3: fit on a fixed-size sample, then measure u on the file.** The fit takes a fixed sample of 100,000 records, made of whole postal areas, so a household's records stay together. On it, λ (the chance that two random records are the same entity) comes from near-certain rules, and m from EM. The fit's own u sample, 10⁶ pairs, feeds only EM. Then u, how often two different entities agree on a field by chance, is measured on the whole file:

- **Counted** for the leading exact levels, from value counts.
- **Counted** for a one-edit level right after them on the same column: the CIF ID, the phone and the birth date "one digit off". The distinct values are joined on their one-deletion keys, so these three comparisons need no sample at all.
- **Sampled** for the other levels of the name, the company and the address, from 10⁷ random pairs, every one of them used.

The gate on oversized blocks and the scores both use these u. The fit costs O(n + S·K + P_em·K) and u on the file O(N + S·K): fixed, apart from the O(N) counts. A run fits on the file it resolves, then scores the whole file, with λ rescaled to the file's size ([chapter 5](05-uncertain-evidence-fellegi-sunter.md)). An update scores its batch with the build's model, as a saved model is reused; report.txt says to build again once the run has grown by a tenth, which measures u on the run as it is.

**Not chosen, to keep TF-IDF:**

- **A cap on how common an n-gram may be in TF-IDF.** It is linear, but the share of typo pairs it keeps falls as the file grows. The loss would keep growing with the file.
- **TF-IDF as an exact sparse matrix product.** Cheaper, and still N².
- **TF-IDF within each prefecture.** It misses people who moved, and records without a prefecture.

### Keeping every potential match

The fixes above are judged by the pairs the method takes at its threshold. A stricter test asks about the pairs it *could* take. Call a true pair a **potential match** if its fields, once compared, would reach the 6-point threshold. Blocking must keep every potential match, at every file size. A pair that falls short with all its evidence counted can never reach it, whatever list it is on.

What counts as potential depends on the file size. λ shrinks as the file grows, so the same evidence earns fewer points: about log2(N / 30,000) fewer than on train. u moves too, because u is measured on each scored file ([chapter 5](05-uncertain-evidence-fellegi-sunter.md#challenge-learning-m-u-and-λ-without-labels)): on fields whose values grow with the file, strangers agree less often, so an agreement earns more. That makes every size testable on the training file. Score its true pairs once, then move λ to the target size, and u by the growth measured between half and all of train's entities. The pairs still at 6 points or more are the potential matches at that size.

**Challenge: a sorted window reaches less as the file grows.** A sorted neighbourhood compares each record with the next three in name order. In a bigger file, more records sort between two similar names, so fewer true pairs fall inside the window. The window needed grows with the file: a fixed window loses pairs, and a growing one costs N². Most of these pairs share another key anyway: an address, a CIF ID, a phone. A potential match that shares none is left to the window, and so to the file's size.

**Solution: keys, whose reach does not depend on the file size.** Two records share a key or they don't, however many records lie between them. Five name generators cover the pairs a window would otherwise have to find:

| Generator | What it guarantees | Pairs at a million records |
|---|---|---|
| person name, exact (folded) | every pair with the same name | 0.47 million |
| company name, exact | every pair with the same company name | 0.36 million |
| company name, one-deletion keys | every pair of company names one edit apart | 0.80 million |
| person name, one-deletion keys within the postal area | every pair of names one edit apart in one postal area | 0.12 million |
| given name + postal code | a surname change at the same postal code | 0.06 million |

With them, **no potential match on train depends on a window**: 0 of 3,278 at train's size, and 0 of 3,071 at a million records. Without the windows, no true pair is gained or lost, on cross-validated train or on val, so the method lists pairs by keys alone.

**One-deletion keys.** Each record emits its value, and the value with each single character deleted. サトウヒロシ gives サトウヒロシ, トウヒロシ, サウヒロシ, サトヒロシ, サトウロシ, サトウヒシ and サトウヒロ. Two names one edit apart always share one of these keys:

- **A substituted character** (サトウヒロシ, サトウヒロミ): deleting it from both gives サトウヒロ.
- **A dropped character** (サトウヒロシ, サトヒロシ): the shorter name is itself a deletion of the longer.
- **Two neighbours swapped** (サトウ, サウト): deleting the ウ from both gives サト.

A name of L characters emits at most L + 1 keys (deleting any one of a run of equal characters gives the same key, made once), so the work is O(N·L + P). Spelling correctors such as SymSpell use the same idea, called symmetric deletion. The keys are kept as the run's index (`every_key`): a batch makes its own records' keys and those of the records it makes again (`made_keys`), and they join the index. A batch then reads from the index only the blocks its keys name (`key_blocks`), which the count, the join and the sample check of big blocks all read, and lists only the pairs that touch it. The method uses them for company names, for person names within the postal area, for the CIF ID and for the birth date within the prefecture. The same idea counts u for the "one digit off" levels (Fix 3).

**Why within the postal area?** Many short names differ from another person's by one kana. On their own, the person-name deletion keys would pair them across the whole country. Within the postal area they grow like N^1.03. A potential match whose names are one edit apart but whose postal areas differ needs strong evidence from another field, and that field has a generator of its own. The coverage check below confirms this on train.

**The rules' pairs are no exception.** Every pair the keys list is scored, a pair a rule also finds too, and none merges before people decide it: so no rule pair keeps a pair from being listed.

| Change | Test | Cross-validated train | Val | Adopted |
|---|---|---|---|---|
| the five name generators | safer | +0 / −0 true pairs, no false pair added | +0 / −0 | yes |
| the address only with another field (next) | cheaper | +0 / −0, no false pair added | +0 / −0 | yes |
| no sorted windows | cheaper | +0 / −0 | +0 / −0 | yes |
| score every pair across two entities | better | +8 / −0 | +0 / −0 | yes |

"Safer" is the cheaper test for a change that adds pairs: it may lose no true pair and add no false one. Its gain shows at scale, and the coverage check below measures it.

**Challenge: an address alone grows with the square.** A generator's pairs are of two sorts. Pairs of one entity grow like N: a bigger population of the same sort has proportionally more duplicated entities. Chance pairs between two entities grow like N², whenever the key's values come from a pool that doesn't grow with the file, because two entities then share a value with the same probability at any size. Addresses are such a pool: households share them, and a country has only so many. On train, 5,589 of the address generator's 6,548 pairs join two different entities, and projected that way they reach **5.8 pairs per record at a million records**, over the budget of 5. The address code makes 5.7.

**Solution: the address only with one more field.** A true pair that shares an address almost always shares something else with it: the phone digits, the name's first letter, or, after a marriage, the given name. Two households at one address rarely do. So the address and the address code are each combined with the phone and with the name's first letter, and the address code with the given name:

| Generator | Pairs per record at a million records |
|---|---|
| address alone, address code alone | 5.8 and 5.7 |
| address + phone, address code + phone | 0.05 and 0.10 |
| address + the name's first letter, address code + the name's first letter | 0.40 and 0.60 |
| given name + address code | 0.04 |

With these five generators, every potential match on train still shares a key, at its size and at a million records. The decision rule adopted them as cheaper: no true pair lost or false pair added, on cross-validated train or on val.

### How the configuration keeps it that way

Every generator and rule of the method stays under 5 pairs per record projected to a million records, as measured on the training file when the generators are chosen. For each generator the projection counts the pairs of one entity, P_same, and the chance pairs, P_chance, and projects each by its own law: P(n) = P_same·n/N + P_chance·n(n − 1)/(N(N − 1)). That is what keeping a share of the entities would give on average, computed instead of sampled. Pairs between two members of a household count as chance, the safe side.

For the method, the largest projection of a generator is phone + name initial, at 2.1 pairs per record. And every potential match on train shares a key: all 3,278 at train's size, and all 3,071 at a million records.

Without labels, only the patterns can be checked: every combination of comparison levels that could reach the threshold must imply a shared key. A Jaro–Winkler level implies none, so a pattern built on close names counts as uncovered even when another key, in practice, joins it. Measured at design time for the method at a million records, 190 patterns are uncovered, and the model puts their share of matches at 13.2% at most. The largest pair a name at "fold JW high" with "same address". On labelled train, every potential match shares a key (above).

### Measured: a whole run, up to a million records

`scripts/benchmark.py` generates files of growing size and resolves each with `python -m nayose build`, in a process of its own, as a real run: on DuckDB tables, fitted on the file itself, without labels, under an 8 GB memory limit ([reports/benchmark.md](../../reports/benchmark.md)). Each stage's seconds:

| Records | Records stage | Fit | Score | Decide | Total | Peak memory |
|---|---|---|---|---|---|---|
| 13,019 | 0.72 | 2.75 | 0.29 | 0.04 | 3.8 | 1.25 |
| 25,947 | 1.20 | 2.80 | 0.37 | 0.04 | 4.4 | 1.46 |
| 52,115 | 2.11 | 3.15 | 0.55 | 0.13 | 5.9 | 1.81 |
| 77,926 | 2.96 | 3.76 | 0.78 | 0.06 | 7.6 | 2.3 |
| **1,039,995** | 9.83 | 6.03 | 14.83 | 0.18 | 30.9 | 6.69 |

A million records take 30.9 seconds, 14.83 of them in the score stage (the rules, the keys, the gate and the scores) and 9.83 reading the file. The fit, on a fixed sample, and the u sample of the file inside it, 10 million pairs, grow far slower than the file: 2.75 s at 13,019 records, 6.03 s at a million. So at these sizes the total grows slower than the file, like N^0.5. Only the rules' pairs and the pairs that can reach 0 points are weighed: a bound from a pair's equalities alone rules out the rest before any string comparison. Peak memory is the process's, Python included: 6.69 GB at a million records, under the 8 GB limit. The cost of every step, for a build and for an update, is in [performance.md](../performance.md).

Three choices keep a million records within bounds:

- **The tables stay in the engine.** A run is a set of tables, a DuckDB file or a BigQuery dataset, and each statement reads only the columns it needs (the fit's `compared` view holds only the columns the comparisons read). Python reads only small results: the counts EM learns from, the report's numbers. Copied into pandas with every compared field of both records, the scores would not fit.
- **The lists merge in SQL.** Each generator sets one bit, and one query ORs them, so no Python code runs once per pair.
- **Tables spill to disk.** On DuckDB, a table past the memory limit (`--compute memory_limit=8GB`) spills to disk, beside the run's database file unless `--compute temp_directory=…` names another folder. The file itself is read by DuckDB, straight from Parquet.

The generator has 60,000 distinct personas. Beyond that it must reuse them, which creates clones no matcher can tell apart, so the million-record row measures cost only.

### Quality as the file grows

Up to 78,000 records, every entity is still a distinct persona, so quality can be measured too. Each file is fitted on itself, without labels:

| Records | Recall | False merges | False-merge rate ≤ |
|---|---|---|---|
| 13,019 | 48.4% | 2 | 0.44% |
| 25,947 | 49.2% | 0 | 0.11% |
| 52,115 | 47.8% | 2 | 0.11% |
| 77,926 | 47.5% | 6 | 0.14% |

On train, every true pair that could reach the threshold shares a key, at its size and at a million records. Two things change as the file grows:

- **False pairs appear.** A bigger file holds more pairs of different entities that look alike. Taken at 6 points, the pairs join 2 false pairs at 13,019 records, through 1 false link, 2 at 52,115, through 2, and 6 at 77,926, through 5. Each is a model link between 6.8 and 12.0 points (the threshold is 6), between two people who share an address or a phone, most of them a family name too. The model expects at least as many: the sum of 1 − match probability over its links, which needs no labels, is 1.61 at 13,019 records, 2.33 at 25,947, 4.82 at 52,115 and 8.07 at 77,926; at a million, where personas repeat as clones, 54.54 of 44,065 links. The bound on the false-merge rate is 0.44% at 13,019 records, above the 0.26% reported for test, and 0.11–0.14% at the larger sizes.
- **Recall stays within two percentage points,** between 47.5% and 49.2%. u is measured on each scored file, so an agreement on a field whose values grow with the file, such as the address or the CIF ID, earns the credit it has at that size. On the labelled splits, which are no bigger than train, this choice costs true pairs: 700 on cross-validated train and 92 on val (adopted as "chosen", [chapter 1](01-entity-resolution-and-our-task.md#a-rule-for-every-choice)).

**In short:** two sorts of step grow with the square of the file: generators whose keys come from a fixed pool (the phone digits, the address), and all-against-all similarity. Compound generators, no TF-IDF and a narrower F2 join keep both in check. A sorted window reaches fewer pairs as the file grows, so five more generators make sure no potential match depends on one, and the method uses no window at all. A million records take 30.9 seconds, with peak memory 6.69 GB under an 8 GB limit, on DuckDB tables that spill to disk past it.

## In the code

- `nayose/sql/score.sql`: the generators by name, their order each one's bit in a pair's `mask`; 2. The keys (`made_keys`, the changed records' keys, a deletion generator's every value with one character deleted; `every_key`, the index of every record's keys; `key_blocks`, the blocks the batch's keys name, each with its records counted; `listed`, the pairs of the blocks under `@oversized`, each with its `mask`); 4. The gate (`gate_pairs`, each oversized block's sample; `gated`, each block's `verdict`: listed or skipped); 5. The candidates (`cands`, with the generators whose keys listed each pair); 3. The model's bits (`level_bits`; `bound_of`, the most points a pair's equalities alone allow)
- `nayose/config.toml` `[score]`: `generators` (the generators a run uses, by name), `oversized` (64), `search_floor` (0 points), `keep_from` (0 points: the pairs a run keeps)
- `nayose/sql/records.sql`, 6. The copies: the fields behind the compound keys (`any_name__initial`, `postal_code__first3`, `address__address_first3`, `person_name__kana_fold_long_vowel_last3`)
- `nayose/sql/fit.sql`: 1. The sample (`fit_sample`, whole postal areas by hash); 4. u: 4b `u_counted` (the leading exact levels, from value counts), 4c `u_one_edit` (a one-edit level after them, through one-deletion keys), 4e `u_drawn` and `u_patterns` (the rest sampled), 4d `u_filled` (what bounds a level no sampled pair reached); `config.toml` `[fit]`: `fit_records`, `fit_u_max_pairs`, `u_max_pairs`
- `nayose/em.py`: `exact_u`, `sampled_u`, `u_bound`, `assemble` (u on the file)
- `scripts/benchmark.py`: `cost`, whole builds on generated files from 13,000 to a million records

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 4 (indexing).
- P. Christen, "A survey of indexing techniques for scalable record linkage and deduplication," *IEEE Transactions on Knowledge and Data Engineering* 24(9), 2012.
- G. Papadakis et al., "[Blocking and filtering techniques for entity resolution: a survey](https://arxiv.org/abs/1905.06167)," *ACM Computing Surveys* 53(2), 2020.

**Next:** [4. Certain cases first: rules →](04-certain-cases-first-rules.md)
