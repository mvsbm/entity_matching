# Choosing the configuration

Written by `scripts/choose.py` from `config/pipeline.toml` and `config/experiments.py`, on the labelled synthetic datasets. Test is scored once per stage, at the end of each.

## Stage 1: rules

### Design analysis on train

| keys | same_entity_agree | different_entity_pairs |
| --- | --- | --- |
| address | 0.1055 | 20142 |
| address_code | 0.2714 | 4787 |
| company_name | 0.0129 | 37 |
| customer_id | 0.0234 | 0 |
| full_name | 0.1955 | 150 |
| given_name | 0.3217 | 84380 |
| person_name | 0.2074 | 154 |
| phone | 0.3318 | 45079 |
| postal_code | 0.3558 | 33413 |
| customer_id + full_name | 0.0035 | 0 |
| customer_id + company_name | 0.0003 | 0 |
| customer_id + phone | 0.0078 | 0 |
| full_name + address_code + phone | 0.0198 | 0 |
| company_name + address_code + phone | 0.0007 | 0 |
| address_code + phone | 0.0884 | 1 |
| phone + address__address | 0.0422 | 2 |
| person_name + address_code | 0.0604 | 0 |
| phone + postal_code | 0.1149 | 4 |
| given_name + address_code + phone | 0.0315 | 0 |

### A/B on val, paired against the rules as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | P | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | 0.0921 | 0 | 0.0146 | 6 | 2 | 0.2891 | 0 | 0 | 1041 | 0.2 |
| fold_exact | 0.0804 | 0 | 0.0167 | 0 | 22 | 0.0 | 0 | 0 | 475 | 0.2 |
| raw_jaro_winkler | 0.0718 | 0 | 0.0187 | 0 | 41 | 0.0 | 0 | 0 | 1041 | 0.2 |
| optuna_comparators | 0.0993 | 0 | 0.0135 | 21 | 1 | 0.0 | 0 | 0 | 6706 | 0.2 |
| f2_address_exact | 0.0903 | 0 | 0.0149 | 0 | 0 | 1.0 | 0 | 0 | 1041 | 0.3 |
| f2_address_prefix | 0.0903 | 0 | 0.0149 | 0 | 0 | 1.0 | 0 | 0 | 1041 | 0.2 |

### Decisions

FINAL fuzzy comparators: {'person_name': 'damerau_levenshtein 2 kana_fold', 'company_name': 'levenshtein 1 nfkc+strip_legal_form+kana_fold', 'address': 'jaro_winkler 0.9 address', 'phone': 'hamming 1'} · connected_components

| change | kind | adopted | train_TP_gains | train_TP_losses | train_p | train_FP_added | train_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | better | True | 17 | 4 | 0.0072 | 0 | 0 | 6 | 2 | 0 |
| fold_exact | cheaper | False | 0 | 83 | 0.0 | 0 | 0 | 0 | 26 | 0 |
| f2_address_exact | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| f2_address_prefix | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| optuna_comparators | better | True | 33 | 0 | 0.0 | 0 | 0 | 11 | 0 | 0 |

### Cost of FINAL: every rule now and at target_rows

train: N = 30,103 · total P = 3,710 → 244,185 at 1,000,000 rows

