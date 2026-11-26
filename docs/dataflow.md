[← README](../README.md) · [Architecture](architecture.md)

# Data flow

The run's SQL files, its tables, its jobs and each job's data flow, all drawn from the code by `scripts/dataflow.py`, which a test holds this page to.

## The SQL files

| File | In short | In the code |
|---|---|---|
| `mapping.sql` | Turns the input's columns into the fields nayose works with. | Each column goes through `read_value`; a field takes its first fully filled source. Writes `input_rows` (each distinct row, with `nayose_id`) and `mapped`. The repository's maps the generated data; a deployment deploys its own (`deploy.py --mapping`; in prod, the secret `nayose-mapping`). |
| `functions.sql` | The functions every job creates first. | The intake (`read_value`, `blank`, `trimmed`); the comparison levels (`name_level` with `name_score`, `gamma_company`, `gamma_address`, `gamma_phone`, `gamma_cif`, `gamma_birth`); the rules' fuzzy tests (`near_*`); shared steps (`pairs_of`, `padded`, `numbers_dashed`). |
| `records.sql` | Stage 1: adds a batch to the run's records, cleaned, each marked person or company. | (1) `set_aside`: no ID, an ID already in the run, or one ID with two contents. (2) Standardizes: `nfkc`, katakana, `strip_spaces`, `strip_separators`, `padded`, `strip_legal_form`, `kana_fold`. (3) `kind`: a written legal form; else the name model (logistic regression on character n-grams, `name_weights`) at `name_line`; else the file's flag. (4) Each name to its side's fields. (5) `placeholders` (`placeholder_min`, `spread`, `crowd`). (6) Writes `records` with each field's copies (`field__steps`); a run record holding a new placeholder is made again (`redone`). |
| `fit.sql` | Stage 2, a build only: estimates how many points each comparison level is worth, without labelled pairs. | Fellegi–Sunter. The sample: `fit_records` records, whole postal areas by `er_hash`. λ from the near-certain rules' pairs; m by EM (`fit_model`, `nayose/em.py`) on pairs blocked on phone, then address; u counted exactly where equality allows and sampled elsewhere, on the sample and on the file. Writes `model` and `fit`. |
| `score.sql` | Stage 3: finds the pairs worth comparing and gives each its points. Nothing merges here. | The rules' pairs (`rule_keys`); the 22 generators' keys (`every_key`: exact, deletion and reading keys); the gate on blocks of `oversized` records (kept only if a sample holds a pair at `search_floor`); `bound_of`, an upper bound from cheap tests, so the costly comparisons run only where needed; then each comparison's level and `points_of` (the prior plus each level's bits). Writes `cands` and `scored` (the pairs from `keep_from` points up, and every rule pair). |
| `decide.sql` | Stores people's decisions and groups records into entities from them. | Reads `given` (`given_text`, `said`) and refuses a wrong file with its fix (`ERROR`); adds to `decisions` each decision that changes its pair's latest; `gold` is the connected components of the latest-`match` pairs (`entities_of`, `nayose/entities.py`), each named by its smallest ID. A build and an update run it without `given`. |
| `match.sql` | Makes the review list. | `matched`: the `scored` pairs at `@threshold` points or more, less those whose latest decision is `no_match`, with both records' fields, each level's label and bits (`model`), `household()`, and empty `decision` and `why`. |
| `report.sql` | The run's counts for `report.txt`, never a record's value. | The `report_*` temporary tables `nayose.report_text` prints: counts, each field's fill and look (`[report.looks]`), score bands, each generator's candidates. |
| `lookup.sql` | Finds which entities one record would match, changing nothing. | After `records.sql` and `score.sql` ran on the asked record in temporary tables (`nayose.lookup`): its entities at `@at_least` points or more, or joined by a rule, best first, and each generator's look-up. On BigQuery, `run.py` stores the answer in `looked_up`. |

## The tables

