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
| fold_levenshtein | 0.0921 | 0 | 0.0146 | 6 | 2 | 0.2891 | 0 | 0 | 1041 | 0.4 |
| fold_exact | 0.0804 | 0 | 0.0167 | 0 | 22 | 0.0 | 0 | 0 | 475 | 0.4 |
| raw_jaro_winkler | 0.0718 | 0 | 0.0187 | 0 | 41 | 0.0 | 0 | 0 | 1041 | 0.4 |
| constrained_given_name | 0.0713 | 0 | 0.0188 | 0 | 42 | 0.0 | 0 | 0 | 1041 | 0.6 |
| optuna_comparators | 0.0953 | 0 | 0.0141 | 20 | 9 | 0.0614 | 0 | 0 | 6706 | 0.5 |
| f2_address_exact | 0.0903 | 0 | 0.0149 | 0 | 0 | 1.0 | 0 | 0 | 1041 | 0.4 |
| f2_address_prefix | 0.0903 | 0 | 0.0149 | 0 | 0 | 1.0 | 0 | 0 | 1041 | 0.4 |

### Decisions

FINAL fuzzy comparators: {'person_name': 'levenshtein 1 kana_fold', 'company_name': 'levenshtein 1 nfkc+strip_legal_form+kana_fold', 'address': 'exact  address', 'phone': 'hamming 1'} · connected_components

| change | kind | adopted | train_TP_gains | train_TP_losses | train_p | train_FP_added | train_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fold_levenshtein | better | True | 17 | 4 | 0.0072 | 0 | 0 | 6 | 2 | 0 |
| fold_exact | cheaper | False | 0 | 83 | 0.0 | 0 | 0 | 0 | 26 | 0 |
| optuna_comparators | better | False | 34 | 31 | 0.8043 | 0 | 0 | 16 | 9 | 0 |
| f2_address_exact | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| f2_address_prefix | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |

### Cost of FINAL: every rule now and at target_rows

train: N = 30,103 · total P = 3,339 → 119,476 at 1,000,000 rows

| stage | rule | keys | big_o | filled | P | largest_block | est_fuzzy_ms | alpha | projected_pairs | per_record | within_budget |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | X1_CIF_PERSON_NAME | customer_id + full_name | O(N + P) | O(30,103 + 24) | 24 | 2 | 0.0 | 1.0 | 797 | 0.001 | True |
| exact | X2_CIF_COMPANY_NAME | customer_id + company_name | O(N + P) | O(30,103 + 2) | 2 | 2 | 0.0 | 1.0 | 66 | 0.0 | True |
| exact | X3_CIF_PHONE | customer_id + phone | O(N + P) | O(30,103 + 54) | 54 | 2 | 0.0 | 1.0 | 1793 | 0.002 | True |
| exact | X4_PERSON_NAME_ADDRCD_PHONE | full_name + address_code + phone | O(N + P) | O(30,103 + 137) | 137 | 3 | 0.0 | 1.0 | 4551 | 0.005 | True |
| exact | X5_COMPANY_NAME_ADDRCD_PHONE | company_name + address_code + phone | O(N + P) | O(30,103 + 5) | 5 | 2 | 0.0 | 1.0 | 166 | 0.0 | True |
| fuzzy | F1_NAME~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(30,103 + 613·45) | 613 | 3 | 0.1 | 1.0 | 21433 | 0.021 | True |
| fuzzy | F2_NAME~_ADDRESS~_PHONE | phone + address__address + address__address_first3 | O(N + P·(m·n)) | O(30,103 + 294·45) | 294 | 3 | 0.05 | 1.01 | 11907 | 0.012 | True |
| fuzzy | F3_NAME~_CIF | customer_id | O(N + P·(m·n)) | O(30,103 + 162·45) | 162 | 3 | 0.03 | 1.0 | 5381 | 0.005 | True |
| fuzzy | F4_NAME_ADDRCD_PHONE~ | person_name + address_code | O(N + P·(n)) | O(30,103 + 418·4) | 418 | 3 | 0.04 | 1.0 | 13885 | 0.014 | True |
| fuzzy | F5_COMPANY~_PHONE_POSTAL | phone + postal_code | O(N + P·(m·n)) | O(30,103 + 799·91) | 799 | 3 | 0.15 | 1.01 | 30823 | 0.031 | True |
| fuzzy | F6_COMPANY~_ADDRCD_PHONE | address_code + phone | O(N + P·(m·n)) | O(30,103 + 613·91) | 613 | 3 | 0.11 | 1.0 | 21433 | 0.021 | True |
| fuzzy | F7_GIVEN_ADDRCD_PHONE | given_name + address_code + phone | O(N + P) | O(30,103 + 218) | 218 | 3 | 0.0 | 1.0 | 7241 | 0.007 | True |