| stage | rule | keys | big_o | filled | P | largest_block | est_fuzzy_ms | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | X1_CIF_PERSON_NAME | customer_id + full_name | O(N + P) | O(30,103 + 24) | 24 | 2 | 0.0 | 1.0 | 797 | 0.001 | True |
| exact | X2_CIF_COMPANY_NAME | customer_id + company_name | O(N + P) | O(30,103 + 2) | 2 | 2 | 0.0 | 1.0 | 66 | 0.0 | True |
| exact | X3_CIF_PHONE | customer_id + phone | O(N + P) | O(30,103 + 54) | 54 | 2 | 0.0 | 1.0 | 1793 | 0.002 | True |
| exact | X4_PERSON_NAME_ADDRCD_PHONE | full_name + address_code + phone | O(N + P) | O(30,103 + 137) | 137 | 3 | 0.0 | 1.0 | 4551 | 0.005 | True |
| exact | X5_COMPANY_NAME_ADDRCD_PHONE | company_name + address_code + phone | O(N + P) | O(30,103 + 5) | 5 | 2 | 0.0 | 1.0 | 166 | 0.0 | True |
| fuzzy | F1_NAME~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(30,103 + 613·45) | 613 | 3 | 0.12 | 1.0 | 21433 | 0.021 | True |
| fuzzy | F2_NAME~_ADDRESS~_PHONE | phone + address__address_first3 | O(N + P·(m·n + m·n)) | O(30,103 + 665·153) | 665 | 4 | 0.25 | 1.16 | 136616 | 0.137 | True |
| fuzzy | F3_NAME~_CIF | customer_id | O(N + P·(m·n)) | O(30,103 + 162·45) | 162 | 3 | 0.03 | 1.0 | 5381 | 0.005 | True |
| fuzzy | F4_NAME_ADDRCD_PHONE~ | person_name + address_code | O(N + P·(n)) | O(30,103 + 418·4) | 418 | 3 | 0.02 | 1.0 | 13885 | 0.014 | True |
| fuzzy | F5_COMPANY~_PHONE_POSTAL | phone + postal_code | O(N + P·(m·n)) | O(30,103 + 799·91) | 799 | 3 | 0.16 | 1.01 | 30823 | 0.031 | True |
| fuzzy | F6_COMPANY~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(30,103 + 613·91) | 613 | 3 | 0.12 | 1.0 | 21433 | 0.021 | True |
| fuzzy | F7_GIVEN_ADDRCD_PHONE | given_name + address_code + phone | O(N + P) | O(30,103 + 218) | 218 | 3 | 0.0 | 1.0 | 7241 | 0.007 | True |

### Evaluation on val

rules: Σ ops ≈ 196,662 (see big_o per rule) · normalize: O(N·L), N = 9,966 · cluster: O((N + E)·d), N = 9,966, E = 213 · evaluate: O(N) · total 0.2s · false-positive pairs: 0

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | 66 | 0 | 0.0298 | 0.0235 | 0.0377 | 0.0444 | 0 | 0 | 3573 |
| fuzzy | 215 | 0 | 0.0971 | 0.0854 | 0.1101 | 0.0138 | 0 | 0 | 3281 |

### Rules on val

| rule | P | actual_ms | edges | edge_FP | kept | kept_FP |
| --- | --- | --- | --- | --- | --- | --- |
| X1_CIF_PERSON_NAME | 12 | 2.4 | 12 | 0 | 12 | 0 |
| X2_CIF_COMPANY_NAME | 0 | 1.7 | 0 | 0 | 0 | 0 |
| X3_CIF_PHONE | 15 | 2.1 | 12 | 0 | 12 | 0 |
| X4_PERSON_NAME_ADDRCD_PHONE | 40 | 2.2 | 38 | 0 | 38 | 0 |
| X5_COMPANY_NAME_ADDRCD_PHONE | 4 | 1.9 | 4 | 0 | 4 | 0 |
| F1_NAME~_ADDRCD_PHONE | 198 | 3.9 | 92 | 0 | 92 | 0 |
| F2_NAME~_ADDRESS~_PHONE | 170 | 4.3 | 13 | 0 | 13 | 0 |
| F3_NAME~_CIF | 48 | 3.2 | 17 | 0 | 17 | 0 |
| F4_NAME_ADDRCD_PHONE~ | 120 | 2.4 | 2 | 0 | 2 | 0 |
| F5_COMPANY~_PHONE_POSTAL | 246 | 2.8 | 13 | 0 | 13 | 0 |
| F6_COMPANY~_ADDRCD_PHONE | 198 | 2.6 | 2 | 0 | 2 | 0 |
| F7_GIVEN_ADDRCD_PHONE | 66 | 2.1 | 8 | 0 | 8 | 0 |

### FINAL on train, val and test

