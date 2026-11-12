# Choosing the configuration

Written by `scripts/choose.py` from `config/pipeline.toml` and `config/experiments.py`, on the labelled synthetic datasets. Test is scored once per stage, at the end of each.

## Stage 1: rules

### Design analysis on train

| keys | same_entity_agree | different_entity_pairs |
| --- | --- | --- |
| address | 0.0974 | 20241 |
| address_code | 0.267 | 5525 |
| company_name | 0.0113 | 43 |
| customer_id | 0.0221 | 0 |
| full_name | 0.2005 | 104 |
| given_name | 0.3291 | 84084 |
| person_name | 0.2115 | 113 |
| phone | 0.3322 | 49342 |
| postal_code | 0.3491 | 36723 |
| customer_id + full_name | 0.0039 | 0 |
| customer_id + company_name | 0.0003 | 0 |
| customer_id + phone | 0.0083 | 0 |
| full_name + address_code + phone | 0.0177 | 0 |
| company_name + address_code + phone | 0.0014 | 0 |
| address_code + phone | 0.0867 | 76 |
| phone + address__address | 0.0434 | 43 |
| person_name + address_code | 0.0589 | 0 |
| phone + postal_code | 0.1172 | 109 |
| given_name + address_code + phone | 0.0304 | 0 |

### A/B on val, paired against the rules as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | P | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | 0.1127 | 0 | 0.0106 | 5 | 1 | 0.2188 | 0 | 0 | 1408 | 1.7 |
| fold_exact | 0.099 | 0 | 0.0121 | 0 | 30 | 0.0 | 0 | 0 | 608 | 1.4 |
| raw_jaro_winkler | 0.0878 | 0 | 0.0136 | 0 | 58 | 0.0 | 0 | 0 | 1408 | 1.7 |
| optuna_comparators | 0.1191 | 0 | 0.01 | 21 | 1 | 0.0 | 0 | 0 | 7592 | 1.6 |
| f2_address_exact | 0.1111 | 0 | 0.0108 | 0 | 0 | 1.0 | 0 | 0 | 1408 | 1.7 |
| f2_address_prefix | 0.1111 | 0 | 0.0108 | 0 | 0 | 1.0 | 0 | 0 | 1408 | 1.6 |

### Decisions

FINAL fuzzy comparators: {'person_name': 'damerau_levenshtein 2 kana_fold', 'company_name': 'levenshtein 1 nfkc+strip_legal_form+kana_fold', 'address': 'jaro_winkler 0.9 address', 'phone': 'hamming 1'} · connected_components

| change | kind | adopted | train_TP_gains | train_TP_losses | train_p | train_FP_added | train_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | better | True | 18 | 6 | 0.0227 | 0 | 0 | 5 | 1 | 0 |
| fold_exact | cheaper | False | 0 | 79 | 0.0 | 0 | 0 | 0 | 34 | 0 |
| f2_address_exact | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| f2_address_prefix | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| optuna_comparators | better | True | 42 | 0 | 0.0 | 0 | 0 | 15 | 0 | 0 |

### Cost of FINAL: every rule now and at target_rows

train: N = 31,226 · total P = 4,090 → 549,274 at 1,000,000 rows

