[← README](../README.md) · [Commands](commands.md) · [Architecture](architecture.md)

# Using it on your records

Install it, start a workspace, load your file and map its columns, run it, read what it wrote. Later, add new records as they arrive, and have a person check the borderline pairs. Every step is a `nayose` command; `nayose open ui` runs the same commands in a browser ([section 9](#9--in-a-browser)).

## 1 · Install

```bash
./setup_venv.sh                         # .venv with Python ≥ 3.12, the pinned dependencies, and the er package
.venv/bin/python -m pytest tests/       # engine checks, whole runs, the design against the code
```

GitHub runs the same tests on Python 3.12 and 3.14 for every pull request (`.github/workflows/tests.yml`). `main` changes only through a pull request whose checks pass.

The setup installs `.venv/bin/nayose` (名寄せ, gathering one customer's records), the command line. It reads as a sentence, a verb then a noun: `nayose check records`, `nayose resolve records`, `nayose list pairs`. `nayose --help` lists every command, `nayose VERB NOUN --help` explains one, and [commands](commands.md) has them all. Each takes `--format json` for one JSON object per line, for programs. The development scripts run as `.venv/bin/python scripts/<name>.py`.

## 2 · Map your columns

Each matching job lives in a workspace: a folder that keeps your records file, how its columns are read, the results and people's answers, so opening it again finds all of it.

```bash
.venv/bin/nayose create workspace customers                                        # workspaces/customers, with its own mapping
.venv/bin/nayose load records customers.parquet --workspace workspaces/customers   # copied into it, then described
.venv/bin/nayose list workspaces                                                   # every workspace, the latest active first
```

`load records` copies the file into the workspace's `inputs/` (`inputs/0001-customers/`), so its runs read the copy and the original can move or go. The same content loaded twice is copied once. Until the original is deleted, every file is on disk twice. It then describes the copy, as `nayose describe records FILE` does for any file, without preparing a record: each column's share filled and an example, each field's columns with their own shares and the share that looks like the field, and for a field the file holds none of, the column its name or values suggest. On a million records that takes about a second.

The pipeline never names your columns. It works on logical fields, and the workspace's `columns.toml` says which of your columns hold each one. A new workspace copies it from `config/settings.toml` `[columns]` and `[kind]` (`ER_SETTINGS=<file>` points nayose at another settings file); a workspace without one reads the project's. `nayose list columns --workspace W` shows the mapping, and `nayose set columns … --workspace W` changes it, keeping every comment and option, and checking the file before it saves. Without `--workspace`, both work on the project's mapping, which new workspaces start from. People know their file as features, not fields, so a workspace shows its mapping as groups of them: ID (Record ID, Customer number), Name (Full name, with its Family name and Given name; Company name; Person or company), Address, Phone and Birth date. `nayose list features --workspace W` shows each with its columns; `nayose set feature "Name/Full name/Family name=SEI" --workspace W` puts a column in one and writes the fields it means: a full name fills `full_name` and `person_name`, its family and given names a joined fallback of `person_name` and `given_name`, and every name `any_name`. `describe records` places each feature whose columns the file lacks from the file's contents: known family and given names (`data/reference/individual.json`, in kanji and kana), a family name followed by a given name, a legal form, a prefecture or city followed by more, and the field patterns; each placement says why, and none is applied without you.

A name can also be written in another script, a kanji or a romaji name beside the kana one. `nayose add feature "Name/Kanji name" --type "person name" --script kanji --column SHIMEI --workspace W` adds it, with its own family and given names (`remove feature` takes it away; a company name in another script is added the same way). A run compares it beside the kana name: each step of the name comparison is reached when either name agrees, as one piece of evidence, not two; a pair with no name on both sides in any script has no name compared; and pairs are also found on the added name. The sure-match rules, and the person-or-company model (trained on kana), read the kana name only. The steps' thresholds were tuned on kana; their weights are fitted on each run's own file. `describe records` offers such a feature when an unused column holds full names in a script no feature has.

For the fields it suggests, `describe records` ends with the `set columns` line to run; a suggestion is never applied without you:

```bash
.venv/bin/nayose set columns id=CUSTOMER_NO phone=TEL4 person_name=NAME_KANA,SEI+MEI --workspace workspaces/customers   # , a fallback; + columns joined
```

In the file itself:

```toml
[columns]
id = "CONT_ID"                                        # one column
address = [["STD_ADDRESS"], ["ORIGINAL_ADDRESS"]]     # fallbacks: the first filled one wins
person_name = { sources = [["FULL_NAME_KANA"], ["LAST_NAME_KANA", "GIVEN_NAME_KANA"]], normalize = ["strip_spaces"] }
                                                      # an inner list is joined: last name, then given name
```

The fields, and which ones a run needs (`[fields]` in `config/final.toml`; `kind_flag` is read by the person-or-company step only, and `any_name` is the name it reads):

| Field | Holds | Needed |
|---|---|---|
| `id` | a record ID, filled and unique | yes: the run stops without it |
| `person_name`, `company_name` | the name of a person or of a company, in katakana | at least one of the two |
| `full_name`, `given_name`, `any_name` | the full name; the given name alone; a person's or a company's name | optional; without `any_name`, records get no kind |
| `address`, `address_code`, `postal_code`, `town_code`, `city`, `prefecture` | the address in any format; an address code; the postal code; the town code (municipality, town and chome); the city; the prefecture | optional |
| `phone` | the phone number's last four digits | optional |
| `customer_id` | the ID another system gave the customer | optional |
| `birth_date` | a person's birth date, in one format throughout, so equal dates are equal strings (a company's date there is read too) | optional |
| `kind_flag` | the file's own person/company flag; `config/settings.toml` `[kind] flag_company` lists the values that say company (`2`), any other says person | optional |
| `entity` | the true entity, in labelled files only | never read by a run |

- **A missing optional field** turns off only the rules, keys and comparison levels that read it. The run lists them in `qa.md`.
- **Names are matched loosely.** A column whose name differs from the mapping only in case, width or separators (`cont_id`, `ＣＯＮＴ＿ＩＤ`) is used, and the summary says so. A column named like a field but for case (`BIRTH_DATE` for `birth_date`) is dropped once the field is built from it, and one named exactly like a field it doesn't map to stops the run.
- **Every column is read as text.** A blank value, or one made only of spaces (full-width ones included), counts as missing. A code stored as a number (`599` for `0599`) is read as text with a warning: its leading zeros were lost before the file reached the run.
- **A nearly empty field** is used where it is filled. If no two records of the fit's sample share it, the fit learns nothing from it, and the summary says so.
- **One column for every name**, a person's or a company's: map `full_name`, `person_name`, `company_name` and `any_name` to it, and add `kind = "person"` to the first two and `kind = "company"` to `company_name`. Each record's name then goes to the side its kind leans to, and a pair of a person and a company has no name compared, so the model leaves it to people ([section 6](#6--review-and-decide)). A record whose lean and flag disagree goes to neither side until a person decides.
- **A field the run needs and no column holds** stops the run with the file's columns and, for each missing field, the column whose values look most like it (in JSON, as `hints`). These suggestions are never applied without you.

The full check, every record prepared and every key's pairs counted, as a run's first steps do:

```bash
.venv/bin/nayose check records customers.parquet
```

It prints each field, its fill rate and the columns it comes from, what would be turned off, each key's pairs per record, and the blocks of 64 or more records that the run will check on a sample. For each field, two shares from a sample of 10,000 records point at a mistake before it costs a run:

- **looks right**: the share of filled values that look like the field (`[locale.detect]`). A low share is a wrong column, or a format the comparisons don't expect: a full phone number where the last four digits are expected, dates written two ways.
- **top value**: the share of filled values held by the most common one. A placeholder (`0000`, `19000101`) shows as one value on many records, and the model counts it as an agreement between every two records that hold it. A field whose values are few by nature, such as the prefecture, has a high share anyway.
- **Other names for the same information** need only `[columns]`. Another language needs `[locale]`. A different kind of record needs a new `config/pipeline.toml`, chosen again with `scripts/choose.py` on labelled or synthetic data ([architecture](architecture.md#1--context-two-loops)).

## 3 · Run

```bash
.venv/bin/nayose resolve records --workspace workspaces/customers     # the file loaded last
```

| Parameter | Does |
|---|---|
| `INPUT` | a Parquet file, a quoted glob (`'data/in/*.parquet'`) or a folder of them; several files are read together by column name. Copied into the workspace first, as `load records` does; left out, the file loaded into it last |
| `--workspace` | the workspace: the folder that keeps one matching job. A full run refuses one that already holds a run |
| `--overwrite` | replaces the run in `--workspace`; people's decisions and answers in it stand |
| `--compute KEY=VALUE …` | DuckDB limits for this run, overriding `config/settings.toml` `[compute]`: `memory_limit=8GB`, `threads=4`, `temp_directory=<folder>`. Past the memory limit, DuckDB spills to that folder |
| `--pipeline` | another pipeline file. Default: `config/final.toml` |
| `--model` | a model fitted before, used instead of fitting on this file; an increment scores with the model of the run it adds to |

`[compute]` in `config/settings.toml` sets the same three for every run. Left empty, each keeps DuckDB's default: all cores, 80% of the memory, and spilling to `.tmp/` under the folder the run starts in. Before any join, a full run checks that the pairs fit in memory plus the room DuckDB may spill to: 90% of that disk's free space. An increment checks the blocks of 64 or more records its batch reaches; its other pairs all touch the batch.

The run needs no labels: it fits its model on the file itself. It prints each step as it finishes, with its time and what it did, then a summary: records, entities, who joined them (the rules, the model, people), the model's links and how many of them it expects to be false, the pairs to decide, the records' and customers' kinds, where the kinds come from (no answers yet; or the answers, the lines and how often the flag is wrong on those drawn at random), how many records are held back, how often a sure kind contradicts the flag, and notes. The expected false links are the sum of 1 − match probability over the model's links: the model's own estimate, with no labels. A bigger file holds more people who share a name and an address, so at a fixed threshold the count grows with the file: on generated files, 0.84 at 12,532 records, 4.38 at 74,959 (1 and 3 found) and 30.11 at a million ([benchmark](../reports/benchmark.md)). A note says what the loader fixed, a field filled in under 5% of records (often a mapping mistake), a part turned off, or what the fit couldn't learn from. Last, `next` lists the commands that usually follow: the pairs and the records left to people, and the folder at a glance. What each step does, and what it costs: [architecture, the run](architecture.md#4--the-run).

## 4 · Read the outputs

Everything is in the workspace. A run also reads `config/kind_names.npz`, the name model that tells persons from companies, and `steps.json` names it with its SHA-256.

```bash
.venv/bin/nayose describe workspace workspaces/customers                         # records, entities, the largest, each run, what is open
.venv/bin/nayose describe entity 0000000151 --workspace workspaces/customers     # one record's entity: its records, and what joined them
.venv/bin/nayose describe matching --workspace workspaces/customers              # every method, on which fields, with this run's numbers
```

| File | One row per | Holds | Use it to |
|---|---|---|---|
| `gold.parquet` | record | `cluster_id` (the smallest record ID of its cluster); `resolved_stage` (`deterministic`, `probabilistic` or `review`; empty for a record found alone); `resolved_by` (the rule, `fs` for the model, or `review` for people); `kind` (1 person, 2 company, 0 not sure), `kind_p` (the probability of a company), `kind_by` (`engine` or `people`), `kind_held` (held back from matching: the engine and the flag disagree) and `customer_kind`, the entity's (2 if any record surely is a company; 1 if none leans company and one surely is a person; else 0) | give every record its entity, and every entity its kind |
| `matches/` | accepted pair | both IDs; `match_weight` in bits; `match_probability`; `sources`, the candidate generators that listed it | see why two records were joined |
| `rule_kept/` | pair a rule accepted | both IDs, the rule and its stage | audit the rules |
| `qa.md` | | the summary; each field's fill rate (flagged under 5%), the share that looks right and the share of its most common value; what was turned off; each step's Big-O, time and memory; pairs by weight; cluster sizes; the 10 largest clusters; match patterns no key guarantees; the review queue; records and customers by kind; clusters holding both a sure person and a sure company; the oversized blocks and what was decided for each | check the run without labels |
| `report.txt` | | the run on one page of plain text, with no record's value in it: what ran (the code, the tracked files changed in this copy, the pipeline, the machine's limits), the summary, the fields, scores and links by weight with the false links expected, cluster sizes, each step's time and memory, the model's m, u and bits per level, the costliest blocks (a full run), the match patterns no key pairs | send it to whoever helps with the run ([section 7](#7--when-something-is-wrong)) |
| `review.parquet` | pair for people | `why` (`decide` or `audit`); an empty `decision`; both records' compared fields; per comparison, the level reached and its bits; `accepted`, whether the run accepted the pair | decide the pairs just below the line and those above it with no name compared, audit those just above ([section 6](#6--review-and-decide)) |
| `kind_review.parquet` | record for people | `why` (`decide` or `measure`), `reason` in words, `engine_says`, `name_says`, `flag` and `birth_date` if the file has them, the name; `engine` and `engine_p` (the engine's kind and its probability of a company), `name_p`, `drawn`; an empty `kind` | answer 1 person, 2 company or 0 can't tell ([section 6](#6--review-and-decide)) |
| `decisions/` | decided pair | both IDs and `decision`, one part per file people gave back | what people decided; a full run applies it again |
| `kind_answers/` | answered record | the answered rows of each `kind_review.parquet` given back, one part per sheet, as given | what people answered; every later run reads it |
| `set_aside/` | record not resolved | the record as read, and `reason`: no ID; the same ID with different content; already in the run | fix them and add them with `nayose add records` |
| `steps.json` | run, increment or set of decisions | when; the code's commit; the config hash; each file read with what it is, its size and SHA-256; each step's Big-O with the numbers filled in, seconds, peak memory | see the cost; say exactly what went into the run; `nayose rerun records` reads its files again |
| `state/` | | the standardized records, the rules' clusters, the model, the u it scored with, the hash of the config the full run used | needed by `nayose add records`; don't edit |

```python
import pandas as pd
gold = pd.read_parquet("workspaces/customers/gold.parquet")
matches = pd.read_parquet("workspaces/customers/matches")      # a folder of parts reads as one table
```

`gold.parquet` is rewritten whole by every run. To see which records a downstream system must update, keep the copy it read last and compare: a new record, or one whose `cluster_id` changed (two entities joined take the smaller ID).

```sql
-- duckdb
SELECT n.CONT_ID, o.cluster_id AS was, n.cluster_id AS now
FROM 'workspaces/customers/gold.parquet' n LEFT JOIN 'last_read/gold.parquet' o USING (CONT_ID)
WHERE o.cluster_id IS DISTINCT FROM n.cluster_id;
```

## 5 · Add new records

```bash
.venv/bin/nayose match records new.parquet --workspace workspaces/customers     # what adding them would do; nothing written
.venv/bin/nayose add records new.parquet --workspace workspaces/customers
```

- **The same model.** The batch is scored with the model the full run fitted, so weights stay comparable. The u of the exact and one-digit-off levels are counted again on every record, before the rules. A sampled u is measured again only once its drift, read from those exact counts, exceeds its own sampling error; before that, a new sample would only redraw the noise.
- **Compared with everything.** Each new record is compared with every stored one, and can join an existing cluster. Earlier answers stand.
- **Stored records aren't compared again.** A record left alone gets a new chance whenever a new record matches it, directly or through a third record. But two stored records that were not matched with each other stay apart until a full run compares them again, for example after the matching changes: `nayose rerun records --workspace workspaces/customers` resolves the run's own files again, the full run's and each batch's, in the order they came, so it keeps the records the increments kept.
- **Cost follows the batch.** The joins start from the new records, so a small batch is fast whatever the run's size: into a million-record run, 1,000 new records take about 4 s.
- **New records only.** A record whose ID is already in the run is set aside: an increment adds, it doesn't update. So running the same batch twice is harmless; the second time prints "nothing new".
- **Safe to interrupt.** An interrupted write is finished by the next increment.
- **Match without adding.** `nayose match records` runs the increment's steps and writes nothing: for each record, the entity it would join or a new one, and the rule or the model's best weight that links it.

## 6 · Review and decide

The run accepts a pair at 8 bits or more. Just below that line, from 6 to 8 bits, is the threshold rule's safety margin: pairs that were never wrong on cross-validated training data, but are held back in case of noise. People decide them. On the synthetic val split, the margin holds 112 pairs, all true: accepting them would raise recall from 46.3% to 51.7%, with no false merge. One grid step lower, at 4 bits, the first false pair appears ([results](results.md)).

`review.parquet` has two kinds of rows, named in `why`:

- **decide:** every pair of clusters whose best link scored in the margin, or above the line with no name compared (the name check, `[model] needs`: a person and a company at one address, a record with no name), one row per pair of clusters, highest first. Pairs already decided are left out. An increment keeps the rows still open, and any decision typed into the sheet but not yet given back, and adds its own.
- **audit:** about 50 accepted pairs up to 4 bits above the line, a few from each 1-bit band. A wrong one is a false merge.

Each row shows the two records' compared fields side by side, then, per comparison, the level the pair reached (for example "fold JW high": the kana-folded names close by Jaro–Winkler) and the bits it earned. The bits, plus the starting point, add up to `match_weight`. `accepted` says what the run decided.

List the open pairs, decide each, then apply the decisions:

```bash
.venv/bin/nayose list pairs --workspace workspaces/customers --open
.venv/bin/nayose decide pair 0000000151 0000000874 match --workspace workspaces/customers     # or no_match; clear takes it back
.venv/bin/nayose apply decisions --workspace workspaces/customers
```

Each decision is written into the workspace's `review.parquet` (its `decision` column) and applied by `apply decisions`. `list pairs` marks each row open, written in, or applied. A sheet filled in elsewhere, any file with the two ID columns and `decision`, goes back with `apply decisions --file reviewed.parquet`.

- **`match`** joins the two clusters at once, scoring nothing. A record joined only this way gets `resolved_by` = `review`.
- **`no_match`** splits nothing at once. It is kept, and a full run never accepts the pair. It applies to that pair only: a third record can still join the two.
- **Kept for good.** Decisions are stored in `decisions/`, which every full run on the same folder applies again. `decisions/` and `kind_answers/` are people's work: back them up. Rows without a decision are skipped, and a decision applied before changes nothing, so applying a sheet twice is harmless.

### Persons and companies

A full run writes `kind_review.parquet`, records for people, as `review.parquet` holds pairs. Each row says in `reason` why it is there, and what the engine (`engine_says`: `1 person`, `2 company`, `0 not sure`), the name alone (`name_says`, with how sure) and the file's flag (`flag`) say. Two kinds of rows, named in `why`:

- **decide:** records where the engine and the flag disagree, held back from matching until you decide, the engine's sure calls first ("the engine is sure it is 1 person, the flag says 2"); then records the engine and the flag agree on but whose name alone says the other kind, the flag's likely errors. At most `[kind] review_max` (1,000).
- **measure:** 2,000 records drawn at random, to measure the flag and the engine. They place the engine's lines and say how often the flag is wrong. Records you were sent to decide can't do that: they were picked because they look wrong.

Answer each record `person`, `company` or `unsure` (stored as `1`, `2`, `0`: can't tell from the record). A sole trader is a person, legally. Then apply the answers:

```bash
.venv/bin/nayose list kinds --workspace workspaces/customers --open
.venv/bin/nayose answer kind 0000000151 company --workspace workspaces/customers
.venv/bin/nayose apply answers --workspace workspaces/customers
```

Answers change how each record's name is matched, so `apply answers` is a rerun: a full run on the run's own files ([section 5](#5--add-new-records)), with the answers. A sheet filled in elsewhere, any file with the ID column and `kind` (`1`, `2` or `0`), goes back with `apply answers --file answered.parquet`.

- **Your answers stand** for their records (`kind_by` = `people`): a held record's name goes to its side, and matching can use it. A `0` stands too: the record's name stays out of matching, and its pairs come to you in `review.parquet` with no name compared.
- **They teach the engine.** The combiner fits on every answer 1 or 2 and places its lines on the measuring draw only, once 50 of the draw are answered, both kinds among them; until then a written legal form decides, as without answers (answer the whole draw: on fewer answers the company line goes a step stricter, and below 1,000 answers it can still be too loose); the person line only where the answers above it keep it within 1% wrong at 95% confidence (with none wrong, 300 answers above it). The summary says where the lines fall, how often the flag is wrong on the answers drawn at random, and how many records stay held back.
- **They add up.** The run keeps each sheet's answers as given, one part per sheet in `kind_answers/`; per record the newest answer stands, and a blank row erases nothing. The next sheet leaves out the records answered, and brings back those left blank. A sheet answered wrong is undone by deleting its part, then `nayose rerun records`.
- **A full run writes the sheet.** A record an increment holds back is on the sheet of the next full run.

`[kind] trust_flag = true` takes the file's flag as it is, with no engine and no review sheet: the benchmark's flag-alone baseline.

Without answers, a record is `2` only where a legal form is written (株式会社, カ)〇〇, 〇〇(カ …), and never surely `1`. A company record under its representative's name, at the representative's address and phone and flagged person, looks like the person's own record in every column; nothing in the file tells them apart, so no sheet finds it.

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
| `… already holds a run` | `resolve records` into a used folder: add `--overwrite`, or pick another folder |
| `the model was fitted on other comparison levels` | `--model` was fitted on another pipeline, or on a file with other fields |
| `the file has a column named …, which is also the name of a field` | a column named like a field it doesn't map to |
| `no rule can run`, `no candidate generator can run`, `no prior rule can run`, `no EM blocking rule can run` | the file lacks every field they read: map them, or give the file those columns |
| `no record left to resolve`, `no new record to add` | every record was set aside (`set_aside/` says why) |
| `no run in … to add records to` | `add records` into a folder with no run: `resolve records` first |
| `the pipeline or the column mapping changed since the full run` | an increment would resolve its batch otherwise than the records it joins: `rerun records`, or add the batch with the pipeline and settings that run used |
| `… gone since the run read it`, `… changed since the run read it` | `rerun records` needs the run's files as they were read: resolve the files again with `resolve records … --overwrite` |
| `needs the columns … and kind` | `apply answers --file` points at the wrong file |
| `needs the columns …_l, …_r and decision` | a decisions file without both IDs and `decision` |
| `IDs that name no record of …` | a sheet of answers or decisions whose IDs changed: a spreadsheet may read 0000000151 as the number 151. Give the IDs back as the run wrote them |
| `no row has a decision`, `no row is answered` | nothing decided or answered yet: `decide pair` or `answer kind` first, or fill in the sheet |
| `answered rows have no …`, `decided rows lack an ID`, `a decision is match or no_match`, `a kind is 1, 2 or 0`, `pairs decided both ways` | a sheet to correct |

A workspace another job is writing to stops the run with `another job is writing to …` and exit code 75: nothing to fix, try again once the other job is done. The lock and the renames that finish each write hold on a local disk: keep workspaces and inboxes on one. On network or object storage they don't, so there let one scheduler be a folder's only writer.

Pairs are counted before any join, so a run that couldn't fit stops within seconds instead of running out of memory or disk.

**To ask for help, send `report.txt`** from the workspace. It holds field and column names, counts, shares, times and the model's parameters, and no record's value: no ID, name, phone or address. The notes that quote a value (a placeholder phone, a customer ID a rule doesn't trust) are only in the terminal and `qa.md`. For a run that stopped, send the two lines it printed, and the output of `nayose check records`.

## 8 · Run it on a schedule

`nayose serve inbox` takes in every Parquet file dropped in an inbox, one at a time, in the order it arrived.

```bash
.venv/bin/nayose serve inbox inbox --workspace workspaces/customers                # one pass; cron can call it
.venv/bin/nayose serve inbox inbox --workspace workspaces/customers --every 300    # a pass every 5 minutes
```

```
inbox/batches/*.parquet      new records: add records; into an empty workspace, the first batch is resolve records
inbox/decisions/*.parquet    people's decisions: apply decisions (section 6)
inbox/answers/*.parquet      people's person/company answers: apply answers, a rerun (section 6)
inbox/done/, inbox/failed/   where each file goes once it ran
workspaces/customers/jobs.jsonl    one line per file per pass: file, SHA-256, outcome, exit code, attempts, seconds, error, where it went
```

Each file runs as its `nayose` command in a process of its own, so a crash can't take the scheduler down. What happens next depends on how that process ends:

| It ends | The file |
|---|---|
| well (exit 0) | moves to `done/`. A batch already in the run is done too, so a retry is harmless |
| on a mistake people must fix (exit 2) | moves to `failed/`, with its two-line error beside it (`….error.txt`). The pass goes on |
| any other way: busy (exit 75: another job writes to the workspace), a crash, memory | is tried again, waiting 2, 4, 8 … s (`--retries`, default 2). If it still fails, the pass stops and the file stays, so nothing jumps ahead of it; the next pass tries again |

`--compute` passes DuckDB limits on to every run. A file whose content was done before, by its SHA-256, moves to `done/` without running. The pass ends with exit code 1 if it stopped on a file. One scheduler serves an inbox at a time, and a workspace takes one writer at a time, so starting a second one, or running `nayose` on the folder by hand meanwhile, is refused, not raced, on a local disk.

## 9 · In a browser

```bash
.venv/bin/nayose open ui --workspace workspaces/customers      # prints a link and opens it; Ctrl-C stops it
```

The page runs the same commands, and nothing else. It opens on step 1: what nayose needs (a workspace, the folder that keeps the job, then your records file, copied into it) and what it gives (customers, one ID each); what can't act before the first run (adding records, matching again, looking up a record) is greyed out until then. On the left, the work in six steps, in order, each marked done (✓), next, needs you (!) or optional, with one line of where it stands. Each page says how much each part of it covers: a grey band for all the records, a titled list for some of them, and a card with a blue edge for the one picked; the path under the heading strings them together (*All 8,936 records › 151 pairs to review › This pair*), and each card asks one question (*Same customer?*). The grey band is the step's part of the pipeline: chips joined by arrows, each with how many records or pairs it handled, in everyday words (*Sure matches*, *Compared*, *Weighed*, *Matched*, *Customers formed*); click a chip to see how it works, drawn rather than written, with the method's own name beside it. The methods show on real values: before and after with the changed letters marked, the differing letters of two records marked, each comparison's step on its ladder and the points (bits of evidence) it adds toward the 8 needed. Every button runs one `nayose` command; a run opens in a dialog with its equivalent command line, and the drawer at the bottom (the terminal icon) lists every command the page ran.

| Step | Runs | Shows |
|---|---|---|
| 1 Choose a workspace | `list workspaces`, `create workspace` | the workspaces in `workspaces/` (`open ui --home` names another folder), the latest active first, or a new one by name |
| 2 Prepare your data | `load records`, `describe records`, `set feature`, `add feature`, `remove feature` | your file, loaded into the workspace (each file it holds, and whether a run has read it); then the file's columns as chips, and each group's features (ID; Name: a full name with its family and given names, a company name; Address; Phone; Birth date) as slots to drag them into: dropped on a slot, a column read where those before are empty; on a chip, joined to it; × takes one off. Each slot shows its share filled, an example, and a ⚠ when few of its values look right; ✦ *Suggest* on a group shows what the file's contents place in its empty slots, ✓ keeps one, *Keep all* every one, and offers a name feature in another script for an unused column; *+ Add a feature* in Name adds one by hand (its name, a person's or a company name, its script), ✕ removes it; a group opens when it needs something |
| 3 Find matches | `resolve records`, `add records`, `match records`, `rerun records` | records → rules → candidates (each way of listing pairs, as a bar) → weighed (what each level of each comparison is worth, in points) → matched (pairs by weight, against the line) → customers |
| 4 Review possible matches | `list pairs`, `decide pair`, `apply decisions` | the pairs to review beside the picked pair, and why it is asked: its two records with their differences marked, each comparison's step and points, the total against the line. <kbd>M</kbd> same customer, <kbd>N</kbd> different, <kbd>S</kbd> skip, <kbd>↑</kbd> <kbd>↓</kbd> move |
| 5 Confirm person or company | `list kinds`, `answer kind`, `apply answers` | each record on a slider from person to company, where the engine and its name alone place it. <kbd>1</kbd> person, <kbd>2</kbd> company, <kbd>0</kbd> can't tell |
| 6 View customers | `describe workspace`, `describe entity` | the largest customers, and any customer's records as dots joined by what linked them: a rule, the model (with its points) or a person |

*When things change*, under the steps, leads to adding new records (preview first) and to matching everything again. The Overview shows the whole pipeline in one strip, and the next step to take.

- **Only this machine, only this link.** The page is served on `127.0.0.1`, and every request needs the random token in the link `open ui` prints, so another user of the machine can't use it, and a web page elsewhere can't reach it. It loads nothing from the network: the records never leave the machine.
- **One long command at a time.** Lists, describes and single answers run at once; a run, a rerun or applying the answers runs in a process of its own, so a crash can't take the page down, and a second one waits its turn. A workspace another job is writing to says so: answer again once it is done.

## Development scripts

For changing the matching or measuring it, on synthetic labelled data:

| To | Run | Time |
|---|---|---|
| generate the synthetic train, val and test files | `scripts/generate.py` | seconds |
| choose the configuration on them | `scripts/choose.py`: a development round on train and val → `data/artifacts/choose/` (untracked); `--test`, the round to commit, scores test once → `config/final.toml`, `reports/choose.md`; `--optuna` adds the searches | minutes |
| measure quality and cost on growing files | `scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB` → `reports/benchmark.md`, which starts with the command that wrote it | minutes |
| choose how persons and companies are told apart | `scripts/choose_kind.py` → `reports/choose_kind.md` | minutes |
| train the name model again, after changing `data/reference/`, the generator's `kana_confusions` or `branches`, the legal forms or kana folding, or `[kind] ngram` (a run refuses a model trained under other settings; commit the file) | `scripts/train_name_model.py` → `config/kind_names.npz` | seconds |
| see every step on a small file | `notebooks/demo.ipynb`, or `scripts/export_pdfs.py` for its PDF (first: `.venv/bin/python -m playwright install chromium`) | under a minute |
| write the commands' reference again, after changing a command in `er/cli.py` (a test fails until it matches) | `scripts/document_commands.py` → `docs/commands.md` | seconds |