| dataset | records | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30103 | 743 | 0 | 0.1074 | 0.1003 | 0.1149 | 0.004 | 0 | 0 | 10040 | 0.5 |
| val | 9966 | 215 | 0 | 0.0971 | 0.0854 | 0.1101 | 0.0138 | 0 | 0 | 3281 | 0.3 |
| test | 10047 | 227 | 0 | 0.0971 | 0.0858 | 0.1098 | 0.0131 | 0 | 0 | 3394 | 0.2 |

## Stage 2: Fellegi–Sunter

### Candidates on train: reach and cost of every generator

train: 6,177 true pairs missed by the rules

| generator | big_o | filled | pairs | seconds | finds | cumulative | different_entity_pairs | alpha | projected_pairs | per_record |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phone | O(N + P) | O(30,103 + 47,375) | 46675 | 0.013 | 0.2702 | 0.2702 | 45006 | 1.95 | 49823479 | 49.823 |
| address | O(N + P) | O(30,103 + 5,788) | 5507 | 0.009 | 0.1099 | 0.3719 | 4828 | 1.84 | 5372703 | 5.373 |
| address_code | O(N + P) | O(30,103 + 6,665) | 6063 | 0.008 | 0.2101 | 0.48 | 4765 | 1.72 | 5345109 | 5.345 |
| cif | O(N + P) | O(30,103 + 162) | 37 | 0.007 | 0.006 | 0.485 | 0 | 1.0 | 5381 | 0.005 |
| person_name | O(N + P) | O(30,103 + 4,185) | 3651 | 0.008 | 0.52 | 0.7531 | 439 | 1.1 | 608900 | 0.609 |
| company_name | O(N + P) | O(30,103 + 795) | 746 | 0.006 | 0.0712 | 0.795 | 306 | 1.38 | 353932 | 0.354 |
| sn_person_name | O(N log N + N·w) | O(23,741·log 23,741 + 23,741·4) | 70472 | 0.009 | 0.5932 | 0.8297 | 66808 | 1.0 | 3000000 | 3.0 |
| sn_company_name | O(N log N + N·w) | O(5,032·log 5,032 + 5,032·4) | 15030 | 0.005 | 0.0954 | 0.8433 | 14441 | 1.0 | 3000000 | 3.0 |
| tfidf_person_name | O(N·L + U·N·q) | O(23,741·L + 28,692·23,741·13) | 28092 | 2.86 | 0.6184 | 0.8603 | 24272 | 2.0 | 1000000000000 | 1000000.0 |
| tfidf_company_name | O(N·L + U·N·q) | O(5,032·L + 28,692·5,032·19) | 2805 | 0.266 | 0.0949 | 0.8611 | 2219 | 2.0 | 1000000000000 | 1000000.0 |
| phone_prefecture | O(N + P) | O(30,103 + 2,070) | 1729 | 0.008 | 0.1221 | 0.8611 | 975 | 1.47 | 1115553 | 1.116 |
| phone_postal_area | O(N + P) | O(30,103 + 981) | 462 | 0.008 | 0.0599 | 0.8611 | 92 | 1.09 | 131059 | 0.131 |
| phone_name_initial | O(N + P) | O(30,103 + 3,307) | 2730 | 0.008 | 0.1949 | 0.8611 | 1526 | 1.46 | 1745330 | 1.745 |
| sn_person_name_reversed | O(N log N + N·w) | O(23,741·log 23,741 + 23,741·4) | 70478 | 0.009 | 0.6082 | 0.8841 | 66721 | 1.0 | 3000000 | 3.0 |
| company_name_deletions | O(N·L + P) | O(30,103·L + 1,264) | 1210 | 0.01 | 0.0748 | 0.8844 | 748 | 1.59 | 842601 | 0.843 |
| cif_deletions | O(N·L + P) | O(30,103·L + 181) | 53 | 0.025 | 0.0086 | 0.8846 | 0 | 1.0 | 6012 | 0.006 |
| person_name_deletions_postal_area | O(N·L + P) | O(30,103·L + 1,925) | 1418 | 0.025 | 0.227 | 0.8851 | 16 | 1.01 | 81072 | 0.081 |
| given_name_postal | O(N + P) | O(30,103 + 1,338) | 971 | 0.008 | 0.1556 | 0.8873 | 10 | 1.01 | 55150 | 0.055 |
| address_phone | O(N + P) | O(30,103 + 294) | 53 | 0.01 | 0.0083 | 0.8873 | 2 | 1.01 | 11907 | 0.012 |
| address_code_phone | O(N + P) | O(30,103 + 613) | 92 | 0.008 | 0.0147 | 0.8873 | 1 | 1.0 | 21433 | 0.021 |
| address_name_initial | O(N + P) | O(30,103 + 895) | 649 | 0.01 | 0.0743 | 0.8873 | 190 | 1.21 | 233095 | 0.233 |
| address_code_name_initial | O(N + P) | O(30,103 + 1,650) | 1110 | 0.008 | 0.1462 | 0.8873 | 207 | 1.13 | 276371 | 0.276 |
| given_name_address_code | O(N + P) | O(30,103 + 1,009) | 637 | 0.007 | 0.103 | 0.8873 | 1 | 1.0 | 34588 | 0.035 |
| given_name_phone | O(N + P) | O(30,103 + 1,290) | 905 | 0.007 | 0.1447 | 0.8873 | 11 | 1.01 | 54626 | 0.055 |
| birth_date | O(N + P) | O(30,103 + 352) | 333 | 0.005 | 0.013 | 0.8883 | 253 | 1.72 | 282488 | 0.282 |
| birth_date_deletions_prefecture | O(N·L + P) | O(30,103·L + 342) | 324 | 0.005 | 0.0083 | 0.8883 | 273 | 1.82 | 313195 | 0.313 |

