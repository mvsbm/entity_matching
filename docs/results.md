[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Each table is explained in chapters [4](guide/04-certain-cases-first-rules.md), [5](guide/05-uncertain-evidence-fellegi-sunter.md) and [6](guide/06-measuring-and-choosing.md).*

# Results

Every number here is printed by `scripts/choose.py` ([`reports/choose.md`](../reports/choose.md)) or `scripts/benchmark.py` ([`reports/benchmark.md`](../reports/benchmark.md)); the rules and the model are in `config/final.toml`, in the logical fields of `config/settings.toml` `[columns]`. `FINAL` is the reports' name for that chosen pipeline: every change `scripts/choose.py` adopted, written to `config/final.toml`.

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
  | person name | kana fold → JW ≥ 0.92 | kana fold → Damerau–Levenshtein ≤ 2 |
  | company name | NFKC, legal form stripped, kana fold → JW ≥ 0.92 | NFKC, legal form stripped, kana fold → Levenshtein ≤ 1 |
  | address | normalized (all typed formats give one key) → exact | normalized → JW ≥ 0.9 |
  | phone | Hamming ≤ 1 | Hamming ≤ 1 |

  Rule F2 (name, address and phone) joins on the phone and the first three characters of the normalized address.

The train-only design analysis justifies "never one key alone". Single keys collide across entities: phone 45,079 different-entity pairs, postal code 33,413, given name 84,380, even the full name 150. Every exact rule's key combination has 0. The fuzzy rules' join keys have at most 4, and their fuzzy conditions reject those.

**Decisions** (`adopt`, each on top of the choice so far; rules fit nothing, so train is the selection set):

| Change | Kind | Train: true pairs gained / lost | Val: gained / lost | Adopted |
|---|---|---|---|---|
| names: fold → Levenshtein ≤ 1 (`fold_levenshtein`) | better | 17 / 4 (p = 0.0072) | 6 / 2 | yes |
| names: fold → exact (`fold_exact`) | cheaper | 0 / 83 | 0 / 26 | no |
| F2's address exact, so F2 joins on phone + normalized address (`f2_address_exact`, scale) | cheaper | 0 / 0 | 0 / 0 | yes |
| F2 joins on phone + first 3 characters of the normalized address (`f2_address_prefix`, scale) | cheaper | 0 / 0 | 0 / 0 | yes |
| Optuna's comparators, the table above (`optuna_comparators`) | better | 33 / 0 (p < 0.0001) | 11 / 0 | yes |

None adds a false pair. The two F2 rows are there for scale. With a fuzzy address check, F2 would join on the last four phone digits alone, the phone key's blocks: about 50 million pairs at a million records. Close normalized addresses share their start, so F2 joins on the phone and the address's first three characters (the city), which loses no true pair and projects to 136,616 pairs at a million records. All the rules together project to 244,185 pairs there, from 3,710 on train ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).

**Optuna** (60 trials on train, seeded; off by default: `rules_tune`, `enabled=False`; `scripts/choose.py --optuna` runs it) searches each field's comparator. Its suggestion passed the same rule and is a change in `config/experiments.py` (`optuna_comparators`), decided last because it was found on top of the rest.

**Results with `FINAL`:**

| Data | Recall | 95% interval | FP | FP rate ≤ |
|---|---|---|---|---|
| train | 10.74% | 10.03–11.49% | 0 | 0.40% |
| val | 9.71% (exact rules alone: 2.98%) | 8.54–11.01% | 0 | 1.38% |
| **test** | **9.71%** | 8.58–10.98% | **0** | 1.31% |

Paired A/B on val against the rules as written (informational; decisions use the rule above), all with 0 FP:

| Variant | True pairs gained / lost | p |
|---|---|---|
| fold → Levenshtein ≤ 1 | 6 / 2 | 0.2891 |
| fold → exact | 0 / 22 | < 0.0001 |
| raw Jaro-Winkler (no kana folding) | 0 / 41 | < 0.0001 |
| constrained resolver (cannot-link on given name) | 0 / 42 | < 0.0001 |
| Optuna's comparators | 21 / 1 | < 0.0001 |
| F2's address exact | 0 / 0 | 1.0 |
| F2 on phone + address prefix | 0 / 0 | 1.0 |

The constrained resolver loses because given-name typos look like conflicts.