### Evaluation on val

rules: Σ ops ≈ 174,456 (see big_o per rule) · normalize: O(N·L), N = 9,966 · cluster: O((N + E)·d), N = 9,966, E = 202 · evaluate: O(N) · total 0.5s · false-positive pairs: 0

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact | 66 | 0 | 0.0298 | 0.0235 | 0.0377 | 0.0444 | 0 | 0 | 3573 |
| fuzzy | 204 | 0 | 0.0921 | 0.0808 | 0.1049 | 0.0146 | 0 | 0 | 3303 |

### Rules on val

| rule | P | actual_ms | edges | edge_FP | kept | kept_FP |
| --- | --- | --- | --- | --- | --- | --- |
| X1_CIF_PERSON_NAME | 12 | 23.2 | 12 | 0 | 12 | 0 |
| X2_CIF_COMPANY_NAME | 0 | 22.2 | 0 | 0 | 0 | 0 |
| X3_CIF_PHONE | 15 | 22.2 | 12 | 0 | 12 | 0 |
| X4_PERSON_NAME_ADDRCD_PHONE | 40 | 23.5 | 38 | 0 | 38 | 0 |
| X5_COMPANY_NAME_ADDRCD_PHONE | 4 | 23.0 | 4 | 0 | 4 | 0 |
| F1_NAME~_ADDRCD_PHONE | 198 | 24.8 | 88 | 0 | 88 | 0 |
| F2_NAME~_ADDRESS~_PHONE | 94 | 27.3 | 7 | 0 | 7 | 0 |
| F3_NAME~_CIF | 48 | 24.3 | 16 | 0 | 16 | 0 |
| F4_NAME_ADDRCD_PHONE~ | 120 | 25.1 | 2 | 0 | 2 | 0 |
| F5_COMPANY~_PHONE_POSTAL | 246 | 25.0 | 13 | 0 | 13 | 0 |
| F6_COMPANY~_ADDRCD_PHONE | 198 | 24.8 | 2 | 0 | 2 | 0 |
| F7_GIVEN_ADDRCD_PHONE | 66 | 23.2 | 8 | 0 | 8 | 0 |

### FINAL on train, val and test

| dataset | records | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30103 | 710 | 0 | 0.1026 | 0.0957 | 0.11 | 0.0042 | 0 | 0 | 10100 | 0.9 |
| val | 9966 | 204 | 0 | 0.0921 | 0.0808 | 0.1049 | 0.0146 | 0 | 0 | 3303 | 0.5 |

### Optuna: the Pareto front, re-scored on val

suggested: trial 33 → adopt by rule ('better' vs FINAL): True · train {'TP_gains': 33, 'TP_losses': 0, 'p': np.float64(2.3283064365386963e-10), 'FP_added': 0, 'FP_removed': 0} · val {'TP_gains': 11, 'TP_losses': 0, 'p': np.float64(0.0009765625), 'FP_added': 0, 'FP_removed': 0}

| trial | train_FP | train_recall | train_recall_lo | train_recall_hi | train_zero_fp | val_FP | val_recall | P |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 33 | 0.0 | 0.1074 | 0.1003 | 0.1149 | True | 0 | 0.0971 | 1117 |
| 37 | 0.0 | 0.1074 | 0.1003 | 0.1149 | True | 0 | 0.0971 | 1117 |
| 47 | 0.0 | 0.1074 | 0.1003 | 0.1149 | True | 0 | 0.0971 | 1117 |

## Stage 2: Fellegi–Sunter

### Candidates on train: reach and cost of every generator

train: 6,210 true pairs missed by the rules

