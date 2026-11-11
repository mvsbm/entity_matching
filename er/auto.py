"""The rehearsal (nayose rehearse records): the whole pipeline on a generated file of the same size and shape as a real
one, under the same limits, to measure what this machine needs before the real file is run.

    shape       the real file's records, and each field's share filled, as describe reads them: no value kept
    generate    parts of 50,000 entities each, each with its own seed, so memory is O(chunk) at any size; each
                field's first column filled at the real share; a field the file lacks, and fallback columns, left out
    measure     nayose resolve records on the parts, in a process of its own, with the same limits and its own spill
                folder on the same disk; the parent reads its size every half second (DuckDB deletes spill files as it
                goes, so only polling sees the peak); seconds and peak memory from the run's steps.json

O(N) to generate and O(a full run) to measure. Past 60,000 entities the generator's personas repeat, so names repeat
more than in a real file and name keys make more pairs: the result says so, and a check of the real file
(check records) counts its pairs exactly.

Auto mode (nayose try everything): the commands a person would run on a file, in order, each in a process of its own,
then one report to send that holds no record's value (auto/report.md, and the facts behind it in auto/report.json).

    workspace   create workspace auto-<month><day>-<time>, strict: nothing merges before people check
    load        load records; set feature with what its contents suggest (placements); describe records again
    check       check records: will a run go through, what to look at first
    rehearse    rehearse records: a file of its size and shape, measured; a stop here stops before the real run
    resolve     resolve records
    method      describe method, list patterns
    trial N     try method, for each change describe method proposes (--trials of them)
    offers      a name in another script the file holds (describe records offers): a workspace of its own in auto/,
                with it added, loaded and run, its pairs beside the run's
    review      describe review
A step that fails is kept with its error and fix, and a step that needs it is skipped; the report is written whatever
happened. What it holds is taken field by field from each result: counts, shares, seconds and the names of columns,
fields, rules and keys; no example, ID, path or block value. Then it is checked against every value of a sample of
20,000 records (non-ASCII of 3 characters or more, other text of 4, digits of 6), against every run of six digits or
more (its counts are written 1,234,567) and every run of kana or kanji that is no column name: each found is put as
[redacted], and counted. O(the commands it runs) + O(sample · columns + report · value lengths) for the check.
"""
import collections
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import duckdb
import numpy as np

from er.config import InputError, lit
from er.folder import method, runs
from er.generate import generate, load_reference, load_spec
from er.io import CHILD, alive, code_version, replace_text
from er.run import peak_gb
from er.settings import Settings, added_of, beside, load_settings
from er.source import describe, find, lexicon, profiled
from er.strings import connect

CHUNK = 50_000  # entities a generated part: generation's memory, whatever the file's size
PILOT = 5_000  # entities of a first, small draw: each field's share measured on it, then each rate set right
POLL = 0.5  # seconds between two readings of the spill folder's size
LIMIT = ("past 60,000 entities the generator's people repeat, so names repeat more than in a real file and name keys make more "
         "pairs: the real file's own pairs are in check records")
SAMPLE = 20_000  # records whose values the report is checked against
HIDDEN = "[redacted]"
JAPANESE = re.compile(r"[\u3005\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\U00020000-\U0003134f]+")  # kana, kanji, half-width kana
DIGITS = re.compile(r"(?<![A-Za-z0-9_.])\d{6,}(?![A-Za-z0-9_])")  # an ID, a postal code, a phone, even beside kana: the report writes its own counts 1,234,567
CRASH = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit))\b")  # a traceback's last line: the kind of crash, never its words
PLAIN = re.compile(r"[-+]?\d+([.:]\d+)?")  # a number or a time, as a value
RECORD = re.compile(r"[0-9０-９]{4}|@|株式会社|有限会社|合同会社|[(（]株[)）]|カブシキガイシャ|^[MTSHR]\d{1,2}[./]\d|\d[./-]\d{1,2}[./-]\d")  # a value, not a column's name


def shape(s: Settings, path: str | Path) -> dict:
    """The records at `path` and each field's share filled, under the mapping of `s`, from describe's one scan: counts
    and shares only, no value. Its share of companies, the company name's, unless that reads a column a person's name
    reads too (one name column for both: then not known, None). O(N)."""
    d = describe(path, connect(s.compute)[0], s.columns, s.detect)
    fields = {f["field"]: round(f["filled"], 4) for f in d["fields"] if f["filled"]}
    names = lambda f: {c for alt in s.columns.get(f, ()) for c in alt}
    shared = names("company_name") & (names("person_name") | names("full_name"))
    return dict(records=d["records"], fields=fields, company=None if shared else fields.get("company_name", 0.0))


