# Benchmark: look up

Written by `scripts/benchmark_lookup.py --entities 800000` on a generated population of 1,039,995 records: 1,037,995 run (`nayose resolve records`, 31 s), 1,000 held out and looked up one at a time by their values (`nayose match record`), and 1,000 added afterwards as an increment. Past 60,000 entities personas repeat: clones, in blocks larger than a real file's, so the times are an upper bound.

## The index

Built in **3.2 s** from the run's own files (`nayose build index`), **840 MB** on disk in the workspace's `index/`.

| table | of | rows | seconds |
| --- | --- | --- | --- |
| records | records | 1,037,995 | 0.609 |
| g0 | cif | 1,016,786 | 0.043 |
| g1 | phone_prefecture | 721,398 | 0.039 |
| g2 | phone_postal_area | 963,914 | 0.045 |
| g3 | phone_name_initial | 993,673 | 0.039 |
| g4 | person_name | 826,879 | 0.038 |
| g5 | company_name | 166,896 | 0.02 |
| g6 | company_name_deletions | 1,753,265 | 0.12 |
| g7 | person_name_deletions_postal_area | 5,839,418 | 0.369 |
| g8 | given_name_postal | 668,151 | 0.032 |
| g9 | address_phone | 943,746 | 0.039 |
| g10 | address_code_phone | 847,933 | 0.039 |
| g11 | address_name_initial | 903,619 | 0.034 |
| g12 | address_code_name_initial | 811,886 | 0.038 |
| g13 | given_name_address_code | 587,580 | 0.031 |
| g14 | cif_deletions | 13,013,929 | 0.738 |
| g15 | birth_date | 125,787 | 0.017 |
| g16 | given_name_phone | 719,208 | 0.039 |
| g17 | birth_date_deletions_prefecture | 728,670 | 0.054 |
| g18 | name_reading | 826,879 | 0.038 |
| g19 | phone_given_tail | 826,805 | 0.037 |
| g20 | postal_given_tail | 767,974 | 0.032 |
| g21 | postal_area_given_tail | 767,974 | 0.035 |
| r0 | rule X1_CIF_PERSON_NAME | 788,088 | 0.035 |
| r1 | rule X2_CIF_COMPANY_NAME | 163,452 | 0.02 |
| r2 | rule X3_CIF_PHONE | 1,016,684 | 0.039 |
| r3 | rule X4_PERSON_NAME_ADDRCD_PHONE | 657,320 | 0.034 |
| r4 | rule X5_COMPANY_NAME_ADDRCD_PHONE | 136,186 | 0.018 |
| r5 | rule F1_NAME~_ADDRCD_PHONE | 847,933 | 0.038 |
| r6 | rule F2_NAME~_ADDRESS~_PHONE | 943,746 | 0.038 |
| r7 | rule F3_NAME~_CIF | 1,016,786 | 0.038 |
| r8 | rule F4_NAME_ADDRCD_PHONE~ | 675,678 | 0.034 |
| r9 | rule F5_COMPANY~_PHONE_POSTAL | 963,914 | 0.041 |
| r10 | rule F6_COMPANY~_ADDRCD_PHONE | 847,933 | 0.039 |
| r11 | rule F7_GIVEN_ADDRCD_PHONE | 587,517 | 0.032 |

## A lookup

**p50 83 ms, p95 91 ms, max 197 ms**, the index kept open by the process as the page's server keeps it; the first, which opens it, 131 ms. Records compared: median 16, max 93.

| part | mean ms |
| --- | --- |
| prepare | 32.8 |
| keys | 21.7 |
| rules | 6.9 |
| score | 15.7 |

## Kept up to date

`nayose add records` of 1,000 records: the index brought up to date in **0.2 s** (1,000 records added, 112 whose entity or rule cluster moved); built again in full, 3.1 s. Of 20 records looked up by all their values, **20 of 20 answers** of the index kept up to date equal those of the one built again.

## The same as the batch path

20 of the records looked up, each also listed by `er.candidates` among the stored records plus it alone, oversized blocks gated alike, and scored by `er.match.score_fs` with the run's model: the pairs each lists, those the lookup missed or added, and the largest gap between the two weights.

| record | batch | lookup | missed | added | max_weight_gap |
| --- | --- | --- | --- | --- | --- |
| 0000000198 | 49 | 49 | 0 | 0 | 3.552713678800501e-15 |
| 0000000313 | 0 | 0 | 0 | 0 | 0.0 |
| 0000002426 | 1 | 1 | 0 | 0 | 0.0 |
| 0000002772 | 15 | 15 | 0 | 0 | 3.552713678800501e-15 |
| 0000005474 | 10 | 10 | 0 | 0 | 1.7763568394002505e-15 |
| 0000005557 | 9 | 9 | 0 | 0 | 3.552713678800501e-15 |
| 0000005566 | 8 | 8 | 0 | 0 | 0.0 |
| 0000006655 | 79 | 79 | 0 | 0 | 3.552713678800501e-15 |
| 0000008436 | 21 | 21 | 0 | 0 | 3.552713678800501e-15 |
| 0000009760 | 22 | 22 | 0 | 0 | 2.6645352591003757e-15 |
| 0000010336 | 17 | 17 | 0 | 0 | 0.0 |
| 0000012617 | 17 | 17 | 0 | 0 | 2.6645352591003757e-15 |
| 0000012850 | 7 | 7 | 0 | 0 | 0.0 |
| 0000013925 | 24 | 24 | 0 | 0 | 1.7763568394002505e-15 |
| 0000014275 | 18 | 18 | 0 | 0 | 3.552713678800501e-15 |
| 0000014568 | 0 | 0 | 0 | 0 | 0.0 |
| 0000014616 | 11 | 11 | 0 | 0 | 3.552713678800501e-15 |
| 0000016025 | 3 | 3 | 0 | 0 | 3.552713678800501e-15 |
| 0000016603 | 12 | 12 | 0 | 0 | 3.552713678800501e-15 |
| 0000016817 | 22 | 22 | 0 | 0 | 3.552713678800501e-15 |