| stage | rule | keys | big_o | filled | P | largest_block | est_fuzzy_ms | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | X1_CIF_PERSON_NAME | customer_id + full_name | O(N + P) | O(31,226 + 28) | 28 | 2 | 0.0 | 1.0 | 896 | 0.001 | True |
| exact | X2_CIF_COMPANY_NAME | customer_id + company_name | O(N + P) | O(31,226 + 2) | 2 | 2 | 0.0 | 1.0 | 64 | 0.0 | True |
| exact | X3_CIF_PHONE | customer_id + phone | O(N + P) | O(31,226 + 59) | 59 | 2 | 0.0 | 1.0 | 1889 | 0.002 | True |
| exact | X4_PERSON_NAME_ADDRCD_PHONE | full_name + address_code + phone | O(N + P) | O(31,226 + 126) | 126 | 3 | 0.0 | 1.0 | 4035 | 0.004 | True |
| exact | X5_COMPANY_NAME_ADDRCD_PHONE | company_name + address_code + phone | O(N + P) | O(31,226 + 10) | 10 | 2 | 0.0 | 1.0 | 320 | 0.0 | True |
| fuzzy | F1_NAME~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(31,226 + 692·45) | 692 | 3 | 0.65 | 1.11 | 97673 | 0.098 | True |
| fuzzy | F2_NAME~_ADDRESS~_PHONE | phone + address__address_first3 | O(N + P·(m·n + m·n)) | O(31,226 + 749·153) | 749 | 3 | 1.02 | 1.21 | 182959 | 0.183 | True |
| fuzzy | F3_NAME~_CIF | customer_id | O(N + P·(m·n)) | O(31,226 + 157·45) | 157 | 3 | 0.15 | 1.0 | 5027 | 0.005 | True |
| fuzzy | F4_NAME_ADDRCD_PHONE~ | person_name + address_code | O(N + P·(n)) | O(31,226 + 418·4) | 418 | 3 | 0.25 | 1.0 | 13386 | 0.013 | True |
| fuzzy | F5_COMPANY~_PHONE_POSTAL | phone + postal_code | O(N + P·(m·n)) | O(31,226 + 941·91) | 941 | 4 | 0.39 | 1.12 | 138435 | 0.138 | True |
| fuzzy | F6_COMPANY~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(31,226 + 692·91) | 692 | 3 | 0.29 | 1.11 | 97673 | 0.098 | True |
| fuzzy | F7_GIVEN_ADDRCD_PHONE | given_name + address_code + phone | O(N + P) | O(31,226 + 216) | 216 | 3 | 0.0 | 1.0 | 6917 | 0.007 | True |

### Evaluation on val

rules: Σ ops ≈ 239,016 (see big_o per rule) · normalize: O(N·L), N = 10,496 · cluster: O((N + E)·d), N = 10,496, E = 297 · evaluate: O(N) · total 1.7s · false-positive pairs: 0

| stage | TP | FP | household | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | 90 | 0 | 0 | 0.0361 | 0.0295 | 0.0441 | 0.0327 | 0 | 0 | 3909 |
| fuzzy | 296 | 0 | 5 | 0.1187 | 0.1066 | 0.132 | 0.0101 | 0 | 5 | 3522 |

### Rules on val

| rule | P | actual_ms | edges | edge_FP | kept | kept_FP |
| --- | --- | --- | --- | --- | --- | --- |
| X1_CIF_PERSON_NAME | 15 | 9.0 | 15 | 0 | 15 | 0 |
| X2_CIF_COMPANY_NAME | 1 | 2.0 | 1 | 0 | 1 | 0 |
| X3_CIF_PHONE | 17 | 3.0 | 12 | 0 | 12 | 0 |
| X4_PERSON_NAME_ADDRCD_PHONE | 61 | 3.3 | 60 | 0 | 60 | 0 |
| X5_COMPANY_NAME_ADDRCD_PHONE | 1 | 2.5 | 1 | 0 | 1 | 0 |
| F1_NAME~_ADDRCD_PHONE | 270 | 11.1 | 122 | 0 | 122 | 0 |
| F2_NAME~_ADDRESS~_PHONE | 264 | 7.7 | 25 | 0 | 25 | 0 |
| F3_NAME~_CIF | 63 | 15.8 | 23 | 0 | 23 | 0 |
| F4_NAME_ADDRCD_PHONE~ | 149 | 14.4 | 9 | 0 | 9 | 0 |
| F5_COMPANY~_PHONE_POSTAL | 344 | 12.5 | 16 | 0 | 16 | 0 |
| F6_COMPANY~_ADDRCD_PHONE | 270 | 18.1 | 1 | 0 | 1 | 0 |
| F7_GIVEN_ADDRCD_PHONE | 83 | 2.8 | 12 | 0 | 12 | 0 |

### FINAL on train, val and test

| dataset | records | TP | FP | household | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 31226 | 747 | 0 | 18 | 0.1052 | 0.0983 | 0.1125 | 0.004 | 0 | 16 | 10350 | 3.5 |
| val | 10496 | 296 | 0 | 5 | 0.1187 | 0.1066 | 0.132 | 0.0101 | 0 | 5 | 3522 | 1.6 |
| test | 10393 | 226 | 0 | 5 | 0.096 | 0.0848 | 0.1086 | 0.0132 | 0 | 5 | 3465 | 1.8 |

## Stage 2: Fellegi–Sunter

### Candidates on train: reach and cost of every generator

train: 6,355 true pairs missed by the rules

