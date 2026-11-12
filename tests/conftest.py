"""What the tests share: small hand-made frames, a generated population for whole runs, nayose as a user runs it (in
this process, and in its own), and the page in a browser. A test that uses a whole-run fixture is marked slow; one
that uses the browser, browser: run the fast ones with -m "not slow and not browser"."""
import contextlib
import gc
import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from er.config import Comparator, Comparison, FSModel, Key, Level, load_pipeline
from er.settings import load_settings
from er.strings import connect

UID = "uid"
PAIR = pd.DataFrame({"uid_l": ["001a"], "uid_r": ["001b"]}, dtype="string")  # same name, in 4 of the 120 records
SLOW = {"population", "kind_population", "wide_band", "runs"}  # fixtures that run whole pipelines (runs: test_design.py's)
ROOT = Path(__file__).resolve().parents[1]
# the processes the tests start import this checkout's er: the venv's editable install names the one it was made from
os.environ["PYTHONPATH"] = os.pathsep.join([str(ROOT), *filter(None, [os.environ.get("PYTHONPATH")])])


def pytest_collection_modifyitems(items):
    for item in items:
        if SLOW & set(item.fixturenames):
            item.add_marker(pytest.mark.slow)
        if "ui_page" in item.fixturenames:
            item.add_marker(pytest.mark.browser)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # each phase's report kept on the test, for a fixture to see how it went
    report = (yield).get_result()
    setattr(item, f"report_{report.when}", report)


@pytest.fixture(scope="session")
def con_db():
    return connect()


