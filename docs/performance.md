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
| L | characters in a name or address (about 7 and 15) |
| P_r, P_g | pairs inside rule r's or generator g's key blocks |
| b | records in one key block |
| C | candidate pairs, the union of all P_g; C_Δ, those touching the batch |
| K | comparisons in the model (5) |
| S | random pairs sampled for u (10⁷; fixed) |
| P_em | pairs in EM's blocks (equal phone, equal address) within the fitting sample |
| E | accepted pairs |
| d | diameter of the largest cluster: Splink's connected components take up to d rounds |
| F, D, T | folds (3), decision variants (12), Optuna trials |

**A full run** (`er.run.Run.full`, which `scripts/resolve.py` calls), with the times measured on 999,481 generated records by
`scripts/benchmark.py`, in a process of its own under an 8 GB DuckDB memory limit:

| # | Step | Code | Cost | Grows like | At 1M |
|---|---|---|---|---|---|
| 1 | load: read in chunks, check the fields, standardize each chunk | `Run.load`, `er.standardize.prepare` | O(N·L) | N | 5.5 s |
| 2 | budget: every rule's and generator's pairs, exactly, before any join | `Run.budget`, `er.candidates.estimate` | O(N) per rule and generator, a group-by | N | 0.9 s |
| 3 | fit: λ from near-certain rules, u, m by EM, on a sample of whole postal areas | `Run.fit`, `er.match.train_fs` | O(n + S·K + P_em·K) | **constant** | 7.3 s |
| 4 | rules: one join per rule (the first rule wins a pair), fuzzy checks on the joined pairs only, then the cascade's clusters | `Run.rules`, `er.match.rule_edges_table` | O(N + Σ P_r·L²) + O((N + E)·d) | N; ≤ 0.22 pairs per record per rule at 1M | 3.3 s |
| 5 | candidates: every generator as one SQL join or window, merged by bitmask, pairs inside one rule cluster dropped | `Run.candidates`, `er.candidates.candidates` | O(N·L + Σ P_g) | N; ≤ 2.0 pairs per record per key at 1M, 3 per sorted window | 3.0 s |
| 6 | score: u measured on this file (value counts for the leading exact levels, S pairs for the rest), then every candidate | `Run.score`, `er.match.with_scored_u`, `score_fs` | O(N + S·K) + O(C·K·L²) | C, plus a constant | 18.5 s |
| 7 | cluster: accept at the threshold, connected components with the rules' pairs, gold | `Run.cluster` | O(C + (N + E)·d) | N | 0.4 s |
| 8 | write: gold, matches, the rules' pairs and the state for increments, as Parquet | `Run.write` | O(N + C) | N | 0.9 s |
| | **total** | | | | **39.8 s, 5.5 GB peak** |

**An increment** (`Run.increment`, `scripts/resolve.py --increment`): a batch of Δ new records joins a written run.

| Step | Cost | What it touches |
|---|---|---|
| load | O(Δ·L) | the batch; a record already in the run stops it |
| rules | O(Δ·Σ b) + a scan of the stored records | each rule joins the batch against all records; the cascade merges into the stored clusters, each cluster one node |
| candidates | O(Δ·Σ b) + a scan | every generator, with the batch as the query |
| score | O(N + S·K) + O(C_Δ·K·L²) | u measured again on all the records; only the pairs touching the batch are scored |
| cluster | O(C_Δ + touched clusters) | the stored clusters, with the new pairs merged in |
| write | O(Δ + C_Δ) appended, O(N) rewritten | new Parquet parts for records, rule pairs and matches; gold and the rules' clusters rewritten. Every file is staged under a temporary name and renamed into place only once all are complete, so an interrupted increment leaves the run as it was, or is finished by the next one |

So a full run costs **O(N·L + Σ P + C·K·L² + (N + E)·d)**, plus the fit and the u sample, whose sizes are fixed. It
is linear in N when every key's pairs per record stay flat as the file grows, which `budget` checks exactly on each
file and `scale_check` projects to `budget.target_rows` while choosing (below). An increment costs
**O(Δ·(L + Σ b) + C_Δ·K·L²)**, plus the fixed u sample and sequential scans and rewrites of the stored columns. Its
expensive work grows with the batch, not with the file. A full run re-fits the model and should follow many increments.

**Memory.** Records, pairs, scores and clusters are DuckDB tables. Past `memory_limit` (config/settings.toml `[compute]`,
or `scripts/resolve.py --compute memory_limit=8GB`), DuckDB spills them to `temp_directory`. Python holds one chunk of
`load` (200,000 records), the fitting sample (n records) and small summaries. At a million records the process peaked at
5.5 GB, Python included, while writing the run folder, under an 8 GB limit, so nothing spilled.

## The cost checks before a run

