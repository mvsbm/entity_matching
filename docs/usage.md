[← README](../README.md) · [Commands](commands.md) · [Architecture](architecture.md)

# Using it on your records

Map your file's columns once, run it, read what it wrote. Later, add new records as they arrive, and give back people's decisions on the borderline pairs. Six commands do all of it ([commands](commands.md)):

| Command | Does |
|---|---|
| `nayose resolve records` | a full run: one ID per person or company |
| `nayose add records` | a batch added to the run |
| `nayose match records` | what adding a batch would do; nothing written |
| `nayose apply decisions` | people's decisions given back to the run |
| `nayose build index` | the index a record is looked up in |
| `nayose match record` | the entities one record may belong to |

## 1 · Install

```bash
./setup_venv.sh                         # .venv with Python ≥ 3.12, the pinned dependencies, and the er package
.venv/bin/python -m pytest tests/       # engine checks, whole runs, the design against the code
```

On Windows, in PowerShell, `powershell -ExecutionPolicy Bypass -File setup_venv.ps1` does the same, and every `.venv/bin/X` below is `.venv\Scripts\X`. Keep files and workspaces on a local disk or a network one: the workspace lock holds there.

The setup installs `.venv/bin/nayose` (名寄せ, gathering one customer's records). `nayose --help` lists the commands and `nayose VERB NOUN --help` explains one. Each takes `--format json` for one JSON object per line, for programs.

## 2 · Map your columns

The pipeline never names your columns. It works on logical fields, and `config/settings.toml` `[columns]` says which of your columns hold each one (`ER_SETTINGS=<file>` points nayose at another settings file, which may live outside the repository to keep a mapping private):

```toml
[columns]
id = "CONT_ID"                                        # one column
address = [["STD_ADDRESS"], ["ORIGINAL_ADDRESS"]]     # fallbacks: the first filled one wins
person_name = { sources = [["FULL_NAME_KANA"], ["LAST_NAME_KANA", "GIVEN_NAME_KANA"]], normalize = ["nfkc", "katakana", "strip_spaces"] }
                                                      # an inner list is joined: last name, then given name
phone = { sources = [["PHONE_NUM_4"]], normalize = ["nfkc", "strip_separators"] }
```

`normalize` prepares a field's values before anything compares them, in order, so that one value written two ways is one string: `nfkc` (full-width as half-width, half-width kana as full), `katakana` (hiragana as katakana), `strip_separators` (`03-1234-5678`, `〒100-0001` as their digits; letters stay, so `AB-123` and `XY-123` stay apart), `strip_spaces`, `kana_fold`, `strip_legal_form`, `casefold`. A birth date keeps its separators: `1993-1-12` and `1993-11-2` would become one string.

The fields, and which ones a run needs (`[fields]` in `config/final.toml`):

| Field | Holds | Needed |
|---|---|---|
| `id` | a record ID, filled and unique | yes: the run stops without it |
| `person_name`, `company_name` | the name of a person or of a company, in katakana | at least one of the two |
| `full_name`, `given_name`, `any_name` | the full name; the given name alone; a person's or a company's name | optional; without `any_name`, records get no kind |
| `address`, `address_code`, `postal_code`, `town_code`, `city`, `prefecture` | the address in any format; an address code; the postal code; the town code (municipality, town and chome); the city; the prefecture | optional |
| `phone` | the phone number's last four digits | optional |
| `customer_id` | the ID another system gave the customer | optional |
| `birth_date` | a person's birth date, in one format throughout, so equal dates are equal strings | optional |
| `kind_flag` | the file's own person/company flag; `[kind] flag_company` lists the values that say company | optional |
| `entity` | the true entity, in labelled files only | never read by a run |

- **A missing optional field** turns off only the rules, keys and comparison levels that read it. The run lists them in `qa.md`.
- **A missing needed field** stops the run with the file's columns and, for each missing field, the column whose values look most like it.
- **Names are matched loosely.** A column whose name differs from the mapping only in case, width or separators (`cont_id`, `ＣＯＮＴ＿ＩＤ`) is used, and the summary says so.
- **Every column is read as text.** A blank value counts as missing. A code stored as a number (`599` for `0599`) is read as text with a warning: its leading zeros were lost before the file reached the run.
- **One column for every name**, a person's or a company's: give `full_name`, `person_name`, `company_name` and `any_name` that column, and add `kind = "person"` to `full_name` and `person_name`, `kind = "company"` to `company_name`. Each record's name then goes to the side its kind leans to; without it, a person's name in both columns is scored twice.

### Files as they come

A records file is CSV, TSV or Parquet: a file, a quoted glob (`'in/*.csv'`) or a folder of them, read together by column name. The reader (`er.intake`) decodes each value on its own, so one file may mix encodings by column or by row: a value is read in the one of `[input] encodings` (UTF-8, CP932, EUC-JP) that decodes it strictly. What loses nothing is fixed and counted: control bytes, zero-width characters and BOMs inside values removed, placeholders (`[input] nulls`: NULL, \N, N/A, -, …) made missing, a number a spreadsheet wrote as `5851.0` read as `5851`. What would be a guess (a row whose fields don't line up, a garbled value, a value another encoding reads better) is never applied: it is kept in the part's `proposals.parquet`, and a row nothing can read in `unread.parquet`. A file where more than 1,000 records, and more than a tenth of those read, don't line up with its header is refused: its delimiter or its header is wrong. Not read: gzip and Excel (save it as CSV or Parquet).

## 3 · Run

```bash
.venv/bin/nayose resolve records customers.parquet --workspace workspaces/customers
```

The workspace is the folder that keeps one matching job: the file, copied into its `inputs/`, the results and people's decisions. `resolve records` makes it, and refuses one that holds a run without `--overwrite`; people's decisions in it stand. `--compute memory_limit=8GB threads=4 temp_directory=<folder>` sets DuckDB's limits for the run, over `config/settings.toml` `[compute]`; past the memory limit, DuckDB spills to that folder. Before any join, a full run checks that the pairs fit in memory plus the room DuckDB may spill to, so a run that can't fit stops within seconds.

The run needs no labels: it fits its model on the file itself. On a terminal, one line shows the step under way, how far it is and about how long is left; each step gets a line as it ends. Then the result in short: the records and the entities they became, the pairs waiting for people, the records flagged person or company, and where the report is. `--verbose` prints every field. What each step does, and what it costs: [architecture, the run](architecture.md#4--the-run).

### Before a run on your file

1. **Map the columns** in `config/settings.toml` `[columns]` until nothing needed is missing.
2. **Give DuckDB its limits.** Set `[compute]` `memory_limit` below the machine's memory, leaving room for Python, and `temp_directory` on a disk with room for about 350 bytes per pair.
3. **After the run, read `report.txt`.** Its DIAGNOSIS says what limits what the run finds.
4. **To ask for help, send `report.txt`.** It holds no record's value ([section 7](#7--when-something-is-wrong)).

## 4 · Read the outputs

Everything is in the workspace.

| File | One row per | Holds |
|---|---|---|
| `gold.parquet` | record | `cluster_id` (the smallest record ID of its cluster); `resolved_stage` (`deterministic`, `probabilistic` or `review`); `resolved_by` (the rule, `fs` for the model, or `review` for people); `kind` (1 person, 2 company, 0 not sure), `kind_p` (the probability of a company), `kind_by` (`engine`, or `flag` where the engine is not sure), `kind_flagged` (the engine sure against the file's flag) and `customer_kind`, the entity's |
| `matches/` | accepted pair | both IDs; `match_weight` in bits; `match_probability`; `sources`, the candidate generators that listed it |
| `rule_kept/` | pair a rule found | both IDs, the rule and its stage; `match_weight`, the model's bits for it; `merged`, whether it joined |
| `scored/` | pair at 0 points or more, and every rule's pair | both IDs, `match_weight`, `match_probability`, `sources`, `rule`, `named`, `keep`, and `gamma_<comparison>`, the level each comparison reached |
| `review.parquet` | pair for people | `why` (`decide` or `audit`); an empty `decision`; both records' compared fields; per comparison, the level reached and its bits; `accepted`; `household` ([section 6](#6--review-and-decide)) |
| `qa.md` | | the label-free checks: fill rates, what was turned off, each step's cost, pairs by weight, cluster sizes, the largest clusters, the oversized blocks |
| `report.txt` | | the run on one page, with no record's value in it ([section 7](#7--when-something-is-wrong)) |
| `decisions/` | decided pair | both IDs, `decision`, `why` and `round`; one part per file given back |
| `set_aside/` | record not resolved | the record as read, and `reason`: no ID; the same ID with different content; already in the run |
| `steps.json` | run, increment or set of decisions | the code's commit, the config hash, each file read with its SHA-256, each step's Big-O, seconds and peak memory |
| `state/` | | what increments and lookups need: the standardized records, the rules' clusters, the model, the u it scored with; don't edit |
| `index/` | | the index `build index` writes ([Look up a record](#look-up-a-record)) |

```python
import pandas as pd
gold = pd.read_parquet("workspaces/customers/gold.parquet")
matches = pd.read_parquet("workspaces/customers/matches")      # a folder of parts reads as one table
```

`gold.parquet` is rewritten whole by every run. To see which records a downstream system must update, compare it with the copy that system read last: a new record, or one whose `cluster_id` changed (two entities joined take the smaller ID).

## 5 · Add new records

```bash
.venv/bin/nayose match records new.parquet --workspace workspaces/customers     # what adding them would do; nothing written
.venv/bin/nayose add records new.parquet --workspace workspaces/customers
```

- **The same model.** The batch is scored with the model the full run fitted, so weights stay comparable.
- **Compared with everything.** Each new record is compared with every stored one, and can join an existing entity. Two stored records that were never paired stay apart until a full run compares them again.
- **Cost follows the batch.** Into a million-record run, 1,000 new records take about 4 s.
- **New records only.** A record whose ID is already in the run is set aside, so adding the same batch twice adds nothing.
- **Safe to interrupt.** An interrupted write is finished by the next command that writes.
- **The same pipeline.** A batch is refused when the pipeline or the column mapping is not the one the full run used: resolve the run again, or add the batch with the settings that run used.

`match records` runs the increment's steps and writes nothing: for each record, the entity it would join or a new one, and the rule or the model's best weight that links it.

### Look up a record

```bash
.venv/bin/nayose build index --workspace workspaces/customers      # once: the commands that change the run keep it up to date
.venv/bin/nayose match record FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234 POST_CD=1000001 --workspace workspaces/customers
.venv/bin/nayose match record --record 0000000151 --workspace workspaces/customers   # a stored record, as if it were new
```

- **The answer.** `match record` takes one record by the file's column names and gives the entities it may belong to, best first, from the review floor (4 points) up: each with its points, how each field compared, the rule that would join it, and whether it is likely the same. When none reaches the floor, it names the closest record compared.
- **The same pairs as an increment.** The record is prepared as a run prepares one, each of its keys looked up, and the records found scored with the run's model. So it lists and scores the pairs an increment of that record alone would. It writes nothing.
- **The index.** `build index` reads the run's own files once and writes `index/`: every key of every record, sorted, so a lookup reads only the rows its keys name. On a million records it is built in about 3 s and takes 0.84 GB; a lookup takes under 0.1 s and grows only with the log of the run's size ([performance](performance.md)).
- **Kept up to date.** `add records` and `apply decisions` update the index as their last step; a full run builds it again.

## 6 · Review and decide

The run accepts a pair at 6 bits or more with a name compared. Just below, from 4 to 6 bits, is the threshold rule's safety margin: pairs that were never wrong on cross-validated training data, held back in case of noise. People decide them. On the synthetic val split, the margin holds 55 pairs, none of them false; one grid step lower, at 2 bits, the first false pairs appear ([results](results.md)).

`review.parquet` has two kinds of rows, named in `why`:

- **decide:** every pair of clusters whose best link scored in the margin, or above the line with no name compared (a person and a company at one address, a record with no name), highest first. Pairs already decided are left out; an increment keeps the rows still open and adds its own.
- **audit:** about 50 accepted pairs up to 4 bits above the line. A wrong one is a false merge.

Each row shows the two records' compared fields side by side, then, per comparison, the level the pair reached and the bits it earned. The bits, plus the starting point, add up to `match_weight`.

Reviewers fill in `decision` (`match` or `no_match`) wherever they work: the sheet loaded into a BigQuery table, or a Google Sheet. The decided rows come back as a file with the two ID columns and `decision`:

```bash
.venv/bin/nayose apply decisions --file reviewed.parquet --workspace workspaces/customers
```

- **`match`** joins the two entities at once, scoring nothing. A record joined only this way gets `resolved_by` = `review`.
- **`no_match`** splits nothing at once. It is kept, and a full run never joins the pair. It applies to that pair only: a third record can still join the two.
- **Kept for good.** Decisions are stored in `decisions/`, which every full run on the folder applies again: back it up. Rows without a decision are skipped, and a decision applied before changes nothing, so applying a file twice is harmless.
- **IDs as the run wrote them.** A spreadsheet may read `0000000151` as the number 151; such IDs name no record, and the file is refused.

`review.parquet` holds records: keep it wherever the data itself is kept.

### Maybe one household

A pair whose records share an address or a phone, and whose given names or birth dates differ, is labelled "maybe one household" in the sheet's `household` column: a spouse, a parent or a sibling scores as high as a duplicate, since the family name, the address and the phone are theirs too. The label changes no score or merge: people decide the pair as any other. Its fields are the method's `[household]`.

### Persons and companies

The engine decides each record's kind on its own. It calls a kind it is sure of: a company where a legal form is written (株式会社, カ)〇〇, 〇〇(カ …), and a company or a person where the name model is at least `[kind] name_line` (99%) sure. Else the file's flag (`kind_flag`) decides, and without one the record is `0`, not sure. A sure call the flag contradicts is flagged (`kind_flagged`): the record is matched as the engine says. A name that reads as a person's never overrides a company flag. On generated files it makes fewer false merges than the flag alone, and calls fewer companies persons but more persons companies ([chapter 7](guide/07-person-or-company.md#on-a-whole-run)). `config/final.toml` `[kind] trust_flag = true` takes the file's flag as it is.

## 7 · When something is wrong

`report.txt` starts with DIAGNOSIS: what limits what the run finds, at most eight lines, the most pairs at stake first. It names a compared field filled in under 30% of the records; EM sessions whose matches mostly share no given name (they learned households); pairs below the review floor that agree exactly on a name and another field; levels that learned nothing yet hold pairs; and EM sessions that learned from under 200 pairs. What is fine is left out.

What the run handles by itself, and reports in its summary:

| Found | Done |
|---|---|
| rows identical in every column | kept once |
| a record without an ID, or one ID holding different records | set aside in `set_aside/`; the run goes on |
| several files with different columns | read together by column name; the summary names what each file lacks |
| one key value on 64 or more records (a dummy phone, a big building, a very common name) | a sample of about 2,000 of its pairs is scored first; the block is used only if one of them reaches the search floor, otherwise skipped and named in the summary and `qa.md` |
| a rule's key value on 64 or more records | the rule doesn't trust it, so it can't merge them all; the model can still match those records |

What stops it: two lines, what is wrong and how to fix it, and exit code 2:

| The message says | Why |
|---|---|
| `no file matches …` | a wrong path; it suggests the closest names in that folder |
| `… a ZIP or Excel file, not records` | save it as CSV or Parquet |
| `the file lacks a field every run needs` | `[columns]` points at a column the file lacks |
| `no record has an ID in column …` | `id` is mapped to the wrong column |
| `the normal blocks alone would make … pairs, more than fit` | give DuckDB more room (`--compute memory_limit=… temp_directory=…`) or split the file |
| `… already holds a run` | add `--overwrite`, or pick another folder |
| `… holds its own method.toml` (or `columns.toml`) `, which no run reads` | move what it sets into `config/final.toml` (or `config/settings.toml [columns]`, or a settings file `ER_SETTINGS` names), then delete it |
| `[keys] sets nothing: a run lists pairs by the [model] generators as given` | delete `[keys]` from the pipeline file |
| `… a workspace an earlier nayose wrote (keys learned on its file or left out, which no run reads now)` | run it again into a new folder (`nayose resolve records FILE --workspace PATH`), or replace it with `--overwrite` |
| `out of memory` | raise `--compute memory_limit`, or give `temp_directory` a disk with more room |
| `… don't line up with its header` | a wrong delimiter or header |
| `no run in … to add records to` | `resolve records` first |
| `the pipeline or the column mapping changed since the full run` | resolve the run again, or add the batch with the settings that run used |
| `needs the columns …_l, …_r and decision` | a decisions file without both IDs and `decision` |
| `IDs that name no record of …` | give the IDs back as the run wrote them |
| `no row has a decision`, `a decision is match or no_match`, `pairs decided both ways` | a decisions file to correct |

A workspace another job is writing to stops the command with `another job is writing to …` and exit code 75: try again once the other job is done. A workspace on object storage mounted as files (Cloud Storage FUSE, s3fs) is refused before anything is written: no lock holds there.

**To ask for help, send `report.txt`.** It holds field and column names, counts, shares, times and the model's parameters, and no record's value. The notes that quote a value are only in the terminal and `qa.md`; the workspace's other files hold the records themselves.

## Development scripts

For changing the matching or measuring it, on synthetic labelled data:

| To | Run | Time |
|---|---|---|
| generate the synthetic train, val and test files | `scripts/generate.py` | seconds |
| choose the configuration on them | `scripts/choose.py`: a development round on train and val → `data/artifacts/choose/` (untracked); `--test`, the round to commit, scores test once → `config/final.toml`, `reports/choose.md`; `--optuna` adds the searches | minutes |
| measure quality and cost on growing files | `scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB` → `reports/benchmark.md` | minutes |
| choose how persons and companies are told apart | `scripts/choose_kind.py` → `reports/choose_kind.md` | minutes |
| train the name model again, after changing `data/reference/`, the generator's `kana_confusions` or `branches`, the legal forms or kana folding, or `config/final.toml` `[kind] ngram` | `scripts/train_name_model.py` → `config/kind_names.npz` | seconds |
| see every step on a small file | `notebooks/demo.ipynb`, or `scripts/export_pdfs.py` for its PDF (first: `.venv/bin/python -m playwright install chromium`) | under a minute |
| see what each optimization saves | `notebooks/speedups.ipynb` | about 3 minutes |
| write the commands' reference again, after changing a command in `er/cli.py` | `scripts/document_commands.py` → `docs/commands.md` | seconds |