| Table | In short | Key columns |
|---|---|---|
| `input` | The batch a job reads: a file `run.py` loads, or the table the mapping's `FROM` names. |  |
| `name_weights` | The person-or-company name model, loaded by the deploy. | `term`, `coef` |
| `given` | People's decisions, loaded for `decide`. |  |
| `records` | Every record of the run, cleaned. | `id`, `kind`, `customer`, `batch` |
| `set_aside` | The latest batch's rows that weren't added. | `reason` |
| `placeholders` | Values too common to be evidence, read as missing. | `field`, `value`, `n` |
| `fit` | The fit's result as a whole; an update scores with it. | `probability`, `fitted` |
| `model` | How many points each comparison level gives. | `comparison`, `gamma`, `label`, `bits` |
| `rule_keys` | Each record's keys for the rules. | `i`, `key`, `id` |
| `every_key` | Each record's keys for finding pairs: the key index. | `g`, `key`, `id` |
| `cands` | The latest batch's candidate pairs. | `l`, `r`, `generators` |
| `scored` | Every pair kept, with its points. | `id_l`, `id_r`, `points`, `rule` |
| `decisions` | Every decision people gave, by round. | `id_l`, `id_r`, `decision`, `latest` |
| `gold` | **The answer:** each record's entity. | `id`, `entity` |
| `matched` | The review list. | `decision`, `why`, `id_l`, `id_r`, `points` |
| `method` | The installed method's fingerprint; every job after a build checks it. | `fingerprint` |

Not drawn below: `compared`: a view of `records`, the columns `fit.sql` and `score.sql` read. `looked_up`: on BigQuery, each lookup's answer (`asked`, `asked_at`, `answer`). `job_running` and `before__<table>`: `run.py`'s mark of a job under way, and the clones of the tables it writes; both dropped when it ends.

### Every table's columns

Each of the run's tables with its columns, as BigQuery types them; a line joins a column to the table whose row it names.

