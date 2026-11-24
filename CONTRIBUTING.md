[← README](README.md) · [Architecture](docs/architecture.md)

# Contributing

A change reaches `main` through a pull request, rebased onto it, whose checks pass. `.github/workflows/tests.yml` runs
the lint and the tests on Python 3.12 and 3.14. `deploy.yml` checks the Terraform when a change touches it, and
`checklist.yml` checks the pull request's checklist. After a merge, `main` runs the tests on Windows too, and so does a
run started by hand on a branch (`gh workflow run tests.yml --ref BRANCH`). Each rule below says why it holds and what
checks it: a test, the pipeline, or the review that every pull request gets. Where code can check a rule, it does.

## The rules

| # | Rule | Why | Checked by |
|---|---|---|---|
| 1 | **Errors are values.** Code that a job runs raises `InputError` (what is wrong, and the fix) or returns a value. Only the entry points (`nayose/__main__.py`, `deploy/*.py`, `scripts/*.py`) write to the terminal or exit | whatever calls a job decides what to say and when to stop | `tests/test_jobs.py`: each job's JSON and exit code; review |
| 2 | **No process-wide state.** Nothing in `nayose/` redirects or replaces stdout or stderr, or changes the working folder, the environment or `sys.path` | a process is shared by the code a job calls and by whatever calls the job (a test, the benchmark) | review |
| 3 | **A store that grows says what bounds it.** A module-level dict, list or set that code adds to says, on the line that makes it, what bounds it (`bounded: …`) or which limit it lacks (`shortcut: …`) | a long-lived process keeps what it never drops | review |
| 4 | **Every limit names itself.** A number that caps work or output carries `shortcut: <the limit>, <when to raise it>`, or is a value in `nayose/config.toml` | a silent cap shows only at the real size | review |
| 5 | **Declared once, read by everything.** The method lives in `nayose/sql/`, its values in `nayose/config.toml`, the input's columns in `mapping.sql`, the jobs' words in `nayose/__main__.py`, and the pins in `requirements.txt` (with `deploy/requirements.txt` for the BigQuery client). Things are looked up by name, never by position | a second copy drifts from the first | `tests/test_deploy.py`: every value a procedure reads, declared from `config.toml`; review |
| 6 | **One owner per thing.** The run's folder and the terminal belong to `nayose/__main__.py`. Each table belongs to the stage file whose header lists it under `Writes` | two writers of one thing disagree | review |
| 7 | **The unhappy paths are tested:** two writers at once, an input given twice, decisions that name nothing or are given twice. A check done by hand becomes a test | a careful walk that waits after every step never meets a race | `tests/test_jobs.py`; review |
| 8 | **Every pull request is reviewed before it merges**, with its checklist ticked | an author's own walk follows only the paths the author thought of | `.github/workflows/checklist.yml` fails while a box of `.github/pull_request_template.md` is unticked |

Other checks hold the SQL and the results. `tests/test_sql.py` checks that every stage file parses as BigQuery SQL and
translates for DuckDB. It refuses by name each form whose translation answers otherwise (`AVOID` in
`nayose/engines.py`). `tests/test_parity.py` holds every job's tables to their recorded digests
(`tests/fixtures/parity.json`). A change that moves a digest changes the results, so its pull request says so and
writes the digests again. `ruff check .` applies the lint rules in `pyproject.toml`.

## Running the tests

Each area has its own file in `tests/`, and what they share is in `tests/conftest.py`: a generated population, made
once.

```bash
.venv/bin/python -m pytest -n auto                    # every test, on every core, as CI runs them
.venv/bin/python -m pytest -n auto tests/test_sql.py  # one file
NAYOSE_PARITY_WRITE=1 .venv/bin/python -m pytest tests/test_parity.py tests/test_model.py tests/test_records.py   # a change of results: the digests written again
```

The tests run this checkout's code, a git worktree's too: the processes they start get its root on `PYTHONPATH`.

A pull request that changes SQL quotes BigQuery's cost before and after, as measured by
`scripts/estimate_cost.py FILE [FILE ...]` (bytes billed and work, statement by statement, on DuckDB).

## Docs

Docs describe the code as it is, in the present tense. Its history is in git. Each diagram in `docs/diagrams/` is a
`.puml` file with the `.svg` it renders to. After an edit, run `plantuml -tsvg docs/diagrams/NAME.puml`.
