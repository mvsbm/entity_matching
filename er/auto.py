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
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from er.generate import generate, load_reference, load_spec
from er.io import replace_text
from er.run import peak_gb
from er.settings import Settings, load_settings
from er.source import describe
from er.strings import connect

CHUNK = 50_000  # entities a generated part: generation's memory, whatever the file's size
PILOT = 5_000  # entities of a first, small draw: each field's share measured on it, then each rate set right
POLL = 0.5  # seconds between two readings of the spill folder's size
LIMIT = ("past 60,000 entities the generator's people repeat, so names repeat more than in a real file and name keys make more "
         "pairs: the real file's own pairs are in check records")


def shape(s: Settings, path: str | Path) -> dict:
    """The records at `path` and each field's share filled, under the mapping of `s`, from describe's one scan: counts
    and shares only, no value. O(N)."""
    d = describe(path, connect(s.compute)[0], s.columns, s.detect)
    return dict(records=d["records"], fields={f["field"]: round(f["filled"], 4) for f in d["fields"] if f["filled"]})


def generated(sh: dict, out: Path, emit: Callable[[dict], None]) -> int:
    """Parquet parts in `out` of a generated file of `sh`'s size and shape, under the project's mapping (the
    generator's own column names): about records ÷ 1.25 entities, CHUNK a part, each part with its own seed and the
    record IDs numbered on across the parts; each field's first column filled at the file's share (each rate measured
    on a small pilot draw, then set right), the company share from the file's company names; the columns of a field
    the file lacks, and every fallback column, left out, so a field's share is its first column's. The records
    written. O(N) time, O(CHUNK) memory."""
    s0 = load_settings()
    base, _ = load_spec(s0.root / "config" / "generator.toml")
    persons, companies, towns = load_reference(s0.paths["reference"])
    company = sh["fields"].get("company_name")
    share = min(max(company, 0.01), 0.99) if company else base.company_share
    of_kind = lambda c: 1 - share if c.kind == "person" else share if c.kind == "company" else 1.0
    columns = {c.name: c for c in base.columns}
    first = {f: alts[0][0] for f, alts in s0.columns.items() if alts and alts[0] and alts[0][0] in columns}
    target = {first[f]: sh["fields"][f] for f in sorted(sh["fields"], key=lambda f: -len(s0.columns.get(f, ())))  # a column several fields read
              if f in first and columns[first[f]].nullable and not columns[first[f]].parts}  # first: the share of the one it alone makes
    rate = {c: min(1.0, v / of_kind(columns[c])) for c, v in target.items()}
    keep = {c for f in sh["fields"] for c in (s0.columns.get(f) or ((),))[0]} | {s0.data.unique_id}  # a field's first columns: its share is theirs
    unused = {c for alts in s0.columns.values() for alt in alts for c in alt} - keep
    with_rates = lambda r: replace(base, company_share=share, columns=tuple(replace(c, rate=r[c.name]) if c.name in r else c for c in base.columns))
    entities, uid, records = max(1, round(sh["records"] / (1 + base.dup_lambda))), s0.data.unique_id, 0
    pilot = generate(replace(with_rates(rate), entities=min(PILOT, entities), seed=base.seed + 10_000), persons, companies, towns).df
    filled = lambda c: float((pilot[c].notna() & pilot[c].astype("string").str.strip().ne("")).mean())  # a share as the file's is read
    rate = {c: min(1.0, r * target[c] / got) if (got := filled(c)) else r for c, r in rate.items()}  # measured on a pilot, then set right
    spec = with_rates(rate)
    out.mkdir(parents=True, exist_ok=True)
    for i, start in enumerate(range(0, entities, CHUNK)):
        g = generate(replace(spec, entities=min(CHUNK, entities - start), seed=base.seed + i), persons, companies, towns)
        df = g.df.drop(columns=[c for c in unused if c in g.df.columns])
        width = len(df[uid].iloc[0])
        df[uid] = [f"{records + j + 1:0{width}d}" for j in range(len(df))]  # one ID per record across the parts
        df.to_parquet(out / f"part-{i:05d}.parquet", index=False)
        records += len(df)
        emit(dict(step="generate", records=records, seconds=0.0))
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
    and --compute): the generated file in ws/rehearsal/, run there in a process of its own, measured, then both
    removed; the result kept in ws/rehearsal.json. Its seconds (generating, and each step of the run), peak memory,
    peak spill, the pairs the run listed, the generated shape beside the file's, and what went wrong if the run
    stopped (an out-of-memory or a full disk: the real file would stop there too)."""
    root, t = ws / "rehearsal", time.perf_counter()
    shutil.rmtree(root, ignore_errors=True)
    records = generated(sh, root / "records", emit)
    made, made_seconds, made_gb = shape(load_settings(), root / "records"), round(time.perf_counter() - t, 1), peak_gb()  # this process's, before the run's own
    temp = Path(connect(s.compute)[0].execute("SELECT current_setting('temp_directory')").fetchall()[0][0])
    spill = temp / f"rehearsal-{os.getpid()}"  # on the disk a real run spills to, and only this run's
    spill.mkdir(mode=0o700, parents=True, exist_ok=True)
    limits = [f"{k}={v}" for k, v in {**s.compute, "temp_directory": str(spill)}.items() if v not in ("", None)]
    child = subprocess.Popen([sys.executable, "-m", "er.cli", "resolve", "records", str(root / "records"), "--workspace", str(root / "run"),
                              "--format", "json", "--compute", *limits, *(["--pipeline", str(pipeline)] if pipeline else [])],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    events: list[dict] = []

    def read() -> None:  # the run's steps, passed on as they end: progress while it runs
        for line in child.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            events.append(e)
            if e.get("event") == "step":
                emit(dict(step=f"rehearse {e['step']}", seconds=e.get("seconds", 0.0)))
    reader, peak = threading.Thread(target=read, daemon=True), 0
    reader.start()
    while child.poll() is None:
        peak = max(peak, size_of(spill))
        time.sleep(POLL)
    reader.join(30)
    steps = [e for e in events if e.get("event") == "step"]
    last = events[-1] if events else {}
    result = dict(ok=child.returncode == 0, records=records, generate_seconds=made_seconds, generate_peak_gb=made_gb,
                  seconds=round(sum(x.get("seconds", 0.0) for x in steps), 1), steps={x["step"]: x.get("seconds") for x in steps},
                  peak_memory_gb=max((x.get("peak_memory_gb", 0.0) for x in steps), default=None), peak_spill_gb=round(peak / 2**30, 2),
                  pairs=next((x.get("pairs") for x in steps if x["step"] == "budget"), None),
                  shape={f: dict(file=v, rehearsal=made["fields"].get(f)) for f, v in sh["fields"].items()},
                  error=last.get("error") if child.returncode else None, fix=last.get("fix") if child.returncode else None, limit=LIMIT)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(spill, ignore_errors=True)
    replace_text(ws / "rehearsal.json", json.dumps(result, ensure_ascii=False, indent=1))
    return result
