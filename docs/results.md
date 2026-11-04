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

None adds a false pair. **Optuna** (60 trials on train, ≈ 50 s) starts from `FINAL`: its suggestion passed the same rule and became a `CHANGES` entry. Re-run from the new `FINAL`, the search's suggestion joins exactly the same pairs as `FINAL` (it differs only in using address Levenshtein ≤ 1 instead of JW ≥ 0.91), so the loop has converged.

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
- λ comes from near-certain rules, u from 1e7 random pairs, m from EM (or labels).
- There are five comparisons: name, company, address, phone, cif. Correlated columns share one comparison (address code / normalized address / postal form one), because FS assumes independence.
- Levels use the `cl_*` functions.
- **A level without an estimate never uses Splink's defaults.** No sampled pair reached it → u at its 95% upper bound, so its weight is a lower bound on the evidence. Never seen in training → m = u, 0 bits. The training cell lists such levels (none in `SPEC`).

**Scores don't depend on the size of the scored set** (`er.match.score_fs`):
- **Term frequencies** come from the fitting records, stored in the model. A value never seen in training gets no adjustment, the conservative side.
- **λ** is a per-pair rate: true pairs grow with N, pairs with N². It is rescaled from the fitting set's size to the scored set's. So CV folds, val and test (about 10k records each) are scored on the same scale, and the threshold keeps its meaning at production size. There, the same evidence earns log2(N/10k) fewer bits.
- Why this matters, and the bug it replaced: [lessons.md](lessons.md).

**Candidates** (val: 683 true pairs the deterministic stage missed):

| Generators (cumulative) | Candidates | Missed pairs reached |
|---|---|---|
| phone | 4,985 | 47.6% |
| + address, address code, CIF | 6,566 | 84.3% |
| + folded person name, folded company name | 6,724 | 93.1% |
| + sorted neighbourhood | 31,942 | 93.6% |
| + TF-IDF | 33,871 | **93.9%** |

`FINAL` keeps six of them (phone, address, address code, CIF, company sorted neighbourhood, person TF-IDF): 14,180 candidates on val.

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

**Results with `FINAL`** (six generators, term frequency off, m by EM, Optuna's JW thresholds, threshold 6, connected components):

| Data | After deterministic → after probabilistic | 95% interval | FP | FP rate ≤ |
|---|---|---|---|---|
| train | 69.2% → 89.3% | 88.5–90.0% | 0 | 0.05% |
| val | 69.3% → 91.5% | 90.2–92.6% | 0 | 0.15% |
| **test** | 71.1% → **90.2%** | 88.9–91.3% | **0** | 0.14% |

**The threshold transfers:** at weight 6, cross-validated train accepts 0 false of 1,430 pairs (rate ≤ 0.21%) and val 0 of 471. The evaluation cell prints this check on every run.

**Worked example:** the notebook's "Why a pair matches" cell breaks one accepted and one rejected pair into bits; the README walks through both.

**Optuna** (cross-validated objective, 30 trials, seeded): each trial switches generators off and picks the m method, term frequency, level thresholds and resolver. Its threshold comes from `THRESHOLD_RULE`, as `FINAL`'s does.
- **Round 1** searched the threshold directly. Its 0-FP suggestion (trial 12) passed `adopt` against `FINAL` (cross-validated train +280 / −0, val +92 / −0) and became the `optuna_suggestion` decision. It drops four generators (folded-name keys, person sorted neighbourhood, company TF-IDF) and changes the JW thresholds (names 0.95 / 0.75, companies 0.97 / 0.80).
- That round searched the threshold directly, which could never converge with the threshold rule ([lessons.md](lessons.md)); trials now take the rule's threshold.
- **Round 2,** from the new `FINAL`: the suggestion (trial 19: 0 FP out-of-fold, 90.8% recall; 0 FP on val, 91.5%) does not pass `adopt` (+11 / −7, p = 0.48). The search has converged.
