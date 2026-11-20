[← README](../README.md) · [Usage](usage.md)

# Commands

Written by `scripts/document_commands.py` from the declarations in `er/cli.py`; `tests/test_design.py` fails when the two differ.

`nayose` (名寄せ: gathering each customer's records under one name) reads as a sentence: a verb, a noun, then the parameters. Every command takes `--help` and `--format`.

- **`--format text`**, the default, for a person: a long command shows each step as it ends and, on a terminal, one line for the step under way (what it does, how far, how long is left, measured on the step's own pace and on the workspace's last run of the same kind); elsewhere that line every 30 seconds. Then the result in short: what it found first, then what to look at, then the commands that usually follow. `--verbose` writes every field of the result, and every fact of each step.
- **`--format json`**: one JSON object per line: `{"event": "step", …}` per step (a file being read: `{"event": "progress", "done": …, "total": …, "unit": "rows"}` as it goes, the total about; a run's long steps, each its own count: `"records"` loaded, `"rules"` applied, `"keys"` joined (weighed by the pairs each lists, with `"more"` when oversized blocks wait for the gate), `"sampled pairs"` the gate scored, and `"pairs"` scored with `"likely"`, the pairs at the model's line so far), then `{"event": "result", "command": …, …}` with the fields listed below, or `{"event": "error", "error": …, "fix": …, "hints": …, "exit": …}`. IDs are `id`, `id_l`, `id_r`, whatever the file calls them.
- **Exit codes:** 0; 2, a mistake people fix (two lines: what is wrong, and the fix); 75, the workspace is busy: try again later; 130, stopped with Ctrl-C.
- **`next`**, in every result: the commands that usually follow, each with why.

| Command | Does |
|---|---|
| [`resolve records`](#nayose-resolve-records) | Resolve a file: one ID per person or company |
| [`add records`](#nayose-add-records) | Add new records to a run |
| [`match records`](#nayose-match-records) | Which entity each record would join; nothing written |
| [`build index`](#nayose-build-index) | The index a record is looked up in, from the run |
| [`match record`](#nayose-match-record) | The entities one record may belong to, from the index; nothing written |
| [`apply decisions`](#nayose-apply-decisions) | Apply people's decisions to the run |

## nayose resolve records

Resolve a file: one ID per person or company.

```
nayose resolve records [INPUT] --workspace WORKSPACE [--overwrite] [--pipeline PIPELINE] [--model MODEL] [--compute KEY=VALUE …] [--format text|json]
```

A full run, without labels: load, budget, fit, rules, candidates, score, cluster, write, report. Writes the workspace: gold.parquet, matches/, rule_kept/, set_aside/, state/, steps.json, and for people qa.md, report.txt and review.parquet. A folder that holds a run is refused without --overwrite; people's decisions in it stand. O(N·L + ΣP + C·K·L²).

| Parameter | |
|---|---|
| `INPUT` | the records: a CSV, TSV or Parquet file, a quoted glob ('in/*.csv') or a folder of them, read as they come and together by column name; copied into the workspace first. Without it, the file loaded into it last |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--overwrite` | replace the results it holds |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--model MODEL` | a fitted model to score with instead of fitting one on the file (its JSON, or the file that holds it under 'model') |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `summary` | the run in words: records, entities, who joined them, the model's links, what is left to people |
| `facts` | what to read first: records, entities, joined, waiting (pairs for people from review_from points), merging, too_big, kinds (flagged person or company), report |
| `seconds` | the run's time |
| `wrote` | the files written |
| `index` | the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix |
| `next` | the commands that usually follow |

```bash
nayose resolve records customers.parquet --workspace workspaces/customers
```

## nayose add records

Add new records to a run.

```
nayose add records [INPUT] --workspace WORKSPACE [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

An increment: each new record compared with every stored one, with the run's model; it can join an existing entity. A record whose ID is already in the run is set aside, so adding the same file twice adds nothing. O(Δ·(L + Σb) + C_Δ·K·L²) plus narrow O(N) scans.

| Parameter | |
|---|---|
| `INPUT` | the records: a CSV, TSV or Parquet file, a quoted glob ('in/*.csv') or a folder of them, read as they come and together by column name; copied into the workspace first. Without it, the file loaded into it last |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `summary` | the run in words: records, entities, who joined them, the model's links, what is left to people |
| `facts` | what to read first: records, entities, joined, waiting (pairs for people from review_from points), merging, too_big, kinds (flagged person or company), report |
| `seconds` | the run's time |
| `wrote` | the files written |
| `index` | the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix |
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
| `INPUT` | the records: a CSV, TSV or Parquet file, a quoted glob ('in/*.csv') or a folder of them, read as they come and together by column name |
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

## nayose build index

The index a record is looked up in, from the run.

```
nayose build index --workspace WORKSPACE [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

Every key of every record the run holds, sorted, in the workspace's index/ (DuckDB databases), with what it was built from. Read once from the run's own files, nothing standardized again; built beside the last index, which stays until the new one is whole. Once built, it is kept up to date by the commands that change the run: an increment or decisions write what changed beside it; a full run builds it again. O(N·(G + R + D·L) + N log N): N records, G pair keys, R rules, D deletion keys, L a value's length.

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `index` | its folder |
| `records` | the records it holds |
| `tables` | each table: of (its key or rule), rows, seconds |
| `seconds` | in all |
| `next` | the commands that usually follow |

```bash
nayose build index --workspace workspaces/customers
```

## nayose match record

The entities one record may belong to, from the index; nothing written.

```
nayose match record [COLUMN=VALUE …] [--record ID] [--from POINTS] [--count N] --workspace WORKSPACE [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

One record, by the file's column names (or a stored one's ID, as if it were new), prepared as a run prepares it, looked up by each of its keys in the index (nayose build index), and scored with the run's model: the entities at --from points or more, best first, each with its best record, its points, each comparison's level and the rule that would join it; likely ones at the line or above. The pairs an increment of that record alone would list, scored alike. O(G·(log N + b) + C·K·L²): N only in log N.

| Parameter | |
|---|---|
| `COLUMN=VALUE` | the record's values, by the file's column names |
| `--record ID` | a stored record's ID, looked up as if it were new |
| `--from POINTS` | from these points (default: the review floor) |
| `--count N` | the most entities (default 20) |
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `record` | the record as compared: its fields and kind |
| `entities` | each: entity, record, points, likely, rule, keys, compared, records, shown |
| `found` | entities at --from or more |
| `at_least` | the points listed from: --from, else the review floor |
| `closest` | none at --from or more: the nearest record compared (record, entity, points, shown), else null |
| `read_as` | the values as read, when they were typed otherwise than records hold them (a name in hiragana, 03-1234-5678) and so read find more or come closer |
| `candidates` | records compared |
| `likely` | of them, at the line or joined by a rule |
| `checked` | each key: found, or why not; a block too big: its records and the gate's decision |
| `seconds` | each part |
| `index` | built_at, records |
| `next` | the commands that usually follow |

```bash
nayose match record FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234 --workspace workspaces/customers
```

## nayose apply decisions

Apply people's decisions to the run.

```
nayose apply decisions --workspace WORKSPACE [--file FILE] [--pipeline PIPELINE] [--compute KEY=VALUE …] [--format text|json]
```

Each match pair joins its two entities at once, scoring nothing; no_match is kept, and a full run never accepts the pair. Decisions are kept in decisions/; one applied before changes nothing. O(D + touched clusters) + O(N).

| Parameter | |
|---|---|
| `--workspace WORKSPACE` | the workspace: the folder that keeps one matching job (required) |
| `--file FILE` | a file of decisions: the two ID columns and decision (default: the workspace's own sheet, with the answers written in) |
| `--pipeline PIPELINE` | the pipeline file (default: config/final.toml) |
| `--compute KEY=VALUE` | DuckDB limits for this run, over config/settings.toml [compute]: memory_limit=8GB, threads=4, temp_directory=<folder> (past the memory limit DuckDB spills there) |

| Result | |
|---|---|
| `decisions` | decisions applied |
| `matches` | of them, match |
| `clusters_joined` | entities joined |
| `summary` | said when nothing was new |
| `index` | the workspace's index, if built: brought up to date (records, added, moved, seconds, rebuilt: why built again), or error and fix |
| `next` | the commands that usually follow |

```bash
nayose apply decisions --workspace workspaces/customers
```

