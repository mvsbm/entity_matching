# Choosing the configuration

Written by `scripts/choose.py` from `config/pipeline.toml` and `config/experiments.py`, on the labelled synthetic datasets. Test is scored once per stage, at the end of each.

## Stage 1: rules

### Design analysis on train

| keys | same_entity_agree | different_entity_pairs |
| --- | --- | --- |
| address | 0.4154 | 7724 |
| address_code | 0.5636 | 10671 |
| company_name | 0.0677 | 180 |
| customer_id | 0.452 | 0 |
| full_name | 0.4253 | 230 |
| given_name | 0.4804 | 117118 |
| person_name | 0.4491 | 251 |
| phone | 0.7452 | 45506 |
| postal_code | 0.7078 | 41868 |
| customer_id + full_name | 0.1916 | 0 |
| customer_id + company_name | 0.0334 | 0 |
| customer_id + phone | 0.3318 | 0 |
| full_name + address_code + phone | 0.1988 | 0 |
| company_name + address_code + phone | 0.018 | 0 |
| address_code + phone | 0.4285 | 0 |
| phone + address__address | 0.4555 | 0 |
| person_name + address_code | 0.2664 | 0 |
| phone + postal_code | 0.5359 | 4 |
| given_name + address_code + phone | 0.2237 | 0 |

### A/B on val, paired against the rules as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | P | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | 0.6924 | 0 | 0.0019 | 7 | 0 | 0.0156 | 0 | 0 | 7654 | 0.4 |
| fold_exact | 0.6722 | 0 | 0.002 | 0 | 38 | 0.0 | 0 | 0 | 4726 | 0.4 |
| raw_jaro_winkler | 0.6682 | 0 | 0.002 | 1 | 48 | 0.0 | 0 | 0 | 7654 | 0.4 |
| constrained_given_name | 0.595 | 0 | 0.0023 | 0 | 210 | 0.0 | 0 | 0 | 7654 | 0.7 |
| optuna_comparators | 0.6951 | 0 | 0.0019 | 13 | 0 | 0.0002 | 0 | 0 | 13317 | 0.5 |
| f2_address_exact | 0.6893 | 0 | 0.0019 | 0 | 0 | 1.0 | 0 | 0 | 7654 | 0.4 |
| f2_address_prefix | 0.6893 | 0 | 0.0019 | 0 | 0 | 1.0 | 0 | 0 | 7654 | 0.4 |

### Decisions

FINAL fuzzy comparators: {'person_name': 'levenshtein 2 kana_fold', 'company_name': 'jaccard 0.77', 'address': 'jaro_winkler 0.91 address', 'phone': 'damerau_levenshtein 1'} · connected_components

| change | kind | adopted | train_TP_gains | train_TP_losses | train_p | train_FP_added | train_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | better | True | 15 | 0 | 0.0001 | 0 | 0 | 7 | 0 | 0 |
| fold_exact | cheaper | False | 0 | 108 | 0.0 | 0 | 0 | 0 | 45 | 0 |
| optuna_comparators | better | True | 19 | 1 | 0.0 | 0 | 0 | 6 | 0 | 0 |
| f2_address_exact | cheaper | False | 0 | 8 | 0.0078 | 0 | 0 | 0 | 3 | 0 |
| f2_address_prefix | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |

### Cost of FINAL: every rule now and at target_rows

train: N = 30,147 · total P = 24,940 → 943,594 at 1,000,000 rows

