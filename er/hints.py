"""A path read as the door reads it (readable): a workspace's part as its intake read it, or any other file read for
one command alone."""
from __future__ import annotations
import contextlib
import functools
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING


from er import folder, intake
from er.config import InputError
from er.emit import rows_told
from er.source import find

if TYPE_CHECKING:
    from er.emit import Emit


@contextlib.contextmanager
def readable(path: str, s, strict: bool = False, emit: "Emit | None" = None):
    """A path as the door reads it: a workspace's part, as its intake read it (read again first if an older reader
    read it: folder.fresh); any other file or files, read for this command alone into a folder that goes once it ends
    (er.intake); people's files strictly: one that needs a repair is refused."""
    p = Path(path).expanduser()
    if p.is_dir() and intake.report(p):
        yield str(folder.fresh(p, s.input, s.paths["reference"], rows_told(emit)))
        return
    files, root = find(path), p if p.is_dir() else None
    with tempfile.TemporaryDirectory(prefix="nayose-", ignore_cleanup_errors=True) as t:  # Windows: a file DuckDB still holds can't go yet
        named = {f: (f.relative_to(root) if root else Path(f.name)).as_posix() for f in files}
        back = [*((str(Path(t) / (x["read"])), str(f)) for f, x in zip(named, intake.take(Path(t), named, s.input, s.paths["reference"], strict=strict)["files"])), (t, str(path))]
        try:
            yield t
        except InputError as e:  # said of the files people gave, not of the folder they were read into
            say = lambda text: functools.reduce(lambda x, pair: x.replace(*pair), back, text)
            raise InputError(say(str(e)), say(e.fix), e.hints) from None