### Training on train: EM against labels

cost: u O(max_pairs·C) = O(10,000,000·5) · EM O(iterations·P·C), P = 53,163 · em: fitted in 7.5s · no estimate: u - · m - · labels: fitted in 0.3s · no estimate: u - · m -

| comparison | level | em m | em u | em weight | labels m | labels u | labels weight |
| --- | --- | --- | --- | --- | --- | --- | --- |
| name | exact | 0.258 | 0.0 | 15.607 | 0.267 | 0.0 | 15.661 |
| name | fold exact | 0.427 | 0.0 | 15.831 | 0.431 | 0.0 | 15.843 |
| name | fold JW high | 0.124 | 0.0 | 11.601 | 0.127 | 0.0 | 11.631 |
| name | given name | 0.116 | 0.0 | 7.938 | 0.107 | 0.0 | 7.825 |
| name | fold JW low | 0.016 | 0.0 | 5.683 | 0.014 | 0.0 | 5.415 |
| name | else | 0.059 | 0.999 | -4.089 | 0.054 | 0.999 | -4.199 |
| company | exact | 0.613 | 0.0 | 12.732 | 0.507 | 0.0 | 12.458 |
| company | JW high | 0.119 | 0.0 | 11.613 | 0.084 | 0.0 | 11.105 |
| company | JW low | 0.109 | 0.0 | 9.386 | 0.078 | 0.0 | 8.899 |
| company | else | 0.158 | 1.0 | -2.66 | 0.331 | 1.0 | -1.595 |
| address | same address | 0.237 | 0.0 | 13.346 | 0.293 | 0.0 | 13.651 |
| address | address close | 0.007 | 0.001 | 2.208 | 0.006 | 0.001 | 1.991 |
| address | same postal | 0.081 | 0.0 | 10.343 | 0.099 | 0.0 | 10.626 |
| address | else | 0.675 | 0.998 | -0.565 | 0.602 | 0.998 | -0.729 |
| phone | exact | 0.264 | 0.0 | 11.387 | 0.332 | 0.0 | 11.716 |
| phone | one digit off | 0.062 | 0.004 | 4.11 | 0.073 | 0.004 | 4.351 |
| phone | else | 0.674 | 0.996 | -0.564 | 0.595 | 0.996 | -0.744 |
| cif | exact | 0.018 | 0.0 | 17.364 | 0.024 | 0.0 | 17.79 |
| cif | else | 0.982 | 1.0 | -0.027 | 0.976 | 1.0 | -0.036 |

