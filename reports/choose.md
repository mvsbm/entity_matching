# Choosing the configuration

Written by `scripts/choose.py` from `config/pipeline.toml` and `config/experiments.py`, on the labelled synthetic datasets. Test is scored once per stage, at the end of each.

## Stage 1: rules

### Design analysis on train

| keys | same_entity_agree | different_entity_pairs |
| --- | --- | --- |
| address | 0.2015 | 3452 |
| address_code | 0.2676 | 4668 |
| company_name | 0.016 | 37 |
| customer_id | 0.022 | 0 |
| full_name | 0.1919 | 116 |
| given_name | 0.326 | 84601 |
| person_name | 0.2027 | 129 |
| phone | 0.3381 | 45413 |
| postal_code | 0.3496 | 33851 |
| customer_id + full_name | 0.0058 | 0 |
| customer_id + company_name | 0.0004 | 0 |
| customer_id + phone | 0.0078 | 0 |
| full_name + address_code + phone | 0.0161 | 0 |
| company_name + address_code + phone | 0.0013 | 0 |
| address_code + phone | 0.0867 | 0 |
| phone + address__address | 0.0962 | 0 |
| person_name + address_code | 0.0589 | 0 |
| phone + postal_code | 0.1174 | 5 |
| given_name + address_code + phone | 0.032 | 0 |

### A/B on val, paired against the rules as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | P | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | 0.1234 | 0 | 0.0108 | 4 | 3 | 1.0 | 0 | 0 | 1290 | 0.4 |
| fold_exact | 0.1055 | 0 | 0.0126 | 0 | 39 | 0.0 | 0 | 0 | 585 | 0.4 |
| raw_jaro_winkler | 0.0899 | 0 | 0.0148 | 0 | 74 | 0.0 | 0 | 0 | 1290 | 0.4 |
| constrained_given_name | 0.0867 | 0 | 0.0153 | 0 | 81 | 0.0 | 0 | 0 | 1290 | 0.7 |
| optuna_comparators | 0.1234 | 0 | 0.0108 | 9 | 8 | 1.0 | 0 | 0 | 6892 | 0.5 |
| f2_address_exact | 0.1229 | 0 | 0.0108 | 0 | 0 | 1.0 | 0 | 0 | 1290 | 0.4 |
| f2_address_prefix | 0.1229 | 0 | 0.0108 | 0 | 0 | 1.0 | 0 | 0 | 1290 | 0.4 |

### Decisions

FINAL fuzzy comparators: {'person_name': 'jaro_winkler 0.92 kana_fold', 'company_name': 'jaro_winkler 0.92 nfkc+strip_legal_form+kana_fold', 'address': 'exact  address', 'phone': 'hamming 1'} · connected_components

| change | kind | adopted | train_TP_gains | train_TP_losses | train_p | train_FP_added | train_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | better | False | 13 | 6 | 0.1671 | 0 | 0 | 4 | 3 | 0 |
| fold_exact | cheaper | False | 0 | 91 | 0.0 | 0 | 0 | 0 | 39 | 0 |
| optuna_comparators | better | False | 35 | 25 | 0.2451 | 0 | 0 | 9 | 8 | 0 |
| f2_address_exact | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| f2_address_prefix | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |

### Cost of FINAL: every rule now and at target_rows

train: N = 30,098 · total P = 3,694 → 128,080 at 1,000,000 rows