| generator | big_o | filled | pairs | seconds | finds | cumulative | different_entity_pairs | alpha | projected_pairs | per_record |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phone | O(N + P) | O(31,226 + 51,701) | 50939 | 0.041 | 0.2699 | 0.2699 | 49224 | 1.95 | 50681021 | 50.681 |
| address | O(N + P) | O(31,226 + 6,548) | 6250 | 0.05 | 0.1067 | 0.3688 | 5572 | 1.85 | 5762826 | 5.763 |
| address_code | O(N + P) | O(31,226 + 7,421) | 6819 | 0.02 | 0.2083 | 0.478 | 5495 | 1.74 | 5727194 | 5.727 |
| cif | O(N + P) | O(31,226 + 157) | 29 | 0.021 | 0.0046 | 0.4821 | 0 | 1.0 | 5027 | 0.005 |
| person_name | O(N + P) | O(31,226 + 4,273) | 3722 | 0.048 | 0.5355 | 0.7558 | 319 | 1.08 | 465716 | 0.466 |
| company_name | O(N + P) | O(31,226 + 818) | 770 | 0.014 | 0.0686 | 0.7948 | 334 | 1.41 | 362026 | 0.362 |
| sn_person_name | O(N log N + N·w) | O(24,864·log 24,864 + 24,864·4) | 73801 | 0.019 | 0.6071 | 0.8294 | 69943 | 1.0 | 3000000 | 3.0 |
| sn_company_name | O(N log N + N·w) | O(5,038·log 5,038 + 5,038·4) | 15057 | 0.032 | 0.0914 | 0.8433 | 14476 | 1.0 | 3000000 | 3.0 |
| tfidf_person_name | O(N·L + U·N·q) | O(24,864·L + 29,777·24,864·13) | 30234 | 7.442 | 0.6321 | 0.8606 | 26217 | 2.0 | 1000000000000 | 1000000.0 |
| tfidf_company_name | O(N·L + U·N·q) | O(5,038·L + 29,777·5,038·19) | 2892 | 0.648 | 0.0911 | 0.8612 | 2313 | 2.0 | 1000000000000 | 1000000.0 |
| phone_prefecture | O(N + P) | O(31,226 + 2,255) | 1890 | 0.018 | 0.1146 | 0.8612 | 1162 | 1.52 | 1241661 | 1.242 |
| phone_postal_area | O(N + P) | O(31,226 + 1,136) | 597 | 0.04 | 0.0666 | 0.8612 | 174 | 1.17 | 226154 | 0.226 |
| phone_name_initial | O(N + P) | O(31,226 + 3,828) | 3217 | 0.039 | 0.1987 | 0.8612 | 1954 | 1.52 | 2090875 | 2.091 |
| sn_person_name_reversed | O(N log N + N·w) | O(24,864·log 24,864 + 24,864·4) | 73792 | 0.033 | 0.6205 | 0.8842 | 69849 | 1.0 | 3000000 | 3.0 |
| company_name_deletions | O(N·L + P) | O(31,226·L + 1,277) | 1226 | 0.04 | 0.0733 | 0.8847 | 760 | 1.6 | 799991 | 0.8 |
| cif_deletions | O(N·L + P) | O(31,226·L + 178) | 49 | 0.101 | 0.0077 | 0.8847 | 0 | 1.0 | 5700 | 0.006 |
| person_name_deletions_postal_area | O(N·L + P) | O(31,226·L + 1,999) | 1494 | 0.086 | 0.2277 | 0.8858 | 47 | 1.03 | 117670 | 0.118 |
| given_name_postal | O(N + P) | O(31,226 + 1,383) | 1019 | 0.04 | 0.158 | 0.8887 | 15 | 1.01 | 59193 | 0.059 |
| address_phone | O(N + P) | O(31,226 + 351) | 83 | 0.042 | 0.0077 | 0.8887 | 34 | 1.12 | 53964 | 0.054 |
| address_code_phone | O(N + P) | O(31,226 + 692) | 158 | 0.028 | 0.0154 | 0.8887 | 60 | 1.11 | 97673 | 0.098 |
| address_name_initial | O(N + P) | O(31,226 + 1,110) | 839 | 0.03 | 0.0757 | 0.8887 | 358 | 1.33 | 400191 | 0.4 |
| address_code_name_initial | O(N + P) | O(31,226 + 2,009) | 1466 | 0.023 | 0.1482 | 0.8887 | 524 | 1.27 | 602858 | 0.603 |
| given_name_address_code | O(N + P) | O(31,226 + 1,080) | 703 | 0.028 | 0.11 | 0.8887 | 4 | 1.0 | 38560 | 0.039 |
| given_name_phone | O(N + P) | O(31,226 + 1,294) | 877 | 0.03 | 0.1356 | 0.8887 | 15 | 1.01 | 56343 | 0.056 |
| name_reading | O(N + P) | O(31,226 + 4,470) | 3893 | 0.023 | 0.5577 | 0.8889 | 349 | 1.08 | 501833 | 0.502 |
| phone_given_tail | O(N + P) | O(31,226 + 1,744) | 1213 | 0.021 | 0.1852 | 0.8889 | 36 | 1.02 | 91619 | 0.092 |
| postal_given_tail | O(N + P) | O(31,226 + 1,840) | 1364 | 0.035 | 0.2107 | 0.8897 | 25 | 1.01 | 83764 | 0.084 |
| postal_area_given_tail | O(N + P) | O(31,226 + 2,567) | 2075 | 0.032 | 0.2422 | 0.8911 | 536 | 1.21 | 618741 | 0.619 |
| birth_date | O(N + P) | O(31,226 + 358) | 338 | 0.012 | 0.0154 | 0.8919 | 240 | 1.67 | 250918 | 0.251 |
| birth_date_deletions_prefecture | O(N·L + P) | O(31,226·L + 394) | 379 | 0.012 | 0.0094 | 0.8919 | 319 | 1.83 | 337518 | 0.338 |