## Stage 2: probabilistic matching

**Method:** the **Fellegi–Sunter model (Splink 5)** is the only probabilistic method; every A/B row is a variant of it.
- λ comes from near-certain rules and m from EM (or labels), both on the fitting records. EM's own u come from 10⁶ random pairs of those records (`fit_u_max_pairs`). The u the scores use are measured on each scored file (below).
- There are six comparisons: name, company, address, phone, cif, birth. Correlated columns share one comparison (address code, normalized address, postal code, town, city and prefecture form one), because FS assumes independence.
- Levels use the `cl_*` functions.
- **A level without an estimate never uses Splink's defaults.** No sampled pair reached it → u at its 95% upper bound, so its weight is a lower bound on the evidence. Never seen in training → m = u, 0 bits. The training table lists such levels (none in the pipeline as written).

**Scores are calibrated to the scored file** (`er.match.score_fs`, `er.match.with_scored_u`):
- **Term frequencies** come from the fitting records, stored in the model. A value never seen in training gets no adjustment, the conservative side. `FINAL` turns them off.
- **λ** is a per-pair rate: true pairs grow with N, pairs with N². It is rescaled from the fitting set's size to the scored set's. So CV folds, val and test (about 10k records each) are scored on the same scale, and the threshold keeps its meaning at any size: on a file of N records, the same evidence earns log2(N/10k) fewer bits than on a 10k file.
- **u** is measured on the scored file's records, without labels, because a field whose values grow with the file agrees by chance less often in a bigger one. The leading exact levels are counted from value counts. A one-edit level right after them on the same column (the customer ID, phone or birth date one digit off) is counted exactly too: the distinct values are joined on their one-character deletions, which two values one edit apart always share. So cif, phone and birth need no sample; name, company and address are sampled on 10⁷ random pairs, every one of them. m stays from train.
- Why this matters: [lessons.md](lessons.md).

**Candidates on train** (6,177 true pairs the deterministic stage missed): every generator in `config/pipeline.toml` `[generators]`, in order, from `reports/choose.md`. Pairs per record at a million records are projected by `scale_check` (pairs of one entity × N, chance pairs × N²):

| Generator | Pairs | Missed pairs it reaches | Cumulative | Pairs per record at 1M |
|---|---|---|---|---|
| phone | 46,675 | 27.02% | 27.02% | 49.823 |
| address | 5,507 | 10.99% | 37.19% | 5.373 |
| address_code | 6,063 | 21.01% | 48.00% | 5.345 |
| cif | 37 | 0.60% | 48.50% | 0.005 |
| person_name | 3,651 | 52.00% | 75.31% | 0.609 |
| company_name | 746 | 7.12% | 79.50% | 0.354 |
| sn_person_name | 70,472 | 59.32% | 82.97% | 3.0 |
| sn_company_name | 15,030 | 9.54% | 84.33% | 3.0 |
| tfidf_person_name | 28,092 | 61.84% | 86.03% | 1,000,000 (N²) |
| tfidf_company_name | 2,805 | 9.49% | 86.11% | 1,000,000 (N²) |
| phone_prefecture | 1,729 | 12.21% | 86.11% | 1.116 |
| phone_postal_area | 462 | 5.99% | 86.11% | 0.131 |
| phone_name_initial | 2,730 | 19.49% | 86.11% | 1.745 |
| sn_person_name_reversed | 70,478 | 60.82% | 88.41% | 3.0 |
| company_name_deletions | 1,210 | 7.48% | 88.44% | 0.843 |
| cif_deletions | 53 | 0.86% | 88.46% | 0.006 |
| person_name_deletions_postal_area | 1,418 | 22.70% | 88.51% | 0.081 |
| given_name_postal | 971 | 15.56% | 88.73% | 0.055 |
| address_phone | 53 | 0.83% | 88.73% | 0.012 |
| address_code_phone | 92 | 1.47% | 88.73% | 0.021 |
| address_name_initial | 649 | 7.43% | 88.73% | 0.233 |
| address_code_name_initial | 1,110 | 14.62% | 88.73% | 0.276 |
| given_name_address_code | 637 | 10.30% | 88.73% | 0.035 |
| given_name_phone | 905 | 14.47% | 88.73% | 0.055 |
| birth_date | 333 | 1.30% | 88.83% | 0.282 |
| birth_date_deletions_prefecture | 324 | 0.83% | 88.83% | 0.313 |

