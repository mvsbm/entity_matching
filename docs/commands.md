[← README](../README.md) · [Usage](usage.md)

# Commands

Written by `scripts/document_commands.py` from the declarations in `er/cli.py`; `tests/test_design.py` fails when the two differ.

`nayose` (名寄せ: gathering each customer's records under one name) reads as a sentence: a verb, a noun, then the parameters. Every command takes `--help` and `--format`.

- **`--format text`**, the default: each step on a line as it finishes, then the result, for a person.
- **`--format json`**: one JSON object per line: `{"event": "step", …}` per step, then `{"event": "result", "command": …, …}` with the fields listed below, or `{"event": "error", "error": …, "fix": …, "hints": …, "exit": …}`. IDs are `id`, `id_l`, `id_r`, whatever the file calls them.
- **Exit codes:** 0; 2, a mistake people fix (two lines: what is wrong, and the fix); 75, the workspace is busy: try again later; 1, a pass of `serve inbox` stopped on a file.
- **`next`**, in every result: the commands that usually follow, each with why.

| Command | Does |
|---|---|
| [`check records`](#nayose-check-records) | Read, map and check a file, in seconds; resolve nothing |
| [`list columns`](#nayose-list-columns) | Show which of a file's columns hold each field |
| [`set columns`](#nayose-set-columns) | Map fields to a file's columns |
| [`resolve records`](#nayose-resolve-records) | Resolve a file: one ID per person or company |
| [`add records`](#nayose-add-records) | Add new records to a run |
| [`match records`](#nayose-match-records) | Which entity each record would join; nothing written |
| [`rerun records`](#nayose-rerun-records) | A full run again, on the run's own files |
| [`describe workspace`](#nayose-describe-workspace) | What a workspace holds |
| [`describe entity`](#nayose-describe-entity) | One record's entity, and what joined it |
| [`describe matching`](#nayose-describe-matching) | How records are matched: every method, on which fields, with its numbers |
| [`list pairs`](#nayose-list-pairs) | The pairs for people to decide and to audit |
| [`decide pair`](#nayose-decide-pair) | Decide one pair: match or no match |
| [`apply decisions`](#nayose-apply-decisions) | Apply people's decisions to the run |
| [`list kinds`](#nayose-list-kinds) | The records for people to answer person or company |
| [`answer kind`](#nayose-answer-kind) | Answer one record: person, company, or unsure |
| [`apply answers`](#nayose-apply-answers) | Apply people's person/company answers: a rerun |
| [`serve inbox`](#nayose-serve-inbox) | Take in every file dropped in an inbox, one at a time |
| [`open ui`](#nayose-open-ui) | The commands in a browser, on this machine only |

## nayose check records

Read, map and check a file, in seconds; resolve nothing.

```
nayose check records INPUT [--compute KEY=VALUE …] [--pipeline PIPELINE] [--format text|json]
```

Reads the file through the door every input takes, maps its columns to the logical fields (config/settings.toml [columns]), and counts each key's pairs before any join. Shows each field's fill rate, the share of values that look like it and the share of its most common value, what would be turned off, and the blocks the run will check on a sample. A field the run needs and the file lacks stops it, with the column whose values look most like it. O(N) for the counts; a sample of 10,000 records for the shares.

| Parameter | |
|---|---|
| `INPUT` | the records: a Parquet file, a quoted glob ('in/*.parquet') or a folder of them, read together by column name |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |

| Result | |
|---|---|
| `records` | records read |
| `fields` | each field: filled, looks_right, top_value (shares), columns |
| `turned_off` | rules, keys and levels a missing field turns off |
| `keys` | each key's pairs per record and largest block |
| `oversized_from` | the block size checked by sampling |
| `notes` | what the loader detected or fixed |
| `next` | the commands that usually follow |

```bash
nayose check records customers.parquet
```

## nayose list columns

Show which of a file's columns hold each field.

```
nayose list columns [--format text|json]
```

Reads config/settings.toml [columns] (or the ER_SETTINGS file): each field, its columns (a comma between fallbacks, + between columns joined) and its options. O(the file).

| Result | |
|---|---|
| `settings` | the settings file |
| `columns` | each field: columns, options |
| `next` | the commands that usually follow |

```bash
nayose list columns
```

## nayose set columns

Map fields to a file's columns.

```
nayose set columns FIELD=COLUMNS … [--format text|json]
```

Rewrites the named fields' lines in [columns]: FIELD=COLUMN, FIELD=A,B (B where A is empty), FIELD=A+B (A and B joined), FIELD= (the field goes). Every other line, each line's comment and a field's options stay; the new file is checked before it replaces the old. O(the file).

| Parameter | |
|---|---|
| `FIELD=COLUMNS` | one or more FIELD=COLUMNS |

| Result | |
|---|---|
| `settings` | the settings file |
| `columns` | each field: columns, options |
| `next` | the commands that usually follow |

```bash
nayose set columns phone=TEL4 person_name=NAME_KANA,SEI+MEI
```

## nayose resolve records

Resolve a file: one ID per person or company.

```
nayose resolve records INPUT --workspace WORKSPACE [--overwrite] [--pipeline PIPELINE] [--model MODEL] [--compute KEY=VALUE …] [--format text|json]
```

A full run, without labels: load, budget, fit, rules, candidates, score, cluster, write, report. Writes the run folder: gold.parquet, matches/, rule_kept/, set_aside/, state/, steps.json, and for people qa.md, report.txt, review.parquet and kind_review.parquet. A folder that holds a run is refused without --overwrite; people's decisions and answers in it stand. O(N·L + ΣP + C·K·L²).

| Parameter | |
|---|---|
| `INPUT` | the records: a Parquet file, a quoted glob ('in/*.parquet') or a folder of them, read together by column name |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--overwrite` | replace the run the folder holds |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--model MODEL` | a fitted model to score with instead of fitting one on the file (its JSON, or the file that holds it under 'model') |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `summary` | the run in words: records, entities, who joined them, the model's links, what is left to people |
| `seconds` | the run's time |
| `wrote` | the files written |
| `next` | the commands that usually follow |

```bash
nayose resolve records customers.parquet --workspace workspaces/customers
```

## nayose add records

Add new records to a run.

```
nayose add records INPUT --workspace WORKSPACE [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

An increment: each new record compared with every stored one, with the run's model; it can join an existing entity. A record whose ID is already in the run is set aside, so adding the same file twice adds nothing. O(Δ·(L + Σb) + C_Δ·K·L²) plus narrow O(N) scans.

| Parameter | |
|---|---|
| `INPUT` | the records: a Parquet file, a quoted glob ('in/*.parquet') or a folder of them, read together by column name |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `summary` | the run in words: records, entities, who joined them, the model's links, what is left to people |
| `seconds` | the run's time |
| `wrote` | the files written |
| `next` | the commands that usually follow |

```bash
nayose add records new.parquet --workspace workspaces/customers
```

## nayose match records

Which entity each record would join; nothing written.

```
nayose match records INPUT --workspace WORKSPACE [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

An increment's steps without its write: for each record, the entity it would join or a new one, and the rule or the model's best weight that links it. The workspace is left as it was. O(an increment).

| Parameter | |
|---|---|
| `INPUT` | the records: a Parquet file, a quoted glob ('in/*.parquet') or a folder of them, read together by column name |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `counts` | records by status |
| `records` | each record: id, entity, status, by, weight |
| `next` | the commands that usually follow |

```bash
nayose match records new.parquet --workspace workspaces/customers
```

## nayose rerun records

A full run again, on the run's own files.

```
nayose rerun records --workspace WORKSPACE [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

Reads the record files the run read, the full run's and each increment's, in order (steps.json; a scheduled batch found where the scheduler moved it), each checked by its SHA-256, and resolves them again in one full run: every pair compared again, an ID's records kept as the increments kept them. O(a full run).

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `summary` | the run in words: records, entities, who joined them, the model's links, what is left to people |
| `seconds` | the run's time |
| `wrote` | the files written |
| `next` | the commands that usually follow |

```bash
nayose rerun records --workspace workspaces/customers
```

## nayose describe workspace

What a workspace holds.

```
nayose describe workspace WORKSPACE [--format text|json]
```

Records and entities, the largest entities, each run so far, the pairs and kinds still open and the answers written in, records set aside, a write still owed, and the last summary. O(N) in SQL.

| Parameter | |
|---|---|
| `WORKSPACE` | the workspace |

| Result | |
|---|---|
| `workspace` | the workspace |
| `records` | records |
| `entities` | entities |
| `largest` | the 10 largest entities |
| `runs` | each run so far: at, what, files, seconds |
| `pairs` | open pairs to decide and audit, and decisions written in |
| `kinds` | open records to decide and to measure, and answers written in |
| `set_aside` | records set aside |
| `write_owed` | a write cut short, finished by the next one |
| `summary` | the last run's summary |
| `next` | the commands that usually follow |

```bash
nayose describe workspace workspaces/customers
```

## nayose describe entity

One record's entity, and what joined it.

```
nayose describe entity ID --workspace WORKSPACE [--format text|json]
```

The entity of the record ID: each of its records with its fields and kind, and every link between them: a rule, the model with its weight in bits, or people. O(N) in SQL.

| Parameter | |
|---|---|
| `ID` | a record ID, as the run wrote it |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |

| Result | |
|---|---|
| `record` | the ID asked for |
| `entity` | its entity (the cluster_id) |
| `records` | each of the entity's records |
| `links` | each link between them: id_l, id_r, by, weight |
| `next` | the commands that usually follow |

```bash
nayose describe entity 0000000151 --workspace workspaces/customers
```

## nayose describe matching

How records are matched: every method, on which fields, with its numbers.

```
nayose describe matching [--workspace WORKSPACE] [--pipeline PIPELINE] [--format text|json]
```

The pipeline as a graph: records, how each field is made comparable, the rules, the ways pairs are listed, the comparisons and what each level is worth in bits, the line pairs are accepted at, the pairs left to people, and how linked records become customers. With --workspace, each part also holds that run's numbers and a real example. O(E + R + N) in SQL over the run's files.

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | a workspace: its numbers and examples (without it, the methods only) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |

| Result | |
|---|---|
| `nodes` | each part: id, name, method, its parameters and fields, and with --workspace its numbers and examples |
| `edges` | source, target, count |
| `next` | the commands that usually follow |

```bash
nayose describe matching --workspace workspaces/customers
```

## nayose list pairs

The pairs for people to decide and to audit.

```
nayose list pairs --workspace WORKSPACE [--why decide|audit] [--open] [--format text|json]
```

The run's review.parquet: decide rows (the pairs just below the threshold, and those above it with no name compared) and audit rows (accepted pairs just above it), each with both records' fields, each comparison's level and bits, and a status: open, written in, or applied. O(sheet rows).

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--why decide|audit` | decide or audit only |
| `--open` | only the rows nobody has answered |

| Result | |
|---|---|
| `counts` | rows by why and status |
| `pairs` | each pair: why, status, decision, id_l, id_r, match_weight, accepted, fields, levels |
| `next` | the commands that usually follow |

```bash
nayose list pairs --workspace workspaces/customers --open
```

## nayose decide pair

Decide one pair: match or no match.

```
nayose decide pair ID ID match|no_match|clear --workspace WORKSPACE [--format text|json]
```

Writes the decision into the workspace's review.parquet; nothing is applied until apply decisions. clear takes it back. O(sheet rows).

| Parameter | |
|---|---|
| `ID` | one record ID of the pair |
| `ID` | the other |
| `match|no_match|clear` | match, no_match, or clear |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |

| Result | |
|---|---|
| `pair` | the two IDs, lower first |
| `decision` | what was written |
| `next` | the commands that usually follow |

```bash
nayose decide pair 0000000151 0000000152 match --workspace workspaces/customers
```

## nayose apply decisions

Apply people's decisions to the run.

```
nayose apply decisions --workspace WORKSPACE [--file FILE] [--pipeline PIPELINE] [--format text|json]
```

Each match pair joins its two entities at once, scoring nothing; no_match is kept, and a full run never accepts the pair. Decisions are kept in decisions/; one applied before changes nothing. O(D + touched clusters) + O(N).

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--file FILE` | a file of decisions: the two ID columns and decision (default: the workspace's own sheet, with the answers written in) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |

| Result | |
|---|---|
| `decisions` | decisions applied |
| `matches` | of them, match |
| `clusters_joined` | entities joined |
| `summary` | said when nothing was new |
| `next` | the commands that usually follow |

```bash
nayose apply decisions --workspace workspaces/customers
```

## nayose list kinds

The records for people to answer person or company.

```
nayose list kinds --workspace WORKSPACE [--why decide|measure] [--open] [--format text|json]
```

The run's kind_review.parquet: decide rows (where the engine and the file's flag disagree, and the flag's likely errors) and measure rows (a random draw that places the engine's lines), each with what the engine, the name and the flag say, and why it is there. O(sheet rows).

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--why decide|measure` | decide or measure only |
| `--open` | only the rows nobody has answered |

| Result | |
|---|---|
| `counts` | rows by why and status |
| `kinds` | each record: id, why, status, reason, engine_says, name_says, name, kind |
| `next` | the commands that usually follow |

```bash
nayose list kinds --workspace workspaces/customers --open
```

## nayose answer kind

Answer one record: person, company, or unsure.

```
nayose answer kind ID person|company|unsure|clear --workspace WORKSPACE [--format text|json]
```

Writes the answer into the workspace's kind_review.parquet (1 person, 2 company, 0 can't tell); nothing is applied until apply answers. clear takes it back. A sole trader is a person. O(sheet rows).

| Parameter | |
|---|---|
| `ID` | the record ID |
| `person|company|unsure|clear` | person, company, unsure, or clear |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |

| Result | |
|---|---|
| `record` | the ID |
| `kind` | what was written |
| `next` | the commands that usually follow |

```bash
nayose answer kind 0000000151 company --workspace workspaces/customers
```

## nayose apply answers

Apply people's person/company answers: a rerun.

```
nayose apply answers --workspace WORKSPACE [--file FILE] [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

The answers stand for their records, teach the engine, and the draw to measure places its lines; they are kept in kind_answers/. They change how each name is matched, so they are applied by a full run on the run's own files (rerun records). O(a full run).

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--file FILE` | a file of answers: the ID column and kind (default: the workspace's own sheet, with the answers written in) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `summary` | the run in words: records, entities, who joined them, the model's links, what is left to people |
| `seconds` | the run's time |
| `wrote` | the files written |
| `next` | the commands that usually follow |

```bash
nayose apply answers --workspace workspaces/customers
```

## nayose serve inbox

Take in every file dropped in an inbox, one at a time.

```
nayose serve inbox INBOX --workspace WORKSPACE [--every SECONDS] [--retries N] [--compute KEY=VALUE …] [--format text|json]
```

inbox/batches/ (new records: add records; into an empty workspace, resolve records), inbox/decisions/ (apply decisions), inbox/answers/ (apply answers), oldest first, each as its nayose command in a process of its own. Done files go to inbox/done/, ones people must fix to inbox/failed/ with their error; any other failure is tried again, then stops the pass with the file left in place. One pass, or one every --every seconds. Each file is a line in <run>/jobs.jsonl.

| Parameter | |
|---|---|
| `INBOX` | the inbox folder |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--every SECONDS` | seconds between passes; without it, one pass |
| `--retries N` | attempts after an unexpected failure (default 2) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `stopped` | the pass stopped on a file that kept failing |
| `next` | the commands that usually follow |

```bash
nayose serve inbox inbox --workspace workspaces/customers --every 300
```

## nayose open ui

The commands in a browser, on this machine only.

```
nayose open ui [--workspace WORKSPACE] [--port PORT] [--link] [--format text|json]
```

Serves a page on 127.0.0.1, reachable only from this machine and only with the link it prints, and opens it. Its screens follow the work: records, columns, check and run, results, pairs (keys M, N, S), kinds (keys 1, 2, 0). Each button runs one of these commands, shown as the command line it is; lists, describes and single answers run in the page's own process, the others each in a process of their own, one at a time. Nothing is loaded from the network. Ctrl-C stops it.

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace the page starts with |
| `--port PORT` | the port (default 8765; 0: any free one) |
| `--link` | print the link only; open no browser |

| Result | |
|---|---|
| `next` | the commands that usually follow |

```bash
nayose open ui --workspace workspaces/customers
```

