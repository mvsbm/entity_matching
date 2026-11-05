[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Each table is explained in chapters [4](guide/04-certain-cases-first-rules.md), [5](guide/05-uncertain-evidence-fellegi-sunter.md) and [6](guide/06-measuring-and-choosing.md).*

# Results

Every number here is printed by a notebook; the full outputs are in [`notebooks/pdf/`](../notebooks/pdf/).

## Stage 1: deterministic matching

**Rules:**
- **exact:**
  - CIF_ID + FULL_NAME_KANA
  - CIF_ID + NYS_CNV_P_NAME_KANA
  - CIF_ID + PHONE_NUM_4
  - FULL_NAME_KANA + SOURCE_ADDR_CD + PHONE_NUM_4
  - NYS_CNV_P_NAME_KANA + SOURCE_ADDR_CD + PHONE_NUM_4
- **fuzzy:** one `Comparator` per column over derived fallback columns, plus the surname-change rule (given name + address code + phone):

  | Column | As written (`SPEC`) | Adopted (`FINAL`) |
  |---|---|---|
  | `PERSON_NAME` | kana fold → JW ≥ 0.92 | kana fold → Levenshtein ≤ 2 |
  | company name | legal form stripped, kana fold → JW ≥ 0.92 | character-set Jaccard ≥ 0.77 |
  | `ADDRESS` | normalized (all typed formats give one key) → exact | normalized → JW ≥ 0.91 |
  | phone | Hamming ≤ 1 | Damerau–Levenshtein ≤ 1 |

The train-only design analysis justifies "never one key alone". Single keys collide across entities: phone 45,506 different-entity pairs, postal code 41,868, given name 117,118, even the full name 230. Every exact rule's key combination has 0. The fuzzy rules' join keys have at most 4, and their fuzzy conditions reject those.

**Decisions** (`adopt`, each on top of the choice so far; rules fit nothing, so train is the selection set):

| Change | Rule | Train: true pairs gained / lost | Val: gained / lost | Adopted |
|---|---|---|---|---|
| names: fold → Levenshtein ≤ 1 | better | 14 / 3 (p = 0.013) | 6 / 0 | yes |
| names: fold → exact | cheaper | 0 / 173 | 0 / 66 | no |
| Optuna's comparators (below) | better | 26 / 1 (p < 0.001) | 6 / 0 | yes |
| F2 joins on phone + exact normalized address (scale) | cheaper | 0 / 8 (p = 0.008) | 0 / 3 | no |
| F2 joins on phone + first 3 characters of the normalized address (scale) | cheaper | 0 / 0 | 0 / 0 | **yes** |

None adds a false pair. The two F2 rows exist for scale: as written, F2 joins on the last four phone digits alone, which grows like N^1.89 and projects to 55.8 million pairs at a million records. An earlier alternative, joining on the phone plus the name initial or the postal area, lost 2 true pairs on train and was dropped. The adopted one projects to 0.12 million ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).

**Optuna** (60 trials on train, ≈ 90 s) starts from `FINAL`: its first suggestion passed the same rule and became a `CHANGES` entry. Re-run from the final `FINAL`, the suggestion (trial 47) gains 1 true pair and loses none (p = 1.0), so it is not adopted and the loop has converged. The study is now off by default (`TUNE.enabled`).

**Results with `FINAL`:**

| Data | Recall | 95% interval | FP | FP rate ≤ |
|---|---|---|---|---|
| train | 69.2% | 68.1–70.3% | 0 | 0.06% |
| val | 69.3% (exact rules alone: 52.2%) | 67.4–71.2% | 0 | 0.19% |
| **test** | **71.1%** | 69.2–72.9% | **0** | 0.18% |

Paired A/B on val against `SPEC` (informational; decisions use the rule above), all with 0 FP:

| Variant | True pairs gained / lost | p |
|---|---|---|
| fold → Levenshtein ≤ 1 | 6 / 0 | 0.031 |
| fold → exact | 0 / 60 | < 0.001 |
| raw Jaro-Winkler (no kana folding) | 1 / 53 | < 0.001 |
| constrained resolver (cannot-link on given name) | 0 / 210 | < 0.001 |
| Optuna's comparators | 12 / 0 | < 0.001 |

The constrained resolver loses because given-name typos look like conflicts.

## Stage 2: probabilistic matching

**Method:** the **Fellegi–Sunter model (Splink 5)** is the only probabilistic method so far; every A/B row is a variant of it.
- λ comes from near-certain rules, u from 1e7 random pairs, m from EM (or labels). `FINAL` re-samples u on each scored file.
- There are five comparisons: name, company, address, phone, cif. Correlated columns share one comparison (address code / normalized address / postal form one), because FS assumes independence.
- Levels use the `cl_*` functions.
- **A level without an estimate never uses Splink's defaults.** No sampled pair reached it → u at its 95% upper bound, so its weight is a lower bound on the evidence. Never seen in training → m = u, 0 bits. The training cell lists such levels (none in `SPEC`).