| stage | rule | keys | big_o | filled | P | largest_block | est_fuzzy_ms | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | X1_CIF_PERSON_NAME | customer_id + full_name | O(N + P) | O(30,098 + 40) | 40 | 2 | 0.0 | 1.0 | 1328 | 0.001 | True |
| exact | X2_CIF_COMPANY_NAME | customer_id + company_name | O(N + P) | O(30,098 + 3) | 3 | 2 | 0.0 | 1.0 | 99 | 0.0 | True |
| exact | X3_CIF_PHONE | customer_id + phone | O(N + P) | O(30,098 + 54) | 54 | 2 | 0.0 | 1.0 | 1794 | 0.002 | True |
| exact | X4_PERSON_NAME_ADDRCD_PHONE | full_name + address_code + phone | O(N + P) | O(30,098 + 112) | 112 | 3 | 0.0 | 1.0 | 3721 | 0.004 | True |
| exact | X5_COMPANY_NAME_ADDRCD_PHONE | company_name + address_code + phone | O(N + P) | O(30,098 + 9) | 9 | 2 | 0.0 | 1.0 | 299 | 0.0 | True |
| fuzzy | F1_NAME~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(30,098 + 602·45) | 602 | 3 | 0.1 | 1.0 | 20001 | 0.02 | True |
| fuzzy | F2_NAME~_ADDRESS~_PHONE | phone + address__address + address__address_first3 | O(N + P·(m·n)) | O(30,098 + 668·45) | 668 | 3 | 0.11 | 1.0 | 22194 | 0.022 | True |
| fuzzy | F3_NAME~_CIF | customer_id | O(N + P·(m·n)) | O(30,098 + 153·45) | 153 | 2 | 0.03 | 1.0 | 5083 | 0.005 | True |
| fuzzy | F4_NAME_ADDRCD_PHONE~ | person_name + address_code | O(N + P·(n)) | O(30,098 + 409·4) | 409 | 3 | 0.04 | 1.0 | 13588 | 0.014 | True |
| fuzzy | F5_COMPANY~_PHONE_POSTAL | phone + postal_code | O(N + P·(m·n)) | O(30,098 + 820·90) | 820 | 3 | 0.15 | 1.01 | 32597 | 0.033 | True |
| fuzzy | F6_COMPANY~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(30,098 + 602·90) | 602 | 3 | 0.11 | 1.0 | 20001 | 0.02 | True |
| fuzzy | F7_GIVEN_ADDRCD_PHONE | given_name + address_code + phone | O(N + P) | O(30,098 + 222) | 222 | 3 | 0.0 | 1.0 | 7375 | 0.007 | True |

### Evaluation on val

rules: Σ ops ≈ 191,343 (see big_o per rule) · normalize: O(N·L), N = 9,995 · cluster: O((N + E)·d), N = 9,995, E = 272 · evaluate: O(N) · total 0.5s · false-positive pairs: 0

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | 60 | 0 | 0.0268 | 0.0209 | 0.0344 | 0.0487 | 0 | 0 | 3641 |
| fuzzy | 275 | 0 | 0.1229 | 0.11 | 0.1372 | 0.0108 | 0 | 0 | 3241 |

### Rules on val

| rule | P | actual_ms | edges | edge_FP | kept | kept_FP |
| --- | --- | --- | --- | --- | --- | --- |
| X1_CIF_PERSON_NAME | 8 | 22.5 | 8 | 0 | 8 | 0 |
| X2_CIF_COMPANY_NAME | 2 | 21.7 | 2 | 0 | 2 | 0 |
| X3_CIF_PHONE | 15 | 21.5 | 10 | 0 | 10 | 0 |
| X4_PERSON_NAME_ADDRCD_PHONE | 40 | 22.3 | 39 | 0 | 39 | 0 |
| X5_COMPANY_NAME_ADDRCD_PHONE | 1 | 22.4 | 1 | 0 | 1 | 0 |
| F1_NAME~_ADDRCD_PHONE | 227 | 25.1 | 118 | 0 | 118 | 0 |
| F2_NAME~_ADDRESS~_PHONE | 232 | 25.5 | 37 | 0 | 37 | 0 |
| F3_NAME~_CIF | 52 | 23.8 | 21 | 0 | 21 | 0 |
| F4_NAME_ADDRCD_PHONE~ | 127 | 24.1 | 15 | 0 | 15 | 0 |
| F5_COMPANY~_PHONE_POSTAL | 289 | 24.5 | 11 | 0 | 11 | 0 |
| F6_COMPANY~_ADDRCD_PHONE | 227 | 24.2 | 2 | 0 | 2 | 0 |
| F7_GIVEN_ADDRCD_PHONE | 70 | 22.6 | 8 | 0 | 8 | 0 |

### FINAL on train, val and test