| stage | rule | keys | big_o | filled | P | largest_block | est_fuzzy_ms | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | X1_CIF_PERSON_NAME | customer_id + full_name | O(N + P) | O(30,147 + 1,329) | 1329 | 4 | 0.0 | 1.0 | 44083 | 0.044 | True |
| exact | X2_CIF_COMPANY_NAME | customer_id + company_name | O(N + P) | O(30,147 + 232) | 232 | 4 | 0.0 | 1.0 | 7695 | 0.008 | True |
| exact | X3_CIF_PHONE | customer_id + phone | O(N + P) | O(30,147 + 2,302) | 2302 | 4 | 0.0 | 1.0 | 76359 | 0.076 | True |
| exact | X4_PERSON_NAME_ADDRCD_PHONE | full_name + address_code + phone | O(N + P) | O(30,147 + 1,379) | 1379 | 4 | 0.0 | 1.0 | 45742 | 0.046 | True |
| exact | X5_COMPANY_NAME_ADDRCD_PHONE | company_name + address_code + phone | O(N + P) | O(30,147 + 125) | 125 | 3 | 0.0 | 1.0 | 4146 | 0.004 | True |
| fuzzy | F1_NAME~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(30,147 + 2,973·46) | 2973 | 4 | 0.54 | 1.0 | 98616 | 0.099 | True |
| fuzzy | F2_NAME~_ADDRESS~_PHONE | phone + address__address_first3 | O(N + P·(m·n + m·n)) | O(30,147 + 3,369·205) | 3369 | 4 | 1.34 | 1.03 | 223804 | 0.224 | True |
| fuzzy | F3_NAME~_CIF | customer_id | O(N + P·(m·n)) | O(30,147 + 3,136·46) | 3136 | 4 | 0.57 | 1.0 | 104023 | 0.104 | True |
| fuzzy | F4_NAME_ADDRCD_PHONE~ | person_name + address_code | O(N + P·(m·n)) | O(30,147 + 1,848·16) | 1848 | 4 | 0.26 | 1.0 | 61299 | 0.061 | True |
| fuzzy | F5_COMPANY~_PHONE_POSTAL | phone + postal_code | O(N + P·(m+n)) | O(30,147 + 3,722·34) | 3722 | 4 | 12.08 | 1.0 | 127730 | 0.128 | True |
| fuzzy | F6_COMPANY~_ADDRCD_PHONE | address_code + phone | O(N + P·(m+n)) | O(30,147 + 2,973·34) | 2973 | 4 | 9.65 | 1.0 | 98616 | 0.099 | True |
| fuzzy | F7_GIVEN_ADDRCD_PHONE | given_name + address_code + phone | O(N + P) | O(30,147 + 1,552) | 1552 | 4 | 0.0 | 1.0 | 51481 | 0.051 | True |

### Evaluation on val

rules: Σ ops ≈ 499,331 (see big_o per rule) · normalize: O(N·L), N = 10,002 · cluster: O((N + E)·d), N = 10,002, E = 1,496 · evaluate: O(N) · total 0.5s · false-positive pairs: 0

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | 1162 | 0 | 0.5218 | 0.501 | 0.5425 | 0.0026 | 0 | 0 | 1713 |
| fuzzy | 1548 | 0 | 0.6951 | 0.6757 | 0.7139 | 0.0019 | 0 | 0 | 1083 |

### Rules on val

| rule | P | actual_ms | edges | edge_FP | kept | kept_FP |
| --- | --- | --- | --- | --- | --- | --- |
| X1_CIF_PERSON_NAME | 438 | 23.2 | 438 | 0 | 438 | 0 |
| X2_CIF_COMPANY_NAME | 64 | 21.6 | 64 | 0 | 64 | 0 |
| X3_CIF_PHONE | 772 | 24.3 | 401 | 0 | 401 | 0 |
| X4_PERSON_NAME_ADDRCD_PHONE | 400 | 24.8 | 216 | 0 | 216 | 0 |
| X5_COMPANY_NAME_ADDRCD_PHONE | 25 | 24.0 | 15 | 0 | 15 | 0 |
| F1_NAME~_ADDRCD_PHONE | 881 | 27.0 | 157 | 0 | 149 | 0 |
| F2_NAME~_ADDRESS~_PHONE | 1032 | 31.2 | 97 | 0 | 93 | 0 |
| F3_NAME~_CIF | 1041 | 26.9 | 56 | 0 | 54 | 0 |
| F4_NAME_ADDRCD_PHONE~ | 563 | 27.5 | 27 | 0 | 26 | 0 |
| F5_COMPANY~_PHONE_POSTAL | 1149 | 24.7 | 11 | 0 | 11 | 0 |
| F6_COMPANY~_ADDRCD_PHONE | 881 | 25.3 | 1 | 0 | 1 | 0 |
| F7_GIVEN_ADDRCD_PHONE | 469 | 27.8 | 30 | 0 | 28 | 0 |

### FINAL on train, val and test