| generator | big_o | filled | pairs | seconds | finds | cumulative | different_entity_pairs | alpha | projected_pairs | per_record |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phone | O(N + P) | O(30,103 + 47,375) | 46707 | 0.013 | 0.2733 | 0.2733 | 45010 | 1.95 | 49823479 | 49.823 |
| address | O(N + P) | O(30,103 + 5,788) | 5512 | 0.01 | 0.1101 | 0.3749 | 4828 | 1.84 | 5372703 | 5.373 |
| address_code | O(N + P) | O(30,103 + 6,665) | 6074 | 0.008 | 0.2108 | 0.4824 | 4765 | 1.72 | 5345109 | 5.345 |
| cif | O(N + P) | O(30,103 + 162) | 41 | 0.008 | 0.0066 | 0.4876 | 0 | 1.0 | 5381 | 0.005 |
| person_name | O(N + P) | O(30,103 + 4,185) | 3668 | 0.008 | 0.52 | 0.7544 | 439 | 1.1 | 608900 | 0.609 |
| company_name | O(N + P) | O(30,103 + 795) | 746 | 0.006 | 0.0709 | 0.7961 | 306 | 1.38 | 353932 | 0.354 |
| sn_person_name | O(N log N + N·w) | O(23,741·log 23,741 + 23,741·4) | 70508 | 0.009 | 0.5936 | 0.8306 | 66822 | 1.0 | 3000000 | 3.0 |
| sn_company_name | O(N log N + N·w) | O(5,032·log 5,032 + 5,032·4) | 15030 | 0.004 | 0.0948 | 0.8441 | 14441 | 1.0 | 3000000 | 3.0 |
| tfidf_person_name | O(N·L + U·N·q) | O(23,741·L + 28,752·23,741·13) | 28132 | 3.374 | 0.6187 | 0.861 | 24290 | 2.0 | 1000000000000 | 1000000.0 |
| tfidf_company_name | O(N·L + U·N·q) | O(5,032·L + 28,752·5,032·19) | 2805 | 0.322 | 0.0944 | 0.8618 | 2219 | 2.0 | 1000000000000 | 1000000.0 |
| phone_prefecture | O(N + P) | O(30,103 + 2,070) | 1740 | 0.008 | 0.123 | 0.8618 | 976 | 1.47 | 1115553 | 1.116 |
| phone_postal_area | O(N + P) | O(30,103 + 981) | 487 | 0.009 | 0.0636 | 0.8618 | 92 | 1.09 | 131059 | 0.131 |
| phone_name_initial | O(N + P) | O(30,103 + 3,307) | 2756 | 0.009 | 0.1981 | 0.8618 | 1526 | 1.46 | 1745330 | 1.745 |
| sn_person_name_reversed | O(N log N + N·w) | O(23,741·log 23,741 + 23,741·4) | 70526 | 0.01 | 0.6081 | 0.8847 | 66750 | 1.0 | 3000000 | 3.0 |
| company_name_deletions | O(N·L + P) | O(30,103·L + 1,264) | 1210 | 0.044 | 0.0744 | 0.885 | 748 | 1.59 | 842601 | 0.843 |
| cif_deletions | O(N·L + P) | O(30,103·L + 181) | 57 | 0.194 | 0.0092 | 0.8852 | 0 | 1.0 | 6012 | 0.006 |
| person_name_deletions_postal_area | O(N·L + P) | O(30,103·L + 1,925) | 1438 | 0.11 | 0.229 | 0.8857 | 16 | 1.01 | 81072 | 0.081 |
| given_name_postal | O(N + P) | O(30,103 + 1,338) | 982 | 0.008 | 0.1565 | 0.8879 | 10 | 1.01 | 55150 | 0.055 |
| address_phone | O(N + P) | O(30,103 + 294) | 55 | 0.01 | 0.0085 | 0.8879 | 2 | 1.01 | 11907 | 0.012 |
| address_code_phone | O(N + P) | O(30,103 + 613) | 100 | 0.008 | 0.0159 | 0.8879 | 1 | 1.0 | 21433 | 0.021 |
| address_name_initial | O(N + P) | O(30,103 + 895) | 653 | 0.01 | 0.0746 | 0.8879 | 190 | 1.21 | 233095 | 0.233 |
| address_code_name_initial | O(N + P) | O(30,103 + 1,650) | 1118 | 0.008 | 0.1467 | 0.8879 | 207 | 1.13 | 276371 | 0.276 |
| given_name_address_code | O(N + P) | O(30,103 + 1,009) | 638 | 0.007 | 0.1026 | 0.8879 | 1 | 1.0 | 34588 | 0.035 |
| given_name_phone | O(N + P) | O(30,103 + 1,290) | 917 | 0.008 | 0.1459 | 0.8879 | 11 | 1.01 | 54626 | 0.055 |
| birth_date | O(N + P) | O(30,103 + 352) | 337 | 0.005 | 0.0135 | 0.8889 | 253 | 1.72 | 282488 | 0.282 |
| birth_date_deletions_prefecture | O(N·L + P) | O(30,103·L + 342) | 326 | 0.015 | 0.0085 | 0.8889 | 273 | 1.82 | 313195 | 0.313 |

