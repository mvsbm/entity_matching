# Benchmark: look up

Written by `scripts/benchmark_lookup.py --entities 800000 --lookups 1000 --checked 20 --memory-limit 8GB` on a generated population of 1,000,338 records: 999,338 run (`nayose resolve records`, 75 s), 1,000 held out and looked up one at a time by their values, as a person types them (`nayose match record`), each opening the index afresh. Past 60,000 entities personas repeat: clones, in blocks larger than a real file's, so the times are an upper bound.

## The index

Built in **7.0 s** from the run's own files (`nayose build index`), **901 MB** on disk in the workspace's `index/`.

| table | of | rows | seconds |
| --- | --- | --- | --- |
| records | records | 999,338 | 1.009 |
| g0 | cif | 978,935 | 0.096 |
| g1 | sn_company_name | 167,037 | 0.086 |
| g1_sparse | sn_company_name, every 1,024th | 164 | 0.005 |
| g2 | phone_prefecture | 694,512 | 0.068 |
| g3 | phone_postal_area | 927,988 | 0.15 |
| g4 | phone_name_initial | 955,585 | 0.112 |
| g5 | sn_person_name | 788,644 | 0.148 |
| g5_sparse | sn_person_name, every 1,024th | 771 | 0.005 |
| g6 | sn_person_name_reversed | 788,644 | 0.159 |
| g6_sparse | sn_person_name_reversed, every 1,024th | 771 | 0.005 |
| g7 | person_name | 788,644 | 0.073 |
| g8 | company_name | 167,037 | 0.037 |
| g9 | company_name_deletions | 1,755,502 | 0.243 |
| g10 | person_name_deletions_postal_area | 5,557,967 | 0.84 |
| g11 | given_name_postal | 637,067 | 0.07 |
| g12 | address_phone | 908,822 | 0.08 |
| g13 | address_code_phone | 816,361 | 0.077 |
| g14 | address_name_initial | 869,207 | 0.074 |
| g15 | address_code_name_initial | 780,775 | 0.076 |
| g16 | given_name_address_code | 560,403 | 0.066 |
| g17 | cif_deletions | 12,529,081 | 1.582 |
| g18 | birth_date | 119,977 | 0.035 |
| g19 | given_name_phone | 685,920 | 0.068 |
| g20 | birth_date_deletions_prefecture | 692,494 | 0.1 |
| r0 | rule X1_CIF_PERSON_NAME | 751,541 | 0.069 |
| r1 | rule X2_CIF_COMPANY_NAME | 163,688 | 0.039 |
| r2 | rule X3_CIF_PHONE | 978,836 | 0.09 |
| r3 | rule X4_PERSON_NAME_ADDRCD_PHONE | 626,872 | 0.06 |
| r4 | rule X5_COMPANY_NAME_ADDRCD_PHONE | 136,384 | 0.041 |
| r5 | rule F1_NAME~_ADDRCD_PHONE | 816,361 | 0.096 |
| r6 | rule F2_NAME~_ADDRESS~_PHONE | 908,822 | 0.075 |
| r7 | rule F3_NAME~_CIF | 978,935 | 0.09 |
| r8 | rule F4_NAME_ADDRCD_PHONE~ | 644,378 | 0.065 |
| r9 | rule F5_COMPANY~_PHONE_POSTAL | 927,988 | 0.073 |
| r10 | rule F6_COMPANY~_ADDRCD_PHONE | 816,361 | 0.075 |
| r11 | rule F7_GIVEN_ADDRCD_PHONE | 560,348 | 0.058 |
| big | big | 32 | 0.59 |

## A lookup

**p50 201 ms, p95 230 ms, max 330 ms**; records compared: median 21, max 108.

| part | mean ms |
| --- | --- |
| open | 20.5 |
| prepare | 61.9 |
| keys | 31.4 |
| rules | 9.4 |
| score | 69.8 |

## The same as the batch path

20 of the records looked up, each also listed by `er.candidates` among the stored records plus it alone, oversized blocks gated alike, and scored by `er.match.score_fs` with the run's model: the pairs each lists, those the lookup missed or added, and the largest gap between the two weights.

| record | batch | lookup | missed | added | max_weight_gap |
| --- | --- | --- | --- | --- | --- |
| 0000000301 | 26 | 26 | 0 | 0 | 0.0 |
| 0000002737 | 21 | 21 | 0 | 0 | 3.552713678800501e-15 |
| 0000003536 | 22 | 22 | 0 | 0 | 7.105427357601002e-15 |
| 0000004901 | 23 | 23 | 0 | 0 | 3.552713678800501e-15 |
| 0000005350 | 29 | 29 | 0 | 0 | 3.552713678800501e-15 |
| 0000005358 | 18 | 18 | 0 | 0 | 3.552713678800501e-15 |
| 0000006408 | 19 | 19 | 0 | 0 | 3.552713678800501e-15 |
| 0000008034 | 21 | 21 | 0 | 0 | 3.552713678800501e-15 |
| 0000008122 | 21 | 21 | 0 | 0 | 3.552713678800501e-15 |
| 0000008280 | 24 | 24 | 0 | 0 | 3.552713678800501e-15 |
| 0000009951 | 23 | 23 | 0 | 0 | 3.552713678800501e-15 |
| 0000012147 | 21 | 21 | 0 | 0 | 3.552713678800501e-15 |
| 0000014026 | 26 | 26 | 0 | 0 | 3.552713678800501e-15 |
| 0000014513 | 47 | 47 | 0 | 0 | 3.552713678800501e-15 |
| 0000014700 | 16 | 16 | 0 | 0 | 0.0 |
| 0000015985 | 38 | 38 | 0 | 0 | 1.4210854715202004e-14 |
| 0000016324 | 25 | 25 | 0 | 0 | 3.552713678800501e-15 |
| 0000016517 | 21 | 21 | 0 | 0 | 3.552713678800501e-15 |
| 0000017893 | 22 | 22 | 0 | 0 | 3.552713678800501e-15 |
| 0000020881 | 8 | 8 | 0 | 0 | 3.552713678800501e-15 |