### Training on train: EM against labels

cost: u O(max_pairs·C) = O(10,000,000·5) · EM O(iterations·P·C), P = 58,249 · em: fitted in 6.5s · no estimate: u - · m - · labels: fitted in 1.0s · no estimate: u - · m -

| comparison | level | em m | em u | em weight | labels m | labels u | labels weight |
| --- | --- | --- | --- | --- | --- | --- | --- |
| name | exact | 0.228 | 0.0 | 15.545 | 0.271 | 0.0 | 15.791 |
| name | fold exact | 0.371 | 0.0 | 15.403 | 0.44 | 0.0 | 15.648 |
| name | fold JW high | 0.127 | 0.0 | 11.501 | 0.125 | 0.0 | 11.48 |
| name | given name | 0.087 | 0.0 | 7.638 | 0.106 | 0.0 | 7.918 |
| name | fold JW low | 0.03 | 0.0 | 6.437 | 0.011 | 0.0 | 5.026 |
| name | else | 0.157 | 0.999 | -2.673 | 0.048 | 0.999 | -4.393 |
| company | exact | 0.696 | 0.0 | 13.432 | 0.492 | 0.0 | 12.931 |
| company | JW high | 0.082 | 0.0 | 11.843 | 0.09 | 0.0 | 11.986 |
| company | JW low | 0.069 | 0.0 | 8.889 | 0.067 | 0.0 | 8.849 |
| company | else | 0.153 | 1.0 | -2.705 | 0.351 | 1.0 | -1.511 |
| address | same address | 0.236 | 0.0 | 13.345 | 0.292 | 0.0 | 13.653 |
| address | address close | 0.005 | 0.002 | 1.622 | 0.006 | 0.002 | 1.991 |
| address | same postal | 0.089 | 0.0 | 10.401 | 0.097 | 0.0 | 10.526 |
| address | else | 0.671 | 0.998 | -0.574 | 0.605 | 0.998 | -0.722 |
| phone | exact | 0.261 | 0.0 | 11.295 | 0.332 | 0.0 | 11.642 |
| phone | one digit off | 0.062 | 0.004 | 4.126 | 0.074 | 0.004 | 4.375 |
| phone | else | 0.677 | 0.996 | -0.558 | 0.594 | 0.996 | -0.746 |
| cif | exact | 0.015 | 0.0 | 14.458 | 0.023 | 0.0 | 15.123 |
| cif | else | 0.985 | 1.0 | -0.021 | 0.977 | 1.0 | -0.034 |

### Threshold: chosen on cross-validated train

3-fold CV in 34.7s → min_match_weight = 10.0

