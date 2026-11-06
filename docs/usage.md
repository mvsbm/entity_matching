[← README](../README.md) · [Architecture](architecture.md)

# Using it on your records

Install it, map your columns, run it, read what it wrote. Later, add new records as they arrive, and have a person check the borderline pairs.

## 1 · Install

```bash
./setup_venv.sh                         # .venv with Python ≥ 3.12, the pinned dependencies, and the er package
.venv/bin/python -m pytest tests/       # engine checks and whole runs
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
| `address`, `address_code`, `postal_code`, `town_code`, `city`, `prefecture` | the address in any format; an address code; the postal code; the town code (municipality, town and chome); the city; the prefecture | optional |
| `phone` | the phone number's last four digits | optional |
| `customer_id` | the ID another system gave the customer | optional |
| `birth_date` | a person's birth date, in one format throughout, so equal dates are equal strings | optional |
| `entity` | the true entity, in labelled files only | never read by a run |

- **A missing optional field** turns off only the rules, keys and comparison levels that read it. The run lists them in `qa.md`.
- **Names are matched loosely.** A column whose name differs from the mapping only in case, width or separators (`cont_id`, `ＣＯＮＴ＿ＩＤ`) is used, and the summary says so.
- **Every column is read as text.** A blank value, or one made only of spaces (full-width ones included), counts as missing. A code stored as a number (`599` for `0599`) is read as text with a warning: its leading zeros were lost before the file reached the run.
- **A nearly empty field** is used where it is filled. If no two records of the fit's sample share it, the fit learns nothing from it, and the summary says so.
- **A field the run needs and no column holds** stops the run with the file's columns and, for each missing field, the column whose values look most like it, as lines to paste into `[columns]`. These suggestions are never applied without you.

Check a file and its mapping in seconds, before a long run:

```bash
.venv/bin/python scripts/resolve.py --input customers.parquet --check
```

It prints each field, its fill rate and the columns it comes from, what would be turned off, each key's pairs per record, and the blocks of 64 or more records that the run will check on a sample. For each field, two shares from a sample of 10,000 records point at a mistake before it costs a run:

- **looks right**: the share of filled values that look like the field (`[locale.detect]`). A low share is a wrong column, or a format the comparisons don't expect: a full phone number where the last four digits are expected, dates written two ways.
- **top value**: the share of filled values held by the most common one. A placeholder (`0000`, `19000101`) shows as one value on many records, and the model counts it as an agreement between every two records that hold it. A field whose values are few by nature, such as the prefecture, has a high share anyway.
- **Other names for the same information** need only `[columns]`. Another language needs `[locale]`. A different kind of record needs a new `config/pipeline.toml`, chosen again with `scripts/choose.py` on labelled or synthetic data ([architecture](architecture.md#1--context-two-loops)).

## 3 · Run

```bash
.venv/bin/python scripts/resolve.py --input customers.parquet --output runs/customers
```

| Option | Does |
|---|---|
| `--input` | a Parquet file, a quoted glob (`'data/in/*.parquet'`) or a folder of them; several files are read together by column name |
| `--check` | reads and maps `--input`, counts each key's pairs, resolves nothing ([section 2](#2--map-your-columns)) |
| `--output` | the run folder. A full run refuses a folder that already holds a run |
| `--overwrite` | replaces the run in `--output` |
| `--increment` | adds the records to the run in `--output` ([section 5](#5--add-new-records)) |
| `--decisions` | applies people's decisions to the run in `--output`, instead of `--input` ([section 6](#6--review-and-decide)) |
| `--compute KEY=VALUE …` | DuckDB limits for this run, overriding `config/settings.toml` `[compute]`: `memory_limit=8GB`, `threads=4`, `temp_directory=<folder>`. Past the memory limit, DuckDB spills to that folder |
| `--pipeline` | another pipeline file. Default: `config/final.toml` |
| `--model` | a model fitted before, used instead of fitting on this file |

`[compute]` in `config/settings.toml` sets the same three for every run. Left empty, each keeps DuckDB's default: all cores, 80% of the memory, and spilling to `.tmp/` under the folder the run starts in. Before any join, the run checks that the pairs fit in memory plus the room DuckDB may spill to: 90% of that disk's free space.

The run needs no labels: it fits its model on the file itself. It prints each step as it finishes, with its time and what it did, then a summary: records, entities, who joined them (the rules, the model, people), the model's links and how many of them it expects to be false, the pairs to decide, and notes. The expected false links are the sum of 1 − match probability over the model's links: the model's own estimate, with no labels. A bigger file holds more people who share a name and an address, so at a fixed threshold the count grows with the file: on generated files, 0.84 at 12,532 records, 4.38 at 74,959 (1 and 3 found) and 30.11 at a million ([benchmark](../reports/benchmark.md)). A note says what the loader fixed, a field filled in under 5% of records (often a mapping mistake), a part turned off, or what the fit couldn't learn from. What each step does, and what it costs: [architecture, the run](architecture.md#3--the-run).

## 4 · Read the outputs

Everything is in the run folder.

| File | One row per | Holds | Use it to |
|---|---|---|---|
| `gold.parquet` | record | `cluster_id` (the smallest record ID of its cluster); `resolved_stage` (`deterministic`, `probabilistic` or `review`; empty for a record found alone); `resolved_by` (the rule, `fs` for the model, or `review` for people) | give every record its entity |
| `matches/` | accepted pair | both IDs; `match_weight` in bits; `match_probability`; `sources`, the candidate generators that listed it | see why two records were joined |
| `rule_kept/` | pair a rule accepted | both IDs, the rule and its stage | audit the rules |
| `qa.md` | | the summary; each field's fill rate (flagged under 5%), the share that looks right and the share of its most common value; what was turned off; each step's Big-O, time and memory; pairs by weight; cluster sizes; the 10 largest clusters; match patterns no key guarantees | check the run without labels |
| `report.txt` | | the run on one page of plain text, with no record's value in it: what ran (the code, the tracked files changed in this copy, the pipeline, the machine's limits), the summary, the fields, scores and links by weight with the false links expected, cluster sizes, each step's time and memory, the model's m, u and bits per level, the costliest blocks | send it to whoever helps with the run ([section 7](#7--when-something-is-wrong)) |
| `review.parquet` | pair for people | `why` (`decide` or `audit`); an empty `decision`; both records' compared fields; per comparison, the level reached and its bits; `accepted` | decide the pairs just below the line and those above it with no name compared, audit those just above ([section 6](#6--review-and-decide)) |
| `decisions/` | decided pair | both IDs and `decision`, one part per file people gave back | what people decided; a full run applies it again |
| `set_aside/` | record not resolved | the record as read, and `reason`: no ID; the same ID with different content; already in the run | fix them and add them with `--increment` |
| `steps.json` | step | its Big-O with the numbers filled in, seconds, peak memory | see the cost |
| `state/` | | the standardized records, the rules' clusters, the model, the u it scored with | needed by `--increment`; don't edit |

```python
import pandas as pd
gold = pd.read_parquet("runs/customers/gold.parquet")
matches = pd.read_parquet("runs/customers/matches")      # a folder of parts reads as one table
```

## 5 · Add new records

```bash
.venv/bin/python scripts/resolve.py --input new.parquet --output runs/customers --increment
```

- **The same model.** The batch is scored with the model the full run fitted, so weights stay comparable. The u of the exact and one-digit-off levels are counted again on every record, before the rules. A sampled u is measured again only once its drift, read from those exact counts, exceeds its own sampling error; before that, a new sample would only redraw the noise.
- **Compared with everything.** Each new record is compared with every stored one, and can join an existing cluster. Earlier answers stand.
- **Stored records aren't compared again.** A record left alone gets a new chance whenever a new record matches it, directly or through a third record. But two stored records that were not matched with each other stay apart until a full run (`--overwrite`) compares them again, for example after the matching changes.
- **Cost follows the batch.** The joins start from the new records, so a small batch is fast whatever the run's size: into a million-record run, 1,000 new records take about 4 s.
- **New records only.** A record whose ID is already in the run is set aside: an increment adds, it doesn't update. So running the same batch twice is harmless; the second time prints "nothing new".
- **Safe to interrupt.** An interrupted write is finished by the next increment.

## 6 · Review and decide

The run accepts a pair at 8 bits or more. Just below that line, from 6 to 8 bits, is the threshold rule's safety margin: pairs that were never wrong on cross-validated training data, but are held back in case of noise. People decide them. On the synthetic val split, the margin holds 112 pairs, all true: accepting them would raise recall from 46.3% to 51.7%, with no false merge. One grid step lower, at 4 bits, the first false pair appears ([results](results.md)).

`review.parquet` has two kinds of rows, named in `why`:

- **decide:** every pair of clusters whose best link scored in the margin, or above the line with no name compared (the name check, `[model] needs`: a person and a company at one address, a record with no name), one row per pair of clusters, highest first. Pairs already decided are left out. An increment keeps the rows still open, and any decision typed into the sheet but not yet given back, and adds its own.
- **audit:** about 50 accepted pairs up to 4 bits above the line, a few from each 1-bit band. A wrong one is a false merge.

Each row shows the two records' compared fields side by side, then, per comparison, the level the pair reached (for example "fold JW high": the kana-folded names close by Jaro–Winkler) and the bits it earned. The bits, plus the starting point, add up to `match_weight`. `accepted` says what the run decided.

Fill in `decision` with `match` or `no_match`, leave the rest empty, and give the file back:

```bash
.venv/bin/python scripts/resolve.py --output runs/customers --decisions reviewed.parquet
```

- **`match`** joins the two clusters at once, scoring nothing. A record joined only this way gets `resolved_by` = `review`.
- **`no_match`** splits nothing at once. It is kept, and a full run never accepts the pair. It applies to that pair only: a third record can still join the two.
- **Kept for good.** Decisions are stored in `decisions/`, which a full run with `--overwrite` on the same folder applies again. Any file with the two ID columns and `decision` works; rows without a decision are skipped.

Wrong audit pairs are also the evidence for changing the matching. In `qa.md`, a cluster far larger than the rest is the first sign of over-merging.

`review.parquet` holds records. Keep it wherever the data itself is kept.

## 7 · When something is wrong

What the run handles by itself, and reports in its summary:

| Found | Done |
|---|---|
| rows identical in every column | kept once |
| a record without an ID, or one ID holding different records | set aside in `set_aside/`; the run goes on |
| a column named like the mapping but for case, width or separators | used |
| several files with different columns | read together by column name; the summary names what each file lacks |
| a code stored as a number | read as text, with a warning |
| one key value on 64 or more records (a dummy phone, a big building, a very common name) | a sample of about 2,000 of its pairs is scored first; the block is used only if one of them reaches the review floor (6 bits), otherwise skipped and named with its sample in the summary and `qa.md` |
| a rule's key value on 64 or more records (one customer ID on thousands) | the rule doesn't trust it, so it can't merge them all; the model can still match those records |

What stops it: two lines, what is wrong and how to fix it, and exit code 2:

| The message says | Why |
|---|---|
| `no file matches …` | a wrong path; it suggests the closest names in that folder |
| `… not a Parquet file; it looks like …` | a CSV or an Excel file; it shows how to convert it |
| `… a Parquet file cut short` | an interrupted copy |
| `the file lacks a field every run needs` | `[columns]` points at a column the file lacks; it lists the file's columns and suggests a mapping |
| `columns … could each be …` | two columns match one name loosely |
| `no record has an ID in column …` | `id` is mapped to the wrong column |
| `the normal blocks alone would make … pairs, more than fit` | the file's pairs would not fit in memory and the temp disk: give DuckDB more room (`--compute memory_limit=… temp_directory=…`) or split the file |
| `… already holds a run` | a full run into a used folder: add `--overwrite`, or pick another folder |
| `another job is writing to …` | a run folder takes one writer at a time: wait for the other one |
| `the model was fitted on other comparison levels` | `--model` was fitted on another pipeline, or on a file with other fields |
| `a decision is match or no_match`, `pairs decided both ways`, `records not in the run` | a decisions file to correct |

Pairs are counted before any join, so a run that couldn't fit stops within seconds instead of running out of memory or disk.

**To ask for help, send `report.txt`** from the run folder. It holds field and column names, counts, shares, times and the model's parameters, and no record's value: no ID, name, phone or address. The notes that quote a value (a placeholder phone, a customer ID a rule doesn't trust) are only in the terminal and `qa.md`. For a run that stopped, send the two lines it printed, and the output of `--check`.

## 8 · Run it on a schedule

`scripts/schedule.py` serves an inbox: every Parquet file dropped in it goes into the run, one at a time, in the order it arrived.

```bash
.venv/bin/python scripts/schedule.py --run runs/customers --inbox inbox                # one pass; cron can call it
.venv/bin/python scripts/schedule.py --run runs/customers --inbox inbox --every 300    # a pass every 5 minutes
```

```
inbox/batches/*.parquet      new records: an increment; into an empty run folder, the first batch is the full run
inbox/decisions/*.parquet    people's decisions (section 6)
inbox/done/, inbox/failed/   where each file goes once it ran
runs/customers/jobs.jsonl    one line per attempt: file, SHA-256, outcome, exit code, attempts, seconds, error
```

Each file runs as `scripts/resolve.py` in a process of its own, so a crash can't take the scheduler down. What happens next depends on how that process ends:

| It ends | The file |
|---|---|
| well (exit 0) | moves to `done/`. A batch already in the run is done too, so a retry is harmless |
| on a mistake people must fix (exit 2) | moves to `failed/`, with its two-line error beside it (`….error.txt`). The pass goes on |
| any other way: a crash, memory | is tried again, waiting 2, 4, 8 … s (`--retries`, default 2). If it still fails, the pass stops and the file stays, so nothing jumps ahead of it; the next pass tries again |

A file whose content was done before, by its SHA-256, moves to `done/` without running. One scheduler serves an inbox at a time, and a run folder takes one writer at a time, so starting a second one, or running `resolve.py` by hand meanwhile, is refused, not raced.

## Development scripts

For changing the matching or measuring it, on synthetic labelled data:

| To | Run | Time |
|---|---|---|
| generate the synthetic train, val and test files | `scripts/generate.py` | seconds |
| choose the configuration on them | `scripts/choose.py` (`--optuna` adds the searches) → `config/final.toml`, `reports/choose.md` | minutes |
| measure quality and cost on growing files | `scripts/benchmark.py --memory-limit 8GB` → `reports/benchmark.md` | minutes |
| see every step on a small file | `notebooks/demo.ipynb`, or `scripts/export_pdfs.py` for its PDF (first: `.venv/bin/python -m playwright install chromium`) | under a minute |