### Training on train: EM against labels

cost: u O(max_pairs·C) = O(10,000,000·5) · EM O(iterations·P·C), P = 53,163 · em: fitted in 8.2s · no estimate: u - · m - · labels: fitted in 0.3s · no estimate: u - · m -

| comparison | level | em m | em u | em weight | labels m | labels u | labels weight |
| --- | --- | --- | --- | --- | --- | --- | --- |
| name | exact | 0.258 | 0.0 | 15.607 | 0.267 | 0.0 | 15.661 |
| name | fold exact | 0.427 | 0.0 | 15.831 | 0.431 | 0.0 | 15.843 |
| name | fold JW high | 0.124 | 0.0 | 11.601 | 0.127 | 0.0 | 11.631 |
| name | given name | 0.116 | 0.0 | 7.938 | 0.107 | 0.0 | 7.825 |
| name | fold JW low | 0.016 | 0.0 | 5.683 | 0.014 | 0.0 | 5.415 |
| name | else | 0.059 | 0.999 | -4.09 | 0.054 | 0.999 | -4.199 |
| company | exact | 0.613 | 0.0 | 12.732 | 0.507 | 0.0 | 12.458 |
| company | JW high | 0.119 | 0.0 | 11.613 | 0.084 | 0.0 | 11.105 |
| company | JW low | 0.109 | 0.0 | 9.386 | 0.078 | 0.0 | 8.899 |
| company | else | 0.158 | 1.0 | -2.66 | 0.331 | 1.0 | -1.595 |
| address | same address | 0.237 | 0.0 | 13.4 | 0.293 | 0.0 | 13.704 |
| address | address close | 0.007 | 0.001 | 2.305 | 0.006 | 0.001 | 2.061 |
| address | same postal | 0.081 | 0.0 | 10.273 | 0.099 | 0.0 | 10.557 |
| address | else | 0.675 | 0.999 | -0.565 | 0.602 | 0.999 | -0.729 |
| phone | exact | 0.264 | 0.0 | 11.373 | 0.332 | 0.0 | 11.702 |
| phone | one digit off | 0.062 | 0.004 | 4.101 | 0.073 | 0.004 | 4.343 |
| phone | else | 0.674 | 0.996 | -0.564 | 0.595 | 0.996 | -0.744 |
| cif | exact | 0.018 | 0.0 | 17.364 | 0.024 | 0.0 | 17.79 |
| cif | else | 0.982 | 1.0 | -0.027 | 0.976 | 1.0 | -0.036 |

### Threshold: chosen on cross-validated train

3-fold CV in 29.0s → min_match_weight = 12.0

| min_match_weight | accepted | pairs_FP | stage_fp_rate_hi | TP | FP | recall | recall_lo | recall_hi | eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 3227 | 27 | 0.0115 | 4100 | 42 | 0.5925 | 0.5809 | 0.604 | False |
| 2 | 3113 | 8 | 0.0046 | 3994 | 14 | 0.5772 | 0.5655 | 0.5888 | False |
| 4 | 2994 | 3 | 0.0026 | 3882 | 5 | 0.561 | 0.5493 | 0.5726 | False |
| 6 | 2684 | 1 | 0.0018 | 3553 | 1 | 0.5134 | 0.5017 | 0.5252 | False |
| 8 | 2354 | 1 | 0.002 | 3196 | 1 | 0.4618 | 0.4501 | 0.4736 | False |
| 10 | 2036 | 0 | 0.0015 | 2871 | 0 | 0.4149 | 0.4033 | 0.4265 | True |
| 12 | 942 | 0 | 0.0032 | 1680 | 0 | 0.2428 | 0.2328 | 0.253 | True |
| 14 | 301 | 0 | 0.0099 | 1017 | 0 | 0.147 | 0.1388 | 0.1555 | True |
| 16 | 233 | 0 | 0.0128 | 947 | 0 | 0.1368 | 0.129 | 0.1451 | True |