### Threshold: chosen on cross-validated train

3-fold CV in 27.5s → min_match_weight = 12.0

| min_match_weight | accepted | pairs_FP | stage_fp_rate_hi | TP | FP | recall | recall_lo | recall_hi | eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 3194 | 27 | 0.0116 | 4099 | 42 | 0.5923 | 0.5807 | 0.6039 | False |
| 2 | 3081 | 8 | 0.0047 | 3994 | 14 | 0.5772 | 0.5655 | 0.5888 | False |
| 4 | 2966 | 3 | 0.0026 | 3886 | 5 | 0.5616 | 0.5498 | 0.5732 | False |
| 6 | 2649 | 1 | 0.0018 | 3545 | 1 | 0.5123 | 0.5005 | 0.5241 | False |
| 8 | 2380 | 1 | 0.002 | 3257 | 1 | 0.4707 | 0.4589 | 0.4824 | False |
| 10 | 2057 | 0 | 0.0015 | 2919 | 0 | 0.4218 | 0.4102 | 0.4335 | True |
| 12 | 925 | 0 | 0.0032 | 1696 | 0 | 0.2451 | 0.2351 | 0.2554 | True |
| 14 | 280 | 0 | 0.0106 | 1028 | 0 | 0.1486 | 0.1404 | 0.1571 | True |
| 16 | 218 | 0 | 0.0136 | 964 | 0 | 0.1393 | 0.1313 | 0.1477 | True |

### A/B on val, paired against the tuned configuration as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | candidates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| labels | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36620 |
| no_term_frequency | 0.3521 | 0 | 0.0038 | 15 | 0 | 0.0001 | 0 | 0 | 36620 |
| exact_keys_only | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 7518 |
| levenshtein_names | 0.3065 | 0 | 0.0044 | 2 | 88 | 0.0 | 0 | 0 | 36620 |
| optuna_suggestion | 0.3639 | 0 | 0.0037 | 42 | 1 | 0.0 | 0 | 0 | 15771 |
| u_from_1e6_pairs | 0.3025 | 0 | 0.0045 | 0 | 95 | 0.0 | 0 | 0 | 36620 |
| compound_phone_keys | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 31845 |
| sorted_names_for_tfidf | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 56392 |
| name_keys | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36678 |
| bounded_address_keys | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 35779 |
| no_sorted_windows | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 11184 |
| bridge_rule_clusters | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36692 |
| u_from_scored_file | 0.1964 | 0 | 0.0069 | 0 | 330 | 0.0 | 0 | 0 | 36620 |
| u_exact_by_counts | 0.2307 | 0 | 0.0058 | 0 | 254 | 0.0 | 0 | 0 | 36620 |
| cif_one_digit_off | 0.3065 | 0 | 0.0044 | 1 | 87 | 0.0 | 0 | 0 | 36620 |
| graded_address | 0.312 | 0 | 0.0043 | 53 | 127 | 0.0 | 0 | 0 | 36620 |
| birth_date | 0.316 | 0 | 0.0043 | 22 | 87 | 0.0 | 0 | 0 | 36620 |
| cif_deletion_key | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36620 |
| birth_date_key | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36649 |
| given_name_phone_key | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36620 |
| birth_date_deletion_key | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36650 |
| name_needed | 0.3449 | 0 | 0.0039 | 0 | 1 | 1.0 | 0 | 0 | 36620 |
| u_near_by_keys | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36620 |
| fit_u_from_1e6_pairs | 0.3025 | 0 | 0.0045 | 0 | 95 | 0.0 | 0 | 0 | 36620 |
| company_without_jw_high | 0.3454 | 0 | 0.0039 | 0 | 0 | 1.0 | 0 | 0 | 36620 |