| Check | When | Cost | What it stops |
|---|---|---|---|
| `budget` | every run, on the actual file | O(N) per rule and generator | a rule or generator over `max_pairs_per_record` × N pairs, or with a block over `max_block_size` |
| `scale_check` | `scripts/choose.py`, on train | O(N) per key | a key whose pairs, projected to `target_rows`, exceed the budget |
| `window_only` | `scripts/choose.py`, on train | O(N + P + P_true·K), P_true true pairs, plus two u samples | a true pair that could reach the threshold but shares no key, now or at `target_rows` |
| `pattern_coverage` | `scripts/choose.py` and every run's QA report | O(Π levels), a few thousand patterns | reported, not stopped: patterns that can reach the threshold with no guaranteed key |

`scale_check` splits a key's pairs P on train into T pairs of one entity and C chance pairs between entities. A
bigger population of the same kind has proportionally more duplicated entities, so T grows like N, and two entities
share a value with the same probability at any size, so C grows like N²: P(n) = T·n/N + C·n(n − 1)/(N(N − 1)). That is
the expectation of keeping a share of the entities, computed instead of sampled. Projected from a quarter of all the
generated records to all of them, it lands within ±5% of the actual count for every key but one (company names, −12%,
from few records). Pairs between members of one household count as chance, the safe side
([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).

## Choosing the configuration

`scripts/choose.py`, once, on the labelled synthetic train and val (4.8 minutes in all, Optuna off):

| Step | Cost | Measured |
|---|---|---|
| rules: design analyses, A/B, decisions, cost, evaluation, output | O(D · run) on train and val | 25 s |
| candidates on train: every generator's reach | O(N·L + Σ P_g) | 5.5 s |
| training: EM against labels | O(n + S·K + P_em·K), twice | 9.4 s |
| threshold rule on out-of-fold scores | O(F · (fit + run on n/F records)) | 32 s |
| A/B on val | O(variants · run) | 36 s |
| decisions | O(D · (F + 1) · run) | 105 s |
| will it scale: `scale_check`, `window_only`, `pattern_coverage` | O(N) per key + O(N + P + P_true·K) + O(Π levels) | 17 s |
| output: train, val and test through the chosen pipeline | O(3 · run) | 20 s |
| gold: train, val and test resolved by `er.run` into `data/medallion/gold/<dataset>/` | O(3 · full run), with train's model | 31 s |
| Optuna (off by default) | O(T · F · run) | +1.5 min (rules), +8.5 min (Fellegi–Sunter) |

u-sampling runs once per scored file (each fold, val, train, test, and the coverage check's two samples), so it is
most of the decision, output and "will it scale" time. `notebooks/demo.ipynb` runs every step of a full run and an
increment on 3,747 records in about 25 seconds; `scripts/export_pdfs.py` prints it in about 30.

**Free savings in the code** (identical results, covered by tests/):
- **u cached per comparison** (`FSModel.u_keys`). A comparison's u depends only on itself and the records it is
  sampled on, and Splink's random sample doesn't depend on which comparisons it scores. So any model that shares a
  comparison reuses its u, from the fit (`FSChooser.u`) or from a scored file (`SCORED_U`, keyed by the records'
  fingerprint).
- **Threshold rule without clustering** (`accept_curve`). The rule reads only accepted and false accepted pairs per
  weight, so decision variants resolve clusters at the chosen weight only.
- **Run cache.** Identical runs (same configuration, dataset and threshold) are computed once.
- **Merged lists by bitmask.** A pair's generators are one bit each, combined with `bit_or` in SQL, then named once
  per combination ([lessons.md](lessons.md#merging-the-candidate-lists-was-most-of-the-work)).

**Tried and rejected by the rule, because it changes results:** u from 10⁶ pairs instead of 10⁷ (`u_from_1e6_pairs`)
would make u-sampling about 6× cheaper, but loses true pairs: cross-validated train +9 / −26 (p = 0.006), val −1.
Dropping the three sorted windows (`no_sorted_windows`) would remove 9 of the run's pairs per record, but loses 3 true
pairs on cross-validated train and 1 on val.

## Files of growing size

`scripts/benchmark.py`: each generated file resolved by `scripts/resolve.py` in a process of its own, the model fitted
on the file itself, without labels ([reports/benchmark.md](../reports/benchmark.md)):

| Records | Seconds | Peak memory | fit | score | everything else |
|---|---|---|---|---|---|
| 12,392 | 17.1 | 0.57 GB | 8.7 | 7.8 | 0.6 |
| 50,215 | 18.4 | 0.78 GB | 8.5 | 8.5 | 1.4 |
| 75,284 | 19.3 | 0.97 GB | 8.3 | 9.0 | 2.0 |
| 999,481 | 39.8 | 5.5 GB | 7.3 | 18.5 | 14.0 |

The fit and the u sample inside `score` (about 8 s) cost the same at every size, so they are nearly all of a small
file's time. Everything else goes from 2.0 s at 75,000 records to 14.0 s at a million: 13 times the records, 7 times
the time, because DuckDB uses its threads better on bigger tables. Scoring the candidates, the rest of `score`, grows
from under a second to about 10 s.