### A/B on val, paired against the tuned configuration as written

| variant | recall | FP | fp_rate_hi | TP_gains | TP_losses | p | FP_added | FP_removed | candidates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| labels | 0.3445 | 0 | 0.0039 | 88 | 0 | 0.0 | 0 | 0 | 36641 |
| no_term_frequency | 0.3102 | 0 | 0.0044 | 12 | 0 | 0.0005 | 0 | 0 | 36641 |
| exact_keys_only | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 7529 |
| levenshtein_names | 0.3056 | 0 | 0.0044 | 2 | 0 | 0.5 | 0 | 0 | 36641 |
| constrained_given_name | 0.2045 | 0 | 0.0066 | 0 | 222 | 0.0 | 0 | 0 | 36641 |
| optuna_suggestion | 0.3223 | 0 | 0.0042 | 40 | 1 | 0.0 | 0 | 0 | 15782 |
| u_from_1e6_pairs | 0.3016 | 0 | 0.0045 | 0 | 7 | 0.0156 | 0 | 0 | 36641 |
| compound_phone_keys | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 31866 |
| sorted_names_for_tfidf | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 56414 |
| name_keys | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 36699 |
| bounded_address_keys | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 35800 |
| no_sorted_windows | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 11195 |
| bridge_rule_clusters | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 36703 |
| u_from_scored_file | 0.2271 | 0 | 0.0059 | 0 | 172 | 0.0 | 0 | 0 | 36641 |
| u_exact_by_counts | 0.2298 | 0 | 0.0059 | 0 | 166 | 0.0 | 0 | 0 | 36641 |
| cif_one_digit_off | 0.3056 | 0 | 0.0044 | 2 | 0 | 0.5 | 0 | 0 | 36641 |
| graded_address | 0.3115 | 0 | 0.0043 | 97 | 82 | 0.2954 | 0 | 0 | 36641 |
| birth_date | 0.3151 | 0 | 0.0043 | 23 | 0 | 0.0 | 0 | 0 | 36641 |
| cif_deletion_key | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 36641 |
| birth_date_key | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 36670 |
| given_name_phone_key | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 36641 |
| birth_date_deletion_key | 0.3047 | 0 | 0.0044 | 0 | 0 | 1.0 | 0 | 0 | 36671 |

### Decisions

FINAL: 21 generators · term frequency off · m by em · min_match_weight 8.0 · connected_components

| change | kind | adopted | cv_TP_gains | cv_TP_losses | cv_p | cv_FP_added | cv_FP_removed | val_TP_gains | val_TP_losses | val_FP_added |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no_term_frequency | better | True | 12 | 0 | 0.0005 | 0 | 0 | 12 | 0 | 0 |
| exact_keys_only | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| optuna_suggestion | better | True | 1501 | 1 | 0.0 | 0 | 0 | 335 | 0 | 0 |
| u_from_1e6_pairs | cheaper | False | 1 | 8 | 0.0391 | 0 | 0 | 0 | 1 | 0 |
| compound_phone_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| sorted_names_for_tfidf | cheaper | True | 1 | 0 | 1.0 | 0 | 0 | 4 | 0 | 0 |
| name_keys | safer | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| bounded_address_keys | cheaper | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| no_sorted_windows | cheaper | False | 0 | 0 | 1.0 | 0 | 0 | 0 | 1 | 0 |
| bridge_rule_clusters | better | False | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| u_from_scored_file | chosen | True | 0 | 63 | 0.0 | 0 | 0 | 0 | 12 | 0 |
| u_exact_by_counts | chosen | True | 47 | 2 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| cif_one_digit_off | better | True | 8 | 0 | 0.0078 | 0 | 0 | 2 | 0 | 0 |
| cif_deletion_key | safer | True | 2 | 0 | 0.5 | 0 | 0 | 0 | 0 | 0 |
| graded_address | better | True | 122 | 67 | 0.0001 | 0 | 0 | 30 | 20 | 0 |
| birth_date | better | True | 56 | 0 | 0.0 | 0 | 0 | 22 | 0 | 0 |
| birth_date_key | safer | True | 1 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| given_name_phone_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |
| birth_date_deletion_key | safer | True | 0 | 0 | 1.0 | 0 | 0 | 0 | 0 | 0 |

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
| 30103 | 3037 | 0 |
| 1000000 | 2958 | 0 |