| min_match_weight | accepted | pairs_FP | stage_fp_rate_hi | TP | FP | recall | recall_lo | recall_hi | eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 3372 | 22 | 0.0093 | 4176 | 33 | 0.588 | 0.5765 | 0.5994 | False |
| 2 | 3286 | 7 | 0.004 | 4113 | 10 | 0.5791 | 0.5676 | 0.5906 | False |
| 4 | 2970 | 1 | 0.0016 | 3813 | 2 | 0.5369 | 0.5253 | 0.5485 | False |
| 6 | 2753 | 1 | 0.0017 | 3615 | 2 | 0.509 | 0.4974 | 0.5206 | False |
| 8 | 2402 | 0 | 0.0012 | 3274 | 0 | 0.461 | 0.4494 | 0.4726 | True |
| 10 | 2086 | 0 | 0.0014 | 2946 | 0 | 0.4148 | 0.4034 | 0.4263 | True |
| 12 | 1002 | 0 | 0.003 | 1764 | 0 | 0.2484 | 0.2385 | 0.2586 | True |
| 14 | 308 | 0 | 0.0097 | 1057 | 0 | 0.1488 | 0.1407 | 0.1573 | True |
| 16 | 242 | 0 | 0.0123 | 994 | 0 | 0.14 | 0.1321 | 0.1482 | True |

### A/B on val, paired against the tuned configuration as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | candidates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| labels | 0.429 | 0 | 0.0028 | 1 | 4 | 0.375 | 0 | 0 | 38892 |
| no_term_frequency | 0.4354 | 0 | 0.0028 | 13 | 0 | 0.0002 | 0 | 0 | 38892 |
| exact_keys_only | 0.4294 | 0 | 0.0028 | 0 | 2 | 0.5 | 0 | 0 | 8372 |
| levenshtein_names | 0.4507 | 0 | 0.0027 | 52 | 1 | 0.0 | 0 | 0 | 38892 |
| optuna_suggestion | 0.4439 | 0 | 0.0027 | 38 | 4 | 0.0 | 0 | 0 | 16806 |
| u_from_1e6_pairs | 0.4583 | 0 | 0.0026 | 72 | 2 | 0.0 | 0 | 0 | 38892 |
| compound_phone_keys | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 33779 |
| sorted_names_for_tfidf | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 59975 |
| name_keys | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38933 |
| bounded_address_keys | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 37879 |
| no_sorted_windows | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 12260 |
| bridge_rule_clusters | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38973 |
| u_from_scored_file | 0.3921 | 0 | 0.0031 | 0 | 95 | 0.0 | 0 | 0 | 38892 |
| u_exact_by_counts | 0.4306 | 0 | 0.0028 | 1 | 0 | 1.0 | 0 | 0 | 38892 |
| cif_one_digit_off | 0.4322 | 0 | 0.0028 | 5 | 0 | 0.0625 | 0 | 0 | 38892 |
| graded_address | 0.4491 | 0 | 0.0027 | 47 | 0 | 0.0 | 0 | 0 | 38892 |
| birth_date | 0.4383 | 0 | 0.0027 | 20 | 0 | 0.0 | 0 | 0 | 38892 |
| cif_deletion_key | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38893 |
| birth_date_key | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38920 |
| given_name_phone_key | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38892 |
| birth_date_deletion_key | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38926 |
| name_reading_key | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38903 |
| given_tail_keys | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38976 |
| same_reading_level | 0.4443 | 0 | 0.0027 | 35 | 0 | 0.0 | 0 | 0 | 38892 |
| same_given_tail_level | 0.4358 | 0 | 0.0028 | 14 | 0 | 0.0001 | 0 | 0 | 38892 |
| given_comparison | 0.6504 | 49 | 0.0371 | 550 | 1 | 0.0 | 49 | 0 | 38892 |
| given_or_tail_comparison | 0.5517 | 8 | 0.0104 | 305 | 2 | 0.0 | 8 | 0 | 38892 |
| name_needed | 0.4226 | 0 | 0.0028 | 0 | 19 | 0.0 | 0 | 0 | 38892 |
| u_near_by_keys | 0.4302 | 0 | 0.0028 | 0 | 0 | 1.0 | 0 | 0 | 38892 |
| fit_u_from_1e6_pairs | 0.4583 | 0 | 0.0026 | 72 | 2 | 0.0 | 0 | 0 | 38892 |
| company_without_jw_high | 0.4294 | 0 | 0.0028 | 0 | 2 | 0.5 | 0 | 0 | 38892 |

