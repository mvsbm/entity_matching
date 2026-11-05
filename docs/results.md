[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Each table is explained in chapters [4](guide/04-certain-cases-first-rules.md), [5](guide/05-uncertain-evidence-fellegi-sunter.md) and [6](guide/06-measuring-and-choosing.md).*

# Results

Every number here is printed by `scripts/choose.py` ([`reports/choose.md`](../reports/choose.md)) or `scripts/benchmark.py` ([`reports/benchmark.md`](../reports/benchmark.md)); the rules and the model are in `config/final.toml`, in the logical fields of `config/settings.toml` `[columns]`.

## Stage 1: deterministic matching

**Rules:**
- **exact:**
  - customer_id + full_name
  - customer_id + company_name
  - customer_id + phone
  - full_name + address_code + phone
  - company_name + address_code + phone
- **fuzzy:** one `Comparator` per field, plus the surname-change rule (given name + address code + phone):

  | Field | As written (`config/pipeline.toml`) | Adopted (`FINAL`) |
  |---|---|---|
  | person name | kana fold → JW ≥ 0.92 | kana fold → Levenshtein ≤ 2 |
  | company name | legal form stripped, kana fold → JW ≥ 0.92 | character-set Jaccard ≥ 0.77 |
  | address | normalized (all typed formats give one key) → exact | normalized → JW ≥ 0.91 |
  | phone | Hamming ≤ 1 | Damerau–Levenshtein ≤ 1 |

The train-only design analysis justifies "never one key alone". Single keys collide across entities: phone 45,506 different-entity pairs, postal code 41,868, given name 117,118, even the full name 230. Every exact rule's key combination has 0. The fuzzy rules' join keys have at most 4, and their fuzzy conditions reject those.

**Decisions** (`adopt`, each on top of the choice so far; rules fit nothing, so train is the selection set):

| Change | Kind | Train: true pairs gained / lost | Val: gained / lost | Adopted |
|---|---|---|---|---|
| names: fold → Levenshtein ≤ 1 | better | 15 / 0 (p = 0.0001) | 7 / 0 | yes |
| names: fold → exact | cheaper | 0 / 108 | 0 / 45 | no |
| Optuna's comparators (below) | better | 19 / 1 (p < 0.001) | 6 / 0 | yes |
| F2 joins on phone + exact normalized address (scale) | cheaper | 0 / 8 (p = 0.008) | 0 / 3 | no |
| F2 joins on phone + first 3 characters of the normalized address (scale) | cheaper | 0 / 0 | 0 / 0 | **yes** |

None adds a false pair. The two F2 rows exist for scale: once Optuna's comparators make F2's address check fuzzy, F2 joins on the last four phone digits alone, the phone key's blocks: 50 million pairs at a million records. An earlier alternative, joining on the phone plus the name initial or the postal area, lost 2 true pairs on train and was dropped. The adopted one projects to 0.22 million ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).

**Optuna** (60 trials on train, ≈ 90 s) starts from `FINAL`: its first suggestion passed the same rule and became a change in `config/experiments.py` (`optuna_comparators`). Re-run from the final `FINAL`, the suggestion (trial 47) gains 1 true pair and loses none (p = 1.0), so it is not adopted and the loop has converged. The study is now off by default (`rules_tune`, `enabled=False`; `scripts/choose.py --optuna` runs it).

**Results with `FINAL`:**

| Data | Recall | 95% interval | FP | FP rate ≤ |
|---|---|---|---|---|
| train | 69.2% | 68.1–70.3% | 0 | 0.06% |
| val | 69.5% (exact rules alone: 52.2%) | 67.6–71.4% | 0 | 0.19% |
| **test** | **71.1%** | 69.2–72.9% | **0** | 0.18% |

Paired A/B on val against the rules as written (informational; decisions use the rule above), all with 0 FP:

| Variant | True pairs gained / lost | p |
|---|---|---|
| fold → Levenshtein ≤ 1 | 7 / 0 | 0.016 |
| fold → exact | 0 / 38 | < 0.001 |
| raw Jaro-Winkler (no kana folding) | 1 / 48 | < 0.001 |
| constrained resolver (cannot-link on given name) | 0 / 210 | < 0.001 |
| Optuna's comparators | 13 / 0 | < 0.001 |

The constrained resolver loses because given-name typos look like conflicts.

## Stage 2: probabilistic matching

**Method:** the **Fellegi–Sunter model (Splink 5)** is the only probabilistic method so far; every A/B row is a variant of it.
- λ comes from near-certain rules, u from 1e7 random pairs, m from EM (or labels). `FINAL` re-samples u on each scored file.
- There are five comparisons: name, company, address, phone, cif. Correlated columns share one comparison (address code / normalized address / postal form one), because FS assumes independence.
- Levels use the `cl_*` functions.
- **A level without an estimate never uses Splink's defaults.** No sampled pair reached it → u at its 95% upper bound, so its weight is a lower bound on the evidence. Never seen in training → m = u, 0 bits. The training table lists such levels (none in the pipeline as written).

**Scores are calibrated to the scored file** (`er.match.score_fs`, `er.match.with_scored_u`):
- **Term frequencies** come from the fitting records, stored in the model. A value never seen in training gets no adjustment, the conservative side.
- **λ** is a per-pair rate: true pairs grow with N, pairs with N². It is rescaled from the fitting set's size to the scored set's. So CV folds, val and test (about 10k records each) are scored on the same scale, and the threshold keeps its meaning at any size: on a file of N records, the same evidence earns log2(N/10k) fewer bits than on a 10k file.
- **u** is re-sampled on the scored file's records (no labels; 1e7 pairs, about 8 s whatever the size), because a field whose values grow with the file agrees by chance less often in a bigger one. m stays from train.
- Why this matters, and the bug it replaced: [lessons.md](lessons.md).

**Candidates on train** (2,135 true pairs the deterministic stage missed): every generator in `config/pipeline.toml`, in order, from `reports/choose.md`. Pairs per record at a million records are projected by `scale_check` (pairs of one entity × N, chance pairs × N²):

| Generator | Pairs | Missed pairs it reaches | Cumulative | Pairs per record at 1M |
|---|---|---|---|---|
| phone | 43,054 | 50.3% | 50.3% | 50.24 |
| address | 11,534 | 37.7% | 76.1% | 12.80 |
| address_code | 10,689 | 34.3% | 80.6% | 11.87 |
| cif | 230 | 10.8% | 84.8% | 0.10 |
| person_name | 1,228 | 40.2% | 91.2% | 0.58 |
| company_name | 547 | 8.1% | 93.8% | 0.44 |
| sn_person_name | 63,338 | 42.0% | 94.0% | 3.00 |
| sn_company_name | 14,243 | 8.2% | 94.0% | 3.00 |
| tfidf_person_name | 22,865 | 44.2% | 94.5% | N² |
| tfidf_company_name | 2,416 | 8.3% | 94.6% | N² |
| phone_prefecture | 1,211 | 18.6% | 94.6% | 1.05 |
| phone_postal_area | 633 | 26.7% | 94.6% | 0.19 |
| phone_name_initial | 2,134 | 26.4% | 94.6% | 2.03 |
| sn_person_name_reversed | 63,317 | 49.0% | 95.0% | 3.00 |
| company_name_deletions | 1,082 | 8.3% | 95.0% | 1.04 |
| person_name_deletions_postal_area | 567 | 25.7% | 95.0% | 0.14 |
| given_name_postal | 519 | 23.6% | 95.1% | 0.11 |
| address_phone | 256 | 12.0% | 95.1% | 0.10 |
| address_code_phone | 215 | 10.1% | 95.1% | 0.10 |
| address_name_initial | 671 | 14.0% | 95.1% | 0.55 |
| address_code_name_initial | 658 | 13.2% | 95.1% | 0.54 |
| given_name_address_code | 225 | 10.5% | 95.1% | 0.08 |

The last five add nothing to the cumulative reach: they are the address keys, each with one more field, and every pair they list is on the address or address-code key above. They replace those two in `FINAL`, with a tenth of their pairs on train and an eighteenth at a million records.

**`FINAL`'s candidates on val** (679 missed pairs; each generator alone):

| Generator | Pairs | Missed pairs reached |
|---|---|---|
| cif | 81 | 11.9% |
| sn_company_name | 4,810 | 9.7% |
| phone_prefecture | 196 | 17.8% |
| phone_postal_area | 166 | 24.0% |
| phone_name_initial | 370 | 26.5% |
| sn_person_name | 22,543 | 43.6% |
| sn_person_name_reversed | 22,477 | 52.7% |
| person_name | 334 | 42.0% |
| company_name | 116 | 9.7% |
| company_name_deletions | 169 | 10.2% |
| person_name_deletions_postal_area | 191 | 28.1% |
| given_name_postal | 180 | 26.2% |
| address_phone | 73 | 10.8% |
| address_code_phone | 53 | 7.8% |
| address_name_initial | 150 | 15.8% |
| address_code_name_initial | 138 | 14.0% |
| given_name_address_code | 81 | 11.9% |
| **all 17** | **49,987** | **88.4%** (600 of 679) |

That is 49,987 candidates on val (99.90% of all pairs skipped). Before the scale changes, `FINAL` used the phone key, the address keys and person-name TF-IDF instead: 14,180 candidates reaching 93.9%. None of the missed pairs no longer on the list could have been accepted: on every split, every true pair that could reach the threshold shares one of `FINAL`'s keys, at its own size, at 75,000 records and at a million ([chapter 3](guide/03-far-too-many-pairs.md#keeping-every-potential-match); `scripts/choose.py` checks train on every run).

**Training:** EM and labels learn the same weights within noise.
- Agreeing on CIF, phone, same address or postal code is worth about 11–16 bits; an exact name about 15.5.
- "address close" (Levenshtein ≤ 2 on the normalized address) is worth +8.9 bits, "phone one digit off" +4.5.

**Threshold** (`ThresholdRule` on out-of-fold train scores): for the pipeline as written, the lowest weight with 0 false pairs is 6 (0 of 1,392 accepted), and one step of margin gives 8. Every decision variant gets its own threshold the same way; `FINAL`'s is **6**.

**Decisions** (`adopt`: paired on cross-validated train; on val, no true pair lost, except for the owner's "chosen" calls, which may move recall but add no false pair):

| Change | Kind | Cross-validated train | Val | Adopted |
|---|---|---|---|---|
| term-frequency adjustment off | better | +15 / −0 true pairs (p = 0.0001), no FP added | +2 / −0 | **yes** |
| exact keys only (drop sorted neighbourhood, TF-IDF) | cheaper | −3 true pairs | ±0 | no |
| Optuna's suggestion (below) | better | +172 / −0 (p < 10⁻⁵⁰), no FP added | +43 / −0 | **yes** |
| u from 1e6 pairs instead of 1e7 | cheaper | +9 / −26 (p = 0.006) | +0 / −1 | no |
| phone key → three compound keys (scale) | cheaper | +0 / −0 | +0 / −0 | **yes** |
| TF-IDF → sorted neighbourhood on the name and the reversed name (scale) | cheaper | +1 / −0 (p = 1.0) | +0 / −0 | **yes** |
| five name keys: no potential match left to a sorted window (scale) | safer | +1 / −0, no FP added | +0 / −0 | **yes** |
| the address only with the phone, the name's first letter or the given name (scale) | cheaper | +0 / −0 | +0 / −0 | **yes** |
| no sorted windows | cheaper | +0 / −3 | +0 / −1 | no |
| score every pair across two rule clusters | better | +12 / −0 (p = 0.0005), no FP added | +4 / −0 | **yes** |
| u re-sampled on each scored file (owner's decision, for scale) | chosen | +63 / −0 (p < 10⁻¹⁸), no FP added | +20 / −0 | **yes** |
| u of the leading exact levels counted from value counts, not sampled (owner's decision, for scale) | chosen | +0 / −122, no FP added | +0 / −27 | **yes** |

**Results with `FINAL`** (17 generators, pairs across two rule clusters scored, u from each scored file with the exact levels counted, term frequency off, m by EM, Optuna's JW thresholds, threshold 6, connected components):

| Data | After deterministic → after probabilistic | 95% interval | FP | FP rate ≤ |
|---|---|---|---|---|
| train | 69.2% → 89.7% | 89.0–90.4% | 2 | 0.10% |
| val | 69.5% → 91.3% | 90.1–92.4% | 0 | 0.15% |
| **test** | 71.1% → **89.9%** | 88.7–91.1% | **0** | 0.14% |

Train is scored in-sample (the model is fitted on all of it). It has 2 false pairs, in one over-merged cluster; out-of-fold, no adopted change added a false pair.

**The threshold transfers:** at weight 6, cross-validated train accepts 0 false of 1,386 pairs (rate ≤ 0.22%) and val 0 of 460. `scripts/choose.py` checks this on every run.

**Worked example:** `reports/choose.md` breaks one accepted and one rejected pair into bits; the README walks through both, and section 8 of the demo draws two more.

**Optuna** (cross-validated objective, 30 trials, seeded; off by default since round 4, `fs_tune`, `enabled=False`): each trial switches generators off and picks the m method, term frequency, level thresholds and resolver. Its threshold comes from the threshold rule, as `FINAL`'s does.
- **Round 1** searched the threshold directly. Its 0-FP suggestion (trial 12) passed `adopt` against `FINAL` (cross-validated train +280 / −0, val +92 / −0) and became the `optuna_suggestion` decision. It drops four generators (folded-name keys, person sorted neighbourhood, company TF-IDF) and changes the JW thresholds (names 0.95 / 0.75, companies 0.97 / 0.80).
- That round searched the threshold directly, which could never converge with the threshold rule ([lessons.md](lessons.md)); trials now take the rule's threshold.
- **Round 2,** from the new `FINAL`: the suggestion (trial 19: 0 FP out-of-fold, 90.8% recall; 0 FP on val, 91.5%) did not pass `adopt` (+11 / −7, p = 0.48).
- **Round 3,** after the scale changes: the suggestion (trial 25: 0 FP out-of-fold, 90.6%; 0 FP on val, 91.3%) does not pass either (cross-validated train +6 / −18, p = 0.023; val +4 / −8).
- **Round 4,** after the name keys and bridging: the suggestion (trial 3: 0 FP out-of-fold, 90.8%; 0 FP on val, 91.4%) loses true pairs (cross-validated train +0 / −12, p = 0.0005; val +0 / −6). The search has converged.

## Benchmark

`scripts/benchmark.py` runs `FINAL` the way a real file is run (`er.run`, without labels), without re-tuning anything, and writes [`reports/benchmark.md`](../reports/benchmark.md). Chapter [6](guide/06-measuring-and-choosing.md#challenge-does-it-hold-beyond-our-one-dataset) explains the scenarios, and chapter [3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records) the cost.

> Measured before the standardization fixes of 2026-11-05 (full-width spaces, blank values), which changed the matching results; run `scripts/benchmark.py` again to refresh it.

### Scenarios

Each population's test split, with λ, u and m fitted on its train split without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.7106 | 0.899 | 0.886–0.911 | 0 | 0.14% |
| seed 1 | 0.7029 | 0.9069 | 0.895–0.918 | 0 | 0.14% |
| seed 2 | 0.6691 | 0.8877 | 0.874–0.900 | 0 | 0.15% |
| typos doubled | 0.6738 | 0.8881 | 0.874–0.900 | 0 | 0.15% |
| fields emptier (last column 45% filled) | 0.6275 | 0.885 | 0.872–0.897 | 0 | 0.14% |
| prior_recall 0.25 (λ ×2) | 0.7106 | 0.9147 | 0.903–0.925 | 0 | 0.14% |
| prior_recall 0.75 (λ ×⅔) | 0.7106 | 0.8914 | 0.878–0.903 | 0 | 0.14% |

### Cost: files of growing size (time grows like N^0.18)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample inside `score` (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12392 | 19.1 | 0.58 | 0.11 | 0.05 | 9.68 | 0.25 | 0.14 | 8.79 | 0.03 | 0.03 | 0.8888 | 0 | 0.12% |
| 24944 | 19.0 | 0.67 | 0.18 | 0.08 | 9.55 | 0.3 | 0.23 | 8.57 | 0.04 | 0.06 | 0.8955 | 3 | 0.16% |
| 50215 | 18.8 | 0.78 | 0.32 | 0.14 | 8.61 | 0.4 | 0.4 | 8.78 | 0.06 | 0.12 | 0.8929 | 1 | 0.05% |
| 75284 | 19.7 | 0.96 | 0.46 | 0.2 | 8.53 | 0.5 | 0.56 | 9.17 | 0.09 | 0.18 | 0.8902 | 5 | 0.07% |
| 999481 | 40.6 | 4.45 | 5.26 | 0.86 | 7.45 | 3.33 | 3.15 | 18.94 | 0.43 | 1.13 | — | — | — |
