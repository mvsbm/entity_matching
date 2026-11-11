[← README](README.md) · [Architecture](docs/architecture.md) · [Usage](docs/usage.md)

# Contributing

A change reaches `main` through a pull request whose checks pass (`.github/workflows/tests.yml`, on Python 3.12 and
3.14: lint, the page's script and the fast tests), rebased onto it. Its author runs every tier first; `main` runs them
all after it merges, on Windows too, and so does a run started by hand on a branch (`gh workflow run tests.yml --ref BRANCH`). Each rule below says why it holds and what checks it: a test, the pipeline, or the review
every pull request gets. Where code can check a rule, it does.

## The rules

| # | Rule | Why | Checked by |
|---|---|---|---|
| 1 | **Errors are values.** Code that nayose's commands run raises `InputError` (what is wrong, and the fix) or returns a value; only `er/cli.py` writes to the terminal or exits | `nayose open ui` runs commands in threads of one long-lived server: a print lands in its terminal, an exit stops it | `tests/test_design.py`: no print or exit in the run-time tools, the run, the steps or the configuration, `er/cli.py` aside |
| 2 | **No process-wide state.** Nothing in `er/` redirects or replaces stdout or stderr, or changes the working folder, the environment or `sys.path` | threads share them: one thread's change is every thread's | `tests/test_design.py`, on every module of `er/` |
| 3 | **A store that grows says what bounds it.** A module-level dict, list or set that code adds to says, on the line that makes it, what bounds it (`bounded: …`) or which limit it lacks (`shortcut: …`). A server drops a job once the page has read it | a long-lived process keeps what it never drops | `tests/test_design.py`; the job store, `tests/test_ui_server.py` |
| 4 | **Every limit names itself.** A number that caps work or output carries `shortcut: <the limit>, <when to raise it>`, or is a setting | a silent cap shows only at the real size | review |
| 5 | **The page reaches the server through `api()`, which never throws.** A lost server is a value every caller handles | an unhandled failure leaves a page waiting forever | `tests/test_design.py`: one `fetch`, inside `api()`, with its `catch`; the browser test stops the server |
| 6 | **A write is sent once.** The same command with the same arguments, asked again while it runs, is that run; a review answer given while the one before is being written is ignored | a key held down, a button clicked twice | the browser tests in `tests/test_ui_page.py` |
| 7 | **Declared once, read by everything.** Commands in `er/cli.py` `COMMANDS`; what each page runs, in its layout; what differs between the review queues, in `QUEUES`. Things are looked up by name, never by position | a second copy drifts from the first | `tests/test_design.py`: the reference against the declarations; `tests/test_ui_server.py`: the layout against the declarations |
| 8 | **One owner per job.** The workspace is `er/folder.py`'s, every input `er/source.py`'s, a command's events `er/cli.py`'s `Emit` | two writers of one thing disagree | the layer and diagram checks in `tests/test_design.py`; review |
| 9 | **The unhappy paths are tested, at the real size:** two requests at once, an input given twice, the real data size (a kinds sheet holds up to 3,000 records), a server that stops. A check done by hand becomes a test | a careful walk that waits after every step never meets a race | review; the browser tests, run before a push and on `main` with Chromium installed |
| 10 | **Every pull request is reviewed before it merges**, its checklist ticked | an author's own walk follows the paths the author thought of | `.github/workflows/checklist.yml` fails while a box of `.github/pull_request_template.md` is unticked |
| 11 | **The highlight is where you are.** The highlighted item in the page's left column is the step the page serves: with no workspace, the Overview is step 1 | a person reads the highlight, not the heading, to know where they are | the browser tests in `tests/test_ui_page.py`, on the first screen |
| 12 | **A control that can't act yet is off, and says when it will.** A button or box that needs a workspace or a result is disabled, with the reason beside it; a page can always be opened, and says what it needs | a click that does nothing, or fails, teaches a person nothing | the browser tests in `tests/test_ui_page.py`, before and after the first run |
| 13 | **A word a person hasn't learned is explained where it first appears**, in the page's own words: a workspace, a point of evidence, a rule match | a person meets the page before the docs | review: a walk of each page as a new user |

The other checks: each module's layer and the diagrams against the code (`tests/test_design.py`), the lint rules in
`pyproject.toml` (`ruff check .`: names unused or never defined, an error re-raised without its cause), and the
commands' reference against their declarations
(`scripts/document_commands.py` writes `docs/commands.md`).

## Running the tests

Each area of the engine has its own file in `tests/`; what they share is in `tests/conftest.py`. A test that runs whole
pipelines is marked `slow`, and one that opens the page in Chromium `browser`, by the fixtures it uses.

```bash
.venv/bin/python -m pytest -m "not slow and not browser"   # the fast checks: about 20 s
.venv/bin/python -m pytest -m "slow and not browser"       # whole runs on a generated population: minutes
.venv/bin/python -m pytest -m browser                      # the page in Chromium (once: python -m playwright install chromium)
.venv/bin/python -m pytest                                 # all of them: before every push (a pull request's CI runs the fast ones)
.venv/bin/python -m pytest -n auto                         # any of these, on every core at once, as CI runs them
.venv/bin/python -m pytest -n auto --store-durations --durations-path tests/durations.json  # the times CI splits the long tiers by: again once tests are added or grow
```

Without Chromium the browser tests skip; under CI (`CI` set) they fail instead, so a broken install never passes.

## Docs

Docs describe the code as it is, in the present tense; its history is in git. The paths and function names that docs
and diagrams give are checked against the code.