### Decisions

FINAL: 22 generators · term frequency off · m by em · min_match_weight 6.0 · connected_components

| change | kind | adopted | cv_TP_gains | cv_TP_losses | cv_p | cv_FP_added | cv_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_term_frequency | better | True | 33 | 0 | 0.0 | 0 | 0 | 13 | 0 | 0 |
| exact_keys_only | cheaper | False | 0 | 7 | 0.0156 | 0 | 0 | 0 | 2 | 0 |
| optuna_suggestion | better | True | 79 | 14 | 0.0 | 0 | 0 | 25 | 4 | 0 |
| u_from_1e6_pairs | cheaper | False | 93 | 67 | 0.0478 | 0 | 0 | 61 | 0 | 0 |
| compound_phone_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| sorted_names_for_tfidf | cheaper | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| name_keys | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| bounded_address_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| no_sorted_windows | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| bridge_rule_clusters | better | True | 8 | 0 | 0.0078 | 0 | 0 | 0 | 0 | 0 |
| u_from_scored_file | chosen | True | 0 | 700 | 0.0 | 0 | 0 | 0 | 92 | 0 |
| u_exact_by_counts | chosen | True | 437 | 170 | 0.0 | 0 | 0 | 0 | 335 | 0 |
| cif_one_digit_off | better | True | 7 | 0 | 0.0156 | 0 | 0 | 4 | 0 | 0 |
| cif_deletion_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| graded_address | better | False | 159 | 344 | 0.0 | 0 | 0 | 181 | 3 | 0 |
| birth_date | better | True | 49 | 0 | 0.0 | 0 | 0 | 27 | 0 | 0 |
| birth_date_key | safer | True | 8 | 0 | 0.0078 | 0 | 0 | 4 | 0 | 0 |
| given_name_phone_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| birth_date_deletion_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| u_near_by_keys | chosen | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| fit_u_from_1e6_pairs | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| company_without_jw_high | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| name_needed | chosen | True | 682 | 5 | 0.0 | 0 | 0 | 494 | 2 | 0 |
| name_reading_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| given_tail_keys | safer | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| same_reading_level | better | True | 67 | 0 | 0.0 | 0 | 0 | 37 | 0 | 0 |
| same_given_tail_level | better | False | 15 | 8 | 0.21 | 0 | 0 | 10 | 6 | 0 |
| given_comparison | better | False | 117 | 897 | 0.0 | 0 | 0 | 0 | 352 | 0 |
| given_or_tail_comparison | better | False | 0 | 422 | 0.0 | 0 | 0 | 0 | 154 | 0 |

### Will it scale? FINAL's generators at target_rows

| key | columns | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- |
| cif | customer_id | 1.0 | 5027 | 0.005 | True |
| phone_prefecture | phone + prefecture | 1.52 | 1241661 | 1.242 | True |
| phone_postal_area | phone + postal_code__first3 | 1.17 | 226154 | 0.226 | True |
| phone_name_initial | phone + any_name__initial | 1.52 | 2090875 | 2.091 | True |
| person_name | person_name__kana_fold | 1.08 | 465716 | 0.466 | True |
| company_name | company_name__nfkc_strip_legal_form_kana_fold | 1.41 | 362026 | 0.362 | True |
| company_name_deletions | company_name__nfkc_strip_legal_form_kana_fold | 1.6 | 799991 | 0.8 | True |
| person_name_deletions_postal_area | person_name__kana_fold + postal_code__first3 | 1.03 | 117670 | 0.118 | True |
| given_name_postal | given_name__kana_fold + postal_code | 1.01 | 59193 | 0.059 | True |
| address_phone | address__address + phone | 1.12 | 53964 | 0.054 | True |
| address_code_phone | address_code + phone | 1.11 | 97673 | 0.098 | True |
| address_name_initial | address__address + any_name__initial | 1.33 | 400191 | 0.4 | True |
| address_code_name_initial | address_code + any_name__initial | 1.27 | 602858 | 0.603 | True |
| given_name_address_code | given_name__kana_fold + address_code | 1.0 | 38560 | 0.039 | True |
| cif_deletions | customer_id | 1.0 | 5700 | 0.006 | True |
| birth_date | birth_date | 1.67 | 250918 | 0.251 | True |
| given_name_phone | given_name__kana_fold + phone | 1.01 | 56343 | 0.056 | True |
| birth_date_deletions_prefecture | birth_date + prefecture | 1.83 | 337518 | 0.338 | True |
| name_reading | person_name__kana_fold_long_vowel | 1.08 | 501833 | 0.502 | True |
| phone_given_tail | phone + person_name__kana_fold_long_vowel_last3 | 1.02 | 91619 | 0.092 | True |
| postal_given_tail | postal_code + person_name__kana_fold_long_vowel_last3 | 1.01 | 83764 | 0.084 | True |
| postal_area_given_tail | postal_code__first3 + person_name__kana_fold_long_vowel_last3 | 1.21 | 618741 | 0.619 | True |