| dataset | records | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30147 | 4803 | 0 | 0.6923 | 0.6813 | 0.703 | 0.0006 | 0 | 0 | 3380 | 0.9 |
| val | 10002 | 1548 | 0 | 0.6951 | 0.6757 | 0.7139 | 0.0019 | 0 | 0 | 1083 | 0.5 |
| test | 10066 | 1676 | 0 | 0.7111 | 0.6924 | 0.729 | 0.0018 | 0 | 0 | 1032 | 0.5 |

## Stage 2: Fellegi–Sunter

### Candidates on train: reach and cost of every generator

train: 2,135 true pairs missed by the rules

| generator | big_o | filled | pairs | seconds | finds | cumulative | different_entity_pairs | alpha | projected_pairs | per_record |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phone | O(N + P) | O(30,147 + 50,676) | 43054 | 0.008 | 0.5035 | 0.5035 | 41979 | 1.9 | 50243434 | 50.243 |
| address | O(N + P) | O(30,147 + 15,675) | 11534 | 0.006 | 0.377 | 0.7607 | 10729 | 1.73 | 12796633 | 12.797 |
| address_code | O(N + P) | O(30,147 + 14,581) | 10689 | 0.005 | 0.3429 | 0.8061 | 9957 | 1.73 | 11871395 | 11.871 |
| cif | O(N + P) | O(30,147 + 3,136) | 230 | 0.004 | 0.1077 | 0.8478 | 0 | 1.0 | 104023 | 0.104 |
| person_name | O(N + P) | O(30,147 + 4,754) | 1228 | 0.004 | 0.4023 | 0.9124 | 369 | 1.08 | 579224 | 0.579 |
| company_name | O(N + P) | O(30,147 + 946) | 547 | 0.003 | 0.0806 | 0.9377 | 375 | 1.41 | 443305 | 0.443 |
| sn_person_name | O(N log N + N·w) | O(23,848·log 23,848 + 23,848·4) | 63338 | 0.009 | 0.4197 | 0.94 | 62442 | 1.0 | 3000000 | 3.0 |
| sn_company_name | O(N log N + N·w) | O(5,009·log 5,009 + 5,009·4) | 14243 | 0.004 | 0.082 | 0.9405 | 14068 | 1.0 | 3000000 | 3.0 |
| tfidf_person_name | O(N·L + U·N·q) | O(23,848·L + 21,967·23,848·14) | 22865 | 2.652 | 0.4422 | 0.9447 | 21921 | 2.0 | 1000000000000 | 1000000.0 |
| tfidf_company_name | O(N·L + U·N·q) | O(5,009·L + 21,967·5,009·18) | 2416 | 0.277 | 0.0829 | 0.9457 | 2239 | 2.0 | 1000000000000 | 1000000.0 |
| phone_prefecture | O(N + P) | O(30,147 + 3,208) | 1211 | 0.005 | 0.1864 | 0.9457 | 813 | 1.27 | 1046585 | 1.047 |
| phone_postal_area | O(N + P) | O(30,147 + 3,840) | 633 | 0.004 | 0.2674 | 0.9457 | 62 | 1.02 | 193540 | 0.194 |
| phone_name_initial | O(N + P) | O(30,147 + 5,744) | 2134 | 0.005 | 0.2642 | 0.9457 | 1570 | 1.3 | 2026059 | 2.026 |
| sn_person_name_reversed | O(N log N + N·w) | O(23,848·log 23,848 + 23,848·4) | 63317 | 0.011 | 0.4899 | 0.9499 | 62271 | 1.0 | 3000000 | 3.0 |
| company_name_deletions | O(N·L + P) | O(30,147·L + 1,501) | 1082 | 0.024 | 0.0834 | 0.9499 | 904 | 1.62 | 1039052 | 1.039 |
| person_name_deletions_postal_area | O(N·L + P) | O(30,147·L + 3,559) | 567 | 0.06 | 0.2571 | 0.9499 | 18 | 1.01 | 143666 | 0.144 |
| given_name_postal | O(N + P) | O(30,147 + 2,939) | 519 | 0.005 | 0.2365 | 0.9513 | 14 | 1.0 | 112429 | 0.112 |
| address_phone | O(N + P) | O(30,147 + 3,160) | 256 | 0.006 | 0.1199 | 0.9513 | 0 | 1.0 | 104819 | 0.105 |
| address_code_phone | O(N + P) | O(30,147 + 2,973) | 215 | 0.004 | 0.1007 | 0.9513 | 0 | 1.0 | 98616 | 0.099 |
| address_name_initial | O(N + P) | O(30,147 + 3,636) | 671 | 0.005 | 0.14 | 0.9513 | 372 | 1.11 | 548542 | 0.549 |
| address_code_name_initial | O(N + P) | O(30,147 + 3,444) | 658 | 0.004 | 0.1321 | 0.9513 | 376 | 1.11 | 536838 | 0.537 |
| given_name_address_code | O(N + P) | O(30,147 + 2,327) | 225 | 0.004 | 0.1049 | 0.9513 | 1 | 1.0 | 78255 | 0.078 |