def generated(sh: dict, out: Path, emit: Callable[[dict], None]) -> int:
    """Parquet parts in `out` of a generated file of `sh`'s size and shape, under the project's mapping (the
    generator's own column names): about records ÷ 1.25 entities, CHUNK a part, each part with its own seed and the
    record IDs numbered on across the parts; each field's first column filled at the file's share (each rate measured
    on a small pilot draw, then set right; a column built from parts, the address, blanked at random to its share),
    the company share the file's (shape: the generator's own when not known); the columns of a field the file lacks,
    and every fallback column, left out, so a field's share is its first column's. The records written. O(N) time,
    O(CHUNK) memory."""
    s0 = load_settings()
    base, _ = load_spec(s0.root / "config" / "generator.toml")
    if s0.data.unique_id not in {c.name for c in base.columns}:
        raise InputError(f"the project's mapping (config/settings.toml [columns]) names columns the generator doesn't write ({s0.data.unique_id})",
                         fix="a rehearsal maps the generator's columns as the project shipped them: rehearse from a copy with that mapping")
    persons, companies, towns = load_reference(s0.paths["reference"])
    company = sh.get("company")
    share = base.company_share if company is None else min(max(company, 0.01), 0.99) if company else 0.0
    of_kind = lambda c: 1 - share if c.kind == "person" else share if c.kind == "company" else 1.0
    columns = {c.name: c for c in base.columns}
    first = {f: alts[0][0] for f, alts in s0.columns.items() if alts and alts[0] and alts[0][0] in columns}
    target = {first[f]: sh["fields"][f] for f in sorted(sh["fields"], key=lambda f: -len(s0.columns.get(f, ())))  # a column several fields read
              if f in first and columns[first[f]].nullable}  # first: the share of the one it alone makes
    built = {c: v for c, v in target.items() if columns[c].parts}  # filled where a part is: blanked after, at random
    target = {c: v for c, v in target.items() if c not in built}
    rate = {c: min(1.0, v / k) if (k := of_kind(columns[c])) else 0.0 for c, v in target.items()}
    keep = {c for f in sh["fields"] for c in (s0.columns.get(f) or ((),))[0]} | {s0.data.unique_id}  # a field's first columns: its share is theirs
    unused = {c for alts in s0.columns.values() for alt in alts for c in alt} - keep
    with_rates = lambda r: replace(base, company_share=share, columns=tuple(replace(c, rate=r[c.name]) if c.name in r else c for c in base.columns))
    entities, uid = max(1, round(sh["records"] / (1 + base.dup_lambda))), s0.data.unique_id
    pilot = generate(replace(with_rates(rate), entities=min(PILOT, entities), seed=base.seed + 10_000), persons, companies, towns).df
    filled = lambda c: float((pilot[c].notna() & pilot[c].astype("string").str.strip().ne("")).mean())  # a share as the file's is read
    rate = {c: min(1.0, r * target[c] / got) if (got := filled(c)) else r for c, r in rate.items()}  # measured on a pilot, then set right
    keep_built = {c: min(1.0, v / got) if (got := filled(c)) else 1.0 for c, v in built.items()}
    return _parts(with_rates(rate), entities, out, (persons, companies, towns), uid,
                  lambda n: emit(dict(step="generate", records=n, seconds=0.0)), unused, keep_built)


def synthetic(s: Settings, fields, records: int, difficulty: str, out: Path, done: Callable[[int], None]) -> int:
    """Parquet parts in `out` of `records` generated records at `difficulty` (config/generator.toml [difficulty]), every
    column the generator writes, for a workspace whose mapping `s` reads them for each field a run needs (`fields`, the
    pipeline's: mandatory, one_of), else refused before any is made: a tenth more entities than the records need on
    average, the rows past `records` left out (the generator shuffles them, so those are any). O(N) time, O(CHUNK)
    memory."""
    spec, _ = load_spec(s.root / "config" / "generator.toml", difficulty)
    written = {c.name for c in spec.columns}
    reads = lambda f: any(alt and all(c in written for c in alt) for alt in s.columns.get(f, ()))
    lost = [f for f in fields.mandatory if not reads(f)] + [" or ".join(g) for g in fields.one_of if not any(map(reads, g))]
    lost = [x.replace("_", " ") for x in lost]  # said in words: person name or company name
    if lost:
        raise InputError(f"this workspace's mapping reads no column the generator writes for {', '.join(lost)}",
                         fix="generate into a new workspace: nayose create workspace NAME")
    entities = math.ceil(records / (1 + spec.dup_lambda) * 1.1) + 10
    n = _parts(spec, entities, out, load_reference(s.paths["reference"]), s.data.unique_id, done, limit=records)
    if len(files := list(out.glob("*.parquet"))) == 1:
        files[0].rename(out / f"{out.name}.parquet")  # one file: named as the records it holds, as a loaded file is shown
    return n


def _parts(spec, entities: int, out: Path, ref: tuple, uid: str, done: Callable[[int], None],
           unused: set[str] = frozenset(), keep_built: dict[str, float] | None = None, limit: int | None = None) -> int:
    """`entities` generated in parts of CHUNK, each with its own seed and the record IDs numbered on across them; the
    `unused` columns left out, each of `keep_built` blanked at random to keep that share; none past `limit` records.
    The records written."""
    out.mkdir(parents=True, exist_ok=True)
    records = 0
    for i, start in enumerate(range(0, entities, CHUNK)):
        if limit is not None and records >= limit:
            break
        g = generate(replace(spec, entities=min(CHUNK, entities - start), seed=spec.seed + i), *ref)
        df = g.df.drop(columns=[c for c in unused if c in g.df.columns]).iloc[: None if limit is None else limit - records]
        rng = np.random.default_rng(spec.seed + 20_000 + i)
        for c, keep in (keep_built or {}).items():
            df.loc[rng.random(len(df)) >= keep, c] = None
        width = len(df[uid].iloc[0])
        df[uid] = [f"{records + j + 1:0{width}d}" for j in range(len(df))]  # one ID per record across the parts
        df.to_parquet(out / f"part-{i:05d}.parquet", index=False)
        records += len(df)
        done(records)
    return records


