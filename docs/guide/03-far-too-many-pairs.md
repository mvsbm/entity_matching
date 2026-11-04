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

The configuration offers six keys: phone, normalized address, address code, customer number, folded person name and folded company name.

**Sorted neighbourhood.** Sort all records by a key, such as the folded name, and compare each record with the next few, here 4. A typo near the end of a name keeps the record close in the sorted order, so the pair is still found.

**TF-IDF neighbours.** Cut each name into overlapping pieces of 2–3 characters, give rare pieces more weight, and compare each record with its 5 most similar names (a cosine similarity of at least 0.5). This finds typos anywhere in a name, even in the first character.

**Only for the records still unresolved.** The rules in [chapter 4](04-certain-cases-first-rules.md) settle most records first. Candidates are generated only for the records they left, compared against all records. That replaces N × N with (records left) × N.

### Why this solution

- **Keys cost almost nothing.** A database hash join finds all pairs in a block in about O(N + P) time.
- **The three kinds catch different typos.** Keys need an exact agreement. Sorted neighbourhood survives late typos. TF-IDF survives typos anywhere.
- **Every key is measured before use.** Before any join, a *preflight* counts P for every key and projects it to a million records. A run stops if any key goes over budget (here, 5 million pairs).

## How do we know a candidate list is good?

Two numbers, which pull in opposite directions:

- **Completeness:** the share of the true duplicates the list contains. A pair that is not on the list can never be found later.
- **Reduction ratio:** the share of all pairs we skip.

On validation, for the 683 true pairs the rules missed:

| Generators, added one by one | Candidates | Missed pairs on the list |
|---|---|---|
| phone | 4,985 | 47.6% |
| + address, address code, customer number | 6,566 | 84.3% |
| + folded person and company names | 6,724 | 93.1% |
| + sorted neighbourhood | 31,942 | 93.6% |
| + TF-IDF | 33,871 | 93.9% |

Sorted neighbourhood more than quadruples the list but adds only half a point. The final configuration keeps six generators: phone, address, address code, customer number, company-name sorted neighbourhood and person-name TF-IDF. It has **14,180 candidates holding 641 of the 683 missed pairs (93.9%)**, while skipping 99.972% of all pairs.

**In short:** a few cheap keys find most duplicates; the extra generators buy the last few points.

## What it costs: keys that grow with the square

The phone key is useful but dangerous. The last four digits have only 10,000 possible values, so unrelated people collide by chance. With N records spread over 10,000 values, the chance collisions alone are about:

$$P \approx \frac{N^2}{2 \times 10{,}000}$$

On validation that gives about 5,000 chance pairs. About 1,660 true duplicates also share a phone: on train, 74.5% of true pairs do, and 74.5% of val's 2,227 is about 1,660. Together they make roughly 6,660, and the notebook counts 6,634 pairs in the phone blocks.

At a million records, the same formula gives **50 million** chance pairs from the phone key alone. That's why the preflight projects every key to the target size before it runs.

Two more costs:

- **A missed candidate is lost for good.** 42 of the 683 missed pairs are on no list. The second stage can never find them.
- **Sorted neighbourhood fails on early typos.** A wrong first character moves a record far away in the sorted order.

**In short:** blocking sets the ceiling on recall, and keys with few values blow up at scale.

## In the code

- `er/candidates.py`: `KeyBlocker`, `SortedNeighbourhood`, `TfidfNeighbours`, `estimate` (the preflight count)
- `er/config.py`: `Budget` (`max_candidate_pairs`, `max_block_size`, `target_rows`)
- `notebooks/probabilistic_matching.ipynb`: `GENERATORS` in the Configuration cell; the "Candidates on val" cell prints the tables above
- `notebooks/deterministic_matching.ipynb`: the preflight cell, which counts P per rule before any join

## Further reading

- P. Christen, *Data Matching*, Springer, 2012: chapter 4 (indexing).
- P. Christen, "A survey of indexing techniques for scalable record linkage and deduplication," *IEEE Transactions on Knowledge and Data Engineering* 24(9), 2012.
- G. Papadakis et al., "[Blocking and filtering techniques for entity resolution: a survey](https://arxiv.org/abs/1905.06167)," *ACM Computing Surveys* 53(2), 2020.

**Next:** [4. Certain cases first: rules →](04-certain-cases-first-rules.md)