### Training on train: EM against labels

cost: u O(max_pairs·C) = O(10,000,000·5) · EM O(iterations·P·C), P = 66,351 · em: fitted in 9.1s · no estimate: u - · m - · labels: fitted in 0.2s · no estimate: u - · m -

| comparison | level | em m | em u | em weight | labels m | labels u | labels weight |
| --- | --- | --- | --- | --- | --- | --- | --- |
| name | exact | 0.572 | 0.0 | 15.582 | 0.571 | 0.0 | 15.579 |
| name | fold exact | 0.227 | 0.0 | 15.49 | 0.228 | 0.0 | 15.496 |
| name | fold JW high | 0.053 | 0.0 | 10.609 | 0.052 | 0.0 | 10.59 |
| name | given name | 0.109 | 0.0 | 7.807 | 0.108 | 0.0 | 7.787 |
| name | fold JW low | 0.004 | 0.0 | 3.428 | 0.004 | 0.0 | 3.626 |
| name | else | 0.035 | 0.999 | -4.828 | 0.037 | 0.999 | -4.748 |
| company | exact | 0.654 | 0.0 | 13.126 | 0.593 | 0.0 | 12.984 |
| company | JW high | 0.012 | 0.0 | 9.511 | 0.01 | 0.0 | 9.194 |
| company | JW low | 0.003 | 0.0 | 4.452 | 0.003 | 0.0 | 4.439 |
| company | else | 0.331 | 1.0 | -1.596 | 0.395 | 1.0 | -1.341 |
| address | same address | 0.708 | 0.0 | 14.015 | 0.708 | 0.0 | 14.014 |
| address | address close | 0.004 | 0.0 | 8.892 | 0.003 | 0.0 | 8.595 |
| address | same postal | 0.113 | 0.0 | 10.823 | 0.114 | 0.0 | 10.839 |
| address | else | 0.175 | 1.0 | -2.514 | 0.175 | 1.0 | -2.515 |
| phone | exact | 0.746 | 0.0 | 12.54 | 0.745 | 0.0 | 12.539 |
| phone | one digit off | 0.081 | 0.004 | 4.496 | 0.081 | 0.004 | 4.496 |
| phone | else | 0.173 | 0.996 | -2.525 | 0.174 | 0.996 | -2.518 |
| cif | exact | 0.464 | 0.0 | 15.92 | 0.472 | 0.0 | 15.942 |
| cif | else | 0.536 | 1.0 | -0.901 | 0.528 | 1.0 | -0.92 |

### Threshold: chosen on cross-validated train

3-fold CV in 32.2s → min_match_weight = 8.0

| min_match_weight | accepted | pairs_FP | stage_fp_rate_hi | TP | FP | recall | recall_lo | recall_hi | eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 1657 | 15 | 0.0139 | 6497 | 18 | 0.9364 | 0.9305 | 0.9419 | False |
| 2 | 1609 | 14 | 0.0136 | 6450 | 17 | 0.9297 | 0.9234 | 0.9354 | False |
| 4 | 1507 | 1 | 0.0031 | 6362 | 1 | 0.917 | 0.9103 | 0.9232 | False |
| 6 | 1392 | 0 | 0.0021 | 6254 | 0 | 0.9014 | 0.8942 | 0.9082 | True |
| 8 | 1241 | 0 | 0.0024 | 6107 | 0 | 0.8802 | 0.8724 | 0.8877 | True |
| 10 | 921 | 0 | 0.0032 | 5781 | 0 | 0.8332 | 0.8243 | 0.8418 | True |
| 12 | 490 | 0 | 0.0061 | 5328 | 0 | 0.7679 | 0.7579 | 0.7777 | True |
| 14 | 454 | 0 | 0.0066 | 5287 | 0 | 0.762 | 0.7519 | 0.7719 | True |
| 16 | 388 | 0 | 0.0077 | 5221 | 0 | 0.7525 | 0.7422 | 0.7625 | True |