### Patterns without a guaranteed key, at target_rows (label-free)

396 patterns that can reach the threshold at 1,000,000 records have no guaranteed key; the model puts their share of matches at 10.032% at most (Jaro–Winkler implies no key)

| name | company | address | phone | cif | birth | bits | share_of_matches |
| --- | --- | --- | --- | --- | --- | --- | --- |
| given name | JW low | same address | missing | missing | missing | 8.86 | 0.007763086829163466 |
| given name | JW low | same address | missing | else | missing | 8.83 | 0.007587536117010225 |
| given name | JW low | same address | else | missing | missing | 8.3 | 0.005237355046490495 |
| given name | JW low | same address | else | else | missing | 8.27 | 0.005118920018202932 |
| fold JW high | JW low | missing | exact | missing | missing | 12.2 | 0.004342788829399797 |
| fold JW high | JW low | missing | exact | else | missing | 12.17 | 0.0042445830913333035 |
| fold JW high | JW low | same address | missing | missing | missing | 14.41 | 0.004077335031755509 |
| fold JW high | JW low | same address | missing | else | missing | 14.38 | 0.003985132138207665 |
| fold JW high | JW low | same address | else | missing | missing | 13.85 | 0.0027507680481654883 |
| fold JW high | JW low | same address | else | else | missing | 13.81 | 0.0026885635024157576 |

### FINAL's candidates on val

candidates 50,945 · they contain 86.2% of the true pairs the rules missed

| generator | big_o | filled | pairs | completeness_on_targets | seconds |
| --- | --- | --- | --- | --- | --- |
| cif | O(N + P) | O(9,966 + 48) | 8 | 0.004 | 0.005 |
| sn_company_name | O(N log N + N·w) | O(1,708·log 1,708 + 1,708·4) | 5093 | 0.091 | 0.003 |
| phone_prefecture | O(N + P) | O(9,966 + 436) | 343 | 0.1198 | 0.005 |
| phone_postal_area | O(N + P) | O(9,966 + 286) | 148 | 0.0706 | 0.005 |
| phone_name_initial | O(N + P) | O(9,966 + 747) | 585 | 0.1979 | 0.005 |
| sn_person_name | O(N log N + N·w) | O(7,810·log 7,810 + 7,810·4) | 23235 | 0.6007 | 0.004 |
| sn_person_name_reversed | O(N log N + N·w) | O(7,810·log 7,810 + 7,810·4) | 23218 | 0.6469 | 0.004 |
| person_name | O(N + P) | O(9,966 + 1,238) | 1092 | 0.5201 | 0.005 |
| company_name | O(N + P) | O(9,966 + 223) | 203 | 0.0756 | 0.004 |
| company_name_deletions | O(N·L + P) | O(9,966·L + 291) | 270 | 0.0791 | 0.016 |
| person_name_deletions_postal_area | O(N·L + P) | O(9,966·L + 564) | 434 | 0.2133 | 0.04 |
| given_name_postal | O(N + P) | O(9,966 + 387) | 307 | 0.1527 | 0.005 |
| address_phone | O(N + P) | O(9,966 + 94) | 19 | 0.0094 | 0.005 |
| address_code_phone | O(N + P) | O(9,966 + 198) | 42 | 0.0209 | 0.005 |
| address_name_initial | O(N + P) | O(9,966 + 233) | 159 | 0.0721 | 0.005 |
| address_code_name_initial | O(N + P) | O(9,966 + 448) | 296 | 0.1367 | 0.005 |
| given_name_address_code | O(N + P) | O(9,966 + 300) | 206 | 0.1024 | 0.005 |
| cif_deletions | O(N·L + P) | O(9,966·L + 52) | 12 | 0.006 | 0.066 |
| birth_date | O(N + P) | O(9,966 + 71) | 66 | 0.0199 | 0.004 |
| given_name_phone | O(N + P) | O(9,966 + 387) | 289 | 0.1427 | 0.005 |
| birth_date_deletions_prefecture | O(N·L + P) | O(9,966·L + 50) | 48 | 0.0099 | 0.008 |

