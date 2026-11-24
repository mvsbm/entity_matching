"""Files and processes: Parquet read through Arrow (read_parquet), a file lock (lock), object storage told from a disk
(object_store), a write that waits out a reader holding the file (patiently, replace_text), the code's version and a
configuration's hash (code_version, config_hash), a table as markdown (markdown)."""
import hashlib
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pyarrow.fs


if os.name == "nt":
    import msvcrt
else:
    import fcntl


LOCAL = pyarrow.fs.LocalFileSystem()


def read_parquet(path: Path | str, **kwargs) -> pd.DataFrame:
    """pd.read_parquet with the file opened by Arrow. pandas opens a local file as a Python object, which Arrow may let
    go of on its own thread after Python has begun to exit; on Python 3.14 that thread and the exit then wait for each
    other forever, so a command that finished never ends."""
    return pd.read_parquet(path, filesystem=LOCAL, **kwargs)  # noqa: TID251


STORES = ("gcsfuse", "s3fs", "rclone", "goofys", "mountpoint-s3", "blobfuse", "blobfuse2")  # object storage mounted as files: no lock holds there
MOUNTS = Path("/proc/self/mountinfo")  # Linux's mounts, as this process sees them


def object_store(path: Path) -> str | None:
    """The object store `path` is on (one of STORES, by the type or source of the mount that holds it, in MOUNTS), if
    any; None on a disk, local or network (NFS, a Windows share: their locks hold), or where MOUNTS isn't. O(mounts)."""
    try:
        lines = MOUNTS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    at, best, found = str(path.resolve()), -1, None
    for line in lines:
        left, _, right = line.partition(" - ")
        mount, kind = left.split()[4:5], right.split()[:2]
        if not mount or len(kind) < 2:
            continue
        point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), mount[0])  # a space written \040
        if (at == point or at.startswith(point.rstrip("/") + "/")) and len(point) >= best:  # the deepest mount holding it; at one path, the last mounted
            best, found = len(point), next((x for x in STORES if x in (kind[0].removeprefix("fuse."), kind[1])), None)
    return found


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


CHILD = dict(encoding="utf-8", errors="replace")  # a child process's output: UTF-8 (python -m er writes it so), whatever the locale's code page

def patiently(do: Callable, *args, wait: float = 10.0):
    """do(*args), tried again for up to `wait` s while it is refused: Windows won't delete or replace a file a reader has
    open (a describe in the page's threads), and such a read ends in a second."""
    until = time.monotonic() + wait
    while True:
        try:
            return do(*args)
        except PermissionError:
            if time.monotonic() > until:
                raise
            time.sleep(0.05)


def replace_text(path: Path, text: str) -> None:
    """`path` written whole beside itself, then renamed over it, so a write cut short leaves the old file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")  # a writer's own: two at once never share one
    tmp.write_text(text, encoding="utf-8")
    patiently(os.replace, tmp, path)


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


def markdown(df: pd.DataFrame) -> str:
    """A table as GitHub markdown, for the reports."""
    rows = [list(df.columns)] + df.astype(str).to_numpy().tolist()
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")  # a bar in a value never shifts the table; a path's backslashes stay as written
    return "\n".join("| " + " | ".join(map(cell, r)) + " |" for r in rows[:1] + [["---"] * len(df.columns)] + rows[1:])