### A/B on val, paired against the tuned configuration as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | candidates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| labels | 0.894 | 0 | 0.0015 | 0 | 0 | 1.0 | 0 | 0 | 33895 |
| no_term_frequency | 0.8949 | 0 | 0.0015 | 2 | 0 | 0.5 | 0 | 0 | 33895 |
| exact_keys_only | 0.894 | 0 | 0.0015 | 0 | 0 | 1.0 | 0 | 0 | 6722 |
| levenshtein_names | 0.8954 | 0 | 0.0015 | 3 | 0 | 0.25 | 0 | 0 | 33895 |
| constrained_given_name | 0.7786 | 0 | 0.0017 | 0 | 257 | 0.0 | 0 | 0 | 33895 |
| optuna_suggestion | 0.8954 | 0 | 0.0015 | 5 | 2 | 0.4531 | 0 | 0 | 14277 |
| u_from_1e6_pairs | 0.885 | 0 | 0.0015 | 3 | 23 | 0.0001 | 0 | 0 | 33895 |
| compound_phone_keys | 0.894 | 0 | 0.0015 | 0 | 0 | 1.0 | 0 | 0 | 29465 |
| sorted_names_for_tfidf | 0.894 | 0 | 0.0015 | 0 | 0 | 1.0 | 0 | 0 | 52459 |
| name_keys | 0.894 | 0 | 0.0015 | 0 | 0 | 1.0 | 0 | 0 | 33925 |
| bounded_address_keys | 0.8931 | 0 | 0.0015 | 0 | 2 | 0.5 | 0 | 0 | 32578 |
| no_sorted_windows | 0.894 | 0 | 0.0015 | 0 | 0 | 1.0 | 0 | 0 | 9965 |
| bridge_rule_clusters | 0.8958 | 0 | 0.0015 | 4 | 0 | 0.125 | 0 | 0 | 36326 |
| u_from_scored_file | 0.85 | 0 | 0.0016 | 0 | 98 | 0.0 | 0 | 0 | 33895 |
| u_exact_by_counts | 0.89 | 0 | 0.0015 | 0 | 9 | 0.0039 | 0 | 0 | 33895 |

### Decisions

FINAL: 17 generators · term frequency off · m by em · min_match_weight 6.0 · connected_components

| change | kind | adopted | cv_TP_gains | cv_TP_losses | cv_p | cv_FP_added | cv_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_term_frequency | better | True | 15 | 0 | 0.0001 | 0 | 0 | 2 | 0 | 0 |
| exact_keys_only | cheaper | False | 0 | 3 | 0.25 | 0 | 0 | 0 | 0 | 0 |
| optuna_suggestion | better | True | 172 | 0 | 0.0 | 0 | 0 | 43 | 0 | 0 |
| u_from_1e6_pairs | cheaper | False | 9 | 26 | 0.006 | 0 | 0 | 0 | 1 | 0 |
| compound_phone_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| sorted_names_for_tfidf | cheaper | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| name_keys | safer | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| bounded_address_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| no_sorted_windows | cheaper | False | 0 | 3 | 0.25 | 0 | 0 | 0 | 1 | 0 |
| bridge_rule_clusters | better | True | 12 | 0 | 0.0005 | 0 | 0 | 4 | 0 | 0 |
| u_from_scored_file | chosen | True | 63 | 0 | 0.0 | 0 | 0 | 20 | 0 | 0 |
| u_exact_by_counts | chosen | True | 0 | 122 | 0.0 | 0 | 0 | 0 | 27 | 0 |

### Will it scale? FINAL's generators at target_rows

