[← README](../README.md) · [Architecture](architecture.md)

# Using it on your records

Install it, map your columns, run it, read what it wrote. Later, add new records as they arrive, and have a person check the borderline pairs.

## 1 · Install

```bash
./setup_venv.sh                         # .venv with Python ≥ 3.12, the pinned dependencies, and the er package
.venv/bin/python -m pytest tests/       # about 10 s
```

Every script runs as `.venv/bin/python scripts/<name>.py`.

## 2 · Map your columns

The pipeline never names your columns. It works on logical fields, and `config/settings.toml` `[columns]` says which of your columns hold each one:

```toml
[columns]
id = "CONT_ID"                                        # one column
address = [["STD_ADDRESS"], ["ORIGINAL_ADDRESS"]]     # fallbacks: the first filled one wins
person_name = { sources = [["FULL_NAME_KANA"], ["LAST_NAME_KANA", "GIVEN_NAME_KANA"]], normalize = ["strip_spaces"] }
                                                      # an inner list is joined: last name, then given name
```

The fields, and which ones a run needs (`[fields]` in `config/final.toml`):

| Field | Holds | Needed |
|---|---|---|
| `id` | a record ID, filled and unique | yes: the run stops without it |
| `person_name`, `company_name` | the name of a person or of a company, in katakana | at least one of the two |
| `full_name`, `given_name`, `any_name` | the full name; the given name alone; a person's or a company's name | optional |
| `address`, `address_code`, `postal_code`, `prefecture` | the address in any format; an address code; the postal code; the prefecture | optional |
| `phone` | the phone number's last four digits | optional |
| `customer_id` | the ID another system gave the customer | optional |
| `entity` | the true entity, in labelled files only | never read by a run |

