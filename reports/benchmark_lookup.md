# Benchmark: look up

Written by `scripts/benchmark_lookup.py --entities 800000` on a generated population of 1,000,338 records: 998,338 run (`nayose resolve records`, 70 s), 1,000 held out and looked up one at a time by their values (`nayose match record`), and 1,000 added afterwards as an increment. Past 60,000 entities personas repeat: clones, in blocks larger than a real file's, so the times are an upper bound.

## The index

Built in **7.2 s** from the run's own files (`nayose build index`), **844 MB** on disk in the workspace's `index/`.

| table | of | rows | seconds |
| --- | --- | --- | --- |
| records | records | 998,338 | 0.982 |
| g0 | cif | 977,954 | 0.08 |
| g1 | sn_company_name | 166,916 | 0.092 |
| g2 | phone_prefecture | 693,810 | 0.065 |
| g3 | phone_postal_area | 927,056 | 0.075 |
| g4 | phone_name_initial | 954,608 | 0.082 |
| g5 | sn_person_name | 787,788 | 0.157 |
| g6 | sn_person_name_reversed | 787,788 | 0.154 |
| g7 | person_name | 787,788 | 0.063 |
| g8 | company_name | 166,916 | 0.037 |
| g9 | company_name_deletions | 1,754,204 | 0.29 |
| g10 | person_name_deletions_postal_area | 5,551,931 | 0.788 |
| g11 | given_name_postal | 636,368 | 0.066 |
| g12 | address_phone | 907,935 | 0.082 |
| g13 | address_code_phone | 815,562 | 0.07 |
| g14 | address_name_initial | 868,333 | 0.063 |
| g15 | address_code_name_initial | 779,986 | 0.07 |
| g16 | given_name_address_code | 559,777 | 0.056 |
| g17 | cif_deletions | 12,516,539 | 1.466 |
| g18 | birth_date | 119,853 | 0.034 |
| g19 | given_name_phone | 685,161 | 0.08 |
| g20 | birth_date_deletions_prefecture | 691,673 | 0.109 |
| r0 | rule X1_CIF_PERSON_NAME | 750,721 | 0.061 |
| r1 | rule X2_CIF_COMPANY_NAME | 163,570 | 0.041 |
| r2 | rule X3_CIF_PHONE | 977,855 | 0.081 |
| r3 | rule X4_PERSON_NAME_ADDRCD_PHONE | 626,182 | 0.055 |
| r4 | rule X5_COMPANY_NAME_ADDRCD_PHONE | 136,305 | 0.033 |
| r5 | rule F1_NAME~_ADDRCD_PHONE | 815,562 | 0.063 |
| r6 | rule F2_NAME~_ADDRESS~_PHONE | 907,935 | 0.066 |
| r7 | rule F3_NAME~_CIF | 977,954 | 0.076 |
| r8 | rule F4_NAME_ADDRCD_PHONE~ | 643,668 | 0.053 |
| r9 | rule F5_COMPANY~_PHONE_POSTAL | 927,056 | 0.068 |
| r10 | rule F6_COMPANY~_ADDRCD_PHONE | 815,562 | 0.063 |
| r11 | rule F7_GIVEN_ADDRCD_PHONE | 559,722 | 0.062 |
| f_any_name | search by name | 954,704 | 0.154 |
| f_any_name_reverse | search by name, its end | 954,704 | 0.192 |
| f_given_name__kana_fold | search by name | 685,232 | 0.101 |
| f_address__address | search by address | 908,024 | 0.167 |
| f_postal_code | search by postal_code | 927,151 | 0.094 |
| f_phone | search by phone | 998,238 | 0.074 |
| f_customer_id | search by customer_id | 977,954 | 0.127 |
| f_birth_date | search by birth_date | 119,853 | 0.041 |
| f_address_code | search by address_code | 815,640 | 0.109 |

## A lookup

**p50 103 ms, p95 125 ms, max 209 ms**, the index kept open by the process as the page's server keeps it; the first, which opens it, 180 ms. Records compared: median 21, max 72.

| part | mean ms |
| --- | --- |
| prepare | 32.2 |
| keys | 36.6 |
| rules | 10.6 |
| score | 19.6 |

## A search, as a person types

Each held-out record's name searched by its first 2, 3, 4 and 5 characters (`nayose search records`): **p50 69 ms, p95 116 ms, max 222 ms** over 3,780 searches; records listed: median 76.

## Kept up to date

`nayose add records` of 1,000 records: the index brought up to date in **0.3 s** (1,000 records added, 94 whose entity or rule cluster moved); built again in full, 7.3 s. Of 20 records looked up and searched by all their values, **40 of 40 answers** of the index kept up to date equal those of the one built again.

## The same as the batch path

20 of the records looked up, each also listed by `er.candidates` among the stored records plus it alone, oversized blocks gated alike, and scored by `er.match.score_fs` with the run's model: the pairs each lists, those the lookup missed or added, and the largest gap between the two weights.

| record | batch | lookup | missed | added | max_weight_gap |
| --- | --- | --- | --- | --- | --- |
| 0000000191 | 21 | 21 | 0 | 0 | 5.329070518200751e-15 |
| 0000000301 | 26 | 26 | 0 | 0 | 3.552713678800501e-15 |
| 0000002334 | 15 | 15 | 0 | 0 | 3.552713678800501e-15 |
| 0000002666 | 20 | 20 | 0 | 0 | 3.552713678800501e-15 |
| 0000005265 | 22 | 22 | 0 | 0 | 1.4210854715202004e-14 |
| 0000005344 | 72 | 72 | 0 | 0 | 1.4210854715202004e-14 |
| 0000005353 | 26 | 26 | 0 | 0 | 5.329070518200751e-15 |
| 0000006401 | 34 | 34 | 0 | 0 | 5.329070518200751e-15 |
| 0000008114 | 29 | 29 | 0 | 0 | 3.552713678800501e-15 |
| 0000009388 | 19 | 19 | 0 | 0 | 5.329070518200751e-15 |
| 0000009942 | 23 | 23 | 0 | 0 | 5.329070518200751e-15 |
| 0000012135 | 7 | 7 | 0 | 0 | 3.552713678800501e-15 |
| 0000012360 | 22 | 22 | 0 | 0 | 1.4210854715202004e-14 |
| 0000013394 | 21 | 21 | 0 | 0 | 3.552713678800501e-15 |
| 0000013730 | 18 | 18 | 0 | 0 | 1.4210854715202004e-14 |
| 0000014011 | 20 | 20 | 0 | 0 | 3.552713678800501e-15 |
| 0000014058 | 7 | 7 | 0 | 0 | 3.552713678800501e-15 |
| 0000015414 | 22 | 22 | 0 | 0 | 5.329070518200751e-15 |
| 0000015969 | 17 | 17 | 0 | 0 | 1.4210854715202004e-14 |
| 0000016175 | 21 | 21 | 0 | 0 | 5.329070518200751e-15 |