| key | columns | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- |
| cif | customer_id | 1.0 | 104023 | 0.104 | True |
| sn_company_name | company_name__nfkc_strip_legal_form_kana_fold | 1.0 | 3000000 | 3.0 | True |
| phone_prefecture | phone + prefecture | 1.27 | 1046585 | 1.047 | True |
| phone_postal_area | phone + postal_code__first3 | 1.02 | 193540 | 0.194 | True |
| phone_name_initial | phone + any_name__initial | 1.3 | 2026059 | 2.026 | True |
| sn_person_name | person_name__kana_fold | 1.0 | 3000000 | 3.0 | True |
| sn_person_name_reversed | person_name__kana_fold_reverse | 1.0 | 3000000 | 3.0 | True |
| person_name | person_name__kana_fold | 1.08 | 579224 | 0.579 | True |
| company_name | company_name__nfkc_strip_legal_form_kana_fold | 1.41 | 443305 | 0.443 | True |
| company_name_deletions | company_name__nfkc_strip_legal_form_kana_fold | 1.62 | 1039052 | 1.039 | True |
| person_name_deletions_postal_area | person_name__kana_fold + postal_code__first3 | 1.01 | 143666 | 0.144 | True |
| given_name_postal | given_name__kana_fold + postal_code | 1.0 | 112429 | 0.112 | True |
| address_phone | address__address + phone | 1.0 | 104819 | 0.105 | True |
| address_code_phone | address_code + phone | 1.0 | 98616 | 0.099 | True |
| address_name_initial | address__address + any_name__initial | 1.11 | 548542 | 0.549 | True |
| address_code_name_initial | address_code + any_name__initial | 1.11 | 536838 | 0.537 | True |
| given_name_address_code | given_name__kana_fold + address_code | 1.0 | 78255 | 0.078 | True |

### Potential matches that share no key (train)

| records | potential | window_only |
| --- | --- | --- |
| 30147 | 6116 | 0 |
| 1000000 | 6020 | 0 |

### Patterns without a guaranteed key, at target_rows (label-free)

68 patterns that can reach the threshold at 1,000,000 records have no guaranteed key; the model puts their share of matches at 0.581% at most (Jaro–Winkler implies no key)

| name | company | address | phone | cif | bits | share_of_matches |
| --- | --- | --- | --- | --- | --- | --- |
| fold JW high | missing | same address | one digit off | missing | 9.58 | 0.0015423662303841853 |
| fold JW high | missing | same address | one digit off | else | 8.68 | 0.0008276869425310162 |
| fold JW high | else | same address | one digit off | missing | 7.98 | 0.0005090601490760376 |
| given name | missing | address close | exact | missing | 7.86 | 0.00032631273373735895 |
| fold JW high | else | same address | one digit off | else | 7.09 | 0.0002731792424216766 |
| fold JW high | JW low | missing | exact | missing | 7.92 | 0.00025885097332507313 |
| fold JW high | JW low | same address | missing | missing | 9.3 | 0.00024607856553235526 |
| fold JW high | missing | same postal | one digit off | missing | 6.32 | 0.00024559197544601154 |
| given name | missing | address close | exact | else | 6.96 | 0.00017511067318216455 |
| given name | JW high | missing | exact | missing | 6.49 | 0.00017156403990283532 |

### FINAL's candidates on val

candidates 49,987 · they contain 88.4% of the true pairs the rules missed

| generator | big_o | filled | pairs | completeness_on_targets | seconds |
| --- | --- | --- | --- | --- | --- |
| cif | O(N + P) | O(10,002 + 1,041) | 81 | 0.1193 | 0.001 |
| sn_company_name | O(N log N + N·w) | O(1,640·log 1,640 + 1,640·4) | 4810 | 0.0972 | 0.002 |
| phone_prefecture | O(N + P) | O(10,002 + 819) | 196 | 0.1782 | 0.001 |
| phone_postal_area | O(N + P) | O(10,002 + 1,181) | 166 | 0.2401 | 0.001 |
| phone_name_initial | O(N + P) | O(10,002 + 1,468) | 370 | 0.2651 | 0.002 |
| sn_person_name | O(N log N + N·w) | O(7,909·log 7,909 + 7,909·4) | 22543 | 0.4359 | 0.004 |
| sn_person_name_reversed | O(N log N + N·w) | O(7,909·log 7,909 + 7,909·4) | 22477 | 0.5272 | 0.004 |
| person_name | O(N + P) | O(10,002 + 1,450) | 334 | 0.4197 | 0.001 |
| company_name | O(N + P) | O(10,002 + 217) | 116 | 0.0972 | 0.001 |
| company_name_deletions | O(N·L + P) | O(10,002·L + 273) | 169 | 0.1016 | 0.005 |
| person_name_deletions_postal_area | O(N·L + P) | O(10,002·L + 1,160) | 191 | 0.2813 | 0.013 |
| given_name_postal | O(N + P) | O(10,002 + 941) | 180 | 0.2622 | 0.002 |
| address_phone | O(N + P) | O(10,002 + 971) | 73 | 0.1075 | 0.002 |
| address_code_phone | O(N + P) | O(10,002 + 881) | 53 | 0.0781 | 0.001 |
| address_name_initial | O(N + P) | O(10,002 + 1,054) | 150 | 0.1576 | 0.002 |
| address_code_name_initial | O(N + P) | O(10,002 + 975) | 138 | 0.1399 | 0.001 |
| given_name_address_code | O(N + P) | O(10,002 + 730) | 81 | 0.1193 | 0.001 |