- **A missing optional field** turns off only the rules, keys and comparison levels that read it. The run lists them in `qa.md`.
- **Every column is read as text.** A blank value, or one made only of spaces (full-width ones included), counts as missing.
- **Other names for the same information** need only `[columns]`. Another language needs `[locale]`. A different kind of record needs a new `config/pipeline.toml`, chosen again with `scripts/choose.py` on labelled or synthetic data ([architecture](architecture.md#1--context-two-loops)).

## 3 · Run

```bash
.venv/bin/python scripts/resolve.py --input customers.csv --output runs/customers
```

| Option | Does |
|---|---|
| `--input` | a CSV or Parquet file, or a quoted glob of them: `'data/in/*.parquet'` |
| `--output` | the run folder. A full run refuses a folder that already holds a run |
| `--overwrite` | replaces the run in `--output` |
| `--increment` | adds the records to the run in `--output` ([section 5](#5--add-new-records)) |
| `--decisions` | applies people's decisions to the run in `--output`, instead of `--input` ([section 6](#6--review-and-decide)) |
| `--compute KEY=VALUE …` | DuckDB limits for this run: `memory_limit=8GB`, `threads=4`, `temp_directory=<folder>`. Past the memory limit, DuckDB spills to that folder |
| `--pipeline` | another pipeline file. Default: `config/final.toml` |
| `--model` | a model fitted before, used instead of fitting on this file |

The run needs no labels: it fits its model on the file itself. What each step does, and what it costs: [architecture, the run](architecture.md#3--the-run).

## 4 · Read the outputs

Everything is in the run folder.

| File | One row per | Holds | Use it to |
|---|---|---|---|
| `gold.parquet` | record | `cluster_id` (the smallest record ID of its cluster); `resolved_stage` (`deterministic`, `probabilistic` or `review`; empty for a record found alone); `resolved_by` (the rule, `fs` for the model, or `review` for people) | give every record its entity |
| `matches/` | accepted pair | both IDs; `match_weight` in bits; `match_probability`; `sources`, the candidate generators that listed it | see why two records were joined |
| `rule_kept/` | pair a rule accepted | both IDs, the rule and its stage | audit the rules |
| `qa.md` | | each field's fill rate (flagged under 5%); what was turned off; each step's Big-O, time and memory; pairs by weight; cluster sizes; the 10 largest clusters; match patterns no key guarantees | check the run without labels |
| `review.parquet` | pair for people | `why` (`decide` or `audit`); an empty `decision`; both records' compared fields; per comparison, the level reached and its bits; `accepted` | decide the pairs just below the line, audit those just above ([section 6](#6--review-and-decide)) |
| `decisions/` | decided pair | both IDs and `decision`, one part per file people gave back | what people decided; a full run applies it again |
| `steps.json` | step | its Big-O with the numbers filled in, seconds, peak memory | see the cost |
| `state/` | | the standardized records, the rules' clusters, the model, the u it scored with | needed by `--increment`; don't edit |

```python
import pandas as pd
gold = pd.read_parquet("runs/customers/gold.parquet")
matches = pd.read_parquet("runs/customers/matches")      # a folder of parts reads as one table
```

## 5 · Add new records

```bash
.venv/bin/python scripts/resolve.py --input new.csv --output runs/customers --increment
```

- **The same model.** The batch is scored with the model the full run fitted, so weights stay comparable. The exact agreements' u are counted again on every record. A sampled u is measured again only once its drift, read from those exact counts, exceeds its own sampling error; before that, a new sample would only redraw the noise.
- **Compared with everything.** Each new record is compared with every stored one, and can join an existing cluster. Earlier answers stand.
- **Stored records aren't compared again.** A record left alone gets a new chance whenever a new record matches it, directly or through a third record. But two stored records that were not matched with each other stay apart until a full run (`--overwrite`) compares them again, for example after the matching changes.
- **Cost follows the batch.** The joins start from the new records, so a small batch is fast whatever the run's size: into a million-record run, 1,000 new records take about 2 s, plus the write.
- **New records only.** A record whose ID is already in the run stops the increment. An increment adds; it doesn't update.
- **Safe to interrupt.** An interrupted write is finished by the next increment.

## 6 · Review and decide

The run accepts a pair at 6 bits or more. Just below that line, from 4 to 6 bits, is the threshold rule's safety margin: pairs that were never wrong on cross-validated training data, but are held back in case of noise. People decide them. On the synthetic test split, all 47 such pairs were true, and accepting them raised recall from 89.9% to 92.2%, with no false merge.

`review.parquet` has two kinds of rows, named in `why`:

- **decide:** every pair of clusters whose best link scored in the margin, one row per pair of clusters, highest first. Pairs already decided are left out.
- **audit:** about 50 accepted pairs up to 4 bits above the line, a few from each 1-bit band. A wrong one is a false merge.

Each row shows the two records' compared fields side by side, then, per comparison, the level the pair reached (for example "names very close") and the bits it earned. The bits, plus the starting point, add up to `match_weight`. `accepted` says what the run decided.

Fill in `decision` with `match` or `no_match`, leave the rest empty, and give the file back:

```bash
.venv/bin/python scripts/resolve.py --output runs/customers --decisions reviewed.parquet
```

- **`match`** joins the two clusters at once, scoring nothing. A record joined only this way gets `resolved_by` = `review`.
- **`no_match`** splits nothing now. It is kept, and a full run never accepts the pair. It applies to that pair only: a third record can still join the two.
- **Kept for good.** Decisions are stored in `decisions/`, which a full run with `--overwrite` on the same folder applies again. Any file with the two ID columns and `decision` works; rows without a decision are skipped.

Wrong audit pairs are also the evidence for changing the matching. In `qa.md`, a cluster far larger than the rest is the first sign of over-merging.

`review.parquet` holds records. Keep it wherever the data itself is kept.

## 7 · When a run stops

| The message says | Why | What to do |
|---|---|---|
| `mandatory fields absent from the file: id (expected …)` | `[columns]` maps `id` to a column the file lacks | fix `id` in `[columns]` |
| `no field of these groups is in the file` | neither `person_name` nor `company_name` is in the file | map at least one |
| `… must be filled and unique` | some IDs are empty or repeated | fix the IDs first |
| `derived column … shadows an input column` | the file has a column named like a logical field | rename that column |
| `over budget on this file` | a key would make too many pairs: more than 5 per record, or one block of over 5,000 records. Usually a placeholder value repeated in many records, such as one dummy phone number | blank the placeholder out, then run again |
| `… already holds a run` | a full run into a used folder | add `--overwrite`, or pick another folder |
| `… are already in the run: an increment adds new records only` | the batch repeats stored IDs | remove them from the batch |
| `the model was fitted on other comparison levels` | `--model` was fitted on another pipeline, or on a file with other fields | run without `--model` |
| `a decision is match or no_match` | the `decision` column holds another value | fix those rows |
| `pairs decided both ways` | one pair is marked both `match` and `no_match` | keep one |
| `records not in the run` | the file names IDs the run in `--output` doesn't have | check `--output`, or the IDs |

The budget is checked before any join, so a run that would explode stops within seconds instead of running out of memory.

## Development scripts

For changing the matching or measuring it, on synthetic labelled data:

| To | Run | Time |
|---|---|---|
| generate the synthetic train, val and test files | `scripts/generate.py` | ~5 s |
| choose the configuration on them | `scripts/choose.py` (`--optuna` adds the searches) → `config/final.toml`, `reports/choose.md` | ~5 min |
| measure quality and cost on growing files | `scripts/benchmark.py --memory-limit 8GB` → `reports/benchmark.md` | ~5 min |
| see every step on a small file | `notebooks/demo.ipynb`, or `scripts/export_pdfs.py` for its PDF (first: `.venv/bin/python -m playwright install chromium`) | ~1 min |
