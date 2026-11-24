"""Step 1, load: the records file read, what can't be resolved set aside, every record standardized (and its kind
told), placeholders read as missing. O(N·L).

Reads the file (er.source: Parquet, as er.intake read it); with `stored` (an increment), that table of the run's
records too. Writes the table `into` (records, or new_records), set_aside, and er_sample (er.source.suggest's)."""
import collections
import concurrent.futures
import contextlib
import functools
import math
import multiprocessing
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from er.config import InputError, Pipeline, lit, q
from er.kind import KIND_COLUMNS, NAME_MODEL, classifier as kind_classifier
from er.match import ELSE, compared_exactly
from er.report import unmapped_columns
from er.settings import fit_to_file, present_fields
from er.source import file_facts, filled, open_source, suggest
from er.standardize import prepare
from er.steps.job import Job

CHUNK_ROWS = 200_000  # records standardized at a time, each chunk in a process of its own
CROWD = 64        # the fewest customers a compared field's placeholder is held by, however small the budget's oversized blocks
SPREAD = 10       # a placeholder is held by this many times the field's records per value, or more


@dataclass
class Loaded:
    n: int                                    # the records loaded (0: none left, an increment's batch already in the run)
    pipeline: Pipeline                        # the method as this file's fields let it run (settings.fit_to_file)
    disabled: list[str]                       # what of the method it can't run, for lack of a field
    present: dict                             # each field the file holds, and the source columns it is built from
    unmapped: pd.DataFrame | None             # the file's columns no field reads, on a sample (report.unmapped_columns)
    classifier: object | None                 # each record's kind, person or company (er.kind); None: the method doesn't ask
    inputs: list[dict]                        # the files read: path, bytes, SHA-256 (steps.json)
    placeholders: dict[str, list[str]] = field(default_factory=dict)  # each field's values read as missing (placeholders)


def ahead(pool: concurrent.futures.Executor, f: Callable, items: Iterable, most: int) -> Iterator:
    """f of each item, in order, computed in `pool` at most `most` items ahead: memory holds a few, whatever the count.
    Whatever stops it (an item's error, or the reader's) cancels the items not started, instead of waiting them out."""
    waiting: collections.deque = collections.deque()
    try:
        for item in items:
            waiting.append(pool.submit(f, item))
            if len(waiting) >= most:
                yield waiting.popleft().result()
        while waiting:
            yield waiting.popleft().result()
    finally:
        for w in waiting:
            w.cancel()