The keys that pair the phone or the address with one more field add nothing to the cumulative reach: every pair they list shares the phone, the address or the address code, whose keys come first. They replace those three in `FINAL`. At a million records, the phone key alone would make 49.8 pairs per record and its three compound keys 3.0 together; the two address keys 10.7, and their five compound keys 0.6.

**`FINAL`'s candidates on val** (each generator alone, and the share of the true pairs the rules missed that it reaches):

| Generator | Pairs | Missed pairs reached |
|---|---|---|
| cif | 7 | 0.35% |
| sn_company_name | 5,093 | 9.15% |
| phone_prefecture | 342 | 12.00% |
| phone_postal_area | 139 | 6.65% |
| phone_name_initial | 577 | 19.50% |
| sn_person_name | 23,218 | 60.05% |
| sn_person_name_reversed | 23,210 | 64.70% |
| person_name | 1,088 | 52.10% |
| company_name | 203 | 7.60% |
| company_name_deletions | 270 | 7.95% |
| person_name_deletions_postal_area | 426 | 21.05% |
| given_name_postal | 301 | 15.05% |
| address_phone | 18 | 0.90% |
| address_code_phone | 38 | 1.90% |
| address_name_initial | 158 | 7.20% |
| address_code_name_initial | 293 | 13.60% |
| given_name_address_code | 204 | 10.20% |
| cif_deletions | 11 | 0.55% |
| birth_date | 66 | 2.00% |
| given_name_phone | 282 | 14.00% |
| birth_date_deletions_prefecture | 48 | 1.00% |
| **all 21** | **50,923** | **86.1%** |