| dataset | records | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30098 | 750 | 0 | 0.108 | 0.101 | 0.1156 | 0.004 | 0 | 0 | 9999 | 0.8 |
| val | 9995 | 275 | 0 | 0.1229 | 0.11 | 0.1372 | 0.0108 | 0 | 0 | 3241 | 0.5 |
| test | 10023 | 269 | 0 | 0.1173 | 0.1048 | 0.1311 | 0.0111 | 0 | 0 | 3281 | 0.5 |

## Stage 2: Fellegi–Sunter

### Candidates on train: reach and cost of every generator

train: 6,192 true pairs missed by the rules

| generator | big_o | filled | pairs | seconds | finds | cumulative | different_entity_pairs | alpha | projected_pairs | per_record |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phone | O(N + P) | O(30,098 + 47,760) | 47011 | 0.013 | 0.2734 | 0.2734 | 45318 | 1.95 | 50210426 | 50.21 |
| address | O(N + P) | O(30,098 + 7,077) | 6490 | 0.01 | 0.2314 | 0.4813 | 5057 | 1.72 | 5664641 | 5.665 |
| address_code | O(N + P) | O(30,098 + 6,526) | 5975 | 0.007 | 0.2127 | 0.5178 | 4658 | 1.72 | 5214843 | 5.215 |
| cif | O(N + P) | O(30,098 + 153) | 31 | 0.008 | 0.005 | 0.5212 | 0 | 1.0 | 5083 | 0.005 |
| person_name | O(N + P) | O(30,098 + 4,104) | 3562 | 0.009 | 0.5129 | 0.7655 | 386 | 1.09 | 549644 | 0.55 |
| company_name | O(N + P) | O(30,098 + 835) | 785 | 0.006 | 0.078 | 0.8114 | 302 | 1.36 | 351093 | 0.351 |
| sn_person_name | O(N log N + N·w) | O(23,774·log 23,774 + 23,774·4) | 70539 | 0.009 | 0.5762 | 0.8395 | 66971 | 1.0 | 3000000 | 3.0 |
| sn_company_name | O(N log N + N·w) | O(4,989·log 4,989 + 4,989·4) | 14898 | 0.004 | 0.0995 | 0.8514 | 14282 | 1.0 | 3000000 | 3.0 |
| tfidf_person_name | O(N·L + U·N·q) | O(23,774·L + 28,676·23,774·13) | 28865 | 2.847 | 0.6145 | 0.8693 | 25060 | 2.0 | 1000000000000 | 1000000.0 |
| tfidf_company_name | O(N·L + U·N·q) | O(4,989·L + 28,676·4,989·19) | 2665 | 0.284 | 0.0998 | 0.8706 | 2047 | 2.0 | 1000000000000 | 1000000.0 |
| phone_prefecture | O(N + P) | O(30,098 + 2,008) | 1669 | 0.008 | 0.1174 | 0.8706 | 942 | 1.47 | 1075312 | 1.075 |
| phone_postal_area | O(N + P) | O(30,098 + 1,002) | 458 | 0.008 | 0.0598 | 0.8706 | 88 | 1.09 | 127512 | 0.128 |
| phone_name_initial | O(N + P) | O(30,098 + 3,475) | 2868 | 0.008 | 0.1912 | 0.8706 | 1684 | 1.49 | 1920653 | 1.921 |
| sn_person_name_reversed | O(N log N + N·w) | O(23,774·log 23,774 + 23,774·4) | 70571 | 0.009 | 0.6106 | 0.8953 | 66790 | 1.0 | 3000000 | 3.0 |
| company_name_deletions | O(N·L + P) | O(30,098·L + 1,342) | 1287 | 0.043 | 0.084 | 0.8955 | 767 | 1.58 | 871166 | 0.871 |
| cif_deletions | O(N·L + P) | O(30,098·L + 172) | 47 | 0.193 | 0.0076 | 0.8958 | 0 | 1.0 | 5714 | 0.006 |
| person_name_deletions_postal_area | O(N·L + P) | O(30,098·L + 1,884) | 1363 | 0.109 | 0.2179 | 0.8963 | 14 | 1.01 | 77585 | 0.078 |
| given_name_postal | O(N + P) | O(30,098 + 1,343) | 962 | 0.008 | 0.1534 | 0.8981 | 12 | 1.01 | 57469 | 0.057 |
| address_phone | O(N + P) | O(30,098 + 668) | 146 | 0.01 | 0.0236 | 0.8981 | 0 | 1.0 | 22194 | 0.022 |
| address_code_phone | O(N + P) | O(30,098 + 602) | 114 | 0.008 | 0.0184 | 0.8981 | 0 | 1.0 | 20001 | 0.02 |
| address_name_initial | O(N + P) | O(30,098 + 1,715) | 1174 | 0.009 | 0.1625 | 0.8981 | 168 | 1.1 | 236857 | 0.237 |
| address_code_name_initial | O(N + P) | O(30,098 + 1,587) | 1086 | 0.008 | 0.1504 | 0.8981 | 155 | 1.1 | 218685 | 0.219 |
| given_name_address_code | O(N + P) | O(30,098 + 1,038) | 680 | 0.007 | 0.1095 | 0.8981 | 2 | 1.0 | 36628 | 0.037 |