### Evaluation on val

transfer at weight 8.0: CV 0 false of 2429 accepted pairs (rate ≤ 0.12%) · val 0 of 795 (0.00%)

| stage | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | 204 | 0 | 0.0921 | 0.0808 | 0.1049 | 0.0146 | 0 | 0 | 3303 |
| probabilistic | 1048 | 0 | 0.4731 | 0.4524 | 0.494 | 0.0029 | 0 | 0 | 1886 |

### Threshold curve on val

| min_match_weight | accepted | pairs_FP | TP | FP | recall | fp_rate_hi |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1373 | 61 | 1575 | 93 | 0.7111 | 0.0659 |
| 2 | 1215 | 12 | 1462 | 18 | 0.66 | 0.018 |
| 4 | 940 | 1 | 1203 | 1 | 0.5431 | 0.0039 |
| 6 | 910 | 0 | 1170 | 0 | 0.5282 | 0.0026 |
| 8 | 795 | 0 | 1048 | 0 | 0.4731 | 0.0029 |
| 10 | 528 | 0 | 765 | 0 | 0.3454 | 0.0039 |
| 12 | 470 | 0 | 703 | 0 | 0.3174 | 0.0043 |
| 14 | 240 | 0 | 457 | 0 | 0.2063 | 0.0065 |
| 16 | 96 | 0 | 303 | 0 | 0.1368 | 0.0098 |

### An accepted true match with a typo

8.06 bits → match probability 0.9963 · found by sn_person_name_reversed+person_name_deletions_postal_area+given_name_postal

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
| address | same postal | 10.23 |
| phone | one digit off | 4.07 |
| cif | else | -0.03 |
| birth | missing | 0.0 |

### The rejected non-match closest to the threshold

5.42 bits → match probability 0.9772 · found by phone_prefecture+phone_name_initial

| CONT_ID | full_name | company_name | address | phone | customer_id |
| --- | --- | --- | --- | --- | --- |
| 0000004185 | タカハシユカ | nan | 北海道名寄市東三条南2-15-21 | 2887 | 8900662733639 |
| 0000044064 | タカハジトモカ | nan | 北海道登別市札内町12-22 | 2887 | 3517719009256 |

### The rejected non-match closest to the threshold: bits

| evidence | level | bits |
| --- | --- | --- |
| prior | two random records match | -14.4 |
| name | fold JW low | 5.01 |
| company | missing | 0.0 |
| address | same prefecture | 3.7 |
| phone | exact | 11.15 |
| cif | else | -0.03 |
| birth | missing | 0.0 |

### FINAL on train, val and test

| dataset | records | recall_before | TP | FP | recall | recall_lo | recall_hi | fp_rate_hi | pairs_FP | overmerged | dup_unresolved | accepted | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30103 | 0.1026 | 3194 | 0 | 0.4616 | 0.4498 | 0.4733 | 0.0009 | 0 | 0 | 5989 | 2330 | 13.9 |
| val | 9966 | 0.0921 | 1048 | 0 | 0.4731 | 0.4524 | 0.494 | 0.0029 | 0 | 0 | 1886 | 795 | 0.9 |

### Configurations scored on test, per stage

| family | configs_on_test |
| --- | --- |

### Optuna: the Pareto front, re-scored on val

suggested: trial 19 → adopt by rule ('better' vs FINAL): False · cross-validated train {'TP_gains': 423, 'TP_losses': 8, 'p': np.float64(1.0168868014510716e-113), 'FP_added': 0, 'FP_removed': 0} · val {'TP_gains': 134, 'TP_losses': 4, 'p': np.float64(8.552879677427434e-35), 'FP_added': 1, 'FP_removed': 0}

| trial | cv_FP | cv_recall | cv_recall_lo | cv_recall_hi | cv_zero_fp | val_FP | val_recall | candidates | min_match_weight |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 19 | 0.0 | 0.5366 | 0.5248 | 0.5483 | True | 1 | 0.5318 | 87425 | 6.0 |
