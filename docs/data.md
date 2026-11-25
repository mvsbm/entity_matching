[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

# Data

What a run reads, what it makes of it, and what people give back. The method's own tables are in [architecture](architecture.md).

## The input

Records as Parquet. Locally, a file, a folder of them or a quoted glob, joined by column name (`python -m nayose build|update`); in prod, files in the bucket's `in/`, loaded into the run's dataset as the table `input` (`deploy/run.py`). Text that isn't UTF-8 is refused. Locally each column gets a name of its own: control characters dropped, a blank name numbered (`column_4`), one repeating another but for case suffixed (`TEL`, `tel` → `TEL`, `tel_2`). Both engines read column names case aside.

`nayose/config.toml` `[input]`:

| Key | Holds |
|---|---|
| `id` | the column a record's ID is read from (`CONT_ID`) |
| `columns` | every column `mapping.sql` reads; one a file lacks is read as missing |
| `nulls` | the values that mean missing (`NULL`, `\N`, `N/A`, `-` …), spaces around them or not |

## The mapping: columns to fields

`nayose/mapping.sql` turns the input's columns into the fields the method reads. The repository's maps the generated data. Each deployment has its own, in the same form, kept out of the repository: in prod the secret `nayose-mapping`, locally the file `NAYOSE_MAPPING` names. It makes two temporary tables: `input_rows`, every distinct row as given with its ID, and `mapped`, one row a record. Each of its statements is a query or a `CREATE TEMP TABLE`, one to a line ending in `;`; each table it makes has a name the method doesn't use, case aside; and its comments start with `--`, as in the method's files (a `/* */` comment with a line ending in `;` is refused: nayose would end the statement there). Any other statement is refused before anything runs, by the deploy and by a job: a write to any other table, a temporary table named like one of the method's, or a function of its own. A build makes every table it writes again; a temporary table hides the run's table of its name; and a function of its own would replace one of the method's on BigQuery but not on DuckDB. Each column is read through `read_value(column, numeric, @nulls)`; a column that isn't text is cast first. A field with several sources takes the first whose columns are all filled (`A || B` is missing when either part is).

| Field | The generated data's columns | Read by |
|---|---|---|
| `full_name` | FULL_NAME_KANA | rules, the prior |
| `person_name` | FULL_NAME_KANA, else O_PERSON_NAME_KANA, else LAST_NAME_KANA and GIVEN_NAME_KANA joined | the name comparison, rules, generators |
| `given_name` | GIVEN_NAME_KANA | the name comparison, rules, generators, the household label |
| `company_name` | NYS_CNV_P_NAME_KANA | the company comparison, rules, generators |
| `any_name` | person_name's columns, else NYS_CNV_P_NAME_KANA | the kind, the name-initial generators |
| `address` | STD_ADDRESS, else ORIGINAL_ADDRESS | the address comparison, rules, generators |
| `address_code` | SOURCE_ADDR_CD | the address comparison, rules, generators |
| `postal_code` | POST_CD, else POST_CD_KANA | the address comparison, rules, generators, the fit's sample |
| `prefecture` | ADDRESS_ONE | generators |
| `town_code`, `city` | ADDR_CD, ADDRESS_TWO | report.txt only |
| `phone` | PHONE_NUM_4 | the phone comparison, rules, generators |
| `customer_id` | CIF_ID | the cif comparison, rules, generators |
| `birth_date` | BIRTH_DATE | the birth comparison, generators |
| `kind_flag` | PERSON_ORG_CODE | the kind, where the name doesn't settle it |

**Person or company.** A written legal form says company. Otherwise the name model (`config/kind_names.npz`) decides when it is `name_line` sure (0.99), but a person's name never overrides a company flag. Otherwise `kind_flag` decides: `flag_company`'s values say company. `trust_flag = true` lets the flag decide every record. `shared_name_column = true` handles one column that holds every name: the person fields keep it on records that lean person, `company_name` on those that lean company (`design/shared_name_mapping.sql` maps such a file).

## How a value is read

`read_value` (`nayose/sql/functions.sql`) fixes what loses nothing, in this order:

- **damaged:** a value holding U+FFFD (bytes decoded wrong upstream) is missing;
- **lists:** `["8700848"]`, `['大分市']` or `[0708612]` give their first filled item; with none filled, the value is missing;
- **controls:** control characters, zero-width characters and BOMs are removed, and tabs and line breaks become one space;
- **placeholders:** one of `[input] nulls`, or spaces alone (any width), is missing;
- **numbers:** in a numeric column, `12345.0` is read as `12345`; one cut short in E notation (`1.23E+11`: its digits are gone) is missing.

Each field is then standardized (`records.sql`, step 2): NFKC, hiragana as katakana, spaces and separators dropped, legal forms stripped, kana folded, as each field's chain says. A value the chain leaves empty is missing.

## What is set aside

Rows identical in every column are kept once. These are set aside: a record without an ID (blank, of spaces of any width); a record whose ID is already in the run, so a batch given twice adds nothing; every record of an ID that holds different content, because the run can't tell which is right. The table `set_aside` keeps the latest batch's rows as given, each with its `reason`. An update whose every record is already in the run exits 0 with `added: 0`. One that has no new record for any other reason is refused.

## Placeholders

A value held by too many records to be one entity's, such as a dummy phone, is read as missing (`records.sql`, step 5). For `person_name`, `company_name`, `address_code`, `address`, `phone` and `birth_date`, a value is a placeholder when all three of these hold:

- it is held by at least `placeholder_min` records (64), or by `spread` (10) times the field's records per value if that is more;
- it is held by at least `crowd` (64) customers, counted by customer ID, else by record ID;
- its own pairs outnumber those of all the field's values that fail either test above, taken together.

A `customer_id` value is one when it passes the first test alone. Placeholders are counted over the run's records and the batch's together, and they stay with the run (the table `placeholders`). A batch is read with them as missing, and a run record holding a value newly found to be a placeholder is made again without it. report.txt's SUMMARY notes each field's. A lookup adds none.

## The run's answer: `gold`

`gold` is the medallion's gold layer (bronze → silver → gold): the run's resolved table, not labels. It gives each record's entity: `id`, `entity` (named by its smallest ID), `resolved_by` (`review` where people's decisions joined it), `kind`, `kind_p`, `kind_by`, `kind_flagged` (the engine is sure against the flag) and `entity_kind` (the entity's kind: 2 company if a record is one; 1 person if one is a person and none leans company; else 0). Nothing merges by itself: a record that no decision joins is an entity alone.

## People's decisions

A Parquet file with `id_l`, `id_r`, `decision` (`match` or `no_match`) and, optionally, `why`: a match table filled in is one. Every value is read as text and a blank one as missing; the decision is read in lower case, each pair once. A row without a decision is skipped. The file is refused for:

- a decided row without both IDs;
- rows given, but none decided;
- a decision other than `match` or `no_match`;
- a pair decided both ways;
- an ID that names no record of the run (a spreadsheet may have read `0000000151` as `151`).

A decision is stored (`decisions`: `id_l`, `id_r`, `decision`, `why`, `round`, `latest`) only when it changes its pair's latest standing; a round is one call of the decide job. The entities are connected components over the pairs whose latest decision is `match`, so a later `no_match` parts what only that pair joined. A decision kept from an earlier run, naming records the run no longer holds, joins nothing.

## The match table

`python -m nayose match --threshold T` writes `matched/points-T.parquet`; on BigQuery it is the table `matched`. It holds the pairs at T points or more, minus those whose latest decision is `no_match`, highest first:

- `decision`, empty, for people to fill in;
- `id_l` and `id_r`; `points`, `match_probability`, `rule` (a rule's name, if one joins the pair), `named` (a name was compared), `household` (it may be two people of one household: a label only), `generators` (the generators whose keys listed it);
- each record's fields side by side: `person_name_l`, `person_name_r`, and so on for `given_name`, `company_name`, `address_code`, `address`, `postal_code`, `phone`, `customer_id` and `birth_date`;
- each comparison's level and its bits: `name`, `name_bits`, then `company`, `address`, `phone`, `cif` and `birth` the same way.

## A lookup's answer

`python -m nayose lookup` prints one JSON object. `record` is the record as compared. `entities` lists those from `[lookup] at_least` points up, or joined by a rule, best first, `most` of them. Each entry gives the `entity`, its best `record`, `points`, `likely`, `rule`, `generators` (those whose keys listed it), each comparison's level (`compared`), its candidate `records` and its fields (`shown`). Then come `entities_total` (the entities found, before `most` cuts them), `at_least`, `candidates`, `likely`, `closest` (the nearest record when no entity is shown) and `checked`: each `generator` (or rule), the records its keys found in its blocks of normal size (`in_blocks`), and `why` they found none, or the `oversized` blocks it sampled, each with its `records`, `sampled`, `best` and the gate's `verdict` (`listed`, or `skipped` and why). With `--file`, `records` gives one row per entity found for each record asked about: `asked`, `entity`, `record`, `points`, `rule` and `generators`.

## Generated data

`scripts/generate.py` writes a population from `config/generator.toml` and the reference data, split by household into `train`, `val` and `test`:

```
data/reference/*.json                    public reference data, tracked (SOURCES.md: sources, licences, steps)
data/medallion/bronze/<split>.parquet    records as they arrive              scripts/generate.py
data/labels/<split>.parquet              each record's entity and household  scripts/generate.py
data/artifacts/benchmark/cost_<N>/       records.parquet and run/, a run     scripts/benchmark.py
```

`--entities`, `--seed` and `--out DIR` write one unsplit `records.parquet` and `labels.parquet` instead. `test` is held out: no work reads `data/medallion/bronze/test.parquet` or `data/labels/test.parquet`. The tests and the benchmark generate their own populations. The name model is trained from `individual.json` and `registry.json` (`scripts/train_name_model.py`); a run reads only the model.

### How hard it is

Real data holds few direct duplicates, so the generator makes them rare. `design.generate.profile` measures it on the true pairs (two records of one entity), and `scripts/generate.py` prints it: the share that shares the customer ID, the exact name, the phone, the address code, the standard address or the birth date; the share that is **direct** (the same customer ID and name, or the same name, address code and phone: what exact rules settle); and the share with **nothing in common** (no field equal, and the names under 0.75 Jaro–Winkler). No method can find that last share, so recall is read against the rest. of its 11,950 true pairs (40,000 entities, 52,115 records), 2.3% share the customer ID, 9.1% the exact name, 33.2% the phone, 27.1% the address code, 9.9% the standard address and 1.5% the birth date; 1.1% are direct (an exact rule pairs them) and 11.3% share nothing