### Evaluation on val

transfer at weight 6.0: CV 0 false of 1386 accepted pairs (rate ≤ 0.22%) · val 0 of 460 (0.00%)

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | 1548 | 0 | 0.6951 | 0.6757 | 0.7139 | 0.0019 | 0 | 0 | 1083 |
| probabilistic | 2033 | 0 | 0.9129 | 0.9005 | 0.9239 | 0.0015 | 0 | 0 | 332 |

### Threshold curve on val

| min_match_weight | accepted | pairs_FP | TP | FP | recall | fp_rate_hi |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 528 | 4 | 2088 | 5 | 0.9376 | 0.005 |
| 2 | 505 | 0 | 2074 | 0 | 0.9313 | 0.0014 |
| 4 | 487 | 0 | 2060 | 0 | 0.925 | 0.0015 |
| 6 | 460 | 0 | 2033 | 0 | 0.9129 | 0.0015 |
| 8 | 394 | 0 | 1970 | 0 | 0.8846 | 0.0015 |
| 10 | 213 | 0 | 1779 | 0 | 0.7988 | 0.0017 |
| 12 | 132 | 0 | 1692 | 0 | 0.7598 | 0.0018 |
| 14 | 119 | 0 | 1680 | 0 | 0.7544 | 0.0018 |
| 16 | 100 | 0 | 1659 | 0 | 0.7449 | 0.0018 |

### An accepted true match with a typo

6.98 bits → match probability 0.9921 · found by sn_person_name_reversed+person_name_deletions_postal_area+given_name_postal+address_name_initial+address_code_name_initial+given_name_address_code

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000018390 | サワベキチヘイ | nan | 福岡県北九州市八幡東区景勝町10-13 | 3734 | 1037183236105 |
| 0000037400 | サベキチヘイ | nan | 福岡県北九州市八幡東区景勝町10-13 | 0945 | 6765670361201 |

### An accepted true match with a typo: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.98 |
| name | fold JW high | 11.84 |
| company | missing | 0.0 |
| address | same address | 13.52 |
| phone | else | -2.51 |
| cif | else | -0.9 |

### The rejected non-match closest to the threshold

0.24 bits → match probability 0.5418 · found by phone_name_initial

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000011439 | ヤマモトサオリ | nan | 茨城県土浦市木田余東台4-12-27 | 1797 | 2052586092547 |
| 0000029840 | ヤマモトカナコ | nan | nan | 1797 | 2963638209010 |

### The rejected non-match closest to the threshold: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.98 |
| name | fold JW low | 3.66 |
| company | missing | 0.0 |
| address | missing | 0.0 |
| phone | exact | 12.45 |
| cif | else | -0.9 |

### FINAL on train, val and test

| dataset | records | recall_before | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | accepted | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30147 | 0.6923 | 6224 | 2 | 0.8971 | 0.8897 | 0.904 | 0.001 | 2 | 1 | 1181 | 1365 | 9.4 |
| val | 10002 | 0.6951 | 2033 | 0 | 0.9129 | 0.9005 | 0.9239 | 0.0015 | 0 | 0 | 332 | 460 | 0.6 |
| test | 10066 | 0.7111 | 2120 | 0 | 0.8994 | 0.8866 | 0.9109 | 0.0014 | 0 | 0 | 388 | 420 | 8.8 |

### Configurations scored on test, per stage

| family | configs_on_test |
| --- | --- |
| deterministic | 1 |
| probabilistic | 1 |