### Decisions

FINAL: 21 generators · term frequency off · m by em · min_match_weight 8.0 · connected_components

| change | kind | adopted | cv_TP_gains | cv_TP_losses | cv_p | cv_FP_added | cv_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_term_frequency | better | True | 12 | 0 | 0.0005 | 0 | 0 | 15 | 0 | 0 |
| exact_keys_only | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| optuna_suggestion | better | True | 1488 | 1 | 0.0 | 0 | 0 | 243 | 0 | 0 |
| u_from_1e6_pairs | cheaper | False | 1 | 8 | 0.0391 | 0 | 0 | 0 | 1 | 0 |
| compound_phone_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| sorted_names_for_tfidf | cheaper | True | 1 | 0 | 1.0 | 0 | 0 | 4 | 0 | 0 |
| name_keys | safer | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| bounded_address_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| no_sorted_windows | cheaper | False | 0 | 0 | 1.0 | 0 | 0 | 0 | 1 | 0 |
| bridge_rule_clusters | better | False | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| u_from_scored_file | chosen | True | 0 | 60 | 0.0 | 0 | 0 | 0 | 12 | 0 |
| u_exact_by_counts | chosen | True | 47 | 5 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| cif_one_digit_off | better | True | 8 | 0 | 0.0078 | 0 | 0 | 2 | 0 | 0 |
| cif_deletion_key | safer | True | 2 | 0 | 0.5 | 0 | 0 | 0 | 0 | 0 |
| graded_address | better | True | 124 | 67 | 0.0 | 0 | 0 | 29 | 20 | 0 |
| birth_date | better | True | 56 | 0 | 0.0 | 0 | 0 | 22 | 0 | 0 |
| birth_date_key | safer | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| given_name_phone_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| birth_date_deletion_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| u_near_by_keys | chosen | True | 0 | 2 | 0.5 | 0 | 0 | 0 | 0 | 0 |
| fit_u_from_1e6_pairs | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| company_without_jw_high | cheaper | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| name_needed | chosen | True | 0 | 39 | 0.0 | 0 | 0 | 0 | 22 | 0 |

### Will it scale? FINAL's generators at target_rows

| key | columns | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- |
| cif | customer_id | 1.0 | 5381 | 0.005 | True |
| sn_company_name | company_name__nfkc_strip_legal_form_kana_fold | 1.0 | 3000000 | 3.0 | True |
| phone_prefecture | phone + prefecture | 1.47 | 1115553 | 1.116 | True |
| phone_postal_area | phone + postal_code__first3 | 1.09 | 131059 | 0.131 | True |
| phone_name_initial | phone + any_name__initial | 1.46 | 1745330 | 1.745 | True |
| sn_person_name | person_name__kana_fold | 1.0 | 3000000 | 3.0 | True |
| sn_person_name_reversed | person_name__kana_fold_reverse | 1.0 | 3000000 | 3.0 | True |
| person_name | person_name__kana_fold | 1.1 | 608900 | 0.609 | True |
| company_name | company_name__nfkc_strip_legal_form_kana_fold | 1.38 | 353932 | 0.354 | True |
| company_name_deletions | company_name__nfkc_strip_legal_form_kana_fold | 1.59 | 842601 | 0.843 | True |
| person_name_deletions_postal_area | person_name__kana_fold + postal_code__first3 | 1.01 | 81072 | 0.081 | True |
| given_name_postal | given_name__kana_fold + postal_code | 1.01 | 55150 | 0.055 | True |
| address_phone | address__address + phone | 1.01 | 11907 | 0.012 | True |
| address_code_phone | address_code + phone | 1.0 | 21433 | 0.021 | True |
| address_name_initial | address__address + any_name__initial | 1.21 | 233095 | 0.233 | True |
| address_code_name_initial | address_code + any_name__initial | 1.13 | 276371 | 0.276 | True |
| given_name_address_code | given_name__kana_fold + address_code | 1.0 | 34588 | 0.035 | True |
| cif_deletions | customer_id | 1.0 | 6012 | 0.006 | True |
| birth_date | birth_date | 1.72 | 282488 | 0.282 | True |
| given_name_phone | given_name__kana_fold + phone | 1.01 | 54626 | 0.055 | True |
| birth_date_deletions_prefecture | birth_date + prefecture | 1.82 | 313195 | 0.313 | True |

