[← README](../README.md) · [Commands](commands.md) · [Architecture](architecture.md)

# Using it on your records

Install it, start a workspace, load your file and map its columns, run it, read what it wrote. Later, add new records as they arrive, and have a person check the borderline pairs. Every step is a `nayose` command; `nayose open ui` runs the same commands in a browser ([section 9](#9--in-a-browser)).

## 1 · Install

```bash
./setup_venv.sh                         # .venv with Python ≥ 3.12, the pinned dependencies, and the er package
.venv/bin/python -m pytest tests/       # engine checks, whole runs, the design against the code
```

On Windows, in PowerShell, `powershell -ExecutionPolicy Bypass -File setup_venv.ps1` does the same (the execution policy
lets the script run once, without changing it), and every `.venv/bin/X` below is `.venv\Scripts\X`. Paths may use `\`
or `/`; files and workspaces on a local disk (the workspace lock is a local one).

GitHub runs the fast tests on Python 3.12 and 3.14 for every pull request, and every test, on Windows too after `setup_venv.ps1`, on `main` (`.github/workflows/tests.yml`). `main` changes only through a pull request whose checks pass.

The setup installs `.venv/bin/nayose` (名寄せ, gathering one customer's records), the command line. It reads as a sentence, a verb then a noun: `nayose check records`, `nayose resolve records`, `nayose list pairs`. `nayose --help` lists every command, `nayose VERB NOUN --help` explains one, and [commands](commands.md) has them all. Each takes `--format json` for one JSON object per line, for programs. The development scripts run as `.venv/bin/python scripts/<name>.py`.

## 2 · Map your columns

Each matching job lives in a workspace: a folder that keeps your records file, how its columns are read, the results and people's answers, so opening it again finds all of it.

```bash
.venv/bin/nayose create workspace customers                                        # workspaces/customers, with its own mapping
.venv/bin/nayose load records customers.parquet --workspace workspaces/customers   # copied into it, read as it comes, then described
.venv/bin/nayose list workspaces                                                   # every workspace, the latest active first
```

`load records` copies the file into the workspace's `inputs/` (`inputs/0001-customers/`), so its runs read the copy and the original can move or go. The same content loaded twice is copied once. Until the original is deleted, every file is on disk three times: the original, the copy, and the reader's Parquet of it beside the copy (four while `accept repairs` reads it again). It reads the copy as it comes ([below](#files-as-they-come)), then describes it, as `nayose describe records FILE` does for any file, without preparing a record: each column's share filled and an example, each field's columns with their own shares and the share that looks like the field, and for a field the file holds none of, the column its name or values suggest. On a million records the reading takes about 15 seconds, the description about one.

### Files as they come

A records file can be CSV, TSV or Parquet, named anything: the reader goes by its bytes (`er.intake`). A CSV's delimiter is the one its lines hold steadily, and each value is decoded on its own, so one file may mix encodings by column or by row: a value is read in the one of `[input] encodings` (UTF-8, CP932, EUC-JP) that decodes it strictly, UTF-8 first when it reads as Japanese text; one that several read is read in its column's. A file in UTF-16 (with or without a BOM) or in JIS (ISO-2022-JP) is decoded whole first, and so is a file delimited by `|` that is mostly CP932 (`|` is the second byte of some CP932 characters): more than half of the lines with non-ASCII bytes in its first MiB fail UTF-8, nine in ten of those reading as CP932 and not as EUC-JP. Any other is read value by value, and a CP932 row of it that a `|` byte splits is proposed for realigning, or kept unread; a column whose values no other encoding rules out reads in the file's encoding, except a Parquet text column, which is UTF-8. A file where more than 1,000 records, and more than a tenth of those read, don't line up with its header is refused, judged once a chunk of 200,000 is read or on the whole of a smaller file: its delimiter or its header is wrong. A header that repeats a name keeps every column, the repeats numbered past the names it gives, case aside as DuckDB reads names (`TEL, TEL, TEL_2` read as `TEL, TEL_3, TEL_2`, and `TEL, tel` as `TEL, tel_2`); a file of a header alone reads as no records, and a run refuses it. Lines may end in CRLF, LF or CR; blank lines are skipped; a title line above the header, far narrower, is skipped and said; a delimiter every record ends with is dropped; a file that never quotes a value reads a quote as text. Not read: a gzip file (decompress it first), Excel (save it as CSV or Parquet), and quotes escaped with a backslash (`\"`: in CP932 a backslash byte can be half of a kanji, so write quotes doubled, `""`, as CSV does). A first line of numbers is said to look like a record: the header may be missing. What loses nothing is fixed by itself and counted: control bytes, NULs, zero-width characters and BOMs inside values removed; placeholders (`[input] nulls`: NULL, \N, NaN, N/A, -, …) made missing; a number a spreadsheet wrote as `5851.0` read as `5851`, and a Parquet float column's whole numbers as their digits (`123000000000`, never `1.23e+11`), and one it cut short (`1.23E+11`, `1E+11`: its digits gone) made missing, since two IDs cut alike would otherwise agree; a value written as a list of plain items (a Parquet list column, or text such as `["8700848"]`, `['大分県']`, `[0708612]`) read as its item, its numbers as written and then fixed as a bare one is, an empty list made missing, and a list of several items read as its first, counted apart and said, since the rest is left out; anything else in brackets (`[株]`, `[true]`, a list of lists) stays as written. A value no `[input]` encoding decodes is made missing too, counted as damaged: reading it would be a guess with nothing to propose. In a file decoded whole, a value with bytes its encoding can't decode is made missing the same way. A file a workspace holds that an earlier version of the reader read, or that was read under other `[input]` settings, is read again, once, by the next command that opens it, with the repairs people accepted; so is one whose reading was cut short as its files were moved into place. A run that read its records that way takes no new batch (`add records`, `match records`, the inbox) until it runs again (`nayose rerun records`): a batch read now would not compare alike with them.

What would be a guess is proposed, never applied, until people accept its kind with `nayose accept repairs KIND --workspace W` (step 2 shows each with its values, as given and repaired):

| Kind | Proposed when | Until accepted |
|---|---|---|
| `realign` | a row has fields too many (at most `max_extra`, 3: a delimiter inside a value) or too few (a line break inside one), and one way to join them back fits every column far better than any other: each column's profile is what its values hold, digits, kana, kanji, and their lengths | the row is unread |
| `garbled` | a value reads as text garbled by a wrong decoding upstream (UTF-8 read as CP932 or Latin-1, then saved), and decoding it back reads far more like Japanese names and addresses (`data/reference/`) | the value is as given |
| `encoding` | several encodings read a value, and another than its column's reads far better, as text and as its column holds | the value in its column's encoding |

"Far better" is at least e^`margin_text` likelier per character for a value, e^`margin_row` for a row (`config/settings.toml` `[input]`). A row nothing can read stays in `unread.parquet` in the part, with its line number, its bytes and why; fix the file and load it again. A batch read under other `[input]` settings than the full run is refused. People's files given as CSV (`apply decisions --file`, `apply answers --file`) are read the same way but strictly: one that needs a repair is refused, with its line. On damaged copies of a generated file ([reports/benchmark_intake.md](../reports/benchmark_intake.md)) every kind of damage read back in at least 99.9% of its values, and no value that was never damaged changed.

The pipeline never names your columns. It works on logical fields, and the workspace's `columns.toml` says which of your columns hold each one. A new workspace copies it from `config/settings.toml` `[columns]` and `[kind]` (`ER_SETTINGS=<file>` points nayose at another settings file); a workspace without one reads the project's. `nayose list columns --workspace W` shows the mapping, and `nayose set columns … --workspace W` changes it, keeping every comment and option, and checking the file before it saves. Without `--workspace`, both work on the project's mapping, which new workspaces start from. People know their file as features, not fields, so a workspace shows its mapping as groups of them: ID (Record ID, Customer number), Name (Full name, with its Family name and Given name; Company name; Person or company), Address, Phone and Birth date. `nayose list features --workspace W` shows each with its columns; `nayose set feature "Name/Full name/Family name=SEI" --workspace W` puts a column in one and writes the fields it means: a full name fills `full_name` and `person_name`, its family and given names a joined fallback of `person_name` and `given_name`, and every name `any_name`. A family name is read joined to the given name, so it takes one column, and only beside a given name. Two changes at once are written one after the other. `describe records` places each feature whose columns the file lacks from the file's contents: known family and given names (`data/reference/individual.json`, in kanji and kana), a family name followed by a given name, a legal form, a prefecture or city followed by more, and the field patterns; a phone also by its column's name (phone, tel, mobile, 電話, 携帯; never a fax) when its values are 4 to 11 digits, dashes and brackets aside. Each placement says why, and none is applied without you.

A name can also be written in another script, a kanji or a romaji name beside the kana one. `nayose add feature "Name/Kanji name" --type "person name" --script kanji --column SHIMEI --workspace W` adds it, with its own family and given names (`remove feature` takes it away; a company name in another script is added the same way). A run compares it beside the kana name: each step of the name comparison is reached when either name agrees, as one piece of evidence, not two; a pair with no name on both sides in any script has no name compared; and pairs are also found on the added name. The match rules, and the person-or-company model (trained on kana), read the kana name only. The steps' thresholds were tuned on kana; their weights are fitted on each run's own file. `describe records` offers such a feature when an unused column holds full names in a script no feature has.

For the fields it suggests, `describe records` ends with the `set columns` line to run; a suggestion is never applied without you:

```bash
.venv/bin/nayose set columns id=CUSTOMER_NO phone=TEL4 person_name=NAME_KANA,SEI+MEI --workspace workspaces/customers   # , a fallback; + columns joined
```

In the file itself:

```toml
[columns]
id = "CONT_ID"                                        # one column
address = [["STD_ADDRESS"], ["ORIGINAL_ADDRESS"]]     # fallbacks: the first filled one wins
person_name = { sources = [["FULL_NAME_KANA"], ["LAST_NAME_KANA", "GIVEN_NAME_KANA"]], normalize = ["nfkc", "katakana", "strip_spaces"] }
                                                      # an inner list is joined: last name, then given name
phone = { sources = [["PHONE_NUM_4"]], normalize = ["nfkc", "strip_separators"] }
```

`normalize` prepares a field's values before anything compares them, in order, so that one value written two ways is one string: `nfkc` (full-width as half-width, half-width kana as full), `katakana` (hiragana as katakana), `strip_separators` (`03-1234-5678`, `〒100-0001` as their digits; letters stay, so `AB-123` and `XY-123` stay apart), `strip_spaces`, `kana_fold`, `strip_legal_form`, `casefold`. The project's mapping gives the names `katakana` (a kana name feature added too) and the phone, postal code and customer ID `nfkc` and `strip_separators`; on values already written one way they change nothing. A birth date keeps its separators: `1993-1-12` and `1993-11-2` would become one string. `nayose set preparation FIELD=STEP,STEP --workspace W` sets a workspace's own; the run reads its records so once it runs again (`describe workspace` says so, and step 2 of the page, with *Run matching again*).

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
- **One column for every name**, a person's or a company's, or a company-name column that holds people's names too: `nayose set names by-kind --workspace W` adds `kind = "person"` to `full_name` and `person_name` and `kind = "company"` to `company_name`, and `as-mapped` takes them off. Each record's name then goes to the side its kind leans to: without it, a person's name in both columns is scored twice, as a person's and as a company's, and its pairs look far surer than they are. A pair of a person and a company has no name compared, so the model leaves it to people ([section 6](#6--review-and-decide)). A record whose lean and flag disagree goes to neither side until a person decides.
- **What a column's values say is off**: `describe records` (and step 2 of the page, under the column) says it where it can, with the command that sets it right: a name column holding the other kind's names (the name model on a sample; `set names by-kind`), values that look right, written both ways in the file, that a step prepares as one where the fields reading the column lack it (`03-1234-5678` beside `0312345678`, a name in hiragana: `set preparation`, *Read as one*), a birth date written more than one way (`1993-05-25` beside `93-05-25`: the same date won't match), values that look like one other field (`set feature` moves the column there, the field's own columns kept after it, or takes it off a feature when that field reads it already), else how few look right, with one value that doesn't. A feature read from columns joined is judged whole. `check records` says the same, once the file is described. Nothing is changed until you run the command.
- **A field the run needs and no column holds** stops the run with the file's columns and, for each missing field, the column whose values look most like it (in JSON, as `hints`). These suggestions are never applied without you.

The full check, every record prepared and every key's pairs counted, as a run's first steps do:

```bash
.venv/bin/nayose check records customers.parquet
```

It prints each field, its fill rate and the columns it comes from, what would be turned off, each key's pairs per record, and the blocks of 64 or more records that the run will check on a sample. For each field, two shares from a sample of 10,000 records point at a mistake before it costs a run:

- **looks right**: the share of filled values that look like the field (`[locale.detect]`). A low share is a wrong column, or a format the comparisons don't expect: a full phone number where the last four digits are expected, dates written two ways. A birth date may have two or four digits of year (`93-05-25`, `1993-05-25`): dates are compared as written, so one format throughout is what counts.
- **top value**: the share of filled values held by the most common one. A placeholder (`0000`, `19000101`) shows as one value on many records, and the model counts it as an agreement between every two records that hold it. A field whose values are few by nature, such as the prefecture, has a high share anyway.
- **Other names for the same information** need only `[columns]`. Another language needs `[locale]`. A different kind of record needs a new `config/pipeline.toml`, chosen again with `scripts/choose.py` on labelled or synthetic data ([architecture](architecture.md#1--context-two-loops)).

## 3 · Run

```bash
.venv/bin/nayose resolve records --workspace workspaces/customers     # the file given last
```

| Parameter | Does |
|---|---|
| `INPUT` | a CSV, TSV or Parquet file (named as it is, `[` in its name or not), a quoted glob (`'data/in/*.csv'`, its files only) or a folder of them (hidden files and `__MACOSX` left out), read as they come; several files are read together by column name. Copied into the workspace first, as `load records` does; left out, the file given to it last, a file it held already given again included (`inputs/last`) |
| `--workspace` | the workspace: the folder that keeps one matching job. A full run refuses one that already holds a run |
| `--overwrite` | replaces the run in `--workspace`; people's decisions and answers in it stand |
| `--compute KEY=VALUE …` | DuckDB limits for this run, overriding `config/settings.toml` `[compute]`: `memory_limit=8GB`, `threads=4`, `temp_directory=<folder>`. Past the memory limit, DuckDB spills to that folder |
| `--pipeline` | another pipeline file. Default: `config/final.toml` |
| `--model` | a model fitted before, used instead of fitting on this file; an increment scores with the model of the run it adds to |

`[compute]` in `config/settings.toml` sets the same three for every run. Left empty, each keeps DuckDB's default, all cores and 80% of the memory, and spills to a folder of the person's own, readable only by them, in the system's temporary folder. Before any join, a full run checks that the pairs fit in memory plus the room DuckDB may spill to: 90% of that disk's free space. An increment checks the blocks of 64 or more records its batch reaches; its other pairs all touch the batch.

The run needs no labels: it fits its model on the file itself. On a terminal, one line shows the step under way: what it does, how far it is and about how long is left, from the step's own pace and, for the steps after it, from the workspace's last run of the same kind scaled to the records (a first run gives only what it can measure). Each step gets a line of its own as it ends, with its time and what it found. Then the result in short: the records and the entities they became, the pairs waiting for people and from how many points, what merges without them, about how many matches it may have missed, the records flagged person or company, and where the report is. `--verbose` prints the whole summary: records, entities, who joined them (the rules, the model, people), the model's links and how many of them it expects to be false, the pairs to decide, the records' and customers' kinds, where the kinds come from (no answers yet; or the answers, the lines and how often the flag is wrong on those drawn at random), how many records are flagged, how often a sure kind contradicts the flag, and notes. The expected false links are the sum of 1 − match probability over the model's links: the model's own estimate, with no labels. A bigger file holds more people who share a name and an address, so at a fixed threshold the count grows with the file: on generated files, 0.84 at 12,532 records, 4.38 at 74,959 (1 and 3 found) and 30.11 at a million ([benchmark](../reports/benchmark.md)). A note says what the loader fixed, a field filled in under 5% of records (often a mapping mistake), a part turned off, or what the fit couldn't learn from. Last come the commands that usually follow: the pairs and the records left to people, and the results at a glance. What each step does, and what it costs: [architecture, the run](architecture.md#4--the-run).

### Synthetic records

```bash
.venv/bin/nayose generate records --records 100000 --difficulty hard --workspace workspaces/try   # then resolve records
```

Records of people and companies made from real names, companies and towns, each under one or more records with typos,
other notations, moves, new phones and missing values, then loaded into the workspace as a file is
(`inputs/0001-synthetic-hard-100000`): exactly `--records` of them (default 10,000). The workspace's mapping must read
the generator's columns, as the project's does. The same size and difficulty give the same records, so a second time
copies nothing. `--difficulty` (default medium) sets how hard they are to match, from `config/generator.toml`
`[difficulty]`; measured on 10,000 entities:

| | typos: name / phone, address, birth date | moves and new phones, per person | last column filled | true pairs exact rules settle | true pairs with nothing in common |
|---|---|---|---|---|---|
| easy | 5% / 2% | 0.5 | 90% | 21% | 0.5% |
| medium | 30% / 10% | 2 | 65% | 1.1% | 11% |
| hard | 50% / 20% | 3 | 50% | 0.2% | 24% |

A true pair is two records of one customer; one with nothing in common shares no value and no close name, and no
method can find it. Generating takes about 100 s a million records, in parts of 50,000 entities, and reading them in 40 s more. Past 60,000 entities
names repeat more than in a real file, so name keys make more pairs. On the page: *Synthetic records*, under the file's
path on step 2.

### Auto mode

```bash
.venv/bin/nayose try everything customers.parquet                     # workspaces/auto-<month><day>-<time>, then auto/report.md
```

`try everything` runs, on one file, the commands a person would, each in a process of its own: it makes a strict
workspace, loads the file and places the columns its contents suggest, checks it, rehearses a file of its size, runs
it, reads the method, tries the changes `describe method` proposes (`--trials`, 3), tries the names in another script
the file holds in a workspace of their own, and counts the reviews. A step that fails is kept with its fix, and the
steps that need it are skipped. It never lowers the trust line or adopts a method. At the end it writes
`auto/report.md`, to send for help, and `auto/report.json`, the facts behind it: counts, shares, seconds and the names
of columns, fields, rules and keys. No example, ID or path is taken into it, and it is then checked against every value
of a sample of 20,000 records, every run of six digits or more and every run of kana or kanji that is no column name:
anything found is redacted, and its last line says how many. When the file's first line was a record, not a header
(the reader says so, or two of its names read like values: four digits, an email, a legal form, a date, a known full
name or address), every column name counts as a value.
A step that crashed keeps its own words in `auto/<step>.log` on the machine, never in the report. Stopped with Ctrl-C,
it still writes the report of what ran. About 10 minutes a million records. On the page: *Auto mode*, on the first
screen, the Overview and *Results*.

### Before a run on your file

`try everything` does all of this at once ([above](#auto-mode)). A first run on a file of your own, by hand, in this
order:

1. **Map and check the columns.** `nayose describe records FILE --workspace W` shows each column's share filled and an
   example, which columns each field reads and how many of its values look like it; `nayose check records FILE
   --workspace W` prepares every record and counts every key's pairs, as a run's first steps do, and says whether a run
   will go through (`ready`: what would stop it, and what to look at first, each with what to do). Map until nothing
   needed is missing and no field reads a column of another kind (step 2 of the page warns of both).
2. **Give DuckDB its limits.** Set `[compute]` `memory_limit` below the machine's memory, leaving room for Python, and
   `temp_directory` on a disk with room for about 350 bytes per pair: past the limit DuckDB spills there. `check
   records` gives the room the run has against the pairs this file needs (`capacity`: `headroom`, fit ÷ needed).
3. **Rehearse at the file's size.** `nayose rehearse records --workspace W` runs a generated file of the same size and
   shape under the same limits, in a process of its own, and says the seconds of each step, the peak memory and the
   peak spill on this machine; a run that would stop here stops in the rehearsal first, with why. Past 60,000 entities
   generated names repeat more than real ones, so its pairs run higher than the file's, which `check records` counts
   exactly.
4. **Keep the workspace strict.** A new workspace starts with `trust = "none"`: nothing merges by points until people
   have checked a sample of each range of points ([section 6](#the-trust-line)). Lower the line only as the samples
   prove it. `nayose describe review --workspace W` says, after the run, how many pairs that takes, range by range.
5. **Load, then look at what the reader did.** `nayose load records FILE --workspace W` copies the file in and reads it;
   its answer, and step 2 of the page, say what it fixed by itself, what waits for a repair, and the rows it couldn't
   read (`unread.parquet` in the part). Accept a kind of repair once its examples look right.
6. **After the run, read the probe.** The summary's `missed` estimates the matches no pair key lists; `describe method`
   proposes a key for them, and a trial measures it before you adopt it ([section 6](#improve-the-method)).
7. **Drop inbox files by moving them in.** `serve inbox` leaves a file changed in the last `--settle` seconds for the
   next pass: copy a file next to the inbox, then move it in once it is complete.
8. **To ask for help, send `report.txt`,** or auto mode's `auto/report.md`. Neither holds a record's value
   ([section 7](#7--when-something-is-wrong)).

## 4 · Read the outputs

Everything is in the workspace. A run also reads `config/kind_names.npz`, the name model that tells persons from companies, and `steps.json` names it with its SHA-256.

```bash
.venv/bin/nayose describe workspace workspaces/customers                         # records, entities, the largest, each run, what is open
.venv/bin/nayose describe entity 0000000151 --workspace workspaces/customers     # one record's entity: its records, and what joined them
.venv/bin/nayose describe matching --workspace workspaces/customers              # every method, on which fields, with this run's numbers
.venv/bin/nayose describe key person_name --workspace workspaces/customers       # one pair key: records per value, one real group, what only it found
.venv/bin/nayose describe results --workspace workspaces/customers               # the scores, what waits for you, what joined, what merges without you
.venv/bin/nayose list scored --workspace workspaces/customers --from 12          # every pair at 0 points or more, best first, 100 a page
.venv/bin/nayose show records 0000000151 0000000874 --workspace workspaces/customers   # their full rows, every column as the file gave it
.venv/bin/nayose list entities --workspace workspaces/customers                  # the entities of two records or more, largest first
```

None of these runs anything: they read the workspace's files.

| File | One row per | Holds | Use it to |
|---|---|---|---|
| `gold.parquet` | record | `cluster_id` (the smallest record ID of its cluster); `resolved_stage` (`deterministic`, `probabilistic` or `review`; empty for a record found alone); `resolved_by` (the rule, `fs` for the model, or `review` for people); `kind` (1 person, 2 company, 0 not sure), `kind_p` (the probability of a company), `kind_by` (`engine`, `flag` where the engine is not sure and the file's flag decides, or `people`), `kind_flagged` (the engine sure against the file's flag: matched as the engine says), `kind_held` (people can't tell: its name kept from matching) and `customer_kind`, the entity's (2 if any record is a company; 1 if none leans company and one is a person; else 0) | give every record its entity, and every entity its kind |
| `matches/` | accepted pair | both IDs; `match_weight` in bits; `match_probability`; `sources`, the candidate generators that listed it | see why two records were joined |
| `rule_kept/` | pair a rule found | both IDs, the rule and its stage; `match_weight`, the model's bits for it; `merged`, whether it joined (at the trust line or above, or no line set; and not decided no_match) | audit the rules |
| `proposed/` | the model's pair below the trust line | both IDs, `match_weight`, `match_probability`, `sources`; empty with no trust line | the pairs waiting for people, or for the line to come down |
| `scored/` | pair at 0 points or more, and every rule's pair | both IDs, `match_weight`, `match_probability`, `sources` (none: a rule alone found it), `rule`, `named`, `keep`, and `gamma_<comparison>`, the level each comparison reached | list, filter and review any pair without a run; merge by your own conditions ([section 6](#merge-by-your-own-conditions)). A workspace whose run wrote none gets it once, on first use, from the pairs that run stored, scored again |
| `qa.md` | | the summary (with `missed`: the matches no pair key lists, sampled within `[probe]` groups, as estimated by the probe); each field's fill rate (flagged under 5%), the share that looks right and the share of its most common value; what was turned off; each step's Big-O, time and memory; pairs by weight; cluster sizes; the 10 largest clusters; match patterns no key guarantees; the review queue; records and customers by kind; clusters holding both a sure person and a sure company; the oversized blocks and what was decided for each | check the run without labels |
| `report.txt` | | the run on one page of plain text, with no record's value in it: what ran (the code, the tracked files changed in this copy, the pipeline, the machine's limits), the summary, the fields, scores and links by weight with the false links expected, cluster sizes, each step's time and memory (the fit's own sample and the u measured on the file apart; the gate's samples), where each step's time went in the string comparisons (per function: the wall seconds while it ran, the threads that ran it at once, the values it compared, per value), the model's m, u and bits per level, the costliest blocks (a full run), the match patterns no key pairs | send it to whoever helps with the run ([section 7](#7--when-something-is-wrong)) |
| `review.parquet` | pair for people | `why` (`decide` or `audit`); an empty `decision`; both records' compared fields; per comparison, the level reached and its bits; `accepted`, whether the run joined the pair | decide the next range below the trust line and audit above it, or, with no line, decide the pairs just below the threshold and those above it with no name compared, and audit those just above ([section 6](#6--review-and-decide)) |
| `kind_review.parquet` | record for people | `why` (`decide` or `measure`), `reason` in words, `engine_says`, `name_says`, `flag` and `birth_date` if the file has them, the name; `engine` and `engine_p` (the engine's kind and its probability of a company), `name_p`, `drawn`; an empty `kind` | answer 1 person, 2 company or 0 can't tell ([section 6](#6--review-and-decide)) |
| `decisions/` | decided pair | both IDs and `decision`; `why` (`decide`, `audit`, or `split` from `split entity`) when there is one; `round`, the round it was decided in; one part per file people gave back | what people decided; a full run applies it again |
| `method.toml` | | the workspace's changes to the tuned method: `trust` (the trust line), `merge` (the conditions under which pairs merge without people), `line`, `drop_rules`, `drop_keys`, `add_keys` | every command on the workspace runs the method it says ([section 6](#the-trust-line)) |
| `rounds.json` | round | per method the workspace ran: its `config` hash, `method`, when, the links it made and the false links the model expects | see each round's results side by side |
| `trials/` | trial | each trial's result (`<n>.json`, the last 5); the clusters of the method it was tried against (`base.parquet`, `base.json`) | `adopt method --trial n` |
| `index/` | key of a record | every key of every record and every searched value, sorted (`<id>.duckdb`); the records as compared (`<id>.records.duckdb`); what changed since (`<id>-<n>.duckdb`); the person/company classifier's fitted part (`<id>.kind.pkl`); `manifest.json`, which names them and what they rest on | `match record`, `search records`, the *Look up* page |
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
- **Match without adding.** `nayose match records` runs the increment's steps and writes nothing: for each record, the entity it would join, whether it waits for people (a pair of it below the trust line), or a new one, and the rule or the model's best weight that links it.

### Look up a record

```bash
.venv/bin/nayose build index --workspace workspaces/customers      # once: the commands that change the run keep it up to date
.venv/bin/nayose search records FULL_NAME_KANA=ヤマダ PHONE_NUM_4=1234 --workspace workspaces/customers   # by the start of any values
.venv/bin/nayose match record FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234 POST_CD=1000001 --workspace workspaces/customers
.venv/bin/nayose match record --record 0000000151 --workspace workspaces/customers   # a stored record, as if it were new
```

- **Who could it be?** `search records` takes any values by the file's column names, as much of each as is known. It lists the records whose values start with them (a name also: ends with them), prepared as a run prepares a record, so ダ finds タ too. Values that find nothing as given are read again as people type what records hold otherwise: full-width as half-width, a name's hiragana as katakana, digits without what is written between them (100-0001). The records sharing the most values come first, then those the run's model gives the most points, a field not given counting as missing; `--count` of them (10), from `--from` points (any). A value that starts 2,000 records or more lists none of them, and says how many: give more of it, or another value beside it. Blanks and placeholders alone (`-`, `NULL`: `[input] nulls`) are nothing to search by; `match record` refuses them, saying they read as missing. It searches names, the given name, the address, the postal code, the phone, the customer ID, the birth date and the address code; a value of any other field (the prefecture, the city), or of one this run's records don't hold, is said, `this run can't be searched by prefecture`, not searched.
- **Is this customer already here?** `match record` takes one record by the file's column names. It answers with the entities it may belong to, best first, at the review floor (6 points) or above: each with its points, how each field compared, the rule that would join it, and whether it is likely the same (at the line, or joined by a rule). When none reaches the floor, it names the closest record compared and its points: a name alone weighs too little to reach it. Values typed otherwise than records hold them (a name in hiragana, `03-1234-5678`) that reach nothing as given are looked up again as records hold them, where the workspace's mapping doesn't prepare them so; kept if it finds more or comes closer, and then said (*read as マツモト*).
- **The same pairs as an increment.** The record is prepared as a run prepares one. Each of its keys is looked up, a key value on too many records is gated as a run gates it, and the records found are scored with the run's model. So it lists and scores the pairs an increment of that record alone would. It writes nothing and adds nothing: `add records` does.
- **The index.** `build index` reads the run's own files once and writes the workspace's `index/`: every key of every record and every value a search reads, each sorted, so a lookup reads only the rows its keys name. On a million records it is built in about 7 s and takes 0.85 GB. With the index kept open, as the page's server keeps it, a lookup takes about 0.1 s and a search about 70 ms; both grow only with the log of the run's size ([performance](performance.md)).
- **Kept up to date.** Once built, the index is brought up to date by every command that changes the run, as its last step. An increment's records, people's applied decisions and merging conditions are written beside it: 1,000 records added into a million take about 0.3 s. A full run, a new mapping, people's person/company answers, or records added or moved reaching a tenth of it build it again. An index that is out of date anyway (built by another version, or the update failed) refuses lookups until it is built again.
- **In the browser:** *Look up*, above Setup. As you type, *Who could it be?* lists the records that start with it; *Look up* (or Enter) answers what the run would do with it. *Show* and *From points* set how many, and from how many points, for both; the browser keeps them.

## 6 · Review and decide

### The trust line

A file comes with no answer sheet, so how often a score is right on it is not known until people check. The trust line is one number per workspace, its `method.toml` `trust`: pairs scoring at or above it, a rule's or the model's, join without people. A workspace made with `nayose create workspace` starts with `trust = "none"`, above every step: nothing joins before people check.

- **The next range.** Each run puts on `review.parquet` a random sample of the pairs from the next step down to the line (`[trust] steps`: 20, 12, 8, 6, 0 bits), 300 of them (`checks`), less those already decided. A step whose range holds no pair is passed: lowering the line past it joins nothing, so people start at the first range that holds pairs (on a file where nothing scores 20, at 12). `nayose draw pairs --workspace W` puts the range's pairs on a sheet that lacks them, from those the run kept for people, without a run. A pair people say is the same joins at once; one they say is different never joins.
- **Lowering it.** When the sample's 300 are decided and applied (`apply decisions`) and none is false (at most 1% false, at 95% confidence; a range with fewer pairs is decided whole), `nayose lower trust --workspace W` moves the line down one step and runs the files again: the whole range joins. It refuses before then, and says how far the sample is.
- **A range found false.** Once people say one pair of the next range is different, the line never steps past it: the sheet then holds that range's open pairs and every range's below, best first, 300 at a time, for people to decide one by one.
- **Watching above it.** Each run also puts 20 spot-checks (`watch`) of the pairs above the line on the sheet. One found false: `nayose raise trust --workspace W` moves the line back up a step, and that range waits for people again.
- **Never by itself.** A rule's pair the model scores below the last step, and a model pair with no name compared, join only when people say so.
- **How much is left.** `nayose describe review --workspace W` gives, for each range, its pairs, the sample it needs, the false pairs the model expects in it and so the chance its sample comes back clean, the false rate a clean sample proves, and the checks left to reach that line from the top; then the pairs no line ever merges, the person/company sheet, and the hours at `--seconds` a pair (10 unless given: an assumption, not a measure).

`nayose describe workspace W` says where the line is, the range checked next, how many of its pairs are decided and how many were found false. A workspace with no `trust` runs the method as tuned: every rule's pair, and the model's at 8 bits with a name compared.

### Merge by your own conditions

A workspace can merge pairs without people under conditions people set: its `method.toml` `merge`. With none, nothing merges by points: people decide every pair.

```bash
.venv/bin/nayose describe merging --workspace workspaces/customers --conditions '{"join": "or", "when": [{"points": 14}, {"rules": ["F3_NAME~_CIF"]}]}'
.venv/bin/nayose set merging --workspace workspaces/customers --conditions '{"join": "or", "when": [{"points": 14}, {"rules": ["F3_NAME~_CIF"]}]}'
.venv/bin/nayose set merging --workspace workspaces/customers --conditions '{"when": []}'       # off: people decide every pair
```

- **The conditions.** `{"points": 14}`: the pair scores 14 points or more. `{"rules": [...]}`: one of these rules found it. `{"fields": {"name": "fold JW high", "birth": "exact"}}`: each named comparison reached that step or a closer one (`describe matching` lists each comparison's steps). `join` is `and` (all of them) or `or` (any of them).
- **No run.** `describe merging` counts the pairs they would merge, and the entities of two records or more they would make, each condition alone and together. `set merging` saves them and rebuilds `gold.parquet` from the stored pairs (`scored/`): people's applied *same*, plus the pairs the conditions take, less those people said are different. Seconds, whatever the run's size. A record joined only by them gets `resolved_by` = `auto`.
- **Off again.** Turned off or narrowed, what they joined parts again; people's answers stand.
- **People's answers.** `apply decisions` rebuilds the entities the same way while conditions are set, so a pair people say is different parts at once; one typed in and not yet applied waits, as every answer does.
- **The next run.** Every run on the workspace, an increment included, takes the same conditions in place of the trust line, so a run and `set merging` give the same entities.

### Without a trust line

The run accepts a pair at 8 bits or more. Just below that line, from 6 to 8 bits, is the threshold rule's safety margin: pairs that were never wrong on cross-validated training data, but are held back in case of noise. People decide them. On the synthetic val split, the margin holds 112 pairs, all true: accepting them would raise recall from 46.3% to 51.7%, with no false merge. One grid step lower, at 4 bits, the first false pair appears ([results](results.md)).

`review.parquet` has two kinds of rows, named in `why`:

- **decide:** every pair of clusters whose best link scored in the margin, or above the line with no name compared (the name check, `[model] needs`: a person and a company at one address, a record with no name), one row per pair of clusters, highest first. Pairs already decided are left out. An increment keeps the rows still open, and adds its own. Any run, a full one too, keeps a decision typed into the sheet but not yet given back, and so does the person/company sheet with a kind typed in.
- **audit:** about 50 accepted pairs up to 4 bits above the line, a few from each 1-bit band. A wrong one is a false merge.

Each row shows the two records' compared fields side by side, then, per comparison, the level the pair reached (for example "fold JW high": the kana-folded names close by Jaro–Winkler) and the bits it earned. The bits, plus the starting point, add up to `match_weight`. `accepted` says what the run decided.

List the open pairs, decide each, then apply the decisions:

```bash
.venv/bin/nayose list pairs --workspace workspaces/customers --open        # --pending: with those written in, not applied yet
.venv/bin/nayose decide pair 0000000151 0000000874 match --workspace workspaces/customers     # or no_match; clear takes it back
.venv/bin/nayose apply decisions --workspace workspaces/customers
```

Each decision is written into the workspace's `review.parquet` (its `decision` column) and applied by `apply decisions`. `list pairs` marks each row open, written in, or applied. Any pair the run kept can be decided, not only the sheet's: `list scored` lists them all, and a pair the sheet lacks joins it when decided. A sheet filled in elsewhere, any file with the two ID columns and `decision`, goes back with `apply decisions --file reviewed.parquet`.

- **`match`** joins the two clusters at once, scoring nothing. A record joined only this way gets `resolved_by` = `review`.
- **`no_match`** splits nothing at once. It is kept, and a full run never joins the pair, by the model or by a rule. It applies to that pair only: a third record can still join the two.
- **Kept for good.** Decisions are stored in `decisions/`, which every full run on the same folder applies again. `decisions/` and `kind_answers/` are people's work: back them up. Rows without a decision are skipped, and a decision applied before changes nothing, so applying a sheet twice is harmless.

### Improve the method

The method (pair keys, comparison steps, match rules, the line) is tuned on generated records; on your file only the model's weights are fitted. People's decisions show where it fails, so the review is a loop: find matches, decide the pairs, see what the decisions say about the method, change it, and find matches again.

```bash
.venv/bin/nayose describe method --workspace workspaces/customers
```

- **The rounds.** Each method the workspace ran is a round (`rounds.json`): the links it made, the pairs people decided in it, and the audits they found false.
- **The line.** Every pair people decided, scored again with the run's model, beside the weight bands. A line within the band people review (from the lowest weight they decide to 4 bits above the line) that sets right decided pairs without setting any wrong is proposed.
- **The rules.** Each match rule's pairs, those that score below the line, and those people said are different: a no_match keeps only that pair apart, and the rule still joins pairs like it, so such a rule is proposed to leave out.
- **The pair keys.** Each key's pairs and seconds, the links it found, and those no other key found. A key with a tenth of the pairs or more and no link of its own is proposed to leave out.
- **A key to add.** The full run's probe finds matches the method missed among pairs that share a phone or a postal area (`[probe]`), and says of each whether no key listed it. For those, a key of one or two fields (phone, postal area, city, prefecture, town, address code, name initial, given name, person name, birth date) on which both records of at least a fifth of them agree is proposed, within the pairs per record the budget allows (`[budget] max_pairs_per_record`), with the share it lists, about how many matches it would find, and its cost. Trying it reports the probe's count before and after.
- **The comparison steps.** Each step's bits and the pairs that reached it.

Try a change before you take it, adopt it, and decide the new round's pairs:

```bash
.venv/bin/nayose try method --workspace workspaces/customers --line 9 --drop F3_NAME~_CIF
.venv/bin/nayose try method --workspace workspaces/customers --add phone+city          # a key added: its fields joined by + (field:normalizer)
.venv/bin/nayose adopt method --workspace workspaces/customers --trial 1
.venv/bin/nayose draw pairs --workspace workspaces/customers --count 50
.venv/bin/nayose reset method --workspace workspaces/customers      # back to the tuned method
```

- **`try method`** runs the method as it is and the method with the change on the workspace's files, both without people's decisions, so neither is judged on pairs it was told. It says what the change does to the pairs people decided (those they said are different yet joined: false merges; those they said are the same yet apart) and, without labels, to the links, the false links expected, the entities, and the pairs of records it puts apart or together. Only `trials/` is written: the last 5 trials, and the clusters of the method as it is, kept for the next trial.
- **`adopt method`** writes the trial's method into the workspace's `method.toml` (`line = 9.0`, `drop_rules = ["F3_NAME~_CIF"]`, `drop_keys = ["sn_person_name_reversed"]`) and finds matches again with it; if that run fails, `method.toml` stays as it was. Every command on the workspace then runs that method, an increment included. A new method is a new round. `reset method` goes back to the tuned one, keeping the trust line people earned and their merge conditions, unless `method.toml` doesn't read, or its trust line isn't a step of the pipeline: then it keeps nothing.
- **`draw pairs`** adds audit rows to `review.parquet`: links, the model's and the rules', that nobody has decided, spread over the weight bands. No false link in many audits is what says the links are right: at 50 audits with none false, the false rate is under 6% at 95% confidence (`describe method`, `audits`).

### Persons and companies

The engine decides each record's kind on its own. It calls a kind it is sure of: a company where a legal form is written (株式会社, カ)〇〇, 〇〇(カ …), and a company or a person where the name model is at least `[kind] name_line` (99%) sure; with people's answers, past the lines they place. Else the file's flag (`PERSON_ORG_CODE`) decides, and without one the record is `0`, not sure. A sure call the flag contradicts is **flagged** (`kind_flagged`): the record is matched as the engine says, and listed for you. On generated files it gets fewer kinds wrong than the flag alone, with no more false merges ([chapter 7](guide/07-person-or-company.md#on-a-whole-run)).

A full run writes `kind_review.parquet`, records for people, as `review.parquet` holds pairs. Each row says in `reason` why it is there, and what the engine (`engine_says`: `1 person`, `2 company`, `0 not sure`), the name alone (`name_says`, with how sure) and the file's flag (`flag`) say. Two kinds of rows, named in `why`:

- **decide:** the flagged records, the engine's surest first ("the engine is sure it is 1 person (99.6%), the flag says 2 company: matched as the engine says"). At most `config/final.toml` `[kind] review_max` (1,000); answer the ones you want, and the next sheet brings the rest.
- **measure:** optional. 2,000 records drawn at random, to measure the flag and the engine. Answered, they place the engine's lines on your file and say how often the flag is wrong. Records you were sent to decide can't do that: they were picked because they look wrong.

Answer each record `person`, `company` or `unsure` (stored as `1`, `2`, `0`: can't tell from the record). A sole trader is a person, legally. Then apply the answers:

```bash
.venv/bin/nayose list kinds --workspace workspaces/customers --open
.venv/bin/nayose answer kind 0000000151 company --workspace workspaces/customers
.venv/bin/nayose apply answers --workspace workspaces/customers
```

Answers change how each record's name is matched, so `apply answers` is a rerun: a full run on the run's own files ([section 5](#5--add-new-records)), with the answers. A sheet filled in elsewhere, any file with the ID column and `kind` (`1`, `2` or `0`), goes back with `apply answers --file answered.parquet`.

- **Your answers stand** for their records (`kind_by` = `people`): the record's name goes to the side you said. A `0` stands too: the record's name stays out of matching (`kind_held`), and its pairs come to you in `review.parquet` with no name compared.
- **They teach the engine.** The combiner fits on every answer 1 or 2 and places its lines on the measuring draw only, once 50 of the draw are answered, both kinds among them; until then the engine's own rule decides, as without answers (answer the whole draw: on fewer answers the company line goes a step stricter, and below 1,000 answers it can still be too loose); the person line only where the answers above it keep it within 1% wrong at 95% confidence (with none wrong, 300 answers above it). The summary says where the lines fall, how often the flag is wrong on the answers drawn at random, and how many records are flagged.
- **They add up.** The run keeps each sheet's answers as given, one part per sheet in `kind_answers/`; per record the newest answer stands, and a blank row erases nothing. The next sheet leaves out the records answered, and brings back those left blank. A sheet answered wrong is undone by deleting its part, then `nayose rerun records`.
- **A full run writes the sheet.** A record an increment flags is on the sheet of the next full run.

`config/final.toml` `[kind] trust_flag = true` takes the file's flag as it is, with no engine and no review sheet: the benchmark's flag-alone baseline.

A company record under its representative's name, at the representative's address and phone and flagged person, looks like the person's own record in every column; nothing in the file tells them apart, so no sheet finds it.

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
| `… a ZIP or Excel file, not records` | an Excel workbook; save it as CSV or Parquet |
| `… a Parquet file cut short` | an interrupted copy |
| `the file lacks a field every run needs` | `[columns]` points at a column the file lacks; it lists the file's columns and suggests a mapping |
| `columns … could each be …` | two columns match one name loosely |
| `no record has an ID in column …` | `id` is mapped to the wrong column |
| `the normal blocks alone would make … pairs, more than fit` | the file's pairs would not fit in memory and the temp disk: give DuckDB more room (`--compute memory_limit=… temp_directory=…`) or split the file |
| `… already holds a run` | `resolve records` into a used folder: add `--overwrite`, or pick another folder |
| `… a workspace an earlier nayose wrote` | answers, input parts or rules' pairs in a layout this nayose doesn't read: create the workspace again and load its files (`--overwrite` replaces an old run's rules' pairs) |
| `out of memory` | past `--compute memory_limit`: raise it, or give `temp_directory` a disk with more room |
| `… the spill folder isn't yours alone` | the spill folder in the system's temporary folder was made by someone else, or is open to them: give `temp_directory` a folder of your own |
| `… don't line up with its header` | a wrong delimiter or header: more than 1,000 records, and over a tenth of them, don't fit its columns |
| `… both read …: the model would count one value twice` | one column mapped to two compared fields: map each to a column of its own |
| `--compute …`, `not valid TOML`, `not UTF-8 text`, `… not a number` | a limit, a settings file or an option to correct, as the fix says |
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

A workspace another job is writing to stops the run with `another job is writing to …` and exit code 75: nothing to fix, try again once the other job is done. The lock and the renames that finish each write hold on a local disk and on a network one (NFS, Filestore, a Windows share). A workspace on object storage mounted as files (Cloud Storage FUSE, s3fs, rclone, blobfuse) is refused, `is on object storage (gcsfuse): no lock holds there`, before anything is written: no lock holds there, and a write's rename isn't atomic. In a cloud, keep workspaces on a persistent disk or Filestore.

Pairs are counted before any join, so a run that couldn't fit stops within seconds instead of running out of memory or disk.

**To ask for help, send `report.txt`** from the workspace. It holds field and column names, counts, shares, times and the model's parameters, and no record's value: no ID, name, phone or address. The notes that quote a value (a placeholder phone, a customer ID a rule doesn't trust) are only in the terminal and `qa.md`; `steps.json` holds record IDs (the probe's pairs, up to 200 a group), and the workspace's other files hold the records themselves. For a run that stopped, send the two lines it printed, and the output of `nayose check records`.

## 8 · Run it on a schedule

`nayose serve inbox` takes in every file dropped in an inbox (Parquet, CSV or TSV), one at a time, in the order it arrived.

```bash
.venv/bin/nayose serve inbox inbox --workspace workspaces/customers                # one pass; cron can call it
.venv/bin/nayose serve inbox inbox --workspace workspaces/customers --every 300    # a pass every 5 minutes
.venv/bin/nayose serve inbox inbox --workspace workspaces/customers --settle 120   # a file changed in the last 2 minutes waits for the next pass (default 60)
```

```
inbox/batches/*              new records: add records; into an empty workspace, the first batch is resolve records
inbox/decisions/*            people's decisions: apply decisions (section 6)
inbox/answers/*              people's person/company answers: apply answers, a rerun (section 6)
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

The page runs the same commands, and nothing else. Every page answers the questions a person has on it, in the order they have them, and reads top to bottom, left to right, big before small: its main question first and largest, with its answer in a sentence and the one action that follows from it at the end of that row; each later question smaller, below; the detail folded last. A page with an item to decide (a pair, a record, an entity) puts it first and wide, and the list it comes from beside it. On the left, before the first run, the three steps to it, in order, each marked done (✓), next, needs you (!) or optional, with one line of where it stands; what can't act before the first run (adding records, matching again, looking up a record) is greyed out until then. After it, three places: *Results*, *Review*, with the pairs waiting, and *Explore*; then *Setup*: the workspace, your data, *Find matches* and the *Method*. Nothing on them runs the matching again: they read the workspace's files. The path under the heading says how much each part covers (*2,000 records to check › This record*). Every button runs one `nayose` command; a run asked for through a form opens in a dialog with its command line, while *Try*, *Adopt*, going back to the tuned method and *Apply decisions* start at once; the drawer at the bottom (the terminal icon, taller or shorter by its top edge) lists every command the page ran. A long command's progress shows at the bottom right on every page, as a download panel: what it does, how far (the rows read, the step a run is on, or the pairs scored and the likely matches so far) and about how long is left; it folds or closes, and the command runs on either way. Building the index says how far in the Look up card instead, where its button is. Its step in the list on the left turns and says how far it is, and *Results* shows it with a way to its page. A short notice shows at the bottom left, closed by its ✕. Each step has an address of its own
(`#run`, `#pairs`), so Back, Forward and a reload keep to the steps; a long command still running when the page is
reloaded or opened again is followed to its end: *Find matches* and *Results* say so meanwhile, and another long command
waits, said so. Started again, `nayose
open ui` prints a new link: the old one says to open it.

| Page | Its questions, answered in this order | Runs |
|---|---|---|
| *Results*, after a run | *What did the run do?* The records and the entities they became, and whether anything merges without you, with *Review N pairs*. Then a tile per question, each with one number, a chart and a way to its data: *How did the scores come out?* (every pair compared, the keys' and the rules' alike, the full run's and each increment's, by points; a run logged before each counted its own says which records added since it leaves out, until matching runs again), *What is waiting for you?* (the pairs from your review points, by range, and about how long they take to review if each takes 20 seconds), *What has joined?* (entities by size, and who joined them), *Does anything merge without you?*, *Could it miss a real match?* (what the probe found among the pairs sharing a phone or postal code that no key listed; a match sharing neither isn't checked), *Were any groups too big to compare?* (values on 64 or more records, by the key that made them; it opens their list in *How it works*), *Person or company?* (the records flagged: the engine sure against the file's flag). In a workspace auto mode made, *what should I send?* Its report, with *Copy the report*. Every run, folded | `describe workspace`, `describe results`, `try everything` |
| 1 Choose a workspace | *What will this do for me?* An example: three records written differently become one entity, one ID, and *Create a workspace*, or *Auto mode*: every step on one file, each listed as it ends. *Can I pick up where I left off?* The latest workspaces, each with where it stands, and *Open* | `list workspaces`, `create workspace`, `try everything` |
| 2 Prepare your data | *Which file holds your records?* Its path, with *Load*, or synthetic records by size and difficulty, with *Generate* ([Synthetic records](#synthetic-records)). *Did my file load?* Its records and columns, and what waits for a repair, or what is still needed, with *Suggest the columns*. *Which repairs do I accept?* Each kind the reader proposed, its values as given and repaired, with *Accept these N*; what it fixed by itself; the rows it can't read. *Is anything going to hurt the matching?* Fields mostly empty, and fields no column is mapped to with the ways of finding pairs they turn off. *Did it pick the right columns?* Each group's features: the column in each, how full it is, a real example; *Suggest* shows what the file's contents place there, kept with ✓; a column clicked lists the file's columns to put another in its place, and + adds one read where the others are empty; the file's columns, to drag onto a feature's row, folded below and kept in reach. A change shows at once and is saved behind it, one after another | `load records`, `generate records`, `describe records`, `accept repairs`, `set feature`, `set names`, `set preparation`, `add feature`, `remove feature`, `describe workspace` |
| 3 Find matches | Before a run, *how long will it take?* The records and about how long, and *Find matches*. During it, *is it working?* What it is doing now, the seconds so far and about how long is left, and each stage filling in as its step ends. Before a run, the estimate scales this workspace's last full run to the records, else this machine's reading of the file. During it, the time left is only what this machine measured on this file: a step that counts its work (records loaded, rules applied, keys joined, pairs scored) by its own pace so far, any other by its time in this workspace's last full run, scaled to the records, and the steps after it by that run. What nothing measured yet covers (a first run's later steps) makes it *at least* the time it can count, and with nothing to count it shows only the time so far. The bar is the work done, not the time spent: a step running past its last time holds it and says it is taking longer than last time, rather than stretching the estimate. Left and opened again while it runs, step 3 shows the run as it stands. After it, the records and the entities they became, and *Results*. Then *how did it find matches?* The stages in order, each opening its own question answered: *What did it read?* · *Which pairs did the rules match, and why?* (how the scoring rates the rules' pairs, and where it disagrees) · *Which pairs did it compare, and could a real match have been missed?* (all the possible pairs, how long comparing them all would take, the pairs compared; then a sample of the pairs that share a phone or a postal area, scored: the matches the method missed, with their estimate and the pairs found; each key opens `describe key`) · *How did it score each pair?* (one pair of the run as a waterfall, *Another pair*, and what counts most; every comparison's staircase folded) · *Where did it draw the line, and how many could be wrong?* (the line and its odds, the pairs matched and the wrong ones the model expects, pairs by points; every pattern folded) · *How did matched pairs become entities?* (with what to look at first) | `resolve records`, `add records`, `match records`, `rerun records`, `describe workspace`, `list patterns`, `explain pair`, `compare records`, `describe key` |
| *Review* | Tab *Same customer?*: the pairs waiting for you, best first, from *Review from* points (this browser keeps it), 100 a page, or a record ID's. The pair first and wide: its points and what found it; *Same*, *Different*, *Not sure* (<kbd>M</kbd>, <kbd>N</kbd>, <kbd>S</kbd>; <kbd>↑</kbd> <kbd>↓</kbd> move) and what each does; then both full rows ([Full rows](#full-rows)), and how it scored, folded, with *Why?* beside each step ([Why this match?](#why-this-match)). Beside it, how many wait and how many are decided, *Apply decisions*, then the list, a decided pair marked. *Auto-merge* opens the conditions under which pairs merge without you ([section 6](#merge-by-your-own-conditions)): points, rules, fields that agree, all or any of them, what they would merge counted as they change, then *Apply*; *Turn off* parts what they joined. Tab *Person or company?*: two parts, *Flagged* (the engine sure against the file's flag, surest first) and *Teach the engine* (optional: the draw at random). *Is this record a person or a company?* The name, large; what the engine thinks, and why the record is asked; the answers (<kbd>1</kbd> person, <kbd>2</kbd> company, <kbd>0</kbd> can't tell), saved as given; *Apply answers* matches again with them ([Persons and companies](#persons-and-companies)) | `list scored`, `show records`, `explain pair`, `decide pair`, `apply decisions`, `describe results`, `describe merging`, `set merging`, `list kinds`, `answer kind`, `apply answers` |
| *Explore* | Tab *Pairs*: *Which pairs scored highest?* The score chart (what it leaves out said, with *Run matching again*), then every pair at 0 points or more, as many as it says, best first, 100 a page, filtered by points, how it was found, its status or a record ID; a pair opens its full rows and how it scored. Tab *Entities*: *Which records became one customer?* Entities by size, then those of two records or more, largest first, or a record ID's; one opens the links that joined its records (a rule, the model, you, or your conditions) and their full rows. Tab *Records*: *Which record?* A record ID's full row as the file gave it, its entity, and the pairs it is in. Tab *How it works*: the stages, as on *Find matches* | `list scored`, `list entities`, `show records`, `describe entity`, `explain pair`, `describe results`, `describe matching`, `describe key`, `list patterns`, `compare records` |
| *Method*, under Setup | *Is the matching good enough yet?* From the pairs people checked: not known yet, so far yes (with *Review pairs*), or how many were wrong, with *Look at them*: the pairs people said differ, in *Explore*. *What could be better?* Each change worth trying in words, with what it would do, and *Try*; a trial tried, with *Adopt*; where to draw the line, folded; the rounds, rules, pair keys and comparison steps folded ([section 6](#improve-the-method)) | `describe method`, `try method`, `adopt method`, `reset method`, `describe key` |

### Full rows

Wherever two or more records meet (a pair in *Review* or *Explore*, an entity), their full rows sit side by side: every column the file gave, the different ones first, then the same, then the empty; *Only different*, *Hide empty*, *The file's order* and a column search. A column a comparison reads says how the pair was compared: the method and its score against its threshold, the step it reached and its points (*name: Jaro–Winkler person name 0.960 ≥ 0.95 → very similar · +13.2*); the letters that differ are marked. One record alone shows its row and the fields each column feeds.

### Why this match?

*Why?* beside a comparison's step plays *Why this match?* in a small scene over the page: the comparison's steps in the order the engine tries them, each asked as a question (*very similar?*) on the two records' values, as written and then as that step prepares them, their differing letters marked, until the first that passes and its points; a click keeps it open, and *How Jaro–Winkler 0.911?* below it shows that function's own working. *Compare all N* plays *Compare candidates*: one record against several, a row each, every row stopping at its own first passing step; a tab per comparison.

*When things change*, under the steps, leads to adding new records (preview first) and to matching everything again. Every page also runs `describe matching`, for the stages it shows.

- **Only this machine, only this link.** The page is served on `127.0.0.1`, and every request needs the random token in the link `open ui` prints, so another user of the machine can't use it, and a web page elsewhere can't reach it. It loads nothing from the network: the records never leave the machine.
- **One long command at a time.** Lists, describes and single answers run at once, and one refused because another job is writing to the workspace is tried again for up to 10 seconds; a run, a rerun or applying the answers runs in a process of its own, so a crash can't take the page down, and a second one, asked while one runs, is refused: ask again once it ends. A workspace another job is writing to says so: answer again once it is done.

## Development scripts

For changing the matching or measuring it, on synthetic labelled data:

| To | Run | Time |
|---|---|---|
| generate the synthetic train, val and test files | `scripts/generate.py` | seconds |
| choose the configuration on them | `scripts/choose.py`: a development round on train and val → `data/artifacts/choose/` (untracked); `--test`, the round to commit, scores test once → `config/final.toml`, `reports/choose.md`; `--optuna` adds the searches | minutes |
| measure quality and cost on growing files | `scripts/benchmark.py --entities 10000 20000 40000 60000 800000 --memory-limit 8GB` → `reports/benchmark.md`, which starts with the command that wrote it | minutes |
| choose how persons and companies are told apart | `scripts/choose_kind.py` → `reports/choose_kind.md` | minutes |
| train the name model again, after changing `data/reference/`, the generator's `kana_confusions` or `branches`, the legal forms or kana folding, or `config/final.toml` `[kind] ngram` (a run refuses a model trained under other settings; commit the file) | `scripts/train_name_model.py` → `config/kind_names.npz` | seconds |
| see every step on a small file | `notebooks/demo.ipynb`, or `scripts/export_pdfs.py` for its PDF (first: `.venv/bin/python -m playwright install chromium`) | under a minute |
| see what each optimization saves, and project a run without them | `notebooks/speedups.ipynb` (set `RUN` to a run's numbers to project that run) | about 3 minutes |
| write the commands' reference again, after changing a command in `er/cli.py` (a test fails until it matches) | `scripts/document_commands.py` → `docs/commands.md` | seconds |