### Training on train: EM against labels

cost: u O(max_pairs·C) = O(10,000,000·5) · EM O(iterations·P·C), P = 54,837 · em: fitted in 8.8s · no estimate: u - · m - · labels: fitted in 0.3s · no estimate: u - · m -

| comparison | level | em m | em u | em weight | labels m | labels u | labels weight |
| --- | --- | --- | --- | --- | --- | --- | --- |
| name | exact | 0.261 | 0.0 | 15.319 | 0.263 | 0.0 | 15.329 |
| name | fold exact | 0.416 | 0.0 | 15.743 | 0.432 | 0.0 | 15.795 |
| name | fold JW high | 0.125 | 0.0 | 11.551 | 0.121 | 0.0 | 11.511 |
| name | given name | 0.123 | 0.001 | 7.865 | 0.124 | 0.001 | 7.872 |
| name | fold JW low | 0.017 | 0.0 | 5.605 | 0.013 | 0.0 | 5.161 |
| name | else | 0.057 | 0.999 | -4.129 | 0.047 | 0.999 | -4.396 |
| company | exact | 0.645 | 0.0 | 13.486 | 0.521 | 0.0 | 13.178 |
| company | JW high | 0.084 | 0.0 | 11.285 | 0.076 | 0.0 | 11.142 |
| company | JW low | 0.066 | 0.0 | 8.321 | 0.055 | 0.0 | 8.053 |
| company | else | 0.205 | 1.0 | -2.288 | 0.348 | 1.0 | -1.522 |
| address | same address | 0.278 | 0.0 | 13.851 | 0.345 | 0.0 | 14.159 |
| address | address close | 0.005 | 0.0 | 9.244 | 0.005 | 0.0 | 9.169 |
| address | same postal | 0.046 | 0.0 | 9.56 | 0.057 | 0.0 | 9.871 |
| address | else | 0.67 | 1.0 | -0.578 | 0.593 | 1.0 | -0.754 |
| phone | exact | 0.284 | 0.0 | 11.242 | 0.338 | 0.0 | 11.491 |
| phone | one digit off | 0.067 | 0.004 | 4.183 | 0.074 | 0.004 | 4.323 |
| phone | else | 0.648 | 0.996 | -0.619 | 0.588 | 0.996 | -0.761 |
| cif | exact | 0.02 | 0.0 | 15.922 | 0.023 | 0.0 | 16.083 |
| cif | else | 0.98 | 1.0 | -0.03 | 0.977 | 1.0 | -0.033 |

### Threshold: chosen on cross-validated train

3-fold CV in 31.5s → min_match_weight = 10.0

