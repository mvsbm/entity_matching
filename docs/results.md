[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. Each table is explained in chapters [4](guide/04-certain-cases-first-rules.md), [5](guide/05-uncertain-evidence-fellegi-sunter.md), [6](guide/06-measuring-and-choosing.md) and [7](guide/07-person-or-company.md).*

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

The train-only design analysis justifies "never one key alone". Single keys collide across entities: phone 49,342 different-entity pairs, postal code 36,723, given name 84,084, even the full name 104. Every exact rule's key combination has 0. The fuzzy rules' join keys have at most 109, and their fuzzy conditions reject every false one.

**Decisions** (`adopt`, each on top of the choice so far; rules fit nothing, so train is the selection set):

| Change | Kind | Train: true pairs gained / lost | Val: gained / lost | Adopted |
|---|---|---|---|---|
| names: fold → Levenshtein ≤ 1 (`fold_levenshtein`) | better | 18 / 6 (p = 0.0227) | 5 / 1 | yes |
| names: fold → exact (`fold_exact`) | cheaper | 0 / 79 | 0 / 34 | no |
| F2's address exact, so F2 joins on phone + normalized address (`f2_address_exact`, scale) | cheaper | 0 / 0 | 0 / 0 | yes |
| F2 joins on phone + first 3 characters of the normalized address (`f2_address_prefix`, scale) | cheaper | 0 / 0 | 0 / 0 | yes |
| Optuna's comparators, the table above (`optuna_comparators`) | better | 42 / 0 (p < 0.0001) | 15 / 0 | yes |

None adds a false pair. The two F2 rows are there for scale. With a fuzzy address check, F2 would join on the last four phone digits alone, the phone key's blocks: about 50 million pairs at a million records. Close normalized addresses share their start, so F2 joins on the phone and the address's first three characters (the city), which loses no true pair and projects to 182,959 pairs at a million records. All the rules together project to 549,274 pairs there, from 4,090 on train ([chapter 3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records)).

**Optuna** (60 trials on train, seeded; off by default: `rules_tune`, `enabled=False`; `scripts/choose.py --optuna` runs it) searches each field's comparator. Its suggestion passed the same rule and is a change in `config/experiments.py` (`optuna_comparators`), decided last because it was found on top of the rest.

**Results with `FINAL`:**

| Data | Recall | 95% interval | FP | FP rate ≤ |
|---|---|---|---|---|
| train | 10.52% | 9.83–11.25% | 0 | 0.40% |
| val | 11.87% (exact rules alone: 3.61%) | 10.66–13.20% | 0 | 1.01% |
| **test** | **9.60%** | 8.48–10.86% | **0** | 1.32% |

Pairs of two people of one household are counted apart, neither true nor false: the rules' groups hold 18 on train, 5 on val and 5 on test.

Paired A/B on val against the rules as written (informational; decisions use the rule above), all with 0 FP:

| Variant | True pairs gained / lost | p |
|---|---|---|
| fold → Levenshtein ≤ 1 | 5 / 1 | 0.2188 |
| fold → exact | 0 / 30 | < 0.0001 |
| raw Jaro-Winkler (no kana folding) | 0 / 58 | < 0.0001 |
| Optuna's comparators | 21 / 1 | < 0.0001 |
| F2's address exact | 0 / 0 | 1.0 |
| F2 on phone + address prefix | 0 / 0 | 1.0 |


## Stage 2: probabilistic matching

**Method:** the **Fellegi–Sunter model (Splink 5)** is the only probabilistic method; every A/B row is a variant of it.
- λ comes from near-certain rules and m from EM (or labels), both on the fitting records. EM's own u come from 10⁶ random pairs of those records (`fit_u_max_pairs`). The u the scores use are measured on each scored file (below).
- There are six comparisons: name, company, address, phone, cif, birth. Correlated columns share one comparison (address code, normalized address and postal code form one), because FS assumes independence.
- Levels use the `cl_*` functions.
- **A level without an estimate never uses Splink's defaults.** No sampled pair reached it → u at its 95% upper bound, so its weight is a lower bound on the evidence. Never seen in training → m = u, 0 bits. The training table lists such levels (none in the pipeline as written).

**Scores are calibrated to the scored file** (`er.match.score_fs`, `er.match.scored_u`):
- **Term frequencies** come from the fitting records, stored in the model. A value never seen in training gets no adjustment, the conservative side. `FINAL` turns them off.
- **λ** is a per-pair rate: true pairs grow with N, pairs with N². It is rescaled from the fitting set's size to the scored set's. So CV folds, val and test (about 10k records each) are scored on the same scale, and the threshold keeps its meaning at any size: on a file of N records, the same evidence earns log2(N/10k) fewer bits than on a 10k file.
- **u** is measured on the scored file's records, without labels, because a field whose values grow with the file agrees by chance less often in a bigger one. The leading exact levels are counted from value counts. A one-edit level right after them on the same column (the customer ID, phone or birth date one digit off) is counted exactly too, by keys on the distinct values (one per position for a substitution, one per position for a swap of neighbours, and the deletions of the longer for a length one apart), never pair by pair. So cif, phone and birth need no sample; name, company and address are sampled on 10⁷ random pairs, every one of them. m stays from train.
- Why this matters: [lessons.md](lessons.md).

**Candidates on train** (6,355 true pairs the deterministic stage missed): every generator in `config/pipeline.toml` `[generators]`, in order, from `reports/choose.md`. Pairs per record at a million records are projected by `scale_check` (pairs of one entity × N, chance pairs × N²):

| Generator | Pairs | Missed pairs it reaches | Cumulative | Pairs per record at 1M |
|---|---|---|---|---|
| phone | 50,939 | 26.99% | 26.99% | 50.681 |
| address | 6,250 | 10.67% | 36.88% | 5.763 |
| address_code | 6,819 | 20.83% | 47.80% | 5.727 |
| cif | 29 | 0.46% | 48.21% | 0.005 |
| person_name | 3,722 | 53.55% | 75.58% | 0.466 |
| company_name | 770 | 6.86% | 79.48% | 0.362 |
| sn_person_name | 73,801 | 60.71% | 82.94% | 3.0 |
| sn_company_name | 15,057 | 9.14% | 84.33% | 3.0 |
| tfidf_person_name | 30,234 | 63.21% | 86.06% | 1,000,000 (N²) |
| tfidf_company_name | 2,892 | 9.11% | 86.12% | 1,000,000 (N²) |
| phone_prefecture | 1,890 | 11.46% | 86.12% | 1.242 |
| phone_postal_area | 597 | 6.66% | 86.12% | 0.226 |
| phone_name_initial | 3,217 | 19.87% | 86.12% | 2.091 |
| sn_person_name_reversed | 73,792 | 62.05% | 88.42% | 3.0 |
| company_name_deletions | 1,226 | 7.33% | 88.47% | 0.8 |
| cif_deletions | 49 | 0.77% | 88.47% | 0.006 |
| person_name_deletions_postal_area | 1,494 | 22.77% | 88.58% | 0.118 |
| given_name_postal | 1,019 | 15.80% | 88.87% | 0.059 |
| address_phone | 83 | 0.77% | 88.87% | 0.054 |
| address_code_phone | 158 | 1.54% | 88.87% | 0.098 |
| address_name_initial | 839 | 7.57% | 88.87% | 0.4 |
| address_code_name_initial | 1,466 | 14.82% | 88.87% | 0.603 |
| given_name_address_code | 703 | 11.00% | 88.87% | 0.039 |
| given_name_phone | 877 | 13.56% | 88.87% | 0.056 |
| name_reading | 3,893 | 55.77% | 88.89% | 0.502 |
| phone_given_tail | 1,213 | 18.52% | 88.89% | 0.092 |
| postal_given_tail | 1,364 | 21.07% | 88.97% | 0.084 |
| postal_area_given_tail | 2,075 | 24.22% | 89.11% | 0.619 |
| birth_date | 338 | 1.54% | 89.19% | 0.251 |
| birth_date_deletions_prefecture | 379 | 0.94% | 89.19% | 0.338 |

The keys that pair the phone or the address with one more field add nothing to the cumulative reach: every pair they list shares the phone, the address or the address code, whose keys come first. They replace those three in `FINAL`. At a million records, the phone key alone would make 50.7 pairs per record and its three compound keys 3.6 together; the two address keys 11.5, and their five compound keys 1.2.

**`FINAL`'s candidates on val** (each generator alone, and the share of the true pairs the rules missed that it reaches):

| Generator | Pairs | Missed pairs reached |
|---|---|---|
| cif | 12 | 0.55% |
| phone_prefecture | 417 | 12.33% |
| phone_postal_area | 175 | 6.19% |
| phone_name_initial | 693 | 18.93% |
| person_name | 1,209 | 52.27% |
| company_name | 193 | 7.19% |
| company_name_deletions | 238 | 7.46% |
| person_name_deletions_postal_area | 482 | 21.52% |
| given_name_postal | 354 | 16.11% |
| address_phone | 33 | 1.00% |
| address_code_phone | 60 | 1.87% |
| address_name_initial | 250 | 7.10% |
| address_code_name_initial | 468 | 15.33% |
| given_name_address_code | 231 | 10.51% |
| cif_deletions | 17 | 0.77% |
| birth_date | 57 | 1.50% |
| given_name_phone | 294 | 13.28% |
| birth_date_deletions_prefecture | 52 | 0.82% |
| name_reading | 1,291 | 55.91% |
| phone_given_tail | 420 | 18.84% |
| postal_given_tail | 450 | 20.47% |
| postal_area_given_tail | 578 | 23.07% |
| **all 22** | **2,568** | **79.6%** |

That is 2,568 candidates on val (99.995% of all pairs skipped). Every true pair on train that could reach the threshold shares one of `FINAL`'s keys: 3,278 such pairs at train's size and 3,071 at a million records, none window-only ([chapter 3](guide/03-far-too-many-pairs.md#keeping-every-potential-match); `scripts/choose.py` checks train on every run). Without labels, `pattern_coverage` finds 190 agreement patterns that can reach the threshold at a million records with no guaranteed key. The model puts their share of matches at 13.25% at most, an upper bound, since a Jaro–Winkler level implies no key.

**Training** (the pipeline as written, on train): EM and labels learn close weights, within about half a bit on most agreeing levels. The close name ("fold JW low") differs by 1.4 bits: +6.44 by EM, +5.03 from labels. The name's else level differs most: −2.67 bits by EM, −4.39 from labels.
- By EM, the customer ID is worth 14.5 bits, an exact or folded-exact name 15.4–15.5, the same address 13.3, the phone 11.3, the postal code 10.4.
- "address close" (Levenshtein ≤ 2 on the normalized address) is worth +1.6 bits, "phone one digit off" +4.1.

**Threshold** (`ThresholdRule` on out-of-fold train scores, 3 folds): for the pipeline as written, the lowest weight with 0 false pairs is 8 (0 of 2,402 accepted), and one step of margin gives 10. Every decision variant gets its own threshold the same way; `FINAL`'s is **6**.

| Weight | Accepted | False pairs | Recall | Eligible |
|---|---|---|---|---|
| 0 | 3,372 | 22 | 58.80% | no |
| 2 | 3,286 | 7 | 57.91% | no |
| 4 | 2,970 | 1 | 53.69% | no |
| 6 | 2,753 | 1 | 50.90% | no |
| 8 | 2,402 | 0 | 46.10% | yes |
| 10 | 2,086 | 0 | 41.48% | yes |
| 12 | 1,002 | 0 | 24.84% | yes |
| 14 | 308 | 0 | 14.88% | yes |
| 16 | 242 | 0 | 14.00% | yes |

**Decisions** (`adopt`, in order, each on top of the choice so far: paired on cross-validated train; on val, no more true pairs lost than gained. The owner's "chosen" calls may move recall. No change adds a false pair, on cross-validated train or on val):

| Change | Kind | Cross-validated train: true pairs gained / lost | Val | Adopted |
|---|---|---|---|---|
| term-frequency adjustment off (`no_term_frequency`) | better | +33 / −0 (p < 0.0001) | +13 / −0 | yes |
| exact keys only: no sorted windows, no TF-IDF (`exact_keys_only`) | cheaper | +0 / −7 (p = 0.0156) | +0 / −2 | no |
| Optuna's suggestion, below (`optuna_suggestion`) | better | +79 / −14 (p < 0.0001) | +25 / −4 | yes |
| u from 10⁶ pairs instead of 10⁷ (`u_from_1e6_pairs`) | cheaper | +93 / −67 (p = 0.0478) | +61 / −0 | no |
| phone key → phone + prefecture, postal area or name initial (`compound_phone_keys`, scale) | cheaper | +0 / −0 | +0 / −0 | yes |
| TF-IDF → sorted neighbourhood on the name and the reversed name (`sorted_names_for_tfidf`, scale) | cheaper | +1 / −0 | +0 / −0 | yes |
| five name keys: no potential match left to a sorted window (`name_keys`, scale) | safer | +0 / −0 | +0 / −0 | yes |
| the address only with the phone, the name's first letter or the given name (`bounded_address_keys`, scale) | cheaper | +0 / −0 | +0 / −0 | yes |
| no sorted windows (`no_sorted_windows`) | cheaper | +0 / −0 | +0 / −0 | yes |
| score every pair across two rule clusters (`bridge_rule_clusters`) | better | +8 / −0 (p = 0.0078) | +0 / −0 | yes |
| u measured on each scored file (`u_from_scored_file`, owner's decision, for scale) | chosen | +0 / −700 (p < 0.0001) | +0 / −92 | yes |
| u of the leading exact levels from value counts, not sampled (`u_exact_by_counts`, owner's decision, for scale) | chosen | +437 / −170 (p < 0.0001) | +0 / −335 | yes |
| the customer ID one digit off, a level (`cif_one_digit_off`) | better | +7 / −0 (p = 0.0156) | +4 / −0 | yes |
| its key: the customer ID's one-character deletions (`cif_deletion_key`) | safer | +0 / −0 | +0 / −0 | yes |
| graded address: the same town, city or prefecture after the postal code (`graded_address`) | better | +159 / −344 (p < 0.0001) | +181 / −3 | no |
| the birth date: exact, one digit off (`birth_date`) | better | +49 / −0 (p < 0.0001) | +27 / −0 | yes |
| its key: the birth date (`birth_date_key`) | safer | +8 / −0 (p = 0.0078) | +4 / −0 | yes |
| the given name + the phone, a key (`given_name_phone_key`) | safer | +0 / −0 | +0 / −0 | yes |
| the birth date's deletions within the prefecture, a key (`birth_date_deletion_key`) | safer | +0 / −0 | +0 / −0 | yes |
| one-edit levels counted by keys, not sampled (`u_near_by_keys`, owner's decision, for scale) | chosen | +0 / −0 | +0 / −0 | yes |
| the fit's own u from 10⁶ pairs, for EM only (`fit_u_from_1e6_pairs`) | cheaper | +0 / −0 | +0 / −0 | yes |
| the company without its "JW high" level (`company_without_jw_high`) | cheaper | +0 / −0 | +0 / −0 | yes |
| a name compared, or people decide (`name_needed`, owner's decision) | chosen | +682 / −5 (p < 0.0001) | +494 / −2 | yes |
| the name's reading, its long vowels written one way, a key (`name_reading_key`) | safer | +0 / −0 | +0 / −0 | yes |
| the name's last three sounds with the phone, the postal code or the postal area, three keys (`given_tail_keys`) | safer | +1 / −0 | +0 / −0 | yes |
| the same reading, a name level after the folded-exact one (`same_reading_level`) | better | +67 / −0 (p < 0.0001) | +37 / −0 | yes |
| the same last three sounds, a name level after the given name (`same_given_tail_level`) | better | +15 / −8 (p = 0.21) | +10 / −6 | no |
| the given name compared on its own: exact, one edit apart (`given_comparison`) | better | +117 / −897 (p < 0.0001) | +0 / −352 | no |
| the same, with the name's last three sounds where a record has no given name (`given_or_tail_comparison`) | better | +0 / −422 (p < 0.0001) | +0 / −154 | no |

`optuna_suggestion` sets the generators itself (those of the pipeline as written, less four); the scale changes after it replace the phone, address and TF-IDF keys, and `no_sorted_windows` drops the sorted windows, so `FINAL` lists pairs by keys alone. The four "chosen" calls are made for scale, whatever they do to recall on train-sized files. The three on u make the weights right at any file size: u measured on the file itself, and counted where a sample of 10⁷ pairs can't see an agreement rarer than one in 10⁹ pairs (an exact name, or a customer ID, equal or one digit off, in a big file). The name check holds back pairs with no name compared, such as a household sharing an address and a phone: they go to people ([usage](usage.md#6--review-and-decide)). On train and val it gains true pairs too.

**Results with `FINAL`** (22 generators, all of them keys, u from each scored file with the exact and one-edit levels counted, term frequency off, m by EM, Optuna's JW thresholds, a "same reading" name level, a name compared, every pair across two rule clusters scored, threshold 6, connected components):

| Data | After deterministic → after probabilistic | 95% interval | FP | FP rate ≤ | Accepted pairs |
|---|---|---|---|---|---|
| train | 10.52% → 47.68% | 46.52–48.84% | 0 | 0.09% | 2,566 |
| val | 11.87% → 49.88% | 47.92–51.84% | 0 | 0.24% | 918 |
| **test** | 9.60% → **48.17%** | 46.16–50.19% | **0** | 0.26% | 882 |

Train is scored in-sample (the model is fitted on all of it), and has no false pair either. Test is scored once per stage, with one configuration each. Pairs of two people of one household are counted apart, neither true nor false: 112 on train, 51 on val and 45 on test.

**The threshold transfers:** at weight 6, cross-validated train accepts 0 false of 2,569 pairs (rate ≤ 0.12%) and val 0 of 918. `scripts/choose.py` checks this on every run. On val, the first false pairs come at 2 bits:

| Weight | Accepted | False pairs | Recall |
|---|---|---|---|
| 0 | 1,263 | 8 | 59.66% |
| 2 | 1,195 | 5 | 58.18% |
| 4 | 973 | 0 | 51.96% |
| 6 | 918 | 0 | 49.88% |
| 8 | 877 | 0 | 48.60% |
| 10 | 416 | 0 | 28.83% |
| 12 | 147 | 0 | 17.48% |
| 14 | 128 | 0 | 16.84% |
| 16 | 99 | 0 | 16.00% |

**Households on val:** at weight 6, 32 accepted pairs join two people of one household, counted apart from the false pairs. People see 27 of them labelled "maybe one household" ([usage](usage.md#maybe-one-household)), and 2 other accepted pairs.

**Worked example:** `reports/choose.md` breaks two pairs into bits: an accepted true match with a typo (6.19 bits, from the same address and the same phone, the given names unlike), and the rejected non-match closest to the threshold (3.66 bits, from the phone and the given name, the addresses different). [Chapter 5](guide/05-uncertain-evidence-fellegi-sunter.md#solution-evidence-in-bits) walks through one pair field by field, and section 9 of the demo draws two more.

**Optuna** (cross-validated objective, 30 trials, seeded; off by default: `fs_tune`, `enabled=False`; `scripts/choose.py --optuna` runs it): each trial switches generators off and picks the m method, term frequency and level thresholds. Its threshold comes from the threshold rule, as `FINAL`'s does: a search that set the threshold itself would pull against the rule ([lessons.md](lessons.md#two-policies-that-set-one-parameter)). A tuned level the model doesn't have is skipped.
- Its suggestion that passed `adopt` is the `optuna_suggestion` decision. It drops four generators (the person- and company-name keys, the person-name sorted neighbourhood, the company TF-IDF), turns term frequency off, and sets the JW thresholds: names 0.95 / 0.75, companies 0.97 / 0.80. `company_without_jw_high` then drops the company's 0.97 level, which no pair reached.

## Benchmark

`scripts/benchmark.py` runs `FINAL` the way a real file is run (`er.run`, without labels), without re-tuning anything, and writes [`reports/benchmark.md`](../reports/benchmark.md). Chapter [6](guide/06-measuring-and-choosing.md#challenge-does-it-hold-beyond-our-one-dataset) explains the scenarios, and chapter [3](guide/03-far-too-many-pairs.md#scaling-to-a-million-records) the cost.

### Scenarios

Each population's test split, with λ and m fitted on its train split without labels and u measured on the test split, as a run does. `false_merges` are pairs of records in one cluster that are two entities; `false_links` are the model's links between two entities, and `expected_false` the false links the model expects among its own (the sum of 1 − match probability), which a run reports without labels.

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

Each file is resolved by `nayose resolve records` in a process of its own, fitted on the file itself; DuckDB memory limit: 8GB. Peak memory is the process's, Python included. Step columns are seconds. `fit` (on 30,000 records) and the u sample of the file inside it (10,000,000 pairs) cost the same at any size, so at these sizes the total grows far slower than N. Above 60,000 entities personas repeat, so those rows measure cost only.

| records | seconds | peak_memory_gb | load | budget | fit | rules | candidates | score | cluster | probe | report | write | recall | false_merges | fp_rate_at_most | model_links | expected_false | false_links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12532 | 8.9 | 0.96 | 0.23 | 0.11 | 7.26 | 0.14 | 0.23 | 0.26 | 0.03 | 0.47 | 0.16 | 0.05 | 0.4573 | 2 | 0.48% | 985 | 0.84 | 1 |
| 24955 | 10.7 | 1.08 | 0.39 | 0.17 | 7.81 | 0.18 | 0.34 | 0.38 | 0.04 | 1.12 | 0.19 | 0.09 | 0.4598 | 0 | 0.12% | 1832 | 1.03 | 0 |
| 50116 | 13.1 | 1.44 | 0.69 | 0.3 | 7.85 | 0.25 | 0.58 | 0.76 | 0.06 | 2.28 | 0.21 | 0.17 | 0.4467 | 0 | 0.06% | 3705 | 2.48 | 0 |
| 74959 | 15.4 | 1.66 | 0.96 | 0.45 | 8.03 | 0.36 | 0.85 | 1.16 | 0.08 | 3.04 | 0.24 | 0.24 | 0.4422 | 4 | 0.12% | 5383 | 4.38 | 3 |
| 1000338 | 53.0 | 6.64 | 10.73 | 1.96 | 9.4 | 2.57 | 6.53 | 16.05 | 0.34 | 3.52 | 0.78 | 1.07 | — | — | — | 38786 | 30.11 | — |

The model makes false merges on two of these populations: 2 false pairs at 12,532 records, through 1 false link, and 4 at 74,959, through 3. They are model links at 8.2–10.1 bits, just over the threshold of 8, between near-namesakes a kana typo apart who share an address or a phone. The model expects about as many (`expected_false`: 0.84 and 4.38), and under one on every scenario's test split, where none appears.

## Person or company

`scripts/choose_kind.py` ([`reports/choose_kind.md`](../reports/choose_kind.md)) chose how records are told apart: 768 combinations, 12 scenarios over what a file can't tell about itself, judged correct first (the share of companies called 2 with at most 0.1% of those calls wrong; of persons called 1 with at most 1% wrong). Chapter [7](guide/07-person-or-company.md) explains it.

### What each idea is worth

The best mean among the 48 finalists with the idea, and without it.

| idea | best_mean |
| --- | --- |
| legal: bank table | 67.6% |
| legal: generator's forms | not among the finalists |
| ngram: 1–3 | 67.6% |
| ngram: 1–4 | 67.2% |
| training: public | 66.8% |
| training: public + the file's legal-form records | 67.6% |
| combiner: gbdt2 | 67.6% |
| combiner: gbdt3 | 66.0% |
| combiner: lr | not among the finalists |
| signal flag: with | 67.6% |
| signal flag: without | — |
| signal birth: with | 67.6% |
| signal birth: without | 67.6% |
| signal birth_year: with | 67.6% |
| signal birth_year: without | 66.8% |
| signal legal: with | 67.6% |
| signal legal: without | — |
| signal known_name: with | 67.6% |
| signal known_name: without | 67.3% |

The pipeline's combination (`config/pipeline.toml` `[kind]`: the bank table, n-grams 1–3, trained once on public data, trees of depth 2 on the flag, the birth year and the legal form) is 25th of 48: mean 65.5%, worst 35.3%, against 67.6% for the best, which also trains on the file's own legal-form records and reads a dictionary of names. The name model judged is the run's own (`er.generate.kind_training_names`).

### The scenarios, for the pipeline's combination

| scenario | flag_wrong | on_representatives | representative_named_companies | sole_traders | sole_flagged_company | company_dates | companies | persons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 10% | 79% | 19% | 7% | 37% | 35% (founding) | 72.5% | 0.1% |
| 2 | 3% | 21% | 7% | 14% | 31% | 5% (representative) | 76.0% | 94.9% |
| 3 | 6% | 50% | 10% | 4% | 17% | 7% (founding) | 72.3% | 92.8% |
| 4 | 9% | 43% | 14% | 8% | 14% | 22% (representative) | 72.7% | 70.8% |
| 5 | 2% | 58% | 8% | 4% | 24% | 12% (founding) | 74.4% | 97.5% |
| 6 | 8% | 53% | 15% | 9% | 28% | 33% (representative) | 72.9% | 0.2% |
| 7 | 7% | 66% | 9% | 11% | 48% | 53% (founding) | 74.9% | 52.7% |
| 8 | 4% | 33% | 20% | 5% | 46% | 27% (representative) | 70.5% | 0.2% |
| 9 | 7% | 71% | 5% | 3% | 34% | 50% (founding) | 82.0% | 97.1% |
| 10 | 1% | 64% | 17% | 12% | 13% | 20% (representative) | 74.5% | 0.0% |
| 11 | 5% | 29% | 16% | 10% | 22% | 42% (founding) | 72.7% | 90.0% |
| 12 | 5% | 35% | 12% | 14% | 41% | 55% (representative) | 73.2% | 87.4% |

### Counting sole traders

| policy | companies_mean | companies_worst | persons_mean | persons_worst |
| --- | --- | --- | --- | --- |
| individuals | 74.0% | 70.5% | 57.0% | 0.0% |
| by record (a trade-name record a business) | 72.7% | 48.6% | 7.8% | 0.0% |
| businesses (every record) | 69.8% | 52.4% | 0.1% | 0.0% |

### Placing the lines from people's answers

The lines placed on answers drawn at random, as the review sheet draws them, 5 draws per scenario: 60 trials. `over_budget`: of the 60 trials (person calls: 1% wrong; company calls: 0.1%).

**The person line**, by three rules: (a) the answers above it 30 or more, and at most half of 1% of them wrong; (b) the 95% one-sided upper bound on their wrong share (Clopper–Pearson) within 1%; (c) the company's rule. Chosen before the run: the rule over budget in at most 3 of 60 trials with 2,000 answers, then the most persons decided. Rule a breaks its budget in 4; b in 2, deciding 19.8% of persons; c decides almost none, since an answered company lies above nearly every line. `er.kind.lines` places the person line by b. The best combination decides 2.2 points more persons under b, with as many trials over budget: too little to train the name model on each file.

| combination | answers | person_rule | persons | person_wrong_worst | person_over_budget |
| --- | --- | --- | --- | --- | --- |
| the pipeline's | 500 | a | 26.36% | 3.15% | 8 |
| the pipeline's | 500 | b | 4.47% | 0.95% | 0 |
| the pipeline's | 500 | c | 5.13% | 2.06% | 4 |
| the pipeline's | 1000 | a | 22.27% | 1.54% | 8 |
| the pipeline's | 1000 | b | 10.50% | 1.19% | 2 |
| the pipeline's | 1000 | c | 2.52% | 1.62% | 3 |
| the pipeline's | 2000 | a | 25.34% | 1.23% | 4 |
| the pipeline's | 2000 | b | 19.81% | 1.23% | 2 |
| the pipeline's | 2000 | c | 2.05% | 0.56% | 0 |
| the pipeline's | 4000 | a | 20.57% | 1.51% | 2 |
| the pipeline's | 4000 | b | 29.84% | 1.14% | 2 |
| the pipeline's | 4000 | c | 0.01% | 0.00% | 0 |
| the best | 500 | a | 29.87% | 2.91% | 13 |
| the best | 500 | b | 4.42% | 1.14% | 1 |
| the best | 500 | c | 4.89% | 5.62% | 6 |
| the best | 1000 | a | 26.38% | 2.69% | 10 |
| the best | 1000 | b | 7.27% | 1.02% | 1 |
| the best | 1000 | c | 1.59% | 1.17% | 1 |
| the best | 2000 | a | 24.13% | 1.20% | 3 |
| the best | 2000 | b | 22.03% | 1.20% | 2 |
| the best | 2000 | c | 0.47% | 0.28% | 0 |
| the best | 4000 | a | 22.43% | 1.85% | 4 |
| the best | 4000 | b | 29.82% | 1.00% | 1 |
| the best | 4000 | c | 0.01% | 0.00% | 0 |

**The company line**: no labelled person above it, then this many grid steps stricter. Chosen before the run: the rule over budget in at most 3 of 60 trials at every count from 1,000 answers up, then the most companies decided at 2,000. Two steps broke the budget in 4 trials at 1,000 answers; two steps from 2,000 answers and three below kept it everywhere from 1,000 (1, 1, 0 trials) and decides as many companies as two steps on a full draw (66.7%). `er.kind.lines` places it so. At 500 answers only four steps kept the budget (2 of 60, deciding 35.0%): people should give back the whole draw.

| combination | answers | company_rule | companies | company_wrong_worst | company_over_budget |
| --- | --- | --- | --- | --- | --- |
| the pipeline's | 500 | 2 steps | 61.79% | 3.13% | 10 |
| the pipeline's | 500 | 3 steps | 52.13% | 1.45% | 7 |
| the pipeline's | 500 | 4 steps | 35.02% | 1.41% | 2 |
| the pipeline's | 500 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 52.13% | 1.45% | 7 |
| the pipeline's | 1000 | 2 steps | 66.77% | 0.41% | 4 |
| the pipeline's | 1000 | 3 steps | 57.97% | 0.14% | 1 |
| the pipeline's | 1000 | 4 steps | 40.48% | 0.27% | 1 |
| the pipeline's | 1000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 57.97% | 0.14% | 1 |
| the pipeline's | 2000 | 2 steps | 66.74% | 0.12% | 1 |
| the pipeline's | 2000 | 3 steps | 59.29% | 0.08% | 0 |
| the pipeline's | 2000 | 4 steps | 46.14% | 0.15% | 1 |
| the pipeline's | 2000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 66.74% | 0.12% | 1 |
| the pipeline's | 4000 | 2 steps | 67.69% | 0.04% | 0 |
| the pipeline's | 4000 | 3 steps | 62.03% | 0.03% | 0 |
| the pipeline's | 4000 | 4 steps | 50.68% | 0.09% | 0 |
| the pipeline's | 4000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 67.69% | 0.04% | 0 |
| the best | 500 | 2 steps | 61.42% | 3.01% | 11 |
| the best | 500 | 3 steps | 49.53% | 1.46% | 6 |
| the best | 500 | 4 steps | 35.09% | 1.37% | 3 |
| the best | 500 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 49.53% | 1.46% | 6 |
| the best | 1000 | 2 steps | 65.47% | 0.80% | 3 |
| the best | 1000 | 3 steps | 54.68% | 0.32% | 2 |
| the best | 1000 | 4 steps | 36.66% | 0.14% | 1 |
| the best | 1000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 54.68% | 0.32% | 2 |
| the best | 2000 | 2 steps | 67.06% | 0.13% | 1 |
| the best | 2000 | 3 steps | 59.52% | 0.06% | 0 |
| the best | 2000 | 4 steps | 45.54% | 0.12% | 1 |
| the best | 2000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 67.06% | 0.13% | 1 |
| the best | 4000 | 2 steps | 67.64% | 0.02% | 0 |
| the best | 4000 | 3 steps | 61.91% | 0.03% | 0 |
| the best | 4000 | 4 steps | 50.94% | 0.05% | 0 |
| the best | 4000 | 2 steps from 2,000 answers, 3 below (er.kind.lines) | 67.64% | 0.02% | 0 |

### End to end

From `scripts/benchmark.py` ([`reports/benchmark.md`](../reports/benchmark.md)). Populations with one name column for every kind (`er.generate.kind_problems`): real company names from the registry, held out of the name model's training and written as banks write them; companies with records under their representative's name, the representative a person of the file (half at that person's address and phone); sole traders named like a shop; company dates; and a flag good, medium or poor. Each resolved three ways: names routed by the truth (the flag replaced by it, taken as it is); by the flag alone; by the kind step, people answering its review sheet (here, with the truth). `person_company_clusters` hold a true person and a true company; `sure_*` is the share of true companies called 2 and of true persons called 1; `wrong_*` the records called 2 that are persons and called 1 that are companies.

| flag | routed_by | recall | false_merges | person_company_clusters | pairs_to_decide | sure_companies | wrong_companies | sure_persons | wrong_persons | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| good (1% wrong at random, 20% on representatives) | the truth | 0.4618 | 1 | 0 | 573 | 100.0% | 0 | 100.0% | 0 | 5.7 |
| good (1% wrong at random, 20% on representatives) | the flag alone | 0.4553 | 21 | 20 | 532 | 97.9% | 308 | 98.5% | 103 | 6.3 |
| good (1% wrong at random, 20% on representatives) | the kind step, 2,000 labels | 0.4614 | 21 | 20 | 521 | 98.7% | 180 | 99.1% | 63 | 7.2 |
| medium (3%, 50%) | the truth | 0.4618 | 1 | 0 | 573 | 100.0% | 0 | 100.0% | 0 | 3.5 |
| medium (3%, 50%) | the flag alone | 0.4417 | 62 | 54 | 500 | 94.0% | 840 | 95.8% | 296 | 6.4 |
| medium (3%, 50%) | the kind step, 2,000 labels | 0.4564 | 54 | 47 | 494 | 96.5% | 486 | 97.6% | 172 | 7.3 |
| poor (10%, 80%) | the truth | 0.4618 | 1 | 0 | 573 | 100.0% | 0 | 100.0% | 0 | 3.4 |
| poor (10%, 80%) | the flag alone | 0.3899 | 84 | 72 | 528 | 86.1% | 2398 | 88.0% | 687 | 6.4 |
| poor (10%, 80%) | the kind step, 2,000 labels | 0.426 | 76 | 64 | 499 | 93.5% | 1641 | 91.8% | 322 | 7.4 |
