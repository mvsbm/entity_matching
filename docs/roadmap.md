# Roadmap: BigQuery and Cloud Run, a smaller and plainer engine

A plan, not yet built (written 2026-11-20). The other docs describe the code as it is; this one says where it is going
and in which order. Strike each step through as it lands.

## Where it runs

| | Local (development) | Cloud (production) |
|---|---|---|
| Runs the Python | your machine | a Cloud Run job (the same package, in a container) |
| Runs the SQL | DuckDB, in process | BigQuery |
| String similarity (Jaro–Winkler, Levenshtein, …) | our Python UDFs | BigQuery: `EDIT_DISTANCE` built in; the others as UDFs the deploy creates |
| EM, clustering, reports | in process | in the Cloud Run container (the fit works on a fixed 100k sample; clustering on the edges) |
| Started by | you | Jenkins, through the service account (nobody changes BigQuery by hand) |

**The switch:** one `Engine` with a handful of methods (run SQL into a table, fetch a small result, upload a small
table, name a table, drop one), one DuckDB and one BigQuery implementation, chosen by `ENGINE=duckdb|bigquery`.

- **SQL is written once**, in DuckDB's dialect, and sqlglot translates it for BigQuery. Tried on our hardest queries:
  `DISTINCT ON`, casts and `GROUP BY ALL` translate. String slicing (`x[:i-1]`) and DuckDB's `UNPIVOT … COLUMNS(*)`
  don't: a few patterns to write once in a portable form.
- ~~**One hash for both engines.**~~ Every draw and order by hash goes through `er_hash` (`config.hashed`: MD5's first
  60 bits as an integer), a macro DuckDB's engine defines and BigQuery's will define alike.
- **Parity in CI.** The same small file (100k records) through both engines, compared by digest: clusters and pairs
  exactly, scores to 9 decimals. That check is what makes "the same code" true; it costs cents of BigQuery.

## The jobs

1. **Build** (the first full run: more than 1 billion records): prepare → index → fit → candidate pairs among the
   existing customers → a scored candidates table. Nothing merges by itself.
2. **Update the index** (new customers): prepare the batch → add its keys to the index → score it against the index.
3. **Look up** (on request: "find the likely matches of these people"): input people → keys → probe the index →
   score → the request's threshold, rules and conditions → candidates in BigQuery, then Google Sheets for review.
   The request's settings are job arguments, not code: a request never goes through CI/CD.

In BigQuery the index is key tables clustered by key, and a batch lookup is a join. Today's `er/jobs/index.py` (a sorted
DuckDB file) doesn't carry over. AlloyDB may later serve single-record lookups from the same key tables.

**At 1 billion records**, nothing that grows with N may pass through pandas or Python memory. To watch: clustering about 70
million edges, a JavaScript UDF's speed on the pairs scored in full (about 7% of
records). Cost is measured at 1M → 10M → 100M generated records in a sandbox and extrapolated, not guessed.

## Design-time tuning

It stays in the repo and never runs in production. `scripts/choose.py` runs locally on DuckDB over the labelled
synthetic data and writes `config/final.toml` (and the name model). That change is committed through a PR; Jenkins
tests it (DuckDB, then the BigQuery parity check), builds the image and deploys the jobs, which read the config baked
into the image. Deploy on every push; start the 1B build only by an explicit trigger.

## Making the code plain

The engine is hard to explain today, for reasons that are in the code, not in the reader:

- tables passed between the steps by name (`"records"`, `"rule_edges"`, `"scores"`): each step's docstring names
  those it reads and writes, its signature doesn't;
- dense lines and docstrings that argue edge cases instead of saying what a function does;
- what the method does lives in `final.toml` and some 30 config classes, read by SQL built far from both;
- short names (`q`, `lit`, `_sides`, `_ranked`, `rough_sql`, `first_bound`);
- the UI, CLI, increments, lookups and trials woven through the same modules.

The target, in three named patterns:

- **A pipeline of steps over tables.** Each step is one module with one public function whose arguments and return
  value are its tables and its own config section, as in keys = build_keys(engine, records, keys_config). No shared object
  state.
- **Jobs read top to bottom.** `jobs/build.py` is about 50 lines that read like the diagram: one line per step.
- **Ports and adapters for the engine.** Steps call `engine.run(...)`; DuckDB and BigQuery are two adapters.
- **Configuration-driven.** What the method does (the fields, keys, levels, rules and thresholds) is set in the
  config file and never in code. Each config section names the one step that reads it, and is checked when it
  loads, so a wrong value stops the job before any work.

```
er/
  jobs/     build.py  update.py  decide.py  index.py       a full run, an increment, decisions: one line per step;
                                                         the index: built, kept up to date, looked up
  steps/    job.py  load.py  budget.py  fit.py  rules.py  candidates.py  score.py  cluster.py  write.py  report.py
  engine/   engine.py (the interface)  duckdb.py
            to come: bigquery.py, and the portable forms of slicing and UNPIVOT (the hash is er.config.hashed)
  model.py  to come: the Fellegi–Sunter model as plain Python: levels, points, λ (no SQL)
  config.py the settings and the method, each section saying which step reads it
  …         what the steps call: match.py, candidates.py, cluster.py, folder.py, report.py, …
design/     select.py  experiments.py  pipeline.py  evaluate.py  tune.py  generate.py  sample.py  probe.py  gap.py
            design time's modules, beside er/ and never imported by it; local only, on DuckDB
scripts/    choose.py  benchmark.py  generate.py  …   the design-time entry points
```

House rules for the rewrite, even where they cost lines: plain names; one statement per line; SQL as formatted
multi-line strings; a docstring says what the function takes, what it returns and what it costs, and a reason goes
in a comment only where the code can't show it; each step tested on a table of a few rows (the four-ball example).
And one page for a newcomer, how-it-works.md beside this one: the six ideas (record, key, pair, level, points, candidate),
the jobs, the table each step writes, and where to change what.

## Order

1. ~~The connection without Splink's wrapper (#151), our connected components (#154), our model dict (#156), our
   EM (#157); term frequencies and Splink out, the tests held to values recorded from Splink 5.0~~.
2. **The cut.** Run the production path (build, then an update) under coverage; delete what it never calls (the UI,
   most of the CLI, auto, trials, try sample, …); `design/` keeps the tuning.
3. **The restructure**, step by step, each move checked by digest against the run before it: ~~`er/engine/` with
   the DuckDB engine, `er/steps/` (one module per step), `er/jobs/` (build, update, decide, index)~~; then
   `model.py`.
4. **The BigQuery engine**, the string UDFs and the parity check in CI.
5. **The three jobs** on Cloud Run, wired into Jenkins.
6. **Scale rehearsal**: 10M → 100M generated records on BigQuery, time and bytes billed; then the real build.

## Open questions for infrastructure

- A sandbox dataset the CI service account may write, for the parity check.
- Whether that account may create datasets and UDFs.
- How a lookup request starts a job (a Jenkins parameterized build, `gcloud run jobs execute --args`, or a message).
- The region and the limits for Cloud Run jobs (about 32 GiB of memory and no local disk, from memory: to confirm).
