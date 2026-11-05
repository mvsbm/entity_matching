[README](../../README.md) · **Guide:** [1 Task](01-entity-resolution-and-our-task.md) · [2 Variants](02-the-same-fact-written-differently.md) · **3 Pairs** · [4 Rules](04-certain-cases-first-rules.md) · [5 Evidence](05-uncertain-evidence-fellegi-sunter.md) · [6 Measuring](06-measuring-and-choosing.md)

# 3. Far too many pairs

*Challenge C3.*

## Challenge: comparing everything is impossible

To find every duplicate, we would compare every record with every other one. The number of pairs grows with the square of the file size:

| Records | Pairs to compare |
|---|---|
| 10,002 (our validation file) | 50,015,001 |
| 1,000,000 (a production-sized file) | 499,999,500,000 (5 × 10¹¹) |

Fewer than 2,300 of the 50 million validation pairs are true duplicates. Comparing all of them would waste almost all the work, and at a million records it would not finish in reasonable time.

## Solution: compare only promising pairs

The standard answer is **blocking**: compare two records only if they already share something. We generate a short list of **candidate pairs** in three ways, then score only those.

**Key blocks.** Records that agree exactly on a key, such as the last four phone digits, form a block, and only pairs inside a block are compared. A block of k records holds k(k−1)/2 pairs, so the work for a key is:

$$P = \sum_{\text{blocks}} \binom{k}{2}$$

The configuration offers six keys: phone, normalized address, address code, CIF ID, folded person name and folded company name.

**Sorted neighbourhood.** Sort all records by a key, such as the folded name, and compare each record with the next few, here 4. A typo near the end of a name keeps the record close in the sorted order, so the pair is still found.