@pytest.fixture(scope="session")
def records() -> pd.DataFrame:
    """60 entities, two records each: same phone, the second name sometimes with one kana changed."""
    rng = np.random.default_rng(0)
    names = ["サトウヒロシ", "スズキケイコ", "タカハシアキラ", "タナカユウコ", "イトウタロウ", "ワタナベミホ"]
    rows = []
    for e in range(60):
        name, phone = names[e % len(names)] + "アイウエオ"[e // 12], f"{rng.integers(10_000):04d}"
        rows.append(dict(uid=f"{e:03d}a", name=name, phone=phone, entity=f"E{e}"))
        rows.append(dict(uid=f"{e:03d}b", name=name[:-1] + "カ" if e % 3 == 0 else name, phone=phone, entity=f"E{e}"))
    return pd.DataFrame(rows).astype("string")


def model(m_method: str = "em", tf: bool = False, extra_name_levels: tuple[Level, ...] = ()) -> FSModel:
    return FSModel(
        name="test",
        comparisons=(
            Comparison(name="name", null_if_missing=("name",), tf=Key("name") if tf else None, levels=(
                Level(label="exact", any_of=(("name", Comparator("exact")),), tf=tf),
                Level(label="close", any_of=(("name", Comparator("jaro_winkler", 0.9)),)), *extra_name_levels)),
            Comparison(name="phone", null_if_missing=("phone",), levels=(
                Level(label="exact", any_of=(("phone", Comparator("exact")),)),)),
        ),
        prior_rules=((Key("name"), Key("phone")),), prior_recall=0.9, u_max_pairs=1e4, m_method=m_method,
        em_rules=((Key("phone"),),), seed=0)


@pytest.fixture(scope="session")
def population():
    """A small generated population and the final pipeline, for whole runs: made once for every test that runs one."""
    from er.generate import generate as make, load_reference, load_spec
    s = load_settings()
    p = load_pipeline(ROOT / "tests" / "method.toml", s.standardize, s.chains, s.columns)  # the tests' own method: a method round changes config/final.toml, never what they count on
    g = make(replace(load_spec(s.root / "config" / "generator.toml")[0], entities=400, households={}),  # the tests count on this population; choose.py measures households
             *load_reference(s.paths["reference"]))
    return s, p, g


def flag_wrong(df: pd.DataFrame) -> pd.DataFrame:  # a person/company flag that says person on every record: the engine flags the companies it is sure of
    return df.assign(PERSON_ORG_CODE=pd.Series("1", index=df.index, dtype="string"))


def dirty_csv(df: pd.DataFrame, name: str, address: str, path: Path) -> tuple[int, tuple[str, str], tuple[str, str, str]]:
    """The records as a CSV another system wrote: some names in CP932, one unquoted comma between an address's street
    and building, one name garbled upstream (its UTF-8 read as CP932, then saved). How many CP932 names, (id, the
    address as written), (id, the name, the name garbled)."""
    cols, cp932, spilled, garbled = list(df.columns), 0, None, None
    lines = [",".join(cols).encode()]
    for i, r in enumerate(df.itertuples(index=False)):
        vals = ["" if pd.isna(v) else v for v in r]
        cells = [v.encode("utf-8") for v in vals]
        if i % 40 == 3 and vals[cols.index(name)]:
            cells[cols.index(name)], cp932 = vals[cols.index(name)].encode("cp932"), cp932 + 1
        elif spilled is None and "　" in vals[cols.index(address)]:
            spilled = (vals[0], vals[cols.index(address)].replace("　", ","))
            cells[cols.index(address)] = spilled[1].encode("utf-8")
        elif garbled is None and i % 40 == 7:
            try:
                garbled = (vals[0], vals[cols.index(name)], vals[cols.index(name)].encode("utf-8").decode("cp932"))
                cells[cols.index(name)] = garbled[2].encode("utf-8")
            except UnicodeDecodeError:
                pass
        lines.append(b",".join(cells))
    path.write_bytes(b"\n".join(lines) + b"\n")
    assert spilled and garbled and cp932 > 5
    return cp932, spilled, garbled


def nayose(*words: object, check: bool = False, timeout: float = 600):  # the command line, as a user runs it, in a process of its own
    import subprocess
    import sys
    return subprocess.run([sys.executable, "-m", "er.cli", *map(str, words)], capture_output=True, encoding="utf-8", errors="replace", check=check, timeout=timeout)


@pytest.fixture
def say(capsys):
    """nayose in this process, as a user runs it: say(*words) → (its exit code, its last event)."""
    from er.cli import main

    def run(*words: object) -> tuple[int, dict]:
        code = main([*map(str, words), "--format", "json"])
        return code, json.loads(capsys.readouterr().out.splitlines()[-1])
    return run


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    """fake(code): the nayose commands the code under test starts (python -m er.cli WORDS) run `code` instead, a Python
    script given WORDS as sys.argv[1:] (json, os, shutil, sys and time imported), in a process of its own, on any
    system; any other process (git) runs as it is."""
    import subprocess
    import sys
    real = subprocess.Popen

    def fake(code: str) -> None:
        script = tmp_path / "fake_cli.py"
        script.write_text("import json, os, shutil, sys, time\n" + code, encoding="utf-8")
        swap = lambda cmd: [sys.executable, str(script), *cmd[3:]] if list(cmd[1:3]) == ["-m", "er.cli"] else cmd
        monkeypatch.setattr(subprocess, "Popen", lambda cmd, *a, **k: real(swap(cmd), *a, **k))
    return fake


@pytest.fixture
def ui_page(request):
    """open(workspace, home, viewport=None) → (page, server, httpd): the page on a server of its own, in Chromium, at
    its link. Everything opened is closed after the test, whatever happens in it. No browser: skipped, except under CI,
    where the browser tests must run, so it fails. With ER_TRACES set (CI sets it), a failed test leaves each page's
    Playwright trace there: what it clicked, saw and asked, step by step (npx playwright show-trace FILE)."""
    import threading
    from er import ui
    if os.environ.get("CI"):
        import playwright.sync_api as sync
    else:
        sync = pytest.importorskip("playwright.sync_api")
    with contextlib.ExitStack() as opened:  # each thing closed after the test, the last opened first, even when one close fails
        pw, traced = [], []

        def open_(workspace: str | None, home: str, viewport: dict | None = None):
            if not pw:  # as nayose open ui starts (ui.serve): what is there already never walked again by each command's collection
                gc.collect()
                gc.freeze()
                opened.callback(gc.unfreeze)
            server = ui.Server(workspace, home)
            httpd = ui.Listener(("127.0.0.1", 0), ui.handler(server))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            opened.callback(httpd.server_close)
            opened.callback(httpd.shutdown)
            if not pw:  # started once the test asks for a page: the test's own setup runs outside Playwright's loop
                pw.append(sync.sync_playwright().start())
                opened.callback(pw[0].stop)
            try:
                browser = pw[0].chromium.launch()
            except sync.Error:
                if os.environ.get("CI"):
                    raise
                pytest.skip("no browser: .venv/bin/python -m playwright install chromium")
            opened.callback(browser.close)
            context = browser.new_context(**({"viewport": viewport} if viewport else {}))
            if traces := os.environ.get("ER_TRACES"):
                context.tracing.start(snapshots=True)  # the page as it was at each step; no screenshots, which slow a busy machine
                path = Path(traces) / f"{request.node.name}-{len(traced)}.zip"
                traced.append(path)
                failed = lambda: any(r.failed for r in (getattr(request.node, f"report_{w}", None) for w in ("setup", "call")) if r)
                opened.callback(lambda: context.tracing.stop(**({"path": path} if failed() else {})))  # before the browser closes
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/?token={server.token}")
            return page, server, httpd
        yield open_