**Scores are calibrated to the scored file** (`er.match.score_fs`, `er.match.with_scored_u`):
- **Term frequencies** come from the fitting records, stored in the model. A value never seen in training gets no adjustment, the conservative side.
- **λ** is a per-pair rate: true pairs grow with N, pairs with N². It is rescaled from the fitting set's size to the scored set's. So CV folds, val and test (about 10k records each) are scored on the same scale, and the threshold keeps its meaning at production size. There, the same evidence earns log2(N/10k) fewer bits.
- **u** is re-sampled on the scored file's records (no labels; 1e7 pairs, about 8 s whatever the size), because a field whose values grow with the file agrees by chance less often in a bigger one. m stays from train.
- Why this matters, and the bug it replaced: [lessons.md](lessons.md).

**Candidates on train** (2,135 true pairs the deterministic stage missed), every generator in `SPEC` and `SCALABLE`, in order:

| Generators (cumulative) | Pairs they make | Missed pairs reached | Pairs at 1M |
|---|---|---|---|
| phone | 43,054 | 50.4% | 27.3 million (α 1.80) |
| + address, address code, CIF | 22,453 | 84.8% | ≤ 4.0 million each |
| + folded person name, folded company name | 1,710 | 93.5% | ≤ 0.18 million each |
| + sorted neighbourhood (person, company) | 77,653 | 93.9% | 3 million per pass |
| + TF-IDF (person, company) | 24,417 | 94.4% | N² |
| + phone + prefecture / postal area / name initial | 3,978 | 94.4% | ≤ 0.39 million each |
| + sorted neighbourhood on the reversed name | 63,359 | 94.9% | 3 million |
| + company-name deletion keys, person-name deletion keys within the postal area, given name + postal code | 2,166 | **95.1%** | ≤ 0.23 million each |

**`FINAL`'s candidates on val** (683 missed pairs; each generator alone):

| Generator | Pairs | Missed pairs reached |
|---|---|---|
| address | 1,498 | 36.9% |
| address code | 1,380 | 31.3% |
| CIF | 81 | 11.9% |
| company-name sorted neighbourhood | 4,810 | 9.7% |
| phone + prefecture | 196 | 17.7% |
| phone + postal area | 167 | 24.0% |
| phone + name initial | 371 | 26.5% |
| person-name sorted neighbourhood | 22,577 | 42.9% |
| the same on the reversed name | 22,497 | 52.6% |
| person name, exact | 320 | 39.8% |
| company name, exact | 116 | 9.7% |
| company-name deletion keys | 169 | 10.1% |
| person-name deletion keys within the postal area | 194 | 28.4% |
| given name + postal code | 181 | 26.2% |
| **all 14** | **51,484** | **92.5%** (632 of 683) |

That is 51,484 candidates on val (99.90% of all pairs skipped). Before the scale changes, `FINAL` used the phone key and person-name TF-IDF instead: 14,180 candidates reaching 93.9%. None of the 9 missed pairs no longer on the list could have been accepted: on every split, every true pair that could reach the threshold shares one of `FINAL`'s keys, at its own size and at a million records ([chapter 3](guide/03-far-too-many-pairs.md#keeping-every-potential-match); the "Will it scale?" cell checks train on every run).

**Training:** EM and labels learn the same weights within noise.
- Agreeing on CIF, phone, same address or postal code is worth about 11–16 bits; an exact name about 15.5.
- "address close" (Levenshtein ≤ 2 on the normalized address) is worth +8.9 bits, "phone one digit off" +4.5.

**Threshold** (`ThresholdRule` on out-of-fold train scores): for `SPEC`, the lowest weight with 0 false pairs is 6 (0 of 1,397 accepted), and one step of margin gives 8. Every decision variant gets its own threshold the same way; `FINAL`'s is **6**.

**Decisions** (`adopt`: paired on cross-validated train, plus no paired loss on val):