That is 50,923 candidates on val (99.90% of all pairs skipped). Every true pair on train that could reach the threshold shares one of `FINAL`'s keys, not only a sorted window: 3,036 such pairs at train's size and 2,960 at a million records, none window-only ([chapter 3](guide/03-far-too-many-pairs.md#keeping-every-potential-match); `scripts/choose.py` checks train on every run). Without labels, `pattern_coverage` finds 226 agreement patterns that can reach the threshold at a million records with no guaranteed key. The model puts their share of matches at 11.92% at most, an upper bound, since a Jaro–Winkler level implies no key.

**Training** (the pipeline as written, on train): EM and labels learn nearly the same weights, within about half a bit on every agreeing level. The company's else level differs most: −2.66 bits by EM, −1.60 from labels.
- By EM, the customer ID is worth 17.4 bits, an exact or folded-exact name 15.6–15.8, the same address 13.3, the phone 11.4, the postal code 10.3.
- "address close" (Levenshtein ≤ 2 on the normalized address) is worth +2.2 bits, "phone one digit off" +4.1.

**Threshold** (`ThresholdRule` on out-of-fold train scores, 3 folds): for the pipeline as written, the lowest weight with 0 false pairs is 10 (0 of 2,057 accepted), and one step of margin gives 12. Every decision variant gets its own threshold the same way; `FINAL`'s is **8**.

| Weight | Accepted | False pairs | Recall | Eligible |
|---|---|---|---|---|
| 0 | 3,194 | 27 | 59.23% | no |
| 2 | 3,081 | 8 | 57.72% | no |
| 4 | 2,966 | 3 | 56.16% | no |
| 6 | 2,649 | 1 | 51.23% | no |
| 8 | 2,380 | 1 | 47.07% | no |
| 10 | 2,057 | 0 | 42.18% | yes |
| 12 | 925 | 0 | 24.51% | yes |
| 14 | 280 | 0 | 14.86% | yes |
| 16 | 218 | 0 | 13.93% | yes |

**Decisions** (`adopt`, in order, each on top of the choice so far: paired on cross-validated train; on val, no more true pairs lost than gained. The owner's "chosen" calls may move recall. No change adds a false pair, on cross-validated train or on val):

| Change | Kind | Cross-validated train: true pairs gained / lost | Val | Adopted |
|---|---|---|---|---|
| term-frequency adjustment off (`no_term_frequency`) | better | +12 / −0 (p = 0.0005) | +15 / −0 | yes |
| exact keys only: no sorted windows, no TF-IDF (`exact_keys_only`) | cheaper | +0 / −0 | +0 / −0 | yes |
| Optuna's suggestion, below (`optuna_suggestion`) | better | +1,488 / −1 (p < 0.0001) | +243 / −0 | yes |
| u from 10⁶ pairs instead of 10⁷ (`u_from_1e6_pairs`) | cheaper | +1 / −8 (p = 0.0391) | +0 / −1 | no |
| phone key → phone + prefecture, postal area or name initial (`compound_phone_keys`, scale) | cheaper | +0 / −0 | +0 / −0 | yes |
| TF-IDF → sorted neighbourhood on the name and the reversed name (`sorted_names_for_tfidf`, scale) | cheaper | +1 / −0 | +4 / −0 | yes |
| five name keys: no potential match left to a sorted window (`name_keys`, scale) | safer | +1 / −0 | +0 / −0 | yes |
| the address only with the phone, the name's first letter or the given name (`bounded_address_keys`, scale) | cheaper | +0 / −0 | +0 / −0 | yes |
| no sorted windows (`no_sorted_windows`) | cheaper | +0 / −0 | +0 / −1 | no |
| score every pair across two rule clusters (`bridge_rule_clusters`) | better | +0 / −0 | +0 / −0 | no |
| u measured on each scored file (`u_from_scored_file`, owner's decision, for scale) | chosen | +0 / −60 (p < 0.0001) | +0 / −12 | yes |
| u of the leading exact levels from value counts, not sampled (`u_exact_by_counts`, owner's decision, for scale) | chosen | +47 / −5 (p < 0.0001) | +0 / −0 | yes |
| the customer ID one digit off, a level (`cif_one_digit_off`) | better | +8 / −0 (p = 0.0078) | +2 / −0 | yes |
| its key: the customer ID's one-character deletions (`cif_deletion_key`) | safer | +2 / −0 (p = 0.5) | +0 / −0 | yes |
| graded address: the same town, city or prefecture after the postal code (`graded_address`) | better | +124 / −67 (p < 0.0001) | +29 / −20 | yes |
| the birth date: exact, one digit off (`birth_date`) | better | +56 / −0 (p < 0.0001) | +22 / −0 | yes |
| its key: the birth date (`birth_date_key`) | safer | +1 / −0 | +0 / −0 | yes |
| the given name + the phone, a key (`given_name_phone_key`) | safer | +0 / −0 | +0 / −0 | yes |
| the birth date's deletions within the prefecture, a key (`birth_date_deletion_key`) | safer | +0 / −0 | +0 / −0 | yes |
| one-edit levels counted through one-character deletions, not sampled (`u_near_by_keys`, owner's decision, for scale) | chosen | +0 / −2 (p = 0.5) | +0 / −0 | yes |
| the fit's own u from 10⁶ pairs, for EM only (`fit_u_from_1e6_pairs`) | cheaper | +0 / −0 | +0 / −0 | yes |
| the company without its "JW high" level (`company_without_jw_high`) | cheaper | +1 / −0 | +0 / −0 | yes |
| a name compared, or people decide (`name_needed`, owner's decision) | chosen | +0 / −39 (p < 0.0001) | +0 / −22 | yes |

`optuna_suggestion` sets the generators itself (those of the pipeline as written, less four), so `exact_keys_only` leaves no trace in `FINAL`; the scale changes after it replace the phone, address and TF-IDF keys. The four "chosen" calls lose true pairs on train-sized files on purpose. The three on u make the weights right at any file size: u measured on the file itself, and counted where a sample of 10⁷ pairs can't see an agreement rarer than one in 10⁹ pairs (an exact name, or a customer ID, equal or one digit off, in a big file). The name check holds back pairs with no name compared, such as a household sharing an address and a phone: they go to people ([usage](usage.md#6--review-and-decide)). Train and val hold no such false pair, so its gain shows only at scale.

**Results with `FINAL`** (21 generators, u from each scored file with the exact and one-edit levels counted, term frequency off, m by EM, Optuna's JW thresholds, a name compared, threshold 8, connected components):

| Data | After deterministic → after probabilistic | 95% interval | FP | FP rate ≤ | Accepted pairs |
|---|---|---|---|---|---|
| train | 10.74% → 45.62% | 44.45–46.80% | 0 | 0.09% | 2,267 |
| val | 9.71% → 46.32% | 44.25–48.40% | 0 | 0.29% | 765 |
| **test** | 9.71% → **45.91%** | 43.90–47.94% | **0** | 0.28% | 798 |

Train is scored in-sample (the model is fitted on all of it), and has no false pair either. Test is scored once per stage, with one configuration each.

**The threshold transfers:** at weight 8, cross-validated train accepts 0 false of 2,368 pairs (rate ≤ 0.13%) and val 0 of 765. `scripts/choose.py` checks this on every run. On val, the first false pair comes at 4 bits:

| Weight | Accepted | False pairs | Recall |
|---|---|---|---|
| 0 | 1,280 | 23 | 68.80% |
| 2 | 1,180 | 12 | 64.79% |
| 4 | 907 | 1 | 53.18% |
| 6 | 877 | 0 | 51.74% |
| 8 | 765 | 0 | 46.32% |
| 10 | 518 | 0 | 34.58% |
| 12 | 460 | 0 | 31.78% |
| 14 | 231 | 0 | 20.72% |
| 16 | 90 | 0 | 13.91% |

**Worked example:** `reports/choose.md` breaks two pairs into bits: an accepted true match with a typo (8.07 bits, from the given name, the postal code and a phone one digit off), and the rejected non-match closest to the threshold (5.46 bits, from the phone and the prefecture, the names only loosely alike). [Chapter 5](guide/05-uncertain-evidence-fellegi-sunter.md#solution-evidence-in-bits) walks through one pair field by field, and section 8 of the demo draws two more.

**Optuna** (cross-validated objective, 30 trials, seeded; off by default: `fs_tune`, `enabled=False`; `scripts/choose.py --optuna` runs it): each trial switches generators off and picks the m method, term frequency, level thresholds and resolver. Its threshold comes from the threshold rule, as `FINAL`'s does: a search that set the threshold itself would pull against the rule ([lessons.md](lessons.md#two-policies-that-set-one-parameter)). A tuned level the model doesn't have is skipped.
- Its suggestion that passed `adopt` is the `optuna_suggestion` decision. It drops four generators (the person- and company-name keys, the person-name sorted neighbourhood, the company TF-IDF), turns term frequency off, and sets the JW thresholds: names 0.95 / 0.75, companies 0.97 / 0.80. `company_without_jw_high` then drops the company's 0.97 level, which no pair reached.

## Benchmark

`scripts/benchmark.py` runs `FINAL` the way a real file is run (`er.run`, without labels), without re-tuning anything, and writes [`reports/benchmark.md`](../reports/benchmark.md). Chapter [6](guide/06-measuring-and-choosing.md#challenge-does-it-hold-beyond-our-one-dataset) explains the scenarios, and chapter [3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records) the cost.

### Scenarios

Each population's test split, with λ, u and m fitted on its train split without labels. `false_merges` are pairs of records in one cluster that are two entities; `false_links` are the model's links between two entities, and `expected_false` the false links the model expects among its own (the sum of 1 − match probability), which a run reports without labels.

| scenario | rules_recall | recall | interval | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| as reported (seed 0) | 0.0971 | 0.4591 | 0.439–0.479 | 0 | 0.28% | 798 | 0.54 | 0 |
| seed 1 | 0.1108 | 0.463 | 0.443–0.484 | 0 | 0.29% | 753 | 0.49 | 0 |
| seed 2 | 0.1206 | 0.4929 | 0.472–0.514 | 0 | 0.27% | 801 | 0.63 | 0 |
| typos doubled | 0.0812 | 0.3338 | 0.314–0.354 | 0 | 0.41% | 540 | 0.41 | 0 |
| fields emptier (last column 45% filled) | 0.0727 | 0.4172 | 0.397–0.437 | 0 | 0.31% | 767 | 0.68 | 0 |
| prior_recall halved (λ ×2) | 0.0971 | 0.4908 | 0.471–0.511 | 0 | 0.26% | 869 | 0.5 | 0 |
| prior_recall ×1.5 (λ ×⅔) | 0.0971 | 0.4506 | 0.431–0.471 | 0 | 0.28% | 776 | 0.72 | 0 |

### Cost: files of growing size (time grows like N^0.42)

Each file is resolved by `scripts/resolve.py` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample of the file inside it (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | write | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12532 | 8.0 | 0.81 | 0.22 | 0.1 | 7.09 | 0.06 | 0.21 | 0.23 | 0.03 | 0.04 | 0.4573 | 2 | 0.48% | 985 | 0.84 | 1 |
| 24955 | 9.0 | 0.91 | 0.37 | 0.16 | 7.58 | 0.09 | 0.32 | 0.37 | 0.04 | 0.07 | 0.4598 | 0 | 0.12% | 1832 | 1.03 | 0 |
| 50116 | 9.9 | 1.01 | 0.63 | 0.29 | 7.58 | 0.14 | 0.57 | 0.5 | 0.06 | 0.14 | 0.4467 | 0 | 0.06% | 3705 | 2.48 | 0 |
| 74959 | 11.2 | 1.17 | 0.94 | 0.42 | 7.77 | 0.2 | 0.79 | 0.77 | 0.07 | 0.2 | 0.4422 | 4 | 0.12% | 5383 | 4.38 | 3 |
| 1000338 | 47.2 | 5.93 | 10.67 | 1.83 | 9.17 | 2.29 | 6.21 | 15.84 | 0.34 | 0.86 | — | — | — | 38786 | 30.11 | — |

The model makes false merges on two of these populations: 2 false pairs at 12,532 records, through 1 false link, and 4 at 74,959, through 3. They are model links at 8.2–10.1 bits, just over the threshold of 8, between near-namesakes a kana typo apart who share an address or a phone. The model expects about as many (`expected_false`: 0.84 and 4.38), and under one on every scenario's test split, where none appears.

## Person or company

`scripts/choose_kind.py` ([`reports/choose_kind.md`](../reports/choose_kind.md)) chose how records are told apart: 768 combinations, 12 scenarios over what a file can't tell about itself, judged correct first (the share of companies called 2 with at most 0.1% of those calls wrong; of persons called 1 with at most 1% wrong). Chapter [7](guide/07-person-or-company.md) explains it.

### What each idea is worth

The best mean among the 48 finalists with the idea, and without it.

| idea | best_mean |
| --- | --- |
| legal: bank table | 67.8% |
| legal: generator's forms | not among the finalists |
| ngram: 1–3 | 67.8% |
| ngram: 1–4 | 67.0% |
| training: public | 67.6% |
| training: public + the file's legal-form records | 67.8% |
| combiner: gbdt2 | 67.8% |
| combiner: gbdt3 | 66.5% |
| combiner: lr | not among the finalists |
| signal flag: with | 67.8% |
| signal flag: without | — |
| signal birth: with | 67.8% |
| signal birth: without | 67.8% |
| signal birth_year: with | 67.8% |
| signal birth_year: without | 67.1% |
| signal legal: with | 67.8% |
| signal legal: without | — |
| signal known_name: with | 67.6% |
| signal known_name: without | 67.8% |

The pipeline's combination (`config/pipeline.toml` `[kind]`: the bank table, n-grams 1–3, trained once on public data, trees of depth 2 on the flag, the birth year and the legal form) is 8th of 48: mean 67.4%, worst 36.2%, against 67.8% for the best, which also trains on the file's own legal-form records.

### The scenarios, for the pipeline's combination

| scenario | flag_wrong | on_representatives | representative_named_companies | sole_traders | sole_flagged_company | company_dates | companies | persons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 10% | 79% | 19% | 7% | 37% | 35% (founding) | 72.2% | 0.1% |
| 2 | 3% | 21% | 7% | 14% | 31% | 5% (representative) | 76.0% | 93.1% |
| 3 | 6% | 50% | 10% | 4% | 17% | 7% (founding) | 72.9% | 91.1% |
| 4 | 9% | 43% | 14% | 8% | 14% | 22% (representative) | 72.6% | 66.3% |
| 5 | 2% | 58% | 8% | 4% | 24% | 12% (founding) | 74.4% | 97.3% |
| 6 | 8% | 53% | 15% | 9% | 28% | 33% (representative) | 72.9% | 41.0% |
| 7 | 7% | 66% | 9% | 11% | 48% | 53% (founding) | 74.4% | 68.3% |
| 8 | 4% | 33% | 20% | 5% | 46% | 27% (representative) | 70.3% | 3.1% |
| 9 | 7% | 71% | 5% | 3% | 34% | 50% (founding) | 79.9% | 97.5% |
| 10 | 1% | 64% | 17% | 12% | 13% | 20% (representative) | 72.9% | 0.0% |
| 11 | 5% | 29% | 16% | 10% | 22% | 42% (founding) | 72.2% | 89.7% |
| 12 | 5% | 35% | 12% | 14% | 41% | 55% (representative) | 73.2% | 86.3% |

### Counting sole traders

| policy | companies_mean | companies_worst | persons_mean | persons_worst |
| --- | --- | --- | --- | --- |
| individuals | 73.7% | 70.3% | 61.2% | 0.0% |
| by record (a trade-name record a business) | 75.1% | 68.0% | 7.5% | 0.0% |
| businesses (every record) | 71.1% | 62.0% | 0.1% | 0.0% |

### Placing the lines from people's answers

The company line two grid steps stricter than the first clean one; the person line where the answers' wrong share is at most half of 1%. `over_budget`: of the 12 scenarios.

| answers | drawn | company_rule | companies | company_wrong_worst | company_over_budget | persons | person_wrong_worst | person_over_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 500 | random | no error above, then 2 steps stricter | 59.80% | 0.06% | 0 | 22.26% | 1.28% | 2 |
| 500 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 56.82% | 0.84% | 2 | 19.11% | 1.12% | 1 |
| 1000 | random | no error above, then 2 steps stricter | 62.72% | 0.10% | 0 | 15.50% | 0.65% | 0 |
| 1000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 68.38% | 0.02% | 0 | 18.76% | 1.20% | 1 |
| 2000 | random | no error above, then 2 steps stricter | 64.69% | 0.04% | 0 | 20.72% | 0.95% | 0 |
| 2000 | stratified (a third at random, a third leaning company, a third leaning person) | no error above, then 2 steps stricter | 64.14% | 0.13% | 1 | 21.39% | 3.30% | 1 |

### End to end

From `scripts/benchmark.py` ([`reports/benchmark.md`](../reports/benchmark.md)). Populations with one name column for every kind (`er.generate.kind_problems`): real company names from the registry, written as banks write them; companies with records under their representative's name, the representative a person of the file (half at that person's address and phone); sole traders named like a shop; company dates; and a flag good, medium or poor. Each resolved three ways: names routed by the truth (the flag replaced by it, taken as it is); by the flag alone; by the kind step, people answering its review sheet (here, with the truth). `person_company_clusters` hold a true person and a true company; `sure_*` is the share of true companies called 2 and of true persons called 1; `wrong_*` the records called 2 that are persons and called 1 that are companies.

| flag | routed_by | recall | false_merges | person_company_clusters | pairs_to_decide | sure_companies | wrong_companies | sure_persons | wrong_persons | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| good (1% wrong at random, 20% on representatives) | the truth | 0.4641 | 0 | 0 | 518 | 83.7% | 0 | 98.5% | 0 | 6.0 |
| good (1% wrong at random, 20% on representatives) | the flag alone | 0.4577 | 29 | 23 | 518 | 82.0% | 321 | 96.9% | 83 | 5.9 |
| good (1% wrong at random, 20% on representatives) | the kind step, 2,000 labels | 0.4695 | 30 | 24 | 502 | 67.0% | 1 | 98.2% | 41 | 6.3 |
| medium (3%, 50%) | the truth | 0.4641 | 0 | 0 | 518 | 83.7% | 0 | 98.5% | 0 | 2.4 |
| medium (3%, 50%) | the flag alone | 0.4433 | 63 | 51 | 497 | 79.2% | 858 | 94.2% | 224 | 5.8 |
| medium (3%, 50%) | the kind step, 2,000 labels | 0.4652 | 60 | 49 | 485 | 66.2% | 0 | 92.5% | 75 | 6.3 |
| poor (10%, 80%) | the truth | 0.4641 | 0 | 0 | 518 | 83.7% | 0 | 98.5% | 0 | 2.5 |
| poor (10%, 80%) | the flag alone | 0.3888 | 91 | 77 | 529 | 72.7% | 2372 | 86.7% | 543 | 5.6 |
| poor (10%, 80%) | the kind step, 2,000 labels | 0.4131 | 90 | 76 | 518 | 64.1% | 0 | 72.3% | 89 | 6.1 |

