[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. The synthetic world is explained in [chapter 1](guide/01-entity-resolution-and-our-task.md#where-does-the-truth-come-from).*

# Data

## Datasets

**Datasets:** one generated population of 40,000 entities (50,116 records), split by entity so a duplicate group never spans two splits. Each split uses the same file name in every layer:

| Dataset | Entities | Records | Role |
|---|---|---|---|
| `train` | 60% | 30,103 | fitting, design analyses, cross-validated threshold and decisions, Optuna objective |
| `val` | 20% | 9,966 | A/B confirmation and selection checks |
| `test` | 20% | 10,047 | final report, once per configuration |

Every table is Parquet. Only `reference/` is in git; everything else rebuilds from the scripts (`.gitignore`). The medallion
layers follow the pipeline: bronze is the records as they arrive, silver the standardized records each run keeps in its
folder, gold the resolved workspace. The reference data feeds the generator and the person-or-company name model, so it
sits outside them:

```
data/reference/*.json                       public reference data (tracked; SOURCES.md)
data/medallion/bronze/<dataset>.parquet     records as they arrive (generated)      scripts/generate.py
data/labels/<dataset>.parquet               truth, read only to choose and evaluate scripts/generate.py
data/medallion/gold/<dataset>/              each dataset resolved: a workspace     scripts/choose.py, through er.run
                                            (silver: its state/records/)
data/artifacts/models/*_final.json          the chosen configurations, the fitted model
data/artifacts/experiments/leaderboard.parquet   one row per experiment and dataset (archive/: earlier passes)
data/artifacts/optuna/*.db                  the Optuna studies, with --optuna
data/artifacts/benchmark/, demo/            workspaces of scripts/benchmark.py and the demo
```

A workspace is the same wherever it is written, by `scripts/choose.py` here or by `nayose resolve records` anywhere: `gold.parquet`, `matches/`, `rule_kept/`, `steps.json` and `state/`. `nayose` adds `qa.md`, `report.txt`, `review.parquet` and, on a full run, `kind_review.parquet`; `decisions/`, `set_aside/` and `kind_answers/` (people's person/company answers) appear when there are any. A workspace made with `nayose create workspace` also keeps its own mapping, `columns.toml`, and a copy of every records file given to it, in `inputs/` ([architecture](architecture.md#the-workspace)).

## Reference data: `data/reference/`

Built once from public sources. The downloads are not kept; `SOURCES.md` records the exact steps, filters, counts and licences.

| File | Records | Source (licence) | Content |
|---|---|---|---|
| `individual.json` | 60,000 personas, 8,405 distinct surnames | NVIDIA Nemotron-Personas-Japan (CC BY 4.0) | names parsed from the persona text; kana readings by SudachiPy; sex, age, prefecture |
| `companies.json` | 31,596 companies | Wikidata, direct company types (CC0) | name + kana (official P1814 where present, else SudachiPy); legal forms stripped |
| `addresses.json` | 46,364 towns, all 47 prefectures | geolonia/japanese-addresses (CC BY 4.0) + yubinbango-data | prefecture, city and town with kana, JIS municipality code, chome, postal code |
| `registry.json` | 60,000 corporations of three prefectures (Miyagi, Okayama, Fukuoka) | the National Tax Agency's corporate-number site (Public Data License 1.0; processed) | each name's reading, its legal form's reading and bank abbreviation, whether the form leads the name |

Two of them train the person-or-company name model, `config/kind_names.npz` (`scripts/train_name_model.py`, `er.generate.train_name_model`): `individual.json` and `registry.json`, written as `config/generator.toml`'s `kana_confusions` and `branches` say bank records write them; `companies.json` and `addresses.json` are loaded with the personas. A run reads none of them: it loads the model. It trains on one half of them only (`er.generate.name_model_split`): the companies of Miyagi and Okayama, and the first half of the shuffled personas. Fukuoka's companies and the other personas are held out, for `scripts/choose_kind.py` to test on and for `kind_problems` to draw its companies from. The rest is for the generator.

Two traps in the sources:
- **Wikidata's class tree:** 13,766 of the 16k "Japanese companies" with kana in the transitive `company` tree are dissolved municipalities. Only direct company types give real companies.
- **yubinbango prefecture codes:** they are written without the leading zero (`1`, not `01`), so they are zero-padded; unpadded, the prefectures numbered 1 to 9 would drop out of the join silently.

## Synthetic data: `scripts/generate.py`

All parameters live in `config/generator.toml`: `[population]` (`er.generate.Spec`) and `[split]` (shares and seed). `er.generate.generate` builds the population, `check` asserts its invariants, and `scripts/generate.py` writes `medallion/bronze/<split>.parquet` and `labels/<split>.parquet` (`--entities`, `--seed` and `--out` write another population, unsplit).

- **Entities:** 40,000, 20% companies. Each entity has `1 + Poisson(0.25)` records.
  - **Persons** are sampled personas, each at most once, with realistic surname frequencies (サトウ, スズキ, タカハシ …). Their addresses lie in the persona's prefecture. Sampling with replacement would make clones (same name, same prefecture) that no matcher can tell apart, so same-name pairs come only from the persona file itself.
  - **Companies** are sampled real names with a legal form before or after the name, written as each record's system writes it: カブシキガイシャ, (カ), カ), ｶﾌﾞｼｷｶﾞｲｼｬ or left out; one record in ten adds a branch (ホンシャ, トウキョウシテン …).
  - **Addresses** are real towns with random 番/号, and a real postal code and JIS code.
- **Multi-valued entities:** each entity owns `1 + Poisson(λ)` phones and addresses (λ = 2.0 for persons, 3.0 for companies: moves and new phones) and names (λ = 0.3 and 1.0: married names, other company names). Each record shows one of them.
- **Columns:**
  - IDs and codes: CONT_ID (unique everywhere: the key a user's input is joined back by), PHONE_NUM_4, CIF_ID (a duplicate keeps the entity's CIF 3% of the time, one digit off in a tenth of those)
  - person names in kana: FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA, GIVEN_NAME_KANA
  - BIRTH_DATE (persons, YYYYMMDD): 15% filled, missing independently of everything else
  - company name in kana: NYS_CNV_P_NAME_KANA
  - names in kanji, from the same reference rows as the kana (a maiden or married surname with its own kanji): FULL_NAME_KANJI, LAST_NAME_KANJI, GIVEN_NAME_KANJI (persons; 60%, 50% and 50% filled), COMPANY_NAME_KANJI (companies, 60%: the name with 株式会社 where the record writes a legal form). Fewer systems hold kanji than kana; these columns have their own fill rates and their own random draws, so every other column is exactly what it would be without them
  - postal: POST_CD, POST_CD_KANA
  - address: SOURCE_ADDR_CD, ORIGINAL_ADDRESS (as typed, in 3 formats), ADDRESS_FIVE(_KANA) (`chome-ban-go`, or `ban-go`), ADDR_CD(_KANA) (11-digit 住所コード), ADDRESS_ONE (prefecture), ADDRESS_TWO (city), ADDRESS_THREE (town), and STD_ADDRESS, built from those parts as they arrive (the filled ones joined), so it is missing only where every part is
- **Entry errors and notations:**
  - 30% of name parts get one kana typo (ガ/カ, ッ/ツ, ー/ウ … or a dropped character); the kanji of the same record keeps the right name
  - 10% of kanji name parts have one character written as its variant (斎/齋, 高/髙, 崎/﨑, 辺/邊 …: `kanji_variants`)
  - 30% of person records put a space between surname and given name; 15% of records hold every name in half-width katakana (ｻﾄｳ)
  - 10% of phones, birth dates, ORIGINAL_ADDRESS values and reused CIF IDs get one wrong digit (or, in an address, a dropped character)
- **Missingness:**
  - **Rates:** the non-null rate falls from 0.9999 to 0.6544 along the column order, counted where the column applies; BIRTH_DATE has its own rate, and STD_ADDRESS follows its parts.
  - **Correlation:** shared within the name, postal and address groups by `nesting` ρ.
- **Households:** unrelated entities sometimes share an address, which gives look-alikes that must not be merged.
- **Persons and companies, made hard to tell apart** (`er.generate.kind_problems`, off unless asked for: the benchmark, the demo and the tests turn it on; `scripts/choose_kind.py` builds its own name-only populations). One name column for every kind, NAME_KANA; real company names from `registry.json`'s held-out companies, written as bank records write them (the legal form in full, abbreviated at the front, カ)〇〇, or the end, 〇〇(カ, or left out); company records under their representative's name, the representative a person of the file, half at that person's address and phone; sole traders (legally persons) named like a shop on most of their records; a date in BIRTH_DATE on 30% of company records; and PERSON_ORG_CODE, the file's flag (1 person, 2 company), wrong on 3% of records, on half the representative-named ones and on 30% of the sole traders'. Its own random stream: the records start as `generate` made them.
- **Asserts** run on the whole population before it is split: exact rates, digit formats, kind consistency, CONT_ID unique, no CIF shared across entities, address code ↔ address 1:1.

### How hard it is

Real data holds very few direct duplicates, so the generator is calibrated to make them rare. `er.generate.profile`
measures it on the true pairs (two records of one entity; 11,472 in this population), and `scripts/generate.py` prints it:

| A true pair shares | Share |
|---|---|
| the customer ID | 2.2% |
| the exact name, as written | 9.0% |
| the phone digits | 33.1% |
| the address code | 26.7% |
| the standard address | 10.2% |
| the birth date | 1.6% |
| **direct**: the same customer ID and name, or the same name, address code and phone (what exact rules settle) | **1.0%** |
| **nothing in common**: no field equal, and the names not even close (Jaro–Winkler under 0.75) | **11.5%** |

The pairs with nothing in common can't be found by any method, so recall is read against the other 88.5%.