**TF-IDF neighbours.** Cut each name into overlapping pieces of 2–3 characters, give rare pieces more weight, and compare each record with its 5 most similar names (a cosine similarity of at least 0.5). This finds typos anywhere in a name, even in the first character. It is also the one generator that compares every record with every other, so the final configuration replaces it ([below](#scaling-to-a-million-records)).

**Only pairs the rules have not settled.** The rules in [chapter 4](04-certain-cases-first-rules.md) settle most records first. A pair inside one of their clusters is joined already, so it is dropped. Every other pair a generator finds is scored: most touch a record the rules left alone, and a few join two clusters the rules formed for the same entity ([below](#keeping-every-potential-match)).

### Why this solution

- **Keys cost almost nothing.** A database hash join finds all pairs in a block in about O(N + P) time.
- **The three kinds catch different typos.** Keys need an exact agreement. Sorted neighbourhood survives late typos, and sorting the reversed name too survives early ones. TF-IDF survives typos anywhere.
- **Every key is measured before use.** Before any join, a run counts P for every key and stops if one goes over budget (here, 5 million pairs). A notebook cell also projects every key to a million records ([below](#how-the-notebooks-keep-it-that-way)).

## How do we know a candidate list is good?

Two numbers, which pull in opposite directions:

- **Completeness:** the share of the true duplicates the list contains. A pair that is not on the list can never be found later.
- **Reduction ratio:** the share of all pairs we skip.

On train, for the 2,135 true pairs the rules missed. Each generator is listed with the pairs it makes, and the share of the missed pairs on the list so far:

| Generators, added one by one | Pairs they make | Missed pairs on the list |
|---|---|---|
| phone | 43,054 | 50.4% |
| + address, address code, CIF ID | 22,453 | 84.8% |
| + folded person and company names | 1,710 | 93.5% |
| + sorted neighbourhood (person, company) | 77,653 | 93.9% |
| + TF-IDF (person, company) | 24,417 | 94.4% |
| + the scalable generators (below) | 69,503 | 95.1% |

Sorted neighbourhood adds the most pairs and the fewest missed pairs. Chosen for quality alone, the configuration kept six generators (phone, address, address code, CIF ID, company-name sorted neighbourhood, person-name TF-IDF). On validation: 14,180 candidates holding 641 of the 683 missed pairs (93.9%).

Two of those six cannot run at a million records, so the final configuration has 14 generators instead (next sections). On validation it has **51,484 candidates holding 632 of the 683 missed pairs (92.5%)**, while still skipping 99.90% of all pairs. That is 9 missed pairs fewer than the six-generator list, and none of them could have been accepted: every true pair that could reach the threshold shares one of the final keys ([below](#keeping-every-potential-match)).

**In short:** a few cheap keys find most duplicates; the extra generators buy the last few points.

## What it costs: keys that grow with the square

The phone key is useful but dangerous. The last four digits have only 10,000 possible values, so unrelated people collide by chance. With N records spread over 10,000 values, the chance collisions alone are about:

$$P \approx \frac{N^2}{2 \times 10{,}000}$$

On validation that gives about 5,000 chance pairs. About 1,660 true duplicates also share a phone: on train, 74.5% of true pairs do, and 74.5% of val's 2,227 is about 1,660. Together they make roughly 6,660, and the notebook counts 6,634 pairs in the phone blocks.

At a million records, the same formula gives **50 million** chance pairs from the phone key alone. That's why the preflight projects every key to the target size before it runs.

Two more costs:

- **A missed candidate is lost for good.** 51 of the 683 missed pairs are on no list. The second stage can never find them.
- **Sorted neighbourhood fails on early typos.** A wrong first character moves a record far away in the sorted order. A second pass on the reversed name finds those, unless the name has typos at both ends.

**In short:** blocking sets the ceiling on recall, and keys with few values blow up at scale.

## Scaling to a million records

The pipeline was built and tested on files of 10,000 to 30,000 records. A production file holds a million. So, before changing any code, we priced every step by its time complexity and measured how its work grows with the file.

### Where the work grows faster than the file

We generated files of 12,000, 25,000, 50,000 and 75,000 records, counted each step's work, and fitted a **growth exponent** α, with work ∝ N^α. At α = 1 the work is linear: ten times the records, ten times the work. At α = 2 it is quadratic: ten times the records, a hundred times the work.

| Step | Cost | Grows like | At a million records |
|---|---|---|---|
| standardize | O(N·L) | N | seconds |
| rules, except F2 | O(N + P) per rule | N^1.0 to N^1.4 | ≤ 4.1 million pairs per rule, at worst |
| **rule F2** (joined on the phone alone) | O(N + P) | **N^1.89** | **55.8 million pairs** |
| key: **phone** | O(N + P) | **N^1.89** | **39 million pairs**, 4% of them true |
| keys: address, address code, CIF ID, folded names | O(N + P) | N^1.0 to N^1.4 | ≤ 0.8 million pairs each |
| sorted neighbourhood | O(N log N + N·w) | N | ≤ 3 million pairs per pass |
| **TF-IDF neighbours** | O(U·N·q) | **N^2.01** | **6.4 × 10¹¹ operations** |
| scoring | O(C), for C candidates | as C | |
| clustering | O(N + E), for E accepted pairs | N | seconds |
| fitting and tuning | a fixed-size sample | constant | unchanged |

Everything is near-linear except two kinds of step:

1. **A key with a fixed number of values.** The last four phone digits take only 10,000 values, however large the file. Chance collisions grow like N²/(2 × 10,000), while true duplicates grow only like N. Both the phone key and rule F2 rest on it.
2. **All-against-all similarity.** TF-IDF compares each unresolved record with every record. About 30% of records are unresolved, so the work is about 0.3 N².

### The fixes

Every fix had to pass the decision rule that judges every other change ([chapter 6](06-measuring-and-choosing.md)). A change adopted because it is *cheaper* may lose no true pair on cross-validated train or on val, and may add no false pair.

**Fix 1: the phone key becomes three compound keys.** A true duplicate that shares its phone digits almost always shares something coarse as well. A chance collision rarely does. So instead of the phone alone, we block on:

- phone + prefecture,
- phone + postal area (the first 3 digits of the postal code),
- phone + name initial (the first character of the person name, else the company name, folded, legal form removed).

Each key splits the 10,000 phone values into hundreds of thousands of combinations or more. At a million records, the chance pairs fall from 39 million to about 1.1 million for all three together. On val, the phone key alone reached 70 missed pairs that no other generator reached. The compound keys still reach 48, including all 20 that the model accepts.

*Decision:* 0 true pairs gained or lost, on cross-validated train and on val. **Adopted.** These keys are still quadratic in the limit, with a constant hundreds of times smaller. The check below would flag them first if files grew well past a million.

**Fix 2: TF-IDF becomes a second sorted pass.** TF-IDF earned its place by finding typos near the start of a name, which a sorted order misses. Drop the ト from サトウヒロシ, and サウヒロシ sorts far away, among the names that begin with サウ. Sorted by the **reversed** name, the two stay close (シロヒウサ, シロヒウトサ), because they end alike. Two sorted passes cost O(N log N) each, against TF-IDF's N². Of the missed pairs that only TF-IDF found, the two passes reach 48 of 48 on val and 146 of 149 on train.

*Decision:* +2 true pairs and 0 lost on cross-validated train; 0 and 0 on val. **Adopted.**

**Fix 3: rule F2 joins on more than the phone.** F2 accepts a pair with a similar name, a similar address and the same phone. It joined on the phone alone and checked the rest after the join, so the join inherited the phone's N² growth. Three alternatives were tried:

| F2 joins on | Pairs at a million records | Train: true pairs lost | Val: lost | Adopted |
|---|---|---|---|---|
| phone (as written) | 55.8 million | — | — | over budget |
| phone + exact normalized address | — | 8 | 3 | no |
| phone + name initial, or phone + postal area | — | 2 | 0 | no |
| phone + first 3 characters of the normalized address | 0.12 million | 0 | 0 | **yes** |

The exact address fails because F2 exists for address typos: joining on the exact address defeats its purpose. The first three characters (the start of the city, such as 福島市) survive typos later in the address.

**Fix 4: fit and tune once, on a fixed-size sample.** u comes from 10 million random pairs, whatever the file size. EM runs on blocks of the training file. Cross-validation and Optuna run on train. None of this needs the production file. The model is fitted on train (about 30,000 records) and then scores a file of any size, with λ rescaled to that file's size ([chapter 5](05-uncertain-evidence-fellegi-sunter.md)).

**Not chosen:**

- **A cap on how common an n-gram may be in TF-IDF.** It is linear, but the share of typo pairs it keeps falls as the file grows. With a cap of 200, it falls from 98.5% at 12,000 records to 88.6% at 75,000. The loss would keep growing with the file.
- **TF-IDF as an exact sparse matrix product.** Ten times cheaper, and still N².
- **TF-IDF within each prefecture.** It misses people who moved, and a third of the records have no prefecture.

### Keeping every potential match

The fixes above were judged by the pairs `FINAL` accepts. A stricter test asks about the pairs it *could* accept. Call a true pair a **potential match** if its fields, once compared, would reach the 6-bit threshold. Blocking must keep every potential match, at every file size. A pair that falls short with all its evidence counted can never be accepted, whatever list it is on.

What counts as potential depends on the file size. λ shrinks as the file grows, so the same evidence earns fewer bits: log2(N / 30,000) fewer than on train. That makes every size testable on the training file: score its true pairs once, move λ to the target size, and see which pairs still reach 6 bits.

**Challenge: a sorted window reaches less as the file grows.** A sorted neighbourhood compares each record with the next three in name order. In a bigger file, more records sort between two similar names, so fewer true pairs fall inside the window. Here, "name-close" means a Jaro–Winkler similarity of at least 0.75 after kana folding, the model's lowest name level:

| Records | Name-close true pairs inside the window | Window needed for 95% of them |
|---|---|---|
| 12,392 | 85.8% | 7 |
| 24,944 | 77.9% | 15 |
| 50,215 | 66.0% | 26 |
| 75,284 | 60.9% | 46 |

The window needed grows with the file. A fixed window loses pairs, and a growing one costs N². Most of these pairs share another key anyway: an address, a CIF ID, a phone. But some potential matches shared no exact key at all, so only a window found them: 61 on train, 28 on val and 28 on test. At a million records, 27, 9 and 5 of them are still potential.

**Solution: keys, whose reach does not depend on the file size.** Two records share a key or they don't, however many records lie between them. Five keys cover every one of those pairs:

| Key | What it guarantees | Pairs at a million records |
|---|---|---|
| person name, exact (folded) | every pair with the same name | 0.18 million |
| company name, exact | every pair with the same company name | 0.09 million |
| company name, one-deletion keys | every pair of company names one edit apart | 0.23 million |
| person name, one-deletion keys within the postal area | every pair of names one edit apart in one postal area | 0.12 million |
| given name + postal code | a surname change at the same postal code | 0.09 million |

With them, **no potential match depends on a window**: 0 on train, val and test, at their own size, at 75,000 records and at a million.

**One-deletion keys.** Each record emits its value, and the value with each single character deleted. サトウヒロシ gives サトウヒロシ, トウヒロシ, サウヒロシ, サトヒロシ, サトウロシ, サトウヒシ and サトウヒロ. Two names one edit apart always share one of these keys:

- **A substituted character** (サトウヒロシ, サトウヒロミ): deleting it from both gives サトウヒロ.
- **A dropped character** (サトウヒロシ, サトヒロシ): the shorter name is itself a deletion of the longer.
- **Two neighbours swapped** (サトウ, サウト): deleting the ウ from both gives サト.

A name of L characters emits L + 1 keys, so the work is O(N·L + P). Spelling correctors such as SymSpell use the same idea, called symmetric deletion.

**Why within the postal area?** Many short names differ from another person's by one kana. On their own, the person-name deletion keys would make 5.6 million pairs at a million records, growing like N^1.71. Within the postal area they grow like N^1.01. A potential match whose names are one edit apart but whose postal areas differ needs strong evidence from another field, and that field has a key of its own. The coverage check below confirms this on every split.

**Challenge: two rule clusters were never compared.** In the robustness files, almost all the potential matches that both stages missed lay between two clusters the rules had already formed: 28 of 30 at 50,000 records, 14 of 14 at 75,000. The second stage generated candidates only for records the rules left alone. So when the rules split one entity into two clusters, no pair between them was ever scored, whatever its evidence.

**Solution: score every pair across two clusters.** Candidates are now generated for every record. A pair inside one cluster is dropped before the lists are merged, because it is joined already. The list grows by 7% (val: 48,105 → 51,484 candidates), and scoring time does not measurably change. A false pair between two clusters would merge both of them, so the margin was checked first: between rule clusters, the highest-scoring false pair reaches 1.0 bits on train, far below the 6-bit threshold.

| Change | Rule | Cross-validated train | Val | Adopted |
|---|---|---|---|---|
| the five keys | safer | +1 / −0 true pairs, no false pair added | +1 / −0 | yes |
| score every pair across two clusters | better | +12 / −0 (p = 0.0005), no false pair added | +4 / −0 | yes |

"Safer" is the cheaper test for a change that adds pairs: it may lose no true pair and add no false one. Its gain shows at scale, and the coverage check below measures it.

### How the notebooks keep it that way

Each notebook has a cell that projects every key and rule of `FINAL` to a million records: "Cost of FINAL" in the deterministic notebook and "Will it scale?" in the probabilistic one. The cell stops the run if a key would exceed the budget of 5 million pairs. It needs only the training file:

1. Keep 25%, 50% and 100% of the entities. Whole entities are kept or dropped, so a duplicate keeps its partners.
2. Count each key's pairs P at each size.
3. Fit P ∝ N^α and extrapolate to a million records.

For the probabilistic `FINAL`, the largest projection is the address key, at 4.0 million pairs. Subsampling entities overstates the growth of keys that households share: it gives α 1.58 for the address, against 1.01 measured on growing generated files. So the check errs on the safe side. Optuna trials that fail it are pruned.

The probabilistic cell also counts the potential matches on train that share no key, at train's size and at a million records (`window_only`). It stops the run if any is left. For `FINAL`: 0 of 6,120, and 0 of 5,034.

### Measured: both stages, up to a million records

One model, fitted on train, scores generated files of growing size, both stages, on a 16 GB laptop (`scripts/robustness.py --smoke`):

| Records | Rules | Probabilistic stage | Peak memory |
|---|---|---|---|
| 12,392 | 0.4 s | 0.8 s | 1.2 GB |
| 24,944 | 0.7 s | 1.4 s | 1.3 GB |
| 50,215 | 1.1 s | 2.6 s | 1.6 GB |
| 75,284 | 1.5 s | 4.0 s | 2.3 GB |
| **999,481** | **19.2 s** | **98.4 s** | **6.9 GB** |

The total time grows like **N^1.06**, and a million records take under two minutes.

Two limits had to be removed on the way:

- **Memory.** The first million-record run ran out of memory, because the scores were copied into pandas together with every compared field of both records, about 19 GB at a million. DuckDB now keeps only the columns that are read ([lessons.md](../lessons.md#the-first-million-record-run-ran-out-of-memory)).
- **Merging the lists.** With the five name keys and bridging, the probabilistic stage first took 228 s at a million records. Most of it was Python code that ran once per pair, merging the generators' lists. Vectorized, the stage takes 98 s, less than before those changes ([lessons.md](../lessons.md#merging-the-candidate-lists-was-most-of-the-work)).

The generator has 60,000 distinct personas. Beyond that it must reuse them, which creates clones no matcher can tell apart, so the million-record row measures cost only.

### Quality as the file grows

Up to 75,000 records, every entity is still a distinct persona, so quality can be measured too:

| Records | Recall | False merges | False-merge rate ≤ | Potential matches on no list | Recall, with u from the scored file |
|---|---|---|---|---|---|
| 12,392 | 89.9% | 0 | 0.12% | 0 | 89.8% |
| 24,944 | 89.9% | 4 | 0.18% | 0 | 89.8% |
| 50,215 | 88.7% | 1 | 0.05% | 0 | 89.5% |
| 75,284 | 87.6% | 5 | 0.07% | 0 | 88.7% |

At every size, no missed true pair that could reach the threshold is missing from the candidate lists. Blocking loses nothing that could have been accepted. Two things change as the file grows:

- **False merges appear, but stay rare.** A bigger file holds more pairs of different entities that look alike. The five at 75,000 records come from two accepted pairs. In each, two entities live at the same street address and share their last four phone digits by chance, and the name gives no evidence: one record is a company and the other a person, or one has no name at all. The bound on the false-merge rate stays at the level reported for val and test (0.14–0.15%) or below it, except at 25,000 records (0.18%).
- **Recall falls by about 2 points, and half of that is our own doing.** λ, the chance that two random records match, is rescaled to the file's size. But u, the chance that two different entities agree on a field, stays as measured on train. For the address and the CIF ID, a bigger file has more distinct values, so u should shrink as well. Re-sampling u on the scored file needs no labels and has a fixed cost. At 75,000 records it recovers 87.6% → 88.7%, with the same false merges. On files smaller than train it lowers recall slightly, as it should. It is not adopted yet: it changes every reported number, so it needs its own pass through the decision rule ([lessons.md](../lessons.md#the-size-rescaling-is-only-half-done-open)).

**In short:** two steps grew with the square of the file: keys with a fixed set of values, and all-against-all similarity. Compound keys, a reversed sorted pass and a narrower F2 join remove both. A sorted window reaches fewer pairs as the file grows, so five more keys make sure no potential match depends on one. And the second stage now also scores pairs between two rule clusters. A million records take under two minutes and 7 GB of memory.

## In the code

- `er/candidates.py`: `KeyBlocker`, `SortedNeighbourhood`, `TfidfNeighbours`, `DeletionKeys` (one-deletion keys), `estimate` (the count before any join)
- `er/pipeline.py`: `grown_pairs` (a key's growth α from entity subsamples), `scale_check` (every key and rule projected to `target_rows`), `window_only` (the potential matches no key reaches) and `cascade`'s `bridge` (a stage that may join two clusters)
- `er/config.py`: `ProbSpec.bridge` (score every pair across two clusters)
- `config/settings.toml`: the derived columns behind the compound keys (`ANY_NAME`, the postal area) and the normalizers `initial`, `first3`, `reverse`
- `scripts/robustness.py`: both stages on generated files from 12,000 to a million records
- `er/config.py`: `Budget` (`max_candidate_pairs`, `max_block_size`, `target_rows`)
- `notebooks/probabilistic_matching.ipynb`: `GENERATORS` and `SCALABLE` in the Configuration cell; the "Candidates on train" cell prints the generator table above; the "Will it scale?" cell stops the run if `FINAL` would go over budget at a million records, or would leave a potential match to a window
- `notebooks/deterministic_matching.ipynb`: the "Cost of FINAL" cell, which counts P per rule and projects it to a million records

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 4 (indexing).
- P. Christen, "A survey of indexing techniques for scalable record linkage and deduplication," *IEEE Transactions on Knowledge and Data Engineering* 24(9), 2012.
- G. Papadakis et al., "[Blocking and filtering techniques for entity resolution: a survey](https://arxiv.org/abs/1905.06167)," *ACM Computing Surveys* 53(2), 2020.

**Next:** [4. Certain cases first: rules →](04-certain-cases-first-rules.md)