| min_match_weight | accepted | pairs_FP | stage_fp_rate_hi | TP | FP | recall | recall_lo | recall_hi | eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 3236 | 30 | 0.0126 | 4124 | 36 | 0.5941 | 0.5825 | 0.6056 | False |
| 2 | 3155 | 15 | 0.0073 | 4063 | 18 | 0.5853 | 0.5736 | 0.5968 | False |
| 4 | 3052 | 10 | 0.0056 | 3959 | 12 | 0.5703 | 0.5586 | 0.5819 | False |
| 6 | 2743 | 2 | 0.0023 | 3652 | 2 | 0.5261 | 0.5143 | 0.5378 | False |
| 8 | 2348 | 0 | 0.0013 | 3241 | 0 | 0.4669 | 0.4552 | 0.4786 | True |
| 10 | 2054 | 0 | 0.0015 | 2915 | 0 | 0.4199 | 0.4083 | 0.4316 | True |
| 12 | 1035 | 0 | 0.0029 | 1815 | 0 | 0.2615 | 0.2512 | 0.2719 | True |
| 14 | 275 | 0 | 0.0108 | 1029 | 0 | 0.1482 | 0.1401 | 0.1568 | True |
| 16 | 212 | 0 | 0.014 | 966 | 0 | 0.1392 | 0.1312 | 0.1475 | True |

### A/B on val, paired against the tuned configuration as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | candidates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| labels | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 36406 |
| no_term_frequency | 0.4461 | 0 | 0.003 | 13 | 0 | 0.0002 | 0 | 0 | 36406 |
| exact_keys_only | 0.439 | 0 | 0.003 | 0 | 3 | 0.25 | 0 | 0 | 7348 |
| levenshtein_names | 0.4461 | 0 | 0.003 | 14 | 1 | 0.001 | 0 | 0 | 36406 |
| constrained_given_name | 0.3067 | 0 | 0.0044 | 0 | 299 | 0.0 | 0 | 0 | 36406 |
| optuna_suggestion | 0.4359 | 0 | 0.0031 | 17 | 27 | 0.1742 | 0 | 0 | 15386 |
| u_from_1e6_pairs | 0.4314 | 0 | 0.0031 | 14 | 34 | 0.0055 | 0 | 0 | 36406 |
| compound_phone_keys | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 31577 |
| sorted_names_for_tfidf | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 56402 |
| name_keys | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 36445 |
| bounded_address_keys | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 35705 |
| no_sorted_windows | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 10820 |
| bridge_rule_clusters | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 36508 |
| u_from_scored_file | 0.3965 | 0 | 0.0034 | 0 | 98 | 0.0 | 0 | 0 | 36406 |
| u_exact_by_counts | 0.4305 | 0 | 0.0031 | 11 | 33 | 0.0013 | 0 | 0 | 36406 |
| cif_one_digit_off | 0.4412 | 0 | 0.003 | 2 | 0 | 0.5 | 0 | 0 | 36406 |
| cif_deletion_key | 0.4403 | 0 | 0.003 | 0 | 0 | 1.0 | 0 | 0 | 36406 |

### Decisions

FINAL: 15 generators · term frequency off · m by em · min_match_weight 10.0 · connected_components

| change | kind | adopted | cv_TP_gains | cv_TP_losses | cv_p | cv_FP_added | cv_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_term_frequency | better | True | 29 | 0 | 0.0 | 0 | 0 | 13 | 0 | 0 |
| exact_keys_only | cheaper | False | 0 | 1 | 1.0 | 0 | 0 | 0 | 3 | 0 |
| optuna_suggestion | better | False | 11 | 1126 | 0.0 | 0 | 0 | 2 | 354 | 0 |
| u_from_1e6_pairs | cheaper | False | 132 | 54 | 0.0 | 0 | 0 | 13 | 34 | 0 |
| compound_phone_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| sorted_names_for_tfidf | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| name_keys | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| bounded_address_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| no_sorted_windows | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| bridge_rule_clusters | better | False | 4 | 0 | 0.125 | 0 | 0 | 0 | 0 | 0 |
| u_from_scored_file | chosen | True | 0 | 166 | 0.0 | 0 | 0 | 0 | 95 | 0 |
| u_exact_by_counts | chosen | True | 32 | 21 | 0.169 | 0 | 0 | 18 | 0 | 0 |
| cif_one_digit_off | better | True | 12 | 0 | 0.0005 | 0 | 0 | 1 | 0 | 0 |
| cif_deletion_key | safer | True | 2 | 0 | 0.5 | 0 | 0 | 1 | 0 | 0 |

### Will it scale? FINAL's generators at target_rows