```mermaid
erDiagram
  cands {
    STRING l
    STRING r
    STRING generators
  }
  decisions {
    STRING id_l
    STRING id_r
    STRING decision
    STRING why
    INT64 round
    BOOL latest
  }
  every_key {
    INT64 g
    STRING key
    STRING id
  }
  fit {
    FLOAT64 probability
    INT64 fit_records
    INT64 records
    FLOAT64 prior_bits
    JSON notes
    STRING fitted
  }
  gold {
    STRING id PK
    STRING entity
    STRING resolved_by
    INT64 kind
    FLOAT64 kind_p
    STRING kind_by
    BOOL kind_flagged
    INT64 entity_kind
  }
  matched {
    STRING decision
    STRING why
    STRING id_l
    STRING id_r
    FLOAT64 points
    FLOAT64 match_probability
    STRING rule
    BOOL named
    BOOL household
    STRING generators
    STRING person_name_l
    STRING person_name_r
    STRING given_name_l
    STRING given_name_r
    STRING company_name_l
    STRING company_name_r
    STRING address_code_l
    STRING address_code_r
    STRING address_l
    STRING address_r
    STRING postal_code_l
    STRING postal_code_r
    STRING phone_l
    STRING phone_r
    STRING customer_id_l
    STRING customer_id_r
    STRING birth_date_l
    STRING birth_date_r
    STRING name
    FLOAT64 name_bits
    STRING company
    FLOAT64 company_bits
    STRING address
    FLOAT64 address_bits
    STRING phone
    FLOAT64 phone_bits
    STRING cif
    FLOAT64 cif_bits
    STRING birth
    FLOAT64 birth_bits
  }
  method {
    STRING fingerprint
  }
  model {
    INT64 position
    STRING comparison
    INT64 gamma
    STRING label
    STRING agreement
    FLOAT64 m
    FLOAT64 u
    FLOAT64 file_m
    FLOAT64 file_u
    FLOAT64 bits
  }
  name_weights {
    STRING term
    FLOAT64 coef
  }
  placeholders {
    STRING field
    STRING value
    INT64 n
  }
  records {
    STRING id PK
    STRING given_name
    STRING any_name
    STRING address
    STRING address_code
    STRING postal_code
    STRING prefecture
    STRING town_code
    STRING city
    STRING phone
    STRING customer_id
    STRING birth_date
    INT64 kind
    FLOAT64 kind_p
    STRING kind_by
    BOOL kind_flagged
    STRING full_name
    STRING person_name
    STRING company_name
    STRING person_name__kana_fold
    STRING company_name__nfkc_strip_legal_form_kana_fold
    STRING address__address
    STRING postal_code__first3
    STRING any_name__initial
    STRING given_name__kana_fold
    STRING address__address_first3
    STRING person_name__kana_fold_long_vowel
    STRING person_name__kana_fold_one_byte
    STRING company_name__nfkc_strip_legal_form_kana_fold_one_byte
    STRING address__address_one_byte_hash
    STRING person_name__kana_fold_long_vowel_last3
    INT64 person_name__kana_fold_letters_lo
    INT64 person_name__kana_fold_letters_hi
    STRING customer
    INT64 batch
  }
  rule_keys {
    INT64 i
    STRING key
    STRING id
  }
  scored {
    STRING id_l
    STRING id_r
    FLOAT64 points
    FLOAT64 match_probability
    STRING generators
    STRING rule
    BOOL named
    INT64 gamma_name
    INT64 gamma_company
    INT64 gamma_address
    INT64 gamma_phone
    INT64 gamma_cif
    INT64 gamma_birth
  }
  set_aside {
    STRING CONT_ID
    STRING PHONE_NUM_4
    STRING CIF_ID
    STRING FULL_NAME_KANA
    STRING O_PERSON_NAME_KANA
    STRING POST_CD
    STRING POST_CD_KANA
    STRING LAST_NAME_KANA
    STRING GIVEN_NAME_KANA
    STRING BIRTH_DATE
    STRING NYS_CNV_P_NAME_KANA
    STRING SOURCE_ADDR_CD
    STRING ORIGINAL_ADDRESS
    STRING ADDRESS_FIVE
    STRING ADDRESS_FIVE_KANA
    STRING ADDR_CD_KANA
    STRING ADDR_CD
    STRING STD_ADDRESS
    STRING ADDRESS_ONE
    STRING ADDRESS_TWO
    STRING ADDRESS_THREE
    STRING FULL_NAME_KANJI
    STRING LAST_NAME_KANJI
    STRING GIVEN_NAME_KANJI
    STRING COMPANY_NAME_KANJI
    STRING PERSON_ORG_CODE
    STRING reason
  }
  records ||--o{ rule_keys : "id"
  records ||--o{ every_key : "id"
  records ||--o{ cands : "l"
  records ||--o{ cands : "r"
  records ||--o{ scored : "id_l"
  records ||--o{ scored : "id_r"
  model ||--o{ scored : "gamma_name"
  records ||--o{ decisions : "id_l"
  records ||--o{ decisions : "id_r"
  records ||--o{ gold : "id"
  records ||--o{ gold : "entity"
  records ||--o{ matched : "id_l"
  records ||--o{ matched : "id_r"
```

## The jobs

Each job's stages, in order; an arrow from one job to another names the tables the first writes that the second reads and doesn't write itself.

```mermaid
flowchart LR
  subgraph build_job[build]
    build_functions[functions] --> build_mapping[mapping]
    build_mapping[mapping] --> build_records[records]
    build_records[records] --> build_fit[fit]
    build_fit[fit] --> build_score[score]
    build_score[score] --> build_decide[decide]
    build_decide[decide] --> build_report[report]
  end
  subgraph update_job[update]
    update_functions[functions] --> update_mapping[mapping]
    update_mapping[mapping] --> update_records[records]
    update_records[records] --> update_score[score]
    update_score[score] --> update_decide[decide]
    update_decide[decide] --> update_report[report]
  end
  subgraph decide_job[decide]
    decide_functions[functions] --> decide_decide[decide]
  end
  subgraph match_job[match]
    match_functions[functions] --> match_match[match]
  end
  build_job -->|fit, model| update_job
  build_job -->|records| decide_job
  build_job -->|model, records, scored| match_job
  update_job -->|records| decide_job
  update_job -->|records, scored| match_job
  decide_job -->|decisions| build_job
  decide_job -->|decisions| update_job
  decide_job -->|decisions| match_job
```