| Change | Rule | Cross-validated train | Val | Adopted |
|---|---|---|---|---|
| term-frequency adjustment off | better | +15 / −0 true pairs (p = 0.0001), no FP added | +2 / −0 | **yes** |
| exact keys only (drop sorted neighbourhood, TF-IDF) | cheaper | −4 true pairs | ±0 | no |
| Optuna's suggestion (below) | better | +198 / −0 (p < 10⁻⁵⁰), no FP added | +62 / −1 | **yes** |
| u from 1e6 pairs instead of 1e7 | cheaper | +10 / −24 (p = 0.024) | +0 / −3 | no |
| phone key → three compound keys (scale) | cheaper | +0 / −0 | +0 / −0 | **yes** |
| TF-IDF → sorted neighbourhood on the name and the reversed name (scale) | cheaper | +2 / −0 (p = 0.5) | +0 / −0 | **yes** |
| five name keys: no potential match left to a sorted window (scale) | safer | +1 / −0, no FP added | +1 / −0 | **yes** |
| score every pair across two rule clusters | better | +12 / −0 (p = 0.0005), no FP added | +4 / −0 | **yes** |
| u re-sampled on each scored file (owner's decision, for scale) | chosen | +0 / −27 (p < 10⁻⁷), no FP added | +0 / −8 | **yes** |

**Results with `FINAL`** (14 generators, pairs across two rule clusters scored, u from each scored file, term frequency off, m by EM, Optuna's JW thresholds, threshold 6, connected components):

| Data | After deterministic → after probabilistic | 95% interval | FP | FP rate ≤ |
|---|---|---|---|---|
| train | 69.2% → 89.5% | 88.7–90.2% | 0 | 0.05% |
| val | 69.3% → 91.3% | 90.1–92.4% | 0 | 0.15% |
| **test** | 71.1% → **89.9%** | 88.6–91.1% | **0** | 0.14% |

**The threshold transfers:** at weight 6, cross-validated train accepts 0 false of 1,419 pairs (rate ≤ 0.21%) and val 0 of 466. The evaluation cell prints this check on every run.

**Worked example:** the notebook's "Why a pair matches" cell breaks one accepted and one rejected pair into bits; the README walks through both.

**Optuna** (cross-validated objective, 30 trials, seeded; off by default since round 4, `PTUNE.enabled`): each trial switches generators off and picks the m method, term frequency, level thresholds and resolver. Its threshold comes from `THRESHOLD_RULE`, as `FINAL`'s does.
- **Round 1** searched the threshold directly. Its 0-FP suggestion (trial 12) passed `adopt` against `FINAL` (cross-validated train +280 / −0, val +92 / −0) and became the `optuna_suggestion` decision. It drops four generators (folded-name keys, person sorted neighbourhood, company TF-IDF) and changes the JW thresholds (names 0.95 / 0.75, companies 0.97 / 0.80).
- That round searched the threshold directly, which could never converge with the threshold rule ([lessons.md](lessons.md)); trials now take the rule's threshold.
- **Round 2,** from the new `FINAL`: the suggestion (trial 19: 0 FP out-of-fold, 90.8% recall; 0 FP on val, 91.5%) did not pass `adopt` (+11 / −7, p = 0.48).
- **Round 3,** after the scale changes: the suggestion (trial 25: 0 FP out-of-fold, 90.6%; 0 FP on val, 91.3%) does not pass either (cross-validated train +6 / −18, p = 0.023; val +4 / −8).
- **Round 4,** after the name keys and bridging: the suggestion (trial 3: 0 FP out-of-fold, 90.8%; 0 FP on val, 91.4%) loses true pairs (cross-validated train +0 / −12, p = 0.0005; val +0 / −6). The search has converged.

## Robustness and scale

`scripts/robustness.py` re-runs both final configurations in memory, without re-tuning anything, and writes `data/artifacts/robustness/report.md`. Chapter [6](guide/06-measuring-and-choosing.md#challenge-does-it-hold-beyond-our-one-dataset) explains the scenarios, and chapter [3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records) the cost.

### Scenarios (test split, fixed final configurations, nothing re-tuned)

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most |
| --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.7106 | 0.899 | 0.886–0.911 | 0 | 0.14% |
| seed 1 | 0.7029 | 0.9057 | 0.893–0.917 | 0 | 0.14% |
| seed 2 | 0.6691 | 0.8877 | 0.874–0.900 | 0 | 0.15% |
| typos doubled | 0.6738 | 0.8889 | 0.875–0.901 | 0 | 0.15% |
| fields emptier (last column 45% filled) | 0.6275 | 0.8842 | 0.871–0.896 | 0 | 0.14% |
| prior_recall 0.25 (λ ×2) | 0.7106 | 0.9147 | 0.903–0.925 | 0 | 0.14% |
| prior_recall 0.75 (λ ×⅔) | 0.7106 | 0.8914 | 0.878–0.903 | 0 | 0.14% |

### Cost: both stages on files of growing size (time grows like N^0.59: about 8 s per file is u-sampling, a fixed cost)

One model fitted on train. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | rules_seconds | probabilistic_seconds | peak_memory_gb | recall | false_merges | fp_rate_at_most | potential_off_list | recall_u_from_train |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12392 | 0.4 | 9.3 | 1.2 | 0.8977 | 0 | 0.12% | 0 | 0.8992 |
| 24944 | 0.7 | 10.0 | 1.3 | 0.8978 | 4 | 0.18% | 0 | 0.8987 |
| 50215 | 1.1 | 10.6 | 1.6 | 0.8947 | 1 | 0.05% | 0 | 0.8873 |
| 75284 | 1.5 | 12.0 | 2.2 | 0.8869 | 5 | 0.07% | 0 | 0.8759 |
| 999481 | 17.5 | 96.4 | 7.5 | — | — | — | — | — |