def load(job: Job, path: str | Path, *, model: dict | None = None, into: str = "records", stored: str | None = None) -> Loaded:
    """Read the file through er.source (Parquet; columns matched to config/settings.toml [columns]); check its fields
    against the method's [fields]; set aside what can't be resolved (set_aside); standardize each chunk with
    er.standardize.prepare (each record on its own, so chunking changes nothing) into the table `into`. `model`: a
    fitted model, which must compare what this file lets the method compare. `stored` (an increment): the run's
    records, read as the batch's are, and not read again. The placeholders of a full run are found here; an
    increment's, once its batch joins the run's records (placeholders). CHUNK_ROWS records are cleaned at a time."""
    t, engine, s, log, chunk_rows = time.perf_counter(), job.engine, job.settings, job.log, CHUNK_ROWS
    src = open_source(path, engine, {c for f, alts in s.columns.items() if f != "entity" for alt in alts for c in alt},
                      reserved={*s.columns, *KIND_COLUMNS, "cluster_id", "resolved_stage", "resolved_by", "er_file", "er_path", "er_first"})
    log.notes[:], inputs = list(src.notes), file_facts(src.files, "records")
    present = present_fields(s, src.columns)
    hints = suggest(src, engine, [f for f in s.columns if f not in present and f != "entity"], s.detect)
    mapped = {c for alts in s.columns.values() for alt in alts for c in alt}
    unmapped = unmapped_columns(engine, "er_sample", [c for c in src.columns if c not in mapped], list(s.columns), s.detect).assign(
        column=lambda d: d["column"].map(lambda c: src.given.get(c, c)))  # on suggest's sample: by the names the file gives them
    needed = job.pipeline.fields.needed()
    hints = {f: (src.given.get(c, c), share, why) for f, (c, share, why) in hints.items() if share >= (0.99 if f == "id" else 0.5) and f in needed}  # a likely column, by the name it has in the file
    extra = _lacks(job, stored, src.columns) if stored else []  # an increment's batch is read as the run read its records
    try:
        pipeline, disabled = fit_to_file(job.pipeline, s, [*src.columns, *extra])
    except InputError as e:
        raise InputError(f"{e}. The file's columns: {', '.join(src.given.get(c, c) for c in src.columns)}", e.fix + (
            ". Suggested from the file's values, check them first:\n  [columns]" + "".join(
                f"\n  {f} = \"{c}\"   # {why}" for f, (c, _, why) in hints.items()) if hints else ""),
            hints={f: c for f, (c, _, _) in hints.items()}) from None
    log.notes += [f"no column for {f}; {c} may be it ({why})" for f, (c, share, why) in hints.items() if share > 0.5]
    if model is not None:  # a given model must compare exactly what this file's fields let the method compare
        fitted = {(c["output_column_name"], lv["label_for_charts"]) for c in model["comparisons"]
                  for lv in c["comparison_levels"] if not lv.get("is_null_level")}
        here = {(c.name, label) for c in pipeline.fs.model.comparisons for label in (*(lv.label for lv in c.levels), ELSE)}
        if fitted != here:
            raise InputError(f"{path}: the model was fitted on other comparison levels (only in the model: {sorted(fitted - here)}; "
                             f"only here: {sorted(here - fitted)})", fix="run without --model: the run then fits its model on this file")
    loaded = Loaded(n=0, pipeline=pipeline, disabled=disabled, present=present, unmapped=unmapped, classifier=None, inputs=inputs)
    rows = _set_aside(job, src.sql, stored)
    engine.run(f"DROP TABLE IF EXISTS {into}")
    if not job.count(rows):
        if stored is None and not job.count(src.sql):
            raise InputError(f"{path}: holds no record, only its header", fix="give the file with its records")
        if stored is None:
            raise InputError(f"{path}: no record left to resolve ({'; '.join(log.notes)})", fix="give the records IDs, one per record")
        return loaded
    fs, rules, spec = pipeline.fs, pipeline.rules, pipeline.kind
    if spec and spec.name_field in present:
        loaded.classifier = kind_classifier(s, spec)
        loaded.inputs += file_facts([s.root / NAME_MODEL], "name model")
    home = pipeline.household  # the label's fields: made with the rest
    normalized, used = [*rules.normalized(), *fs.normalized(), *home.normalized()], rules.used() | fs.used() | home.used()
    total, done = job.count(rows), 0
    if log.told:
        log.told(0, total, "records")
    reads = {job.uid, *(c for d in fs.standardize.derived for cols in d.sources for c in cols), *used}  # what cleaning reads: a wide file's other columns never enter the run
    cols = ", ".join([*(q(c) for c, *_ in engine.columns(rows) if c in reads), *(f"NULL::VARCHAR AS {q(c)}" for c in extra)])
    reader = engine.batches(f"SELECT {cols} FROM {rows}", chunk_rows)  # its own cursor: inserts go on alongside
    workers = min(-(-total // chunk_rows), engine.threads(), os.cpu_count() or 1,
                  61 if sys.platform == "win32" else 1 << 20)  # Windows waits on at most 61 processes
    batches = (batch.to_pandas().astype("string") for batch in reader)
    clean = functools.partial(prepare, fs.standardize, normalized=normalized, used=used, kind=loaded.classifier)
    # spawned on every system: a fork of this process, its DuckDB threads running, may deadlock (Linux before 3.14)
    with (concurrent.futures.ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) if workers > 1
          else contextlib.nullcontext()) as pool:
        # each chunk cleaned on its own (every step reads one record, or one chunk's values), so in parallel processes
        # the same records, taken back in order
        for i, chunk in enumerate(ahead(pool, clean, batches, workers + 1) if pool else map(clean, batches)):
            engine.register("er_chunk", chunk)
            engine.run(f"CREATE TABLE {into} AS SELECT * FROM er_chunk" if i == 0 else f"INSERT INTO {into} SELECT * FROM er_chunk")
            engine.unregister("er_chunk")
            done += len(chunk)
            if log.told:
                log.told(done, total, "records")
    engine.run("DROP TABLE IF EXISTS er_in")  # the file kept once, read: a copy of it no step reads again
    loaded.n = job.count(into)
    if stored is None:  # an increment's batch: read as missing with the run's records (jobs.update)
        loaded.placeholders = placeholders(job, pipeline, into, {})
    kinds = {}
    if loaded.classifier is not None:  # how many records each kind holds
        kinds = dict(engine.rows(f"SELECT kind, count(*) FROM {into} GROUP BY 1"))
        kinds = {"companies": kinds.get(2, 0), "persons": kinds.get(1, 0), "not sure": kinds.get(0, 0), "flagged": job.count(f"{into} WHERE kind_flagged")}
    log.done("load", "O(N·L)", f"O({loaded.n:,}·L)", t, records=loaded.n, disabled=len(disabled), set_aside=job.count("set_aside"), **kinds)
    return loaded