| key | columns | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- |
| cif | customer_id | 1.0 | 5083 | 0.005 | True |
| person_name | person_name__kana_fold | 1.09 | 549644 | 0.55 | True |
| company_name | company_name__nfkc_strip_legal_form_kana_fold | 1.36 | 351093 | 0.351 | True |
| phone_prefecture | phone + prefecture | 1.47 | 1075312 | 1.075 | True |
| phone_postal_area | phone + postal_code__first3 | 1.09 | 127512 | 0.128 | True |
| phone_name_initial | phone + any_name__initial | 1.49 | 1920653 | 1.921 | True |
| company_name_deletions | company_name__nfkc_strip_legal_form_kana_fold | 1.58 | 871166 | 0.871 | True |
| person_name_deletions_postal_area | person_name__kana_fold + postal_code__first3 | 1.01 | 77585 | 0.078 | True |
| given_name_postal | given_name__kana_fold + postal_code | 1.01 | 57469 | 0.057 | True |
| address_phone | address__address + phone | 1.0 | 22194 | 0.022 | True |
| address_code_phone | address_code + phone | 1.0 | 20001 | 0.02 | True |
| address_name_initial | address__address + any_name__initial | 1.1 | 236857 | 0.237 | True |
| address_code_name_initial | address_code + any_name__initial | 1.1 | 218685 | 0.219 | True |
| given_name_address_code | given_name__kana_fold + address_code | 1.0 | 36628 | 0.037 | True |
| cif_deletions | customer_id | 1.0 | 5714 | 0.006 | True |

### Potential matches that share no key (train)

| records | potential | window_only |
| --- | --- | --- |
| 30098 | 2383 | 0 |
| 1000000 | 2450 | 0 |

### Patterns without a guaranteed key, at target_rows (label-free)

64 patterns that can reach the threshold at 1,000,000 records have no guaranteed key; the model puts their share of matches at 4.479% at most (Jaro–Winkler implies no key)

| name | company | address | phone | cif | bits | share_of_matches |
| --- | --- | --- | --- | --- | --- | --- |
| fold JW high | JW high | missing | exact | missing | 13.18 | 0.002975949850993346 |
| fold JW high | JW high | missing | exact | else | 13.14 | 0.0029081770319919014 |
| fold JW high | JW high | same address | missing | missing | 15.65 | 0.0029055376323272796 |
| given name | JW high | same address | missing | missing | 11.96 | 0.002869951227341016 |
| fold JW high | JW high | same address | missing | else | 15.62 | 0.00283936834658079 |
| given name | JW high | same address | missing | else | 11.93 | 0.0028045923688882666 |
| fold JW high | JW low | missing | exact | missing | 10.21 | 0.002331546047539983 |
| fold JW high | JW low | missing | exact | else | 10.18 | 0.002278448563985038 |
| fold JW high | JW low | same address | missing | missing | 12.69 | 0.002276380692493899 |
| fold JW high | JW low | same address | missing | else | 12.65 | 0.0022245395176168172 |

### FINAL's candidates on val

candidates 1,899 · they contain 75.4% of the true pairs the rules missed

| generator | big_o | filled | pairs | completeness_on_targets | seconds |
| --- | --- | --- | --- | --- | --- |
| cif | O(N + P) | O(9,995 + 52) | 11 | 0.0056 | 0.005 |
| person_name | O(N + P) | O(9,995 + 1,260) | 1053 | 0.5148 | 0.005 |
| company_name | O(N + P) | O(9,995 + 200) | 186 | 0.0719 | 0.004 |
| phone_prefecture | O(N + P) | O(9,995 + 426) | 316 | 0.1106 | 0.005 |
| phone_postal_area | O(N + P) | O(9,995 + 336) | 139 | 0.0652 | 0.005 |
| phone_name_initial | O(N + P) | O(9,995 + 765) | 543 | 0.1978 | 0.005 |
| company_name_deletions | O(N·L + P) | O(9,995·L + 260) | 245 | 0.077 | 0.016 |
| person_name_deletions_postal_area | O(N·L + P) | O(9,995·L + 612) | 414 | 0.21 | 0.039 |
| given_name_postal | O(N + P) | O(9,995 + 410) | 280 | 0.1417 | 0.005 |
| address_phone | O(N + P) | O(9,995 + 232) | 49 | 0.025 | 0.005 |
| address_code_phone | O(N + P) | O(9,995 + 227) | 49 | 0.025 | 0.004 |
| address_name_initial | O(N + P) | O(9,995 + 509) | 313 | 0.1468 | 0.005 |
| address_code_name_initial | O(N + P) | O(9,995 + 491) | 298 | 0.1442 | 0.005 |
| given_name_address_code | O(N + P) | O(9,995 + 324) | 200 | 0.1014 | 0.004 |
| cif_deletions | O(N·L + P) | O(9,995·L + 57) | 16 | 0.0082 | 0.066 |