## Each job's data flow

A cylinder is one of the run's tables; a slanted box, a table loaded into the dataset (a file, or the deploy's name model). An arrow says that the stage it names writes its end from its start: a statement names the one to write the other, even one a build has just emptied. The temporary tables, views and WITHs between them are folded into the arrow. Not drawn: a table's reads of its own rows, report.sql (it writes only temporary report_ tables, which report.txt reads), and `method`, which the procedure writes after a build and checks first in every other job.

### build

Stages: functions, mapping, records, fit, score, decide, report.

```mermaid
flowchart LR
  cands[(cands)]
  decisions[(decisions)]
  every_key[(every_key)]
  fit[(fit)]
  gold[(gold)]
  input[/input/]
  model[(model)]
  name_weights[/name_weights/]
  placeholders[(placeholders)]
  records[(records)]
  rule_keys[(rule_keys)]
  scored[(scored)]
  set_aside[(set_aside)]
  cands -->|score| scored
  decisions -->|decide| gold
  every_key -->|score| cands
  fit -->|score| cands
  fit -->|fit| model
  fit -->|score| scored
  input -->|records| placeholders
  input -->|records| records
  input -->|records| set_aside
  model -->|score| cands
  model -->|score| scored
  name_weights -->|records| placeholders
  name_weights -->|records| records
  placeholders -->|score| cands
  placeholders -->|score| every_key
  placeholders -->|records| records
  placeholders -->|score| rule_keys
  placeholders -->|score| scored
  records -->|score| cands
  records -->|score| every_key
  records -->|fit| fit
  records -->|decide| gold
  records -->|fit| model
  records -->|records| placeholders
  records -->|score| rule_keys
  records -->|score| scored
  records -->|records| set_aside
  rule_keys -->|score| scored
```

### update

Stages: functions, mapping, records, score, decide, report.

```mermaid
flowchart LR
  cands[(cands)]
  decisions[(decisions)]
  every_key[(every_key)]
  fit[(fit)]
  gold[(gold)]
  input[/input/]
  model[(model)]
  name_weights[/name_weights/]
  placeholders[(placeholders)]
  records[(records)]
  rule_keys[(rule_keys)]
  scored[(scored)]
  set_aside[(set_aside)]
  cands -->|score| scored
  decisions -->|decide| gold
  every_key -->|score| cands
  fit -->|score| cands
  fit -->|score| scored
  input -->|records| placeholders
  input -->|records| records
  input -->|records| set_aside
  model -->|score| cands
  model -->|score| scored
  name_weights -->|records| placeholders
  name_weights -->|records| records
  placeholders -->|score| cands
  placeholders -->|score| every_key
  placeholders -->|records| records
  placeholders -->|score| rule_keys
  placeholders -->|score| scored
  records -->|score| cands
  records -->|score| every_key
  records -->|decide| gold
  records -->|records| placeholders
  records -->|score| rule_keys
  records -->|score| scored
  records -->|records| set_aside
  rule_keys -->|score| scored
```

### decide

Stages: functions, decide.

```mermaid
flowchart LR
  decisions[(decisions)]
  given[/given/]
  gold[(gold)]
  records[(records)]
  decisions -->|decide| gold
  given -->|decide| decisions
  records -->|decide| gold
```

### match

Stages: functions, match.

```mermaid
flowchart LR
  decisions[(decisions)]
  matched[(matched)]
  model[(model)]
  records[(records)]
  scored[(scored)]
  decisions -->|match| matched
  model -->|match| matched
  records -->|match| matched
  scored -->|match| matched
```
