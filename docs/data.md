[← README](../README.md) · [Guide](guide/01-entity-resolution-and-our-task.md)

*Reference for the guide. The synthetic world is explained in [chapter 1](guide/01-entity-resolution-and-our-task.md#where-does-the-truth-come-from).*

# Data

## Datasets

**Datasets:** one generated population of 40,000 entities (50,215 records), split by entity so a duplicate group never spans two splits. Each split uses the same file name in every layer:

| Dataset | Entities | Records | Role |
|---|---|---|---|
| `train` | 60% | 30,147 | fitting, design analyses, cross-validated threshold and decisions, Optuna objective |
| `val` | 20% | 10,002 | A/B confirmation and selection checks |
| `test` | 20% | 10,066 | final report, once per configuration |

Every table is Parquet. Only `reference/` is in git; everything else rebuilds from the scripts (`.gitignore`). The medallion
layers follow the pipeline: bronze is the records as they arrive, silver the standardized records each run keeps in its
folder, gold the resolved run folder. The reference data feeds only the generator, so it sits outside them:

```
data/reference/*.json                       public reference data (tracked; SOURCES.md)
data/medallion/bronze/<dataset>.parquet     records as they arrive (generated)      scripts/generate.py
data/labels/<dataset>.parquet               truth, read only to choose and evaluate scripts/generate.py
data/medallion/gold/<dataset>/              each dataset resolved: a run folder     scripts/choose.py, through er.run
                                            (silver: its state/records/)
data/artifacts/models/*_final.json          the chosen configurations, the fitted model
data/artifacts/experiments/leaderboard.parquet   one row per experiment and dataset (archive/: earlier passes)
data/artifacts/optuna/*.db                  the Optuna studies, with --optuna
data/artifacts/benchmark/, demo/            run folders of scripts/benchmark.py and the demo
```

A run folder is the same wherever it is written, by `scripts/choose.py` here or by `scripts/resolve.py` anywhere: `gold.parquet`, `matches/`, `rule_kept/`, `steps.json` and `state/`. `scripts/resolve.py` adds `qa.md` and `review.parquet`; `decisions/` and `set_aside/` appear when there are any ([architecture](architecture.md#the-run-folder)).

## Reference data: `data/reference/`

Built once from public sources. The downloads were deleted afterwards; `SOURCES.md` records the exact steps, filters, counts and licences.

| File | Records | Source (licence) | Content |
|---|---|---|---|
| `individual.json` | 60,000 personas, 8,405 distinct surnames | NVIDIA Nemotron-Personas-Japan (CC BY 4.0) | names parsed from the persona text; kana readings by SudachiPy; sex, age, prefecture |
| `companies.json` | 31,596 companies | Wikidata, direct company types (CC0) | name + kana (official P1814 where present, else SudachiPy); legal forms stripped |
| `addresses.json` | 46,364 towns, all 47 prefectures | geolonia/japanese-addresses (CC BY 4.0) + yubinbango-data | prefecture, city and town with kana, JIS municipality code, chome, postal code |

Two traps came up while building this:
- **Wikidata's class tree:** 13,766 of the 16k "Japanese companies" with kana in the transitive `company` tree are dissolved municipalities. Only direct company types give real companies.
- **yubinbango prefecture codes:** they are written without the leading zero (`1`, not `01`), which silently dropped 9 prefectures until the codes were zero-padded.

## Synthetic data: `scripts/generate.py`

All parameters live in `config/generator.toml`: `[population]` (`er.generate.Spec`) and `[split]` (shares and seed). `er.generate.generate` builds the population, `check` asserts its invariants, and `scripts/generate.py` writes `medallion/bronze/<split>.parquet` and `labels/<split>.parquet` (`--entities`, `--seed` and `--out` write another population, unsplit).

- **Entities:** 40,000, 20% companies. Each entity has `1 + Poisson(0.25)` records.
  - **Persons** are sampled personas, each at most once, with realistic surname frequencies (サトウ, スズキ, タカハシ …). Their addresses lie in the persona's prefecture. Sampling with replacement made about 8,500 pairs of clones (same name, same prefecture) that no matcher can tell apart; same-name pairs now come only from the persona file itself.
  - **Companies** are sampled real names with a legal form (カブシキガイシャ before or after the name).
  - **Addresses** are real towns with random 番/号, and a real postal code and JIS code.
- **Multi-valued entities:** each entity owns `1 + Poisson(λ)` phones, addresses and names (λ = 0.3 for persons, 1.0 for companies). Each record shows one of them: married names, branch offices.
- **Columns:**
  - IDs and codes: CONT_ID, PHONE_NUM_4, CIF_ID (a duplicate keeps the entity's CIF half the time)
  - person names in kana: FULL_NAME_KANA, O_PERSON_NAME_KANA, LAST_NAME_KANA, GIVEN_NAME_KANA
  - company name in kana: NYS_CNV_P_NAME_KANA
  - postal: POST_CD, POST_CD_KANA
  - address: SOURCE_ADDR_CD, ORIGINAL_ADDRESS (as typed, in 3 formats), ADDRESS_FIVE(_KANA) (`chome-ban-go`, or `ban-go`), ADDR_CD(_KANA) (11-digit 住所コード), STD_ADDRESS, ADDRESS_ONE (prefecture), ADDRESS_TWO (city)
- **Entry errors:**
  - 10% of name parts get one kana typo (ガ/カ, ッ/ツ, ー/ウ … or a dropped character)
  - 5% of phones get one wrong digit
  - 5% of ORIGINAL_ADDRESS values get one wrong digit or a dropped character
- **Missingness:**
  - **Rates:** the non-null rate falls from 0.9999 to 0.6544 along the column order, counted where the column applies.
  - **Correlation:** shared within the name, postal and address groups by `nesting` ρ.
- **Households:** unrelated entities sometimes share an address, which gives look-alikes that must not be merged.
- **Asserts** run on the whole population before it is split: exact rates, digit formats, kind consistency, no CIF shared across entities, address code ↔ address 1:1.