### Evaluation on val

transfer at weight 10.0: CV 0 false of 1939 accepted pairs (rate ≤ 0.15%) · val 0 of 624 (0.00%)

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | 275 | 0 | 0.1229 | 0.11 | 0.1372 | 0.0108 | 0 | 0 | 3241 |
| probabilistic | 923 | 0 | 0.4126 | 0.3924 | 0.4331 | 0.0032 | 0 | 0 | 2122 |

### Threshold curve on val

| min_match_weight | accepted | pairs_FP | TP | FP | recall | fp_rate_hi |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 980 | 3 | 1300 | 3 | 0.5811 | 0.0059 |
| 2 | 965 | 3 | 1282 | 3 | 0.5731 | 0.006 |
| 4 | 897 | 1 | 1216 | 1 | 0.5436 | 0.0039 |
| 6 | 843 | 1 | 1159 | 1 | 0.5181 | 0.0041 |
| 8 | 728 | 0 | 1035 | 0 | 0.4627 | 0.0029 |
| 10 | 624 | 0 | 923 | 0 | 0.4126 | 0.0032 |
| 12 | 299 | 0 | 577 | 0 | 0.2579 | 0.0052 |
| 14 | 81 | 0 | 356 | 0 | 0.1591 | 0.0084 |
| 16 | 71 | 0 | 346 | 0 | 0.1547 | 0.0086 |

### An accepted true match with a typo

10.19 bits → match probability 0.9991 · found by person_name+phone_name_initial

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000004256 | ミヤシタセンイチ | nan | 神奈川県鎌倉市扇ガ谷2-18-5 | 0204 | 1147555593271 |
| 0000004781 | ミヤジタセンイチ | nan | 神奈川県横浜市保土ケ谷区瀬戸ケ谷町11-5 | 0204 | 3253274132622 |

### An accepted true match with a typo: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.41 |
| name | fold exact | 13.96 |
| company | missing | 0.0 |
| address | else | -0.58 |
| phone | exact | 11.25 |
| cif | else | -0.03 |

### The rejected non-match closest to the threshold

6.19 bits → match probability 0.9865 · found by given_name_postal+address_name_initial+address_code_name_initial+given_name_address_code

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000007442 | ハラタトモミ | nan | 東京都杉並区永福3-25-24 | 1356 | nan |
| 0000036893 | ハナシロトモミ | nan | 東京都杉並区永福3-25-24 | 8080 | 5161793490088 |

### The rejected non-match closest to the threshold: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.41 |
| name | given name | 7.98 |
| company | missing | 0.0 |
| address | same address | 13.24 |
| phone | else | -0.62 |
| cif | missing | 0.0 |

### FINAL on train, val and test

| dataset | records | recall_before | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | accepted | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30098 | 0.108 | 2782 | 0 | 0.4007 | 0.3893 | 0.4123 | 0.0011 | 0 | 0 | 6560 | 1925 | 11.6 |
| val | 9995 | 0.1229 | 923 | 0 | 0.4126 | 0.3924 | 0.4331 | 0.0032 | 0 | 0 | 2122 | 624 | 0.6 |
| test | 10023 | 0.1173 | 950 | 0 | 0.4143 | 0.3943 | 0.4346 | 0.0031 | 0 | 0 | 2160 | 641 | 11.6 |

### Configurations scored on test, per stage

| family | configs_on_test |
| --- | --- |
| deterministic | 1 |
| probabilistic | 1 |