def size_of(folder: Path) -> int:  # the bytes under a folder now; a file DuckDB just removed is skipped
    total = 0
    for root, _, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def rehearse(ws: Path, sh: dict, s: Settings, pipeline: Path | None, emit: Callable[[dict], None]) -> dict:
    """The rehearsal of a file of shape `sh` (shape()) in the workspace `ws`, under the limits of `s` (its [compute]
    and --compute) and the workspace's method (method.toml): the generated file in ws/rehearsal/, run there in a
    process of its own, measured; both removed however it ends, and the run stopped if this one is; the result kept in
    ws/rehearsal.json. Its seconds (generating, and each step of the run), peak memory, peak spill, the pairs the run
    listed, the generated shape beside the file's, and what went wrong if the run stopped (an out-of-memory or a full
    disk: the real file would stop there too), in its own words when it died without saying (the last lines it wrote)."""
    root, t = ws / "rehearsal", time.perf_counter()
    temp = Path(connect(s.compute)[0].execute("SELECT current_setting('temp_directory')").fetchall()[0][0])
    for old in temp.glob("rehearsal-*"):  # one a rehearsal killed outright left: its process is gone
        pid = old.name.removeprefix("rehearsal-")
        if pid.isdigit() and not alive(int(pid)):
            shutil.rmtree(old, ignore_errors=True)
    spill, child = temp / f"rehearsal-{os.getpid()}", None  # on the disk a real run spills to, and only this run's
    shutil.rmtree(root, ignore_errors=True)
    try:
        records = generated(sh, root / "records", emit)
        made, made_seconds, made_gb = shape(load_settings(), root / "records"), round(time.perf_counter() - t, 1), peak_gb()  # this process's, before the run's own
        spill.mkdir(mode=0o700, parents=True, exist_ok=True)
        (root / "run").mkdir()
        m, added = method(ws), {f for f, _ in beside(added_of(ws))}  # the workspace's method: its trust line, the keys and rules people changed,
        m["add_keys"] = [k for k in m.get("add_keys", []) if not {f.split(":")[0] for f in k} & added]  # but a key on an added name: the file
        m["drop_keys"] = [k for k in m.get("drop_keys", []) if k.partition("@")[2] not in added]          # generated holds none
        if m := {k: v for k, v in m.items() if v != []}:
            replace_text(root / "run" / "method.toml", "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in m.items()))
        limits = [f"{k}={v}" for k, v in {**s.compute, "temp_directory": str(spill)}.items() if v not in ("", None)]
        child = subprocess.Popen([sys.executable, "-m", "er.cli", "resolve", "records", str(root / "records"), "--workspace", str(root / "run"),
                                  "--format", "json", "--compute", *limits, *(["--pipeline", str(pipeline)] if pipeline else [])],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **CHILD)
        events, said, failed = [], collections.deque(maxlen=20), []

        def read() -> None:  # the run's steps, passed on as they end: progress while it runs; any other line, its last words
            try:
                for line in child.stdout:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        e = None
                    if not isinstance(e, dict):
                        said.append(line.strip())
                        continue
                    events.append(e)
                    if e.get("event") == "step":
                        emit(dict(step=f"rehearse {e['step']}", seconds=e.get("seconds", 0.0)))
            except Exception as e:  # passing progress on failed: said by the rehearsal, which stops the run
                failed.append(e)
        reader, peak = threading.Thread(target=read, daemon=True), 0
        reader.start()
        while child.poll() is None and reader.is_alive():  # a reader gone (its emit failed) can't drain the pipe: the run is stopped below
            peak = max(peak, size_of(spill))
            time.sleep(POLL)
        if child.poll() is None:
            raise failed[0] if failed else RuntimeError("the rehearsal's progress could not be passed on")
        reader.join(30)
        steps = [e for e in events if e.get("event") == "step"]
        last = next((e for e in reversed(events) if e.get("event") == "error"), {})
        died = " ".join(x for x in said if x)[-300:] or f"exit {child.returncode}"
        result = dict(ok=child.returncode == 0, records=records, generate_seconds=made_seconds, generate_peak_gb=made_gb,
                      seconds=round(sum(x.get("seconds", 0.0) for x in steps), 1), steps={x["step"]: x.get("seconds") for x in steps},
                      peak_memory_gb=max((x.get("peak_memory_gb", 0.0) for x in steps), default=None), peak_spill_gb=round(peak / 2**30, 2),
                      pairs=next((x.get("pairs") for x in steps if x["step"] == "budget"), None),
                      shape={f: dict(file=v, rehearsal=made["fields"].get(f)) for f, v in sh["fields"].items()},
                      error=(last.get("error") or died) if child.returncode else None, fix=last.get("fix") if child.returncode else None, limit=LIMIT)
    finally:
        if child and child.poll() is None:
            child.kill()
            child.wait()
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(spill, ignore_errors=True)
    replace_text(ws / "rehearsal.json", json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ---------- auto mode ----------

def nayose(words: list, step: str, emit: Callable[[dict], None]) -> tuple[int, dict, list[str]]:
    """One command as python -m er.cli … --format json, in a process of its own: its steps passed on as `step: <its
    step>`; its exit code, its result or its error, and any other line it wrote (a crash's traceback). A crash's error
    is its kind alone (its message may quote a value). Stopped (Ctrl-C, or the progress can't be passed on), the
    command is stopped too: after Ctrl-C, which reached it as well, given 15 seconds to clean up; else asked to stop
    the same way first."""
    child = subprocess.Popen([sys.executable, "-m", "er.cli", *map(str, words), "--format", "json"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, **CHILD)
    last, other = {}, collections.deque(maxlen=200)
    try:
        for line in child.stdout:  # stderr joins stdout: one pipe read to its end, so a long traceback can't fill it
            try:
                e = json.loads(line)
            except ValueError:
                e = None
            if not isinstance(e, dict):
                other.append(line.rstrip("\n"))
            elif e.get("event") == "step":
                emit(dict(step=f"{step}: {e['step'].removeprefix(step + ' ')}", seconds=e.get("seconds", 0.0)))
            elif e.get("event") in ("result", "error"):
                last = e
        code = child.wait()
    except BaseException as e:
        if child.poll() is None:
            if not isinstance(e, KeyboardInterrupt):  # asked to stop: Ctrl-C's signal on POSIX; Windows has none to send it, so it ends it
                child.send_signal(signal.SIGINT) if os.name != "nt" else child.terminate()
            try:
                child.wait(15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        raise
    if code and last.get("event") != "error":
        kind = next((m.group(1) for x in reversed(other) if (m := CRASH.match(x.strip()))), None)
        last = dict(event="error", error=f"crashed: {kind}" if kind else f"stopped: exit {code}" + (" (killed: out of memory?)" if code == -9 else ""),
                    fix=f"its own words are in auto/{step.replace(' ', '-')}.log in the workspace" if other else "")
    return code, last, list(other)


def values(part: Path, s: Settings) -> set[str]:
    """The distinct values of a sample of SAMPLE records of a loaded part, long enough to mean something: non-ASCII
    of 3 characters or more, digits of 6, other text of 4, but a plain lower-case word (true, file, none: a flag, the
    report's own words; a name is written Sato or SATO) or a number or time of fewer than 6 digits (12.34, 04:19);
    a column's name is none. O(SAMPLE · columns)."""
    files = ", ".join(lit(str(f)) for f in find(part))
    df = connect(s.compute)[0].execute(f"SELECT * FROM read_parquet([{files}], union_by_name = true) USING SAMPLE {SAMPLE} ROWS").df()
    names, out = set(df.columns), set()
    for c in df.columns:
        for v in df[c].dropna().astype(str).str.strip().unique():
            if v not in names and len(v) >= (3 if not v.isascii() else 6 if v.isdigit() else 4) and not (v.isascii() and v.isalpha() and v.islower()) \
                    and not (PLAIN.fullmatch(v) and sum(ch.isdigit() for ch in v) < 6):  # a balance, a score, a time: the report's own numbers look alike
                out.add(v)
    return out


OWN_TIME = re.compile(r"(?<=RUN REPORT · )\d{4}-\d{2}-\d{2} \d{2}:\d{2}|(?<=\*\*When:\*\* )\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")  # when it ran, as the reports write it


def scrub(text: str, found: set[str], names: set[str], ours: frozenset[str] = frozenset()) -> tuple[str, int]:
    """`text` with each value of `found` in it, each run of six digits or more and each run of kana or kanji no
    column name (`names`) holds put as [redacted], and how many: a value in ASCII only where it stands as a word; a
    run of digits that is one of `ours` (the code's commit, which can be all digits) is the report's own.
    O(|text| · L) lookups, L the lengths the values come in."""
    lengths = sorted({len(v) for v in found if len(v) <= 256}, reverse=True)
    out, i, n, hits = [], 0, len(text), 0
    word = lambda ch: ch.isascii() and (ch.isalnum() or ch == "_")
    while i < n:
        for k in lengths:  # the longest value first
            v = text[i:i + k]
            if v in found and (not v.isascii() or not (i and word(text[i - 1])) and not (i + k < n and word(text[i + k]))):
                out.append(HIDDEN)
                i, hits = i + k, hits + 1
                break
        else:
            out.append(text[i])
            i += 1
    text = "".join(out)
    def japanese(m: re.Match) -> str:
        nonlocal hits
        if any(m.group() in c for c in names):
            return m.group()
        hits += 1
        return HIDDEN
    text = JAPANESE.sub(japanese, text)
    def digits(m: re.Match) -> str:
        nonlocal hits
        if m.group() in ours:
            return m.group()
        hits += 1
        return HIDDEN
    return DIGITS.sub(digits, text), hits


def cleaned(x: object, clean: Callable[[str], str]) -> object:  # every text in a result put through `clean`; numbers stay
    if isinstance(x, dict):  # its keys are the report's own names: a column's name is a value in a row (profile), never a key
        return {k: cleaned(v, clean) for k, v in x.items()}
    if isinstance(x, list):
        return [cleaned(v, clean) for v in x]
    return clean(x) if isinstance(x, str) else x


def kept(rows: list[dict] | None, *keys: str) -> list[dict]:  # each row's named fields only
    return [{k: r[k] for k in keys if k in r} for r in rows or []]


def machine(compute: list[str]) -> dict:
    s0 = load_settings()
    try:
        memory = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        memory = None
    return dict(code=code_version(s0.root), python=platform.python_version(), duckdb=duckdb.__version__, splink=version("splink"),
                system=f"{platform.system()} {platform.machine()}", cores=os.cpu_count(), memory_gb=memory, compute=compute)


def change_args(c: dict) -> list[str]:  # a proposal's change as try method's options, as the page gives them
    if "line" in c:
        return ["--line", str(c["line"])]
    if "add_keys" in c:
        return ["--add", *("+".join(k) for k in c["add_keys"])]
    return ["--drop", *c.get("drop_rules", []), *c.get("drop_keys", [])]


def everything(file: str, home: Path, trials: int, compute: list[str], pipeline: str | None, emit: Callable[[dict], None]) -> dict:
    """Auto mode on `file`: a new workspace in `home`, the steps above, and the report. Its facts, the workspace, the
    part loaded, and the exit code: 0 once the run went through, 75 if a workspace was busy, 130 if it was stopped
    (Ctrl-C, or its progress couldn't be passed on: the steps so far kept), else 2. A step that crashed keeps its own
    words in auto/<step>.log in the workspace, never in the report."""
    t0, now, file = time.perf_counter(), datetime.now(), str(Path(file).expanduser())
    limits, pipe = (["--compute", *compute] if compute else []), (["--pipeline", pipeline] if pipeline else [])
    files = find(file)
    facts: dict = dict(at=now.isoformat(timespec="seconds"), machine=machine(compute), steps=[],
                       file=dict(files=len(files), formats=sorted({f.suffix.lower().lstrip(".") for f in files}), bytes=sum(f.stat().st_size for f in files)))
    got: dict = dict(busy=False, ws=None, part=None)

    def do(name: str, words: list) -> dict | None:  # one step: its result, or None once it failed (kept, with its fix)
        t = time.perf_counter()
        code, e, said = nayose(words, name, emit)
        seconds = round(time.perf_counter() - t, 1)
        if code and said and got["ws"] and got["ws"].exists():  # a crash's own words: on this machine only
            (got["ws"] / "auto").mkdir(exist_ok=True)
            replace_text(got["ws"] / "auto" / f"{name.replace(' ', '-')}.log", "\n".join(said) + "\n")
        facts["steps"].append(dict(step=name, ok=code == 0, exit=code, seconds=seconds,
                                   error=e.get("error") if code else None, fix=e.get("fix") if code else None))
        emit(dict(step=name, seconds=seconds, ok=code == 0, **({"workspace": str(got["ws"])} if name == "workspace" and not code else {})))  # the page opens it
        got["busy"] |= code == 75
        return e if code == 0 else None

    def steps() -> None:
        base = f"auto-{now:%m%d-%H%M}"
        for _ in range(5):  # another auto mode may take the same name this minute: then the next one free
            name = next(n for n in (base, *(f"{base}-{i}" for i in range(2, 1000))) if not (home / n).exists())
            got["ws"] = ws = (home / name).resolve()
            if (made := do("workspace", ["create", "workspace", name, "--home", home])) or not ws.exists():
                break
            facts["steps"].pop()
        if not made:
            got["ws"] = None
            return
        there = ["--workspace", ws]
        if not (loaded := do("load", ["load", "records", Path(file).resolve() if Path(file).exists() else file, *there])):
            return
        got["part"] = part = loaded["loaded"]
        described = loaded
        if placed := [f"{x['feature']}={x['column']}" for x in loaded.get("placements", [])]:
            if do("place", ["set", "feature", *placed, *there]):
                described = do("describe", ["describe", "records", part, *there]) or loaded
        facts.update(placed=kept(loaded.get("placements"), "feature", "column", "share", "why"), records=described["records"],
                     columns=kept(described["columns"], "column", "filled"), profile=[dict(column=c, **x) for c, x in described.get("profile", {}).items()],
                     notes=described.get("notes", []),
                     fields=[dict(kept([x], "field", "sources", "filled", "looks_right")[0], alternatives=kept(x.get("alternatives"), "columns", "found", "filled", "looks_right"))
                             for x in described["fields"]],
                     offers=kept(described.get("offers"), "feature", "type", "script", "column", "share", "why"),
                     needed=described.get("needed"), turned_off=described.get("turned_off"),
                     read={k: v for k, v in (loaded.get("read") or {}).items() if k not in ("part", "examples")})
        if not (checked := do("check", ["check", "records", part, *there, *limits, *pipe])):
            return
        facts["check"] = dict(capacity={k: v for k, v in checked["capacity"].items() if k != "spill_folder"}, ready=checked["ready"],
                              keys=checked["keys"], fields=kept(checked["fields"], "field", "filled", "looks_right", "top_value", "columns"),
                              turned_off=checked.get("turned_off"), notes=checked.get("notes"))
        do("rehearse", ["rehearse", "records", part, *there, *pipe, *limits])
        if (ws / "rehearsal.json").exists():  # its run ran: one that stopped (memory, disk) stops the real one too
            facts["rehearsal"] = json.loads((ws / "rehearsal.json").read_text(encoding="utf-8"))
        if not facts.get("rehearsal", {}).get("ok", True) or not do("resolve", ["resolve", "records", *there, *pipe, *limits]):
            return
        facts["run"] = dict(report=(ws / "report.txt").read_text(encoding="utf-8"),
                            steps=[{k: v for k, v in x.items() if isinstance(v, int | float | str) and k != "big_o"} for x in runs(ws)[-1]["steps"]])
        if method := do("method", ["describe", "method", *there, *pipe]):
            facts["method"] = dict(line=method["line"], review_from=method["review_from"], trust=method["trust"], to_decide=method["to_decide"],
                                   bands=method["bands"], rules=method["rules"], keys=method["keys"], steps=method["steps"],
                                   proposals=kept(method["proposals"], "change", "why"), dropped=method["dropped"])
            if patterns := do("patterns", ["list", "patterns", *there, *pipe]):
                near = [x for x in patterns["patterns"] if method["review_from"] <= x["points"] < method["line"] + 4]
                facts["patterns"] = dict(fields=patterns["fields"], pairs=patterns["pairs"], threshold=patterns["threshold"],
                                         near=kept(sorted(near, key=lambda x: -x["pairs"])[:15], "steps", "points", "pairs", "merged", "wait", "held", "apart"))
            order = ("add_keys", "line", "drop_keys", "drop_rules")  # what may find more first, then what costs less
            proposals = sorted(method["proposals"], key=lambda x: min(order.index(k) for k in x["change"] if k in order))
            facts["trials"] = []
            for i, x in enumerate(proposals[:trials], 1):
                tried = do(f"trial {i}", ["try", "method", *there, *change_args(x["change"]), *pipe, *limits])
                facts["trials"].append(dict(change=x["change"], why=x["why"], ok=bool(tried),
                                            **({k: tried[k] for k in ("base", "variant", "apart", "together")} if tried else {})))
        if facts.get("offers"):
            facts["with_offers"] = offered(ws, part, facts["offers"], do, pipe, limits)
        if review := do("review", ["describe", "review", *there, *pipe]):
            facts["review"] = {k: v for k, v in review.items() if k not in ("event", "command", "next")}

    stopped = False
    try:
        steps()
    except (KeyboardInterrupt, BrokenPipeError):  # Ctrl-C, or the page that asked is gone: what ran so far is reported
        stopped = True
        if got["ws"] and not got["ws"].is_dir():  # stopped while it was being made: nowhere to report
            got["ws"] = None
        facts["steps"].append(dict(step="stopped", ok=False, exit=130, seconds=0.0, error="stopped before its end", fix="run it again"))
    facts["seconds"] = round(time.perf_counter() - t0, 1)
    ran = any(x["step"] == "resolve" and x["ok"] for x in facts["steps"])
    return dict(facts=facts, workspace=got["ws"], part=got["part"], exit_code=130 if stopped else 0 if ran else 75 if got["busy"] else 2)


def offered(ws: Path, part: str, offers: list[dict], do: Callable, pipe: list, limits: list) -> dict:
    """The names in another script the file holds, tried: a workspace of their own in auto/offers, with the run's
    mapping and each added, loaded and run; its pairs by range beside the run's, its candidates and the matches its
    probe says no key lists."""
    home = ws / "auto"
    if not do("offers workspace", ["create", "workspace", "offers", "--home", home]):
        return dict(ok=False)
    w = home / "offers"
    shutil.copyfile(ws / "columns.toml", w / "columns.toml")  # the run's mapping, with what was placed
    there = ["--workspace", w]
    for x in offers:
        if not do("offers add", ["add", "feature", x["feature"], "--type", x["type"], "--script", x["script"], "--column", x["column"], *there]):
            return dict(ok=False)
    if not (do("offers load", ["load", "records", part, *there]) and do("offers resolve", ["resolve", "records", *there, *pipe, *limits])):
        return dict(ok=False)
    review = do("offers review", ["describe", "review", *there, *pipe]) or {}
    facts = lambda folder: {x["step"]: x for x in runs(folder)[-1]["steps"]}
    mine, theirs = facts(w), facts(ws)
    missed = lambda f: sum(x.get("keys_missed", 0) for x in f.get("probe", {}).get("strata", []))
    return dict(ok=True, added=kept(offers, "feature", "script", "column"),
                ranges=kept(review.get("ranges"), "down_to", "up_to", "pairs", "expected_false"),
                candidates=dict(without=theirs.get("candidates", {}).get("candidates"), with_=mine.get("candidates", {}).get("candidates")),
                missed=dict(without=missed(theirs), with_=missed(mine)),
                seconds=dict(without=round(sum(x["seconds"] for x in theirs.values()), 1), with_=round(sum(x["seconds"] for x in mine.values()), 1)))


def written(r: dict, file: str, s: Settings) -> dict:
    """The report of `r` (everything's) in its workspace's auto/: report.json, the facts, and report.md, them in words,
    both checked as scrub does against the values of the part loaded. A column's name stays, unless it reads like a
    value (four digits, an email, a legal form, a date, a known full name or address): then it is one; and when the
    first line was a record (the reader says the header may be missing, or two names read like values), every name
    is. The names the mapping expects are the report's own. The file's path
    and name are put as <file>, its part's name as <part>, the workspace's path as its name, the home folder as ~ and
    the current one as ".". The paths, the values checked against, and how many were redacted."""
    ws, facts = r["workspace"], r["facts"]
    found = values(Path(r["part"]), s) if r.get("part") else set()
    names = {x["column"] for x in facts.get("columns", [])}
    known = profiled({c: [c] for c in names}, lexicon(s.paths["reference"], tuple(s.standardize.kana_fold.items())))
    odd = {c for c in names if RECORD.search(c) or (len(c) >= 4 and max(known[c]["full"], known[c]["address"]) >= 1)}
    if any("a header may be missing" in n for n in facts.get("notes", [])) or len(odd) >= 2:  # the first line was a record: its names are values,
        found |= {c for c in names if len(c) >= (2 if not c.isascii() else 4 if c.isdigit() else 3)}  # each long enough to mean anything, and no
        names = set()                                                                                    # kana or kanji of them stays
    else:  # one name that reads like a value is one; the names the mapping expects are the report's own
        found, names = found | odd, (names | {c for alts in s.columns.values() for alt in alts for c in alt}) - odd
    try:
        given = find(file)
    except InputError:
        given = []
    exact = {str(Path(file).resolve()): "<file>", str(ws): ws.name, str(Path.home()): "~", os.getcwd(): "."}
    exact = {k: v for k, v in sorted(exact.items(), key=lambda x: -len(x[0])) if len(Path(k).parts) > 2}  # "/" or "/Users" would garble every path
    tokens = {f.name for f in given if len(f.name) >= 4} | ({Path(file).name} if Path(file).suffix and len(Path(file).name) >= 4 else set())  # files' names; a folder's is in its path
    part = Path(r["part"]).name if r.get("part") else None  # inputs/0001-<the file's name, as the workspace wrote it>
    ours = frozenset(facts["machine"]["code"].split()[:1])  # the commit's short hash: 1572846 is no ID
    hits = 0

    def clean(text: str) -> str:
        nonlocal hits
        for x, to in exact.items():
            text = text.replace(x, to)
        for x in tokens:  # a file's name as a word of its own, not inside another
            text = re.sub(rf"(?<![\w.-]){re.escape(x)}(?![\w-])", "<file>", text)
        if part:
            text = text.replace(part, "<part>")
        stamps = OWN_TIME.findall(text)  # the report's own times: a value of the file's may read like part of one (11-10 on 10 November)
        text, n = scrub(OWN_TIME.sub("\x00", text), found, names, ours)
        hits += n
        return re.sub("\x00", lambda _: stamps.pop(0), text)

    facts = cleaned(facts, clean)
    text = clean(markdown(facts, ws.name))  # again on the whole page: whatever markdown() itself adds is checked too
    end = f"Checked against {len(found):,} values of a sample of {SAMPLE:,} records: {hits:,} redacted."
    text += f"\n## Privacy check\n\n{end}\n"
    out = ws / "auto"
    out.mkdir(exist_ok=True)
    replace_text(out / "report.json", json.dumps({**facts, "privacy": dict(values=len(found), redacted=hits)}, ensure_ascii=False, indent=1))
    replace_text(out / "report.md", text)
    return dict(report=str(out / "report.md"), markdown=text, values=len(found), redacted=hits)


def cell(v: object, share: bool = False) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if share and isinstance(v, int | float):
        return f"{v:.1%}"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, list):
        return ", ".join(" + ".join(x) if isinstance(x, list) else cell(x) for x in v)
    if isinstance(v, dict):
        return " · ".join(f"{k} {cell(x)}" for k, x in v.items() if x not in (None, "", [], {}))
    return str(v).replace("|", "\\|").replace("\n", " ")


SHARES = frozenset({"filled", "looks_right", "top_value", "share", "chance_clean", "bound", "file", "rehearsal", "full", "family", "given", "address", "phone"})


def grid(rows: list[dict], cols: tuple[str, ...], shares: frozenset = SHARES) -> list[str]:  # a Markdown table; shares as percentages
    if not rows:
        return ["none", ""]
    return ["| " + " | ".join(c.replace("_", " ") for c in cols) + " |", "|" + "---|" * len(cols),
            *("| " + " | ".join(cell(x.get(c), c in shares) for c in cols) + " |" for x in rows), ""]


def trusted(t: dict | None) -> str:  # the trust line in words
    if not t:
        return "none: the method merges as tuned"
    line = "above every step" if t["line"] == "none" else f"{t['line']:g} bits"
    span = t.get("next")
    if not span:
        return f"{line}: nothing below it merges before people check"
    top = f" to {span['up_to']:g}" if span.get("up_to") is not None else " and up"
    return (f"{line}: nothing below it merges before people check; the next range, {span['down_to']:g}{top} bits: "
            f"{t['pairs']:,} pairs, {t['checked']:,} checked of {t['needed']:,} needed, {t['false']:,} false")


def said(c: dict) -> str:  # a change of method in words
    return "; ".join(f"add a pair key on {' + '.join(k)}" for k in c.get("add_keys", [])) or (f"accept from {c['line']:g} bits" if "line" in c else "") \
        or "leave out " + ", ".join([*(f"the rule {x}" for x in c.get("drop_rules", [])), *(f"the key {x}" for x in c.get("drop_keys", []))])


def markdown(f: dict, name: str) -> str:
    """The facts as a report to paste: what ran, each step, then each part of the work."""
    m, took = f["machine"], f.get("seconds", 0)
    out = ["# nayose auto mode", "", "No record's value: counts, shares, seconds, and the names of columns, fields, rules and keys.", "",
           f"- **When:** {f['at'].replace('T', ' ')} · took {int(took // 60)} min {took % 60:.0f} s",
           f"- **Code:** {m['code']} · python {m['python']} · duckdb {m['duckdb']} · splink {m['splink']} · {m['system']}",
           f"- **Machine:** {m['cores']} cores · {cell(m['memory_gb'])} GB memory" + (f" · --compute {' '.join(m['compute'])}" if m["compute"] else ""),
           f"- **File:** {', '.join(f['file']['formats'])} · {f['file']['files']:,} file{'s' * (f['file']['files'] > 1)} · {f['file']['bytes'] / 1e6:,.1f} MB"
           + (f" · {f['records']:,} records" if "records" in f else ""),
           f"- **Workspace:** {name}, strict (nothing merges before people check)", "", "## Steps", ""]
    out += [f"- {'✓' if x['ok'] else '✗'} {x['step']} · {x['seconds']:,.1f} s" + ("" if x["ok"] else f" · exit {x['exit']}: {x['error']}" + (f" · fix: {x['fix']}" if x.get("fix") else ""))
            for x in f["steps"]]
    if "fields" in f:
        out += ["", "## The file", "", "Columns:", "", *grid(f["columns"], ("column", "filled")),
                "Each column's script and the shares that look like each kind of value (a sample of 2,000 records):", "",
                *grid(f["profile"], ("column", "script", "full", "family", "given", "address", "phone", "same")),
                "Fields, as the workspace maps them:", "", *grid(f["fields"], ("field", "sources", "filled", "looks_right")),
                "Placed by auto mode (what the contents suggest):", "", *grid(f["placed"], ("feature", "column", "share", "why")),
                "Offered, a name in another script:", "", *grid(f["offers"], ("feature", "type", "script", "column", "share", "why")),
                f"Needed: {cell(f['needed'])}", "", f"Turned off: {cell(f['turned_off']) or 'nothing'}", "",
                f"The reader: {cell(f['read'])}", ""]
    if c := f.get("check"):
        out += ["## Will a run go through (check records)", "", f"Room: {cell(c['capacity'])}", "",
                f"Ready: {cell(c['ready']['ok'])}", "", *(f"- stop: {x['what']} · fix: {x['fix']}" for x in c["ready"]["stops"]),
                *(f"- look first: {x['what']} · fix: {x['fix']}" for x in c["ready"]["warns"]), "",
                *grid(c["keys"], ("key", "per_record", "largest_block", "oversized_blocks", "oversized_records")),
                *grid(c["fields"], ("field", "filled", "looks_right", "top_value", "columns")),
                *(f"- note: {cell(x)}" for x in c.get("notes") or []), ""]
    if h := f.get("rehearsal"):
        real = {x["step"]: x for x in f.get("run", {}).get("steps", [])}
        out += ["## The rehearsal, beside the real run", "",
                *grid([dict(what="records", rehearsal=h["records"], real=f.get("records")),
                       dict(what="seconds", rehearsal=h["seconds"], real=round(sum(x.get("seconds", 0) for x in real.values()), 1) if real else None),
                       dict(what="peak memory, GB", rehearsal=h["peak_memory_gb"], real=max((x.get("peak_memory_gb", 0) for x in real.values()), default=None)),
                       dict(what="peak spill, GB", rehearsal=h["peak_spill_gb"], real=None),
                       dict(what="pairs", rehearsal=h["pairs"], real=real.get("budget", {}).get("pairs"))], ("what", "rehearsal", "real"), frozenset()),
                f"Generating: {h['generate_seconds']:,.1f} s, peak {cell(h['generate_peak_gb'])} GB." + (f" Stopped: {h['error']} · fix: {h['fix']}" if h.get("error") else ""), "",
                *grid([dict(field=k, **v) for k, v in h["shape"].items()], ("field", "file", "rehearsal")), f"Its limit: {h['limit']}", ""]
    if run := f.get("run"):
        out += ["## The run (report.txt)", "", "```", run["report"].rstrip(), "```", ""]
    if mt := f.get("method"):
        out += ["## The method (describe method)", "",
                f"Line {mt['line']:g} bits · review from {mt['review_from']:g} · to decide {mt['to_decide']:,}", "", f"Trust line: {trusted(mt['trust'])}", "",
                "Pairs by weight:", "", *grid(mt["bands"], ("weight_from", "pairs", "accepted")),
                "Match rules:", "", *grid(mt["rules"], ("name", "pairs", "below", "different")),
                "Pair keys:", "", *grid(mt["keys"], ("name", "pairs", "seconds", "matched", "only")),
                "Comparison steps:", "", *grid(mt["steps"], ("comparison", "level", "bits", "reached")),
                "Proposed:", "", *grid([dict(change=said(x["change"]), why=x["why"]) for x in mt["proposals"]], ("change", "why")),
                f"Left out of the method: {cell(mt['dropped'])}", ""]
    if pt := f.get("patterns"):
        out += [f"## Patterns near the line ({pt['pairs']:,} pairs scored; the 15 largest from review to 4 bits above the line)", "",
                "merged: joined · wait: on the review sheet · held: in its band, not asked · apart: left apart", "",
                *grid([dict(x["steps"], **{k: x.get(k) for k in ("points", "pairs", "merged", "wait", "held", "apart")}) for x in pt["near"]],
                      (*pt["fields"], "points", "pairs", "merged", "wait", "held", "apart"), frozenset())]
    if f.get("trials"):
        out += ["## Changes tried (try method: both without people's decisions or the trust line)", ""]
        for x in f["trials"]:
            out += [f"**{said(x['change'])}** ({x['why']})", ""] + (
                grid([dict(what=k, base=x["base"].get(k), variant=x["variant"].get(k)) for k in ("matched", "expected_false", "rule_pairs", "entities", "missed")], ("what", "base", "variant"))
                + [f"Pairs of records it puts apart: {x['apart']:,} · together: {x['together']:,}", ""] if x["ok"] else ["it stopped: see Steps", ""])
    if o := f.get("with_offers"):
        out += ["## The names in another script, tried (a workspace of their own)", ""] + ([
            f"Added: {cell([f'{x['feature']} ({x['script']}) = {x['column']}' for x in o['added']])}", "",
            *grid([dict(what="candidates", without=o["candidates"]["without"], with_them=o["candidates"]["with_"]),
                   dict(what="matches no key lists (probe)", without=o["missed"]["without"], with_them=o["missed"]["with_"]),
                   dict(what="seconds", without=o["seconds"]["without"], with_them=o["seconds"]["with_"])], ("what", "without", "with_them")),
            "Pairs by range of the trust line:", "",
            *grid([dict(down_to=x["down_to"], up_to=x["up_to"], pairs_without=y.get("pairs") if y else None, pairs_with_them=x["pairs"],
                        expected_false_without=y.get("expected_false") if y else None, expected_false_with_them=x["expected_false"])
                   for x, y in zip(o["ranges"], (f.get("review") or {}).get("ranges") or [None] * len(o["ranges"]))],
                  ("down_to", "up_to", "pairs_without", "pairs_with_them", "expected_false_without", "expected_false_with_them"))]
            if o["ok"] else ["it stopped: see Steps", ""])
    if rv := f.get("review"):
        out += ["## How much people must check (describe review)", "",
                *grid(rv["ranges"], ("down_to", "up_to", "pairs", "sample", "expected_false", "chance_clean", "bound", "reviews_to_here")),
                f"Below the last step: {rv['below_last_step']:,} · no name compared: {rv['unnamed']:,} · spot-checks a round: {rv['watch']:,}", "",
                f"Kinds of record (the person/company sheet: decide, the flagged; measure, optional): {cell(rv['kinds'])}", "",
                f"Hours to review, if each pair takes {rv['seconds_per_pair']:g} s (an assumption): {cell(rv['hours'])}", ""]
    return "\n".join(out)
