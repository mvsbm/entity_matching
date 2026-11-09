"""Datasets, the chosen configurations and the experiment log (dataset ∈ train, val, test).

data/medallion/bronze/<dataset>.parquet          records as they arrive: the input
data/labels/<dataset>.parquet                    truth, read only to choose and evaluate
data/medallion/gold/<dataset>/                   each dataset resolved: a workspace, as er.run writes it (its
                                                 state/records/ holds the standardized records, the silver layer)
data/artifacts/models/<name>.json                a final configuration (and model) as it was run
data/artifacts/experiments/leaderboard.parquet   one row per (experiment, dataset)
"""
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from itertools import takewhile
from pathlib import Path

import pandas as pd

from er.config import Data

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def lock(f) -> bool:
    """An exclusive lock on the open file `f`, held until it closes or the process ends, even if it dies: flock on
    POSIX, a byte locked on Windows. False if another process holds it. O(1)."""
    try:
        if os.name == "nt":
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:  # BlockingIOError on POSIX; PermissionError on Windows
        return False


def alive(pid: int) -> bool:
    """Whether a process with this ID runs: os.kill(pid, 0) on POSIX, which sends nothing; on Windows os.kill would end
    it, so its exit code is asked instead (259: still running). O(1)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32")
        k.OpenProcess.argtypes, k.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE  # pointer-wide handles
        k.GetExitCodeProcess.argtypes, k.GetExitCodeProcess.restype = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        running = k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259
        k.CloseHandle(h)
        return bool(running)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # another user's
        return True
    return True


CHILD = dict(encoding="utf-8", errors="replace")  # a nayose child's output: UTF-8 (cli.main writes it so), whatever the locale's code page

def replace_text(path: Path, text: str, check: Callable[[Path], object] | None = None) -> None:
    """`path` written whole beside itself, then renamed over it, so a write cut short leaves the old file. `check` reads
    the new one first: if it raises, the new one goes and the old stays."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        if check:
            check(tmp)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def config_hash(config: object) -> str:
    return hashlib.sha1(repr(config).encode()).hexdigest()[:10]


def code_version(root: Path) -> str:
    """The commit of the code that ran, and the tracked files changed in this copy (the column mapping, say)."""
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10, **CHILD).stdout.strip()
        except OSError:
            return ""
    changed = git("diff", "--name-only", "HEAD").splitlines()
    return (git("rev-parse", "--short", "HEAD") or "unknown (not a git checkout)") + (f" · changed here: {', '.join(changed)}" if changed else "")


def load(data: Data, dataset: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Records and truth, validated: this is where outside data enters every stage."""
    records = pd.read_parquet(data.bronze_dir / f"{dataset}.parquet").astype("string")
    truth = pd.read_parquet(data.labels_dir / f"{dataset}.parquet").astype("string")
    uid = data.unique_id
    for name, frame in (("records", records), ("labels", truth)):
        if uid not in frame:
            raise ValueError(f"{dataset} {name}: no {uid} column")
        if frame[uid].isna().any():
            raise ValueError(f"{dataset} {name}: {int(frame[uid].isna().sum())} records without a {uid}")
        if frame[uid].duplicated().any():
            raise ValueError(f"{dataset} {name}: {uid} {frame[uid][frame[uid].duplicated()].iloc[0]} appears more than once")
    if data.entity_id not in truth or truth[data.entity_id].isna().any():
        raise ValueError(f"{dataset} labels: {data.entity_id} missing for some records")
    if set(records[uid]) != set(truth[uid]):
        raise ValueError(f"{dataset}: records and labels hold different {uid}s")
    return records, truth


def write_final(data: Data, name: str, config: object, model: dict | None = None, **facts: object) -> Path:
    """The configuration a stage ended with (and its fitted model, if any), plus facts such as the adopted
    changes, so a result can be traced and the configuration rebuilt."""
    data.models_dir.mkdir(parents=True, exist_ok=True)
    path = data.models_dir / f"{name}.json"
    path.write_text(json.dumps(dict(config=repr(config), config_hash=config_hash(config), model=model, **facts),
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def population(data: Data) -> str:  # which generated population the labels hold: test is counted per population
    labels = pd.read_parquet(data.labels_dir / "test.parquet").sort_values(data.unique_id, ignore_index=True)
    return f"{int(pd.util.hash_pandas_object(labels, index=False).sum()) & (2**48 - 1):012x}"


def append_leaderboard(data: Data, experiment: str, config: object, dataset: str, metrics: dict) -> None:
    """Append one row; the config hash tells identical configurations apart from same-named ones, the population
    (test rows only) which test they were scored on."""
    path = data.experiments_dir / "leaderboard.parquet"
    data.experiments_dir.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), experiment=experiment, dataset=dataset,
                             population=population(data) if dataset == "test" else None, config_hash=config_hash(config), **metrics)])
    board = pd.concat([pd.read_parquet(path), row], ignore_index=True) if path.exists() else row
    board.to_parquet(path, index=False)


def test_evaluations(data: Data) -> pd.DataFrame:
    """Distinct configurations scored on this population's test, per experiment family (the part before ':'). More
    than one per family means test influenced a choice and its numbers are no longer unbiased. A newly generated
    population has a test nobody has seen, so its count starts again."""
    path = data.experiments_dir / "leaderboard.parquet"
    if "test" not in data.datasets or not path.exists():  # a development round (choose.py --no-test) never reads test
        return pd.DataFrame(columns=["family", "configs_on_test"])
    board = pd.read_parquet(path)
    board = board[board.get("population", pd.Series(index=board.index, dtype="string")) == population(data)]
    test = board[board["dataset"] == "test"].assign(family=lambda b: b["experiment"].str.split(":").str[0])
    return test.groupby("family")["config_hash"].nunique().rename("configs_on_test").reset_index()


def assert_test_scored_once(data: Data) -> None:
    """Fail loudly when a family has been scored on this population's test with more than one configuration. To start a
    clean pass on the same population after a deliberate change, archive the leaderboard (data/artifacts/experiments/archive/)."""
    over = test_evaluations(data).query("configs_on_test > 1")
    if len(over):
        raise AssertionError(f"test was scored with several configurations: {over.to_dict('records')}")


def markdown(df: pd.DataFrame) -> str:
    """A table as GitHub markdown, for the reports."""
    rows = [list(df.columns)] + df.astype(str).to_numpy().tolist()
    return "\n".join("| " + " | ".join(map(str, r)) + " |" for r in rows[:1] + [["---"] * len(df.columns)] + rows[1:])


def table_after(text: str, heading: str) -> pd.DataFrame:
    """The first markdown table after this heading in a report (the reverse of markdown()), as strings."""
    lines = text.split(heading, 1)[1].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in takewhile(lambda x: x.startswith("|"), lines[start:])]
    return pd.DataFrame(rows[2:], columns=rows[0])