def _lacks(job: Job, stored: str, columns: list[str]) -> list[str]:
    """The columns an increment's batch reads as missing: the first source of each optional field the run's records
    hold and the batch doesn't (a file without its birth dates), so it is read, prepared and compared as the run's
    were. Never a column a field the run needs reads: a batch without its IDs or names is refused, as a file is."""
    s = job.settings
    fields, have, given = job.pipeline.fields, job.columns(stored), present_fields(s, columns)
    needed = {c for f in fields.needed() for alt in s.columns.get(f, ()) for c in alt}
    return list(dict.fromkeys(c for f, alts in s.columns.items() if f in fields.optional and f in have and f not in given
                              for c in alts[0] if c not in columns and c not in needed))


def placeholders(job: Job, pipeline: Pipeline, table: str, known: dict[str, list[str]], also: tuple[str, ...] = ()) -> dict[str, list[str]]:
    """Values read as missing, each a placeholder (00000000, a dummy name) and not one entity's nor evidence:
    - of an identifying field ([fields] identifying: one entity's each, as a customer ID), each held by
      min_oversized() records or more;
    - of a field a comparison's first level tests for equality, each held by min_oversized() and CROWD customers or more (copies
      of one customer's record are no crowd; a record without an identifying value is a customer of its own) whose
      pairs outnumber those of all the values held by fewer: the exact level's u would describe it, not the field.
    With those the run already read as missing (`known`), made missing first, so a batch's count is of what is new.
    Each is made missing in `table` and `also`, in the field, every copy of it, and every field built from the same
    columns on those records (a name read into person_name, full_name and any_name), so no rule, key, comparison or
    probe reads it as two records agreeing. Returns them all, `known`'s first. O(N): a group-by and an update per field."""
    engine, log, uid = job.engine, job.log, job.uid
    out = dict(known)
    m, cols = pipeline.fs.budget.min_oversized(), job.columns(table)
    ids = set(pipeline.fields.identifying)
    sources = {d.name: {c for alt in d.sources for c in alt} for d in job.settings.standardize.derived}

    def blank(values: list[str], f: str) -> None:
        fields = [f, *(d for d, cs in sources.items() if d != f and cs & sources.get(f, set()))]
        for t in (table, *also):
            copies = [c for c in job.columns(t) if any(c == x or c.startswith(f"{x}__") for x in fields)]
            engine.run(f"UPDATE {t} SET {', '.join(f'{q(c)} = NULL' for c in copies)} WHERE {q(f)} IN ({', '.join(map(lit, values))})")
    crowd = max(m, CROWD)
    for f in (f for f in dict.fromkeys([*(x for x in compared_exactly(pipeline.fs.model) if x not in ids), *ids]) if f in cols):  # identifying last: copies of one customer's record still share its ID when the others are counted
        if before := out.get(f, []):
            blank(before, f)
        who = f"coalesce({q(next((x for x in pipeline.fields.identifying if x in cols and x != f), uid))}, {q(uid)})"
        filled_n, distinct = engine.row(f"SELECT count({q(f)}), count(DISTINCT {q(f)}) FROM {table}")
        at = max(m, math.ceil(SPREAD * filled_n / max(distinct, 1)))  # far past the field's own records per value: a 4-digit phone's values are no crowd however many records hold each
        held = engine.rows(f"SELECT {q(f)}, count(*) FROM {table} WHERE {q(f)} IS NOT NULL GROUP BY 1 HAVING count(*) >= {at}"
                           f"{'' if f in ids else f' AND count(DISTINCT {who}) >= {crowd}'} ORDER BY count(*) DESC, 1")
        if f not in ids and held:  # a compared field: a crowd whose pairs outnumber all the others' (two placeholders never hide each other)
            every = engine.value(f"SELECT coalesce(sum(c * (c - 1) // 2), 0) FROM (SELECT count(*) AS c FROM {table} WHERE {q(f)} IS NOT NULL GROUP BY {q(f)})")
            rest = every - sum(c * (c - 1) // 2 for _, c in held)
            new = [v for v, c in held if c * (c - 1) // 2 > rest]
        else:
            new = [v for v, _ in held]
        if not new:
            continue
        blank(new, f)
        n = engine.value(f"SELECT count(*) FROM {table} WHERE {q(f)} IS NULL")
        log.notes.append(f"{f}: {len(new):,} value{'s' if len(new) > 1 else ''} held by {at:,}+ records read as missing, a placeholder and not "
                         f"{'one entity' if f in ids else 'evidence'}'s ({n:,} records without one)" + ("; pairs the run joined on it before stay until a full run" if also else ""))
        log.examples.append(f"{f} = {new[0]}: a placeholder, read as missing")
        out[f] = [*before, *new]
    return out


def _set_aside(job: Job, src: str, stored: str | None) -> str:
    """The records a run can resolve. Rows identical in every column are kept once. Set aside, with the reason, in
    the table set_aside (written to set_aside/, to be fixed and added by an increment): a record without an ID;
    every record of an ID that holds different content; with `stored` (an increment), a record already in the run.
    O(N) to count; the rest only when something is off."""
    engine, log, u = job.engine, job.log, q(job.uid)
    blank, known = f"NOT {filled(job.uid)}", f"{u} IN (SELECT {u} FROM {stored})" if stored else "FALSE"  # blank as describe reads it
    n, ids, empty, clash = engine.row(f"""SELECT count(*), count(DISTINCT {u}), count(*) FILTER (WHERE {blank}),
        count(*) FILTER (WHERE {known}) FROM {src}""")
    engine.run(f"CREATE OR REPLACE TABLE set_aside AS SELECT *, ''::VARCHAR AS reason FROM {src} WHERE FALSE")
    if n and empty == n:
        raise InputError(f"no record has an ID in column {job.uid}", fix="map id in config/settings.toml [columns] to the column holding each record's ID")
    if not empty and ids == n and not clash:
        return src
    engine.run(f"CREATE OR REPLACE TABLE er_in AS SELECT DISTINCT * FROM {src}")
    if (kept := job.count("er_in")) < n:
        log.notes.append(f"{n - kept:,} rows identical to another in every column, kept once")
    engine.run(f"""INSERT INTO set_aside SELECT *, CASE WHEN {blank} THEN 'no ID' WHEN {known} THEN 'already in the run'
            ELSE 'the same ID with different content' END FROM er_in
        WHERE {blank} OR {known} OR {u} IN (SELECT {u} FROM er_in GROUP BY {u} HAVING count(*) > 1)""")
    log.notes += [f"{k:,} records set aside: {reason}" for reason, k in engine.rows("SELECT reason, count(*) FROM set_aside GROUP BY 1 ORDER BY 1")]
    return f"(SELECT * FROM er_in WHERE NOT ({blank}) AND {u} NOT IN (SELECT {u} FROM set_aside WHERE {u} IS NOT NULL))"