### Potential matches that share no key (train)

| records | potential | window_only |
| --- | --- | --- |
| 31226 | 3278 | 0 |
| 1000000 | 3071 | 0 |

### Patterns without a guaranteed key, at target_rows (label-free)

190 patterns that can reach the threshold at 1,000,000 records have no guaranteed key; the model puts their share of matches at 13.247% at most (Jaro–Winkler implies no key)

| name | company | address | phone | cif | birth | bits | share_of_matches |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fold JW high | missing | same address | missing | missing | missing | 7.5 | 0.014148260670867944 |
| fold JW high | missing | same address | missing | else | missing | 7.48 | 0.013901563215815526 |
| fold JW high | missing | same address | else | missing | missing | 6.95 | 0.009630125650209483 |
| fold JW high | missing | same address | else | else | missing | 6.93 | 0.009462209074101054 |
| missing | JW low | same address | missing | missing | one digit off | 6.48 | 0.004394160338815343 |
| missing | JW low | same address | missing | else | one digit off | 6.45 | 0.004317541155871528 |
| given name | JW low | same address | missing | missing | missing | 7.17 | 0.003139378866955014 |
| given name | JW low | same address | missing | else | missing | 7.14 | 0.003084638797137256 |
| given name | missing | same address | missing | missing | one digit off | 6.8 | 0.0028149616611422485 |
| given name | missing | same address | missing | else | one digit off | 6.77 | 0.0027658783219227626 |

### FINAL's candidates on val

candidates 2,568 · they contain 79.6% of the true pairs the rules missed

| generator | big_o | filled | pairs | completeness_on_targets | seconds |
| --- | --- | --- | --- | --- | --- |
| cif | O(N + P) | O(10,496 + 63) | 12 | 0.0055 | 0.005 |
| phone_prefecture | O(N + P) | O(10,496 + 550) | 417 | 0.1233 | 0.005 |
| phone_postal_area | O(N + P) | O(10,496 + 388) | 175 | 0.0619 | 0.005 |
| phone_name_initial | O(N + P) | O(10,496 + 923) | 693 | 0.1893 | 0.005 |
| person_name | O(N + P) | O(10,496 + 1,418) | 1209 | 0.5227 | 0.016 |
| company_name | O(N + P) | O(10,496 + 213) | 193 | 0.0719 | 0.004 |
| company_name_deletions | O(N·L + P) | O(10,496·L + 259) | 238 | 0.0746 | 0.007 |
| person_name_deletions_postal_area | O(N·L + P) | O(10,496·L + 679) | 482 | 0.2152 | 0.022 |
| given_name_postal | O(N + P) | O(10,496 + 485) | 354 | 0.1611 | 0.005 |
| address_phone | O(N + P) | O(10,496 + 134) | 33 | 0.01 | 0.005 |
| address_code_phone | O(N + P) | O(10,496 + 270) | 60 | 0.0187 | 0.014 |
| address_name_initial | O(N + P) | O(10,496 + 351) | 250 | 0.071 | 0.007 |
| address_code_name_initial | O(N + P) | O(10,496 + 679) | 468 | 0.1533 | 0.02 |
| given_name_address_code | O(N + P) | O(10,496 + 363) | 231 | 0.1051 | 0.006 |
| cif_deletions | O(N·L + P) | O(10,496·L + 69) | 17 | 0.0077 | 0.029 |
| birth_date | O(N + P) | O(10,496 + 64) | 57 | 0.015 | 0.003 |
| given_name_phone | O(N + P) | O(10,496 + 439) | 294 | 0.1328 | 0.005 |
| birth_date_deletions_prefecture | O(N·L + P) | O(10,496·L + 55) | 52 | 0.0082 | 0.016 |
| name_reading | O(N + P) | O(10,496 + 1,507) | 1291 | 0.5591 | 0.005 |
| phone_given_tail | O(N + P) | O(10,496 + 625) | 420 | 0.1884 | 0.005 |
| postal_given_tail | O(N + P) | O(10,496 + 633) | 450 | 0.2047 | 0.005 |
| postal_area_given_tail | O(N + P) | O(10,496 + 764) | 578 | 0.2307 | 0.005 |