### Potential matches that share no key (train)

| records | potential | window_only |
| --- | --- | --- |
| 30103 | 3036 | 0 |
| 1000000 | 2960 | 0 |

### Patterns without a guaranteed key, at target_rows (label-free)

226 patterns that can reach the threshold at 1,000,000 records have no guaranteed key; the model puts their share of matches at 11.920% at most (Jaro–Winkler implies no key)

| name | company | address | phone | cif | birth | bits | share_of_matches |
| --- | --- | --- | --- | --- | --- | --- | --- |
| missing | JW low | same address | missing | missing | one digit off | 8.45 | 0.008214792308347848 |
| missing | JW low | same address | missing | else | one digit off | 8.42 | 0.00802996422477077 |
| given name | JW low | same address | missing | missing | missing | 9.73 | 0.007840528277182532 |
| given name | JW low | same address | missing | else | missing | 9.7 | 0.007664120918200259 |
| given name | JW low | same address | else | missing | missing | 9.17 | 0.005292774359679308 |
| given name | JW low | same address | else | else | missing | 9.14 | 0.005173689992724428 |
| fold JW high | JW low | missing | exact | missing | missing | 12.59 | 0.004399026064126556 |
| fold JW high | JW low | missing | exact | else | missing | 12.55 | 0.004300050517756151 |
| fold JW high | JW low | same address | missing | missing | missing | 14.79 | 0.00410112027490853 |
| fold JW high | JW low | same address | missing | else | missing | 14.76 | 0.004008847436779663 |

### FINAL's candidates on val

candidates 50,923 · they contain 86.1% of the true pairs the rules missed

| generator | big_o | filled | pairs | completeness_on_targets | seconds |
| --- | --- | --- | --- | --- | --- |
| cif | O(N + P) | O(9,966 + 48) | 7 | 0.0035 | 0.005 |
| sn_company_name | O(N log N + N·w) | O(1,708·log 1,708 + 1,708·4) | 5093 | 0.0915 | 0.003 |
| phone_prefecture | O(N + P) | O(9,966 + 436) | 342 | 0.12 | 0.005 |
| phone_postal_area | O(N + P) | O(9,966 + 286) | 139 | 0.0665 | 0.005 |
| phone_name_initial | O(N + P) | O(9,966 + 747) | 577 | 0.195 | 0.005 |
| sn_person_name | O(N log N + N·w) | O(7,810·log 7,810 + 7,810·4) | 23218 | 0.6005 | 0.004 |
| sn_person_name_reversed | O(N log N + N·w) | O(7,810·log 7,810 + 7,810·4) | 23210 | 0.647 | 0.004 |
| person_name | O(N + P) | O(9,966 + 1,238) | 1088 | 0.521 | 0.005 |
| company_name | O(N + P) | O(9,966 + 223) | 203 | 0.076 | 0.004 |
| company_name_deletions | O(N·L + P) | O(9,966·L + 291) | 270 | 0.0795 | 0.004 |
| person_name_deletions_postal_area | O(N·L + P) | O(9,966·L + 564) | 426 | 0.2105 | 0.011 |
| given_name_postal | O(N + P) | O(9,966 + 387) | 301 | 0.1505 | 0.005 |
| address_phone | O(N + P) | O(9,966 + 94) | 18 | 0.009 | 0.005 |
| address_code_phone | O(N + P) | O(9,966 + 198) | 38 | 0.019 | 0.005 |
| address_name_initial | O(N + P) | O(9,966 + 233) | 158 | 0.072 | 0.005 |
| address_code_name_initial | O(N + P) | O(9,966 + 448) | 293 | 0.136 | 0.005 |
| given_name_address_code | O(N + P) | O(9,966 + 300) | 204 | 0.102 | 0.005 |
| cif_deletions | O(N·L + P) | O(9,966·L + 52) | 11 | 0.0055 | 0.017 |
| birth_date | O(N + P) | O(9,966 + 71) | 66 | 0.02 | 0.004 |
| given_name_phone | O(N + P) | O(9,966 + 387) | 282 | 0.14 | 0.005 |
| birth_date_deletions_prefecture | O(N·L + P) | O(9,966·L + 50) | 48 | 0.01 | 0.003 |

