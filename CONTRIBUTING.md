[← README](README.md) · [Architecture](docs/architecture.md)

# Contributing

A change reaches `main` through a pull request whose checks pass (`.github/workflows/tests.yml`, on Python 3.12 and
3.14: lint and the fast tests, about two minutes), rebased onto it. Its author runs every tier first; `main` runs them
all after it merges, on Windows too, and so does a run started by hand on a branch (`gh workflow run tests.yml --ref BRANCH`): each
tier a job, the long ones split by their recorded times (`tests/durations.json`), all at once, about six minutes. Each rule below says why it holds and what checks it: a test, the pipeline, or the review
every pull request gets. Where code can check a rule, it does.

## The rules

| # | Rule | Why | Checked by |
|---|---|---|---|
| 1 | **Errors are values.** Code a job runs raises `InputError` (what is wrong, and the fix) or returns a value; only `er/__main__.py` writes to the terminal or exits | whatever calls a job decides what to say and when to stop | `tests/test_design.py`: no print or exit in the run, the steps or the configuration, `er/__main__.py` aside |
| 2 | **No process-wide state.** Nothing in `er/` redirects or replaces stdout or stderr, or changes the working folder, the environment or `sys.path` | a process is shared: by the code a job calls, and by whatever calls the job (a test, the benchmark) | `tests/test_design.py`, on every module of `er/` |
| 3 | **A store that grows says what bounds it.** A module-level dict, list or set that code adds to says, on the line that makes it, what bounds it (`bounded: …`) or which limit it lacks (`shortcut: …`) | a long-lived process keeps what it never drops | `tests/test_design.py` |
| 4 | **Every limit names itself.** A number that caps work or output carries `shortcut: <the limit>, <when to raise it>`, or is a setting | a silent cap shows only at the real size | review |
| 5 | **Declared once, read by everything.** The jobs' words in `er/__main__.py`, the method in `config/pipeline.toml`, the column mapping and the limits in `config/settings.toml`, the pins in `requirements.txt`. Things are looked up by name, never by position | a second copy drifts from the first | `tests/test_deploy.py`: the image's pins against `requirements.txt`; review |
| 6 | **One owner per job.** The run's folder is `er/folder.py`'s, every input `er/source.py`'s, the terminal `er/__main__.py`'s | two writers of one thing disagree | the layer and diagram checks in `tests/test_design.py`; review |
| 7 | **The unhappy paths are tested, at the real size:** two writers at once, an input given twice, the real data size, a write cut short. A check done by hand becomes a test | a careful walk that waits after every step never meets a race | review; the whole-run tests, run before a push and on `main` |
| 8 | **Every pull request is reviewed before it merges**, its checklist ticked | an author's own walk follows the paths the author thought of | `.github/workflows/checklist.yml` fails while a box of `.github/pull_request_template.md` is unticked |

The other checks: each module's layer and the diagrams against the code (`tests/test_design.py`), and the lint rules in
`pyproject.toml` (`ruff check .`: names unused or never defined, an error re-raised without its cause).

## Running the tests

Each area of the engine has its own file in `tests/`; what they share is in `tests/conftest.py`. A test that runs whole
pipelines is marked `slow`, by the fixtures it uses.

```bash
.venv/bin/python -m pytest -m "not slow"   # the fast checks: about 15 seconds
.venv/bin/python -m pytest -m slow         # whole runs on a generated population: under a minute with -n auto
.venv/bin/python -m pytest                 # all of them: before every push (a pull request's CI runs the fast ones)
.venv/bin/python -m pytest -n auto         # any of these, on every core at once, as CI runs them
.venv/bin/python -m pytest -n auto --store-durations --durations-path tests/durations.json  # the times CI splits the long tiers by: again once tests are added or grow
```

The tests run this checkout's code, a git worktree's too: the processes they start get its root on `PYTHONPATH`.

## Docs

Docs describe the code as it is, in the present tense; its history is in git. The paths and function names that docs
and diagrams give are checked against the code.