### Evaluation on val

transfer at weight 6.0: CV 0 false of 2569 accepted pairs (rate ≤ 0.12%) · val 0 of 918 (0.00%)

| stage | TP | FP | household | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | 296 | 0 | 5 | 0.1187 | 0.1066 | 0.132 | 0.0101 | 0 | 5 | 3522 |
| probabilistic | 1244 | 0 | 51 | 0.4988 | 0.4792 | 0.5184 | 0.0024 | 0 | 33 | 1968 |

### Households on val

at weight 6.0: 32 accepted pairs join two people of one household, counted apart from the false pairs; people see 27 of them labelled maybe one household, and 2 other accepted pairs

### Threshold curve on val

| min_match_weight | accepted | pairs_FP | TP | FP | recall | fp_rate_hi |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1263 | 8 | 1488 | 13 | 0.5966 | 0.0137 |
| 2 | 1195 | 5 | 1451 | 7 | 0.5818 | 0.009 |
| 4 | 973 | 0 | 1296 | 0 | 0.5196 | 0.0023 |
| 6 | 918 | 0 | 1244 | 0 | 0.4988 | 0.0024 |
| 8 | 877 | 0 | 1212 | 0 | 0.486 | 0.0025 |
| 10 | 416 | 0 | 719 | 0 | 0.2883 | 0.0042 |
| 12 | 147 | 0 | 436 | 0 | 0.1748 | 0.0068 |
| 14 | 128 | 0 | 420 | 0 | 0.1684 | 0.0071 |
| 16 | 99 | 0 | 399 | 0 | 0.16 | 0.0075 |

### An accepted true match with a typo

6.19 bits → match probability 0.9865 · found by phone_postal_area+phone_name_initial+address_phone+address_code_phone+address_name_initial+address_code_name_initial

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000001188 | ミッマテルヤ | nan | 20-2 | 3077 | 9991758286659 |
| 0000011622 | ミッマドウミョオ | nan | 愛知県20-2 | 3077 | 2286801775966 |

### An accepted true match with a typo: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.49 |
| name | else | -3.19 |
| company | missing | 0.0 |
| address | same address | 12.77 |
| phone | exact | 11.14 |
| cif | else | -0.03 |
| birth | missing | 0.0 |

### The rejected non-match closest to the threshold

3.66 bits → match probability 0.9265 · found by given_name_phone+phone_given_tail

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000007614 | ャマノベタカユキ | nan | 北海道岩見沢市日の出台10-26-24 | 2604 | 8852433827058 |
| 0000042176 | イナモチタカユキ | nan | 大阪府泉北郡忠岡町 | 2604 | 7587446239261 |

### The rejected non-match closest to the threshold: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.49 |
| name | given name | 7.62 |
| company | missing | 0.0 |
| address | else | -0.58 |
| phone | exact | 11.14 |
| cif | else | -0.03 |
| birth | missing | 0.0 |

### FINAL on train, val and test

| dataset | records | recall_before | TP | FP | household | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | accepted | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 31226 | 0.1052 | 3386 | 0 | 112 | 0.4768 | 0.4652 | 0.4884 | 0.0009 | 0 | 72 | 5928 | 2566 | 5.0 |
| val | 10496 | 0.1187 | 1244 | 0 | 51 | 0.4988 | 0.4792 | 0.5184 | 0.0024 | 0 | 33 | 1968 | 918 | 3.5 |
| test | 10393 | 0.096 | 1134 | 0 | 45 | 0.4817 | 0.4616 | 0.5019 | 0.0026 | 0 | 26 | 1949 | 882 | 5.5 |

### Configurations scored on test, per stage

| family | configs_on_test |
| --- | --- |
| deterministic | 1 |
| probabilistic | 1 |