### Evaluation on val

transfer at weight 8.0: CV 0 false of 2368 accepted pairs (rate ≤ 0.13%) · val 0 of 765 (0.00%)

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | 215 | 0 | 0.0971 | 0.0854 | 0.1101 | 0.0138 | 0 | 0 | 3281 |
| probabilistic | 1026 | 0 | 0.4632 | 0.4425 | 0.484 | 0.0029 | 0 | 0 | 1918 |

### Threshold curve on val

| min_match_weight | accepted | pairs_FP | TP | FP | recall | fp_rate_hi |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1280 | 23 | 1524 | 34 | 0.688 | 0.0289 |
| 2 | 1180 | 12 | 1435 | 18 | 0.6479 | 0.0183 |
| 4 | 907 | 1 | 1178 | 1 | 0.5318 | 0.004 |
| 6 | 877 | 0 | 1146 | 0 | 0.5174 | 0.0026 |
| 8 | 765 | 0 | 1026 | 0 | 0.4632 | 0.0029 |
| 10 | 518 | 0 | 766 | 0 | 0.3458 | 0.0039 |
| 12 | 460 | 0 | 704 | 0 | 0.3178 | 0.0042 |
| 14 | 231 | 0 | 459 | 0 | 0.2072 | 0.0065 |
| 16 | 90 | 0 | 308 | 0 | 0.1391 | 0.0097 |

### An accepted true match with a typo

8.07 bits → match probability 0.9963 · found by sn_person_name_reversed+person_name_deletions_postal_area+given_name_postal

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000004168 | ウチダュリカ | nan | 7-29-1 | 8521 | 2020638445481 |
| 0000046774 | オチダユリガ | nan | 東京都足立区綾瀬7-29-1 | 8221 | 4623338689560 |

### An accepted true match with a typo: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.4 |
| name | given name | 8.19 |
| company | missing | 0.0 |
| address | same postal | 10.22 |
| phone | one digit off | 4.1 |
| cif | else | -0.03 |
| birth | missing | 0.0 |

### The rejected non-match closest to the threshold

5.46 bits → match probability 0.9777 · found by phone_prefecture+phone_name_initial

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000004185 | タカハシユカ | nan | 北海道名寄市東三条南2-15-21 | 2887 | 8900662733639 |
| 0000044064 | タカハジトモカ | nan | 北海道登別市札内町12-22 | 2887 | 3517719009256 |

### The rejected non-match closest to the threshold: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.4 |
| name | fold JW low | 5.03 |
| company | missing | 0.0 |
| address | same prefecture | 3.71 |
| phone | exact | 11.15 |
| cif | else | -0.03 |
| birth | missing | 0.0 |

### FINAL on train, val and test

| dataset | records | recall_before | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | accepted | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30103 | 0.1074 | 3157 | 0 | 0.4562 | 0.4445 | 0.468 | 0.0009 | 0 | 0 | 6042 | 2267 | 2.0 |
| val | 9966 | 0.0971 | 1026 | 0 | 0.4632 | 0.4425 | 0.484 | 0.0029 | 0 | 0 | 1918 | 765 | 0.9 |
| test | 10047 | 0.0971 | 1073 | 0 | 0.4591 | 0.439 | 0.4794 | 0.0028 | 0 | 0 | 1991 | 798 | 6.7 |

### Configurations scored on test, per stage

| family | configs_on_test |
| --- | --- |
| deterministic | 1 |
| probabilistic | 1 |
