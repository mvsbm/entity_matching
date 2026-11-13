"""Look up: one record against a workspace's run, in well under a second, whatever the number of records stored; and
search: the stored records whose values start with what a person typed, in any field, as they type.

build() reads the written run once (state/records, already standardized; gold; the model it scored with) and writes
<workspace>/index/: a DuckDB database holding every key of every record and every searched value, each table sorted by
its key in row groups small enough that a lookup reads little of it; a second database of what changed since, empty
when built; the person/company classifier's fitted part; and manifest.json, which names them and what they rest on.
update() writes the second again after a change to the run: the records added since the build, with every key and
value of theirs, and the records whose entity or rule cluster moved; anything else changed builds the index again.
look_up() prepares a record as a run prepares one, looks each of its keys up, gates an oversized block as a run does,
scores the candidates with the run's model and groups them by entity. search() reads each value typed by its prefix
and scores the records that share the most. Neither writes.

    build      O(N·(G + R + D·L + F) + N log N)   every key of every record, hashed, sorted: DuckDB, in parallel
    update     O(Δ·(G + R + D·L + F) + N)         the records added since the build; one narrow pass for what moved
    look_up    O(G·(log N + b) + C·K·L²)          N only in log N: a key's rows are a few row groups of its sorted table
    search     O(F·(log N + CAP) + SCORED·K·L²)

N stored records, Δ added since the build, G generators, R rules, D deletion generators, F searched columns, L a
value's length, b a block's size, C candidates, K comparisons. A lookup lists the pairs an increment of that one record
lists (er.candidates) and scores them as er.match.score_fs scores them with the run's model; an increment, unlike it,
counts u again on every record.
"""
from importlib.metadata import version
import contextlib
import hashlib
import json
import os
import pickle
import re
import secrets
import shutil
import threading
import time
from dataclasses import replace
import unicodedata
from bisect import bisect_left
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from er import folder
from er.candidates import deletions_sql
from er.config import DeletionKeys, InputError, KeyBlocker, Pipeline, SortedNeighbourhood, generator, lit, q
from er.intake import tidy
from er.io import read_parquet
from er.kind import Classifier, classifier, merge_answers, name_model
from er.match import levels, read_by, review_floor, scaled_prior
from er.report import run_model
from er.run import run_config
from er.settings import COLUMNS, Settings, fit_to_file, present_fields
from er.standardize import KATAKANA, SEPARATORS, prepare
from er.strings import connect

INDEX = "index"
SPARSE = 1024  # a sorted generator keeps every this many keys apart: a bisect there, then one read of at most this many rows
ROWS = 2048  # a row group's rows in the records' database: a lookup reads whole row groups of each column it fetches, so small ones read little
SHOWN = ("full_name", "person_name", "company_name", "address", "postal_code", "phone", "birth_date", "customer_id")  # a record, as a person reads it
SEARCHED = {"any_name": "name", "given_name__kana_fold": "name", "address__address": "address", "postal_code": "postal_code", "phone": "phone",
            "customer_id": "customer_id", "birth_date": "birth_date", "address_code": "address_code"}  # shortcut: the columns config/final.toml's standardizing writes that a search reads by prefix, each with its field; another method's are added here
REVERSED = ("any_name",)  # also read by its end: a given name typed alone, the family name before it
DIGITS = ("phone", "postal_code", "customer_id")  # fields held as digits: what a person writes between them (_typed), as the project's mapping drops it
CAP = 2000  # shortcut: a value typed that starts this many records or more is too common to list whole: said, its first by value listed; raise it as scoring gets faster
COUNTED = 100_000  # shortcut: a value that common is counted this far (said "100,000+"), so a first keystroke reads a bounded range; raise it if people need the exact count
SCORED = 500  # shortcut: the records scored for a search, those sharing the most values typed; raise it as scoring gets faster
REBUILD = 0.1  # shortcut: the records added since the build reaching this share of it build it again, so the delta stays small; lower it if lookups slow
OPEN = 2  # shortcut: the indexes kept open, each with its DuckDB connection and classifier, for a server's next lookup; raise it when people look up in more workspaces at once
QUERY = "\x7flookup"  # the ID of a record typed in: no record's, and after every one in order
LAST = chr(0x10FFFF)  # after every character: a prefix's range ends at it
MOVES = ("gold.parquet", "state/rule_clusters.parquet", "state/scoring.json", "state/placeholders.json", folder.METHOD)  # what a delta carries: entities, rules' clusters, the u an increment counts again, the values read as missing, merging conditions
INDEXING = hashlib.sha256(b"".join((Path(__file__).parent / f"{m}.py").read_bytes() for m in ("index", "candidates", "config", "standardize", "match", "kind"))
                          + duckdb.__version__.encode() + version("scikit-learn").encode()).hexdigest()[:12]  # what reads and writes an index (kind.pkl pickles a scikit-learn model): another version builds it again

_OPENED: dict[str, tuple] = {}  # bounded: OPEN workspaces, the oldest dropped; each its manifest, connection, classifier and the classifier's lock
_OPENING = threading.Lock()


def _stamp(ws: Path) -> dict[str, list[int]]:  # what an index rests on: each file of the run, the method and the mapping, by size and time
    files = [*sorted((ws / "state" / "records").glob("part-*.parquet")), ws / "gold.parquet", ws / "state" / "scoring.json", ws / "state" / "placeholders.json", ws / "state" / "model.json",
             ws / "state" / "config.txt", ws / "state" / "rule_clusters.parquet", ws / folder.METHOD, ws / COLUMNS, *folder.answer_parts(ws)]
    return {f.relative_to(ws).as_posix(): [f.stat().st_size, f.stat().st_mtime_ns] for f in files if f.exists()}


def _pipeline(ws: Path, s: Settings, p: Pipeline, columns: list[str]) -> Pipeline:  # the pipeline the run ran, fitted to its records' columns
    config = ws / "state" / "config.txt"
    if config.exists() and config.read_text(encoding="utf-8") != run_config(p, s):
        raise InputError(f"the pipeline or the column mapping changed since the run in {ws}: its records would be looked up otherwise",
                         fix=f"run it again first: nayose rerun records --workspace {ws}")
    return fitted(ws, s, p, columns)


def fitted(ws: Path, s: Settings, p: Pipeline, columns: list[str]) -> Pipeline:  # the pipeline fitted to a run's stored records, keys as it listed by
    folded = {c.casefold() for c in columns}  # a source column named as its field but for case (BIRTH_DATE) gave way to it (standardize.prepare)
    p = fit_to_file(p, s, [*columns, *(c for alts in s.columns.values() for alt in alts for c in alt if c not in columns and c.casefold() in folded)])[0]
    kept = ws / "state" / "keys.json"  # the keys the run listed by, learned or left after dropping idle ones (er.keys)
    if kept.exists():
        p = replace(p, fs=replace(p.fs, blockers=tuple(generator(n, d, s.chains) for n, d in json.loads(kept.read_text(encoding="utf-8")).items())))
    return p


def _scorable(ws: Path) -> dict:  # the run's model, refused if a lookup can't score as it does
    model = run_model(ws)
    if model["er"]["tf"]:
        raise InputError(f"the model of the run in {ws} adjusts levels by term frequency, which a lookup doesn't",
                         fix="index a run of config/final.toml's method, which adjusts none")
    return model


def _tables(p: Pipeline) -> list[tuple[str, object]]:  # each index table of keys, by name: its generator or (stage, rule)
    return [*((f"g{i}", b) for i, b in enumerate(p.fs.blockers) if isinstance(b, (KeyBlocker, DeletionKeys, SortedNeighbourhood))),
            *((f"r{i}", (st, rule)) for i, st, rule in p.rules.each() if st.keys(rule))]


def _hashed(x: object, side: str = "") -> str:  # the SQL of a table's key hash, on columns aliased `side`
    if isinstance(x, KeyBlocker):
        return f"hash({', '.join(side + q(k.name) for k in x.keys)})"
    if isinstance(x, DeletionKeys):
        return f"hash(__dk, {', '.join(side + q(w.name) for w in x.within)})" if x.within else "hash(__dk)"
    st, rule = x
    return f"hash({', '.join(side + q(c) for c in st.keys(rule))})"


def _filled(cols: list[str]) -> str:
    return " AND ".join(f"{q(c)} IS NOT NULL" for c in cols)


def _keys(x: object) -> list[str]:  # the columns a table's rows must all hold
    if isinstance(x, KeyBlocker):
        return [k.name for k in x.keys]
    if isinstance(x, (DeletionKeys, SortedNeighbourhood)):
        return [x.key.name, *(w.name for w in getattr(x, "within", ()))]
    st, rule = x
    return list(st.keys(rule))


def _rows(x: object, table: str, uid: str) -> str:  # the rows a table of keys holds, from records in `table`: the key's hash, the uid
    u = q(uid)
    if isinstance(x, DeletionKeys):
        within = ", ".join(q(w.name) for w in x.within)
        return (f"SELECT {_hashed(x)} AS h, {u} AS uid FROM (SELECT {u}{', ' + within if within else ''}, "
                f"unnest({deletions_sql(q(x.key.name))}) AS __dk FROM {table} WHERE {_filled(_keys(x))})")
    return f"SELECT {_hashed(x)} AS h, {u} AS uid FROM {table} WHERE {_filled(_keys(x))}"


def _entities(ws: Path, uid: str) -> str:  # each record's entity, and whether the rules joined it to another, as the run holds them now
    u = q(uid)
    return (f"(SELECT g.{u}, g.cluster_id AS entity, coalesce(c.n >= 2, FALSE) AS resolved FROM read_parquet({lit(ws / 'gold.parquet')}) g LEFT JOIN "
            f"(SELECT {u}, count(*) OVER (PARTITION BY cluster_id) AS n FROM read_parquet({lit(ws / 'state' / 'rule_clusters.parquet')})) c USING ({u}))")


def _write(con: duckdb.DuckDBPyConnection, into: str, src: str, p: Pipeline, ws: Path, uid: str, searched: list[str], records: str | None = None) -> dict[str, list]:
    """The index's tables in the database `into`, of the records in `src`: the records (each with its entity and whether
    the rules joined it; in the database `records`, else `into`), each key's (hash, uid), each window's (pos, key, uid)
    with every SPARSE-th, each searched column's (value, uid), each sorted. Each table's [rows, seconds]."""
    u, jobs, records = q(uid), {}, records or into
    jobs["records"] = [f"CREATE TABLE {records}.records AS SELECT hash(s.{u}) AS h, s.*, e.entity, coalesce(e.resolved, FALSE) AS resolved "
                       f"FROM {src} s LEFT JOIN {_entities(ws, uid)} e USING ({u}) ORDER BY h"]
    for name, x in _tables(p):
        if isinstance(x, SortedNeighbourhood):  # positions in the run's own window order: key, then uid
            k = q(x.key.name)
            jobs[name] = [f"CREATE TABLE {into}.{name} AS SELECT row_number() OVER (ORDER BY {k}, {u}) AS pos, {k} AS key, {u} AS uid FROM {src} WHERE {k} IS NOT NULL ORDER BY pos",
                          f"CREATE TABLE {into}.{name}_sparse AS SELECT pos, key, uid FROM {into}.{name} WHERE (pos - 1) % {SPARSE} = 0 ORDER BY pos"]
        else:
            jobs[name] = [f"CREATE TABLE {into}.{name} AS {_rows(x, src, uid)} ORDER BY h"]
    for c in searched:
        for t, v in ((f"f_{c}", q(c)), *(((f"f_{c}_reverse", f"reverse({q(c)})"),) if c in REVERSED else ())):
            jobs[t] = [f"CREATE TABLE {into}.{q(t)} AS SELECT {v} AS v, {u} AS uid FROM {src} WHERE {q(c)} IS NOT NULL ORDER BY v"]

    made = {}
    for name, sqls in jobs.items():
        t = time.perf_counter()
        for sql in sqls:
            con.execute(sql)
        made[name] = [con.execute(f"SELECT count(*) FROM {records if name == 'records' else into}.{q(name)}").fetchall()[0][0], round(time.perf_counter() - t, 3)]
    return made


def _scratch(ws: Path) -> Path:  # a folder of this process's in the index's, for files written before they are moved into place
    tmp = ws / INDEX / f".build-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    return tmp


def _publish(ws: Path, tmp: Path, m: dict) -> None:
    """The files in `tmp` moved into the index, then its manifest, which names them; then the files it doesn't name
    removed (one held open on Windows, at a later write). A reader open on them reads on; one about to open them, from
    the manifest before, reads the new one (_open)."""
    dest = ws / INDEX
    for f in tmp.iterdir():
        os.replace(f, dest / f.name)
    (tmp / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp / "manifest.json", dest / "manifest.json")
    keep = {"manifest.json", *(f for f in m["files"].values() if f)}
    for f in dest.iterdir():
        if f.is_file() and f.name not in keep:
            with contextlib.suppress(OSError):
                f.unlink()


def build(ws: Path, s: Settings, p: Pipeline) -> dict:
    """The index of the run in `ws`, written to ws/index/ under the workspace's lock: its files written aside, then
    moved into place and named by a new manifest, so one cut short leaves the last whole. O(N·(G + R + D·L + F) + N log N)."""
    ws = Path(ws)
    with folder.run_lock(ws):
        folder.finish_writes(ws)
        return _build(ws, s, p, _stamp(ws))


def _build(ws: Path, s: Settings, p: Pipeline, stamp: dict) -> dict:
    t0, uid = time.perf_counter(), s.data.unique_id
    parts = sorted((ws / "state" / "records").glob("part-*.parquet"))
    if not parts or not (ws / "gold.parquet").exists():
        raise InputError(f"{ws} holds no run to index", fix=f"find matches first: nayose resolve records <file> --workspace {ws}")
    src = f"read_parquet([{', '.join(lit(x) for x in parts)}], union_by_name = true)"
    have = list(dict.fromkeys(c for f in parts for c in pq.read_schema(f).names))  # as union_by_name orders them
    fitted, model = _pipeline(ws, s, p, have), _scorable(ws)
    tables, searched = _tables(fitted), [c for c in SEARCHED if c in have]
    reads = {uid, *read_by(model), *(c for _, x in tables for c in _keys(x)), *(c for c in SHOWN if c in have), *searched,
             *(c for _, x in tables if isinstance(x, tuple) for c in _rule_reads(x, have))}
    con, _ = connect(s.compute)
    tmp, key = _scratch(ws), secrets.token_hex(6)
    try:
        con.execute(f"ATTACH {lit(tmp / f'{key}.duckdb')} AS ix")
        con.execute(f"ATTACH {lit(tmp / f'{key}.records.duckdb')} AS ixr (ROW_GROUP_SIZE {ROWS})")
        con.execute(f"ATTACH {lit(tmp / f'{key}-0.duckdb')} AS dx (ROW_GROUP_SIZE {ROWS})")
        t = time.perf_counter()
        con.execute(f"CREATE TEMP TABLE src AS SELECT {', '.join(q(c) for c in have if c in reads)} FROM {src}")  # read once: every table reads it
        made = {"read": [None, round(time.perf_counter() - t, 3)], **_write(con, "ix", "src", fitted, ws, uid, searched, records="ixr")}
        _write(con, "dx", "(SELECT * FROM src LIMIT 0)", fitted, ws, uid, searched)  # what changed since: nothing yet
        con.execute(f"CREATE TABLE dx.moved AS SELECT {q(uid)}, entity, resolved FROM ixr.records LIMIT 0")
        for db in ("ix", "ixr", "dx"):
            con.execute(f"DETACH {db}")
        spec, kind = fitted.kind, None
        if spec and spec.name_field in present_fields(s, have):  # its fitted part: the name model, which holds a connection, is loaded again by a lookup
            answers = [read_parquet(f).astype({uid: "string"}) for f in folder.answer_parts(ws)]
            c = classifier(s, spec, merge_answers(pd.concat(answers, ignore_index=True) if answers else None, None, uid))
            (tmp / (kind := f"{key}.kind.pkl")).write_bytes(pickle.dumps({k: v for k, v in vars(c).items() if k != "names"}))
        of = {n: f"rule {x[1].name}" if isinstance(x, tuple) else x.name for n, x in tables} | {f"f_{c}": f"search by {SEARCHED[c]}" for c in searched} | {f"f_{c}_reverse": f"search by {SEARCHED[c]}, its end" for c in REVERSED if c in searched}
        m = dict(id=key, built_at=time.strftime("%Y-%m-%dT%H:%M:%S"), records=made["records"][0], added=0, moved=0, columns=have, searched=searched,
                 indexing=INDEXING, stamp=stamp, built_on=stamp, updates=0,
                 files=dict(keys=f"{key}.duckdb", records=f"{key}.records.duckdb", delta=f"{key}-0.duckdb", kind=kind),
                 tables={k: dict(of=of.get(k, k), rows=r, seconds=v) for k, (r, v) in made.items()}, seconds=round(time.perf_counter() - t0, 2))
        _publish(ws, tmp, m)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return dict(index=str(ws / INDEX), records=m["records"], tables=m["tables"], seconds=m["seconds"],
                unsearched=sorted({f for c, f in SEARCHED.items() if c not in have} - {SEARCHED[c] for c in searched}))


def update(ws: Path, s: Settings, p: Pipeline) -> dict:
    """The index of `ws` brought up to date with its run, under the workspace's lock: what changed since the build
    written again, from the records added since (new parts of state/records) and the records whose entity or rule
    cluster moved (gold, the rules' clusters). Anything else changed (a full run, the mapping, the method's keys,
    people's person/company answers, the code), a column of the added records read as another type, or the records added
    or moved reaching REBUILD of the index, builds it again (rebuilt: why). O(Δ·(G + R + D·L + F) + N)."""
    ws, t0, uid = Path(ws), time.perf_counter(), s.data.unique_id
    with folder.run_lock(ws):
        folder.finish_writes(ws)
        m, now = manifest(ws), _stamp(ws)
        new = [ws / f for f in now if m and f.startswith("state/records/") and f not in m["built_on"]]
        why = _since(m, now)
        if why is None and sum(pq.ParquetFile(f).metadata.num_rows for f in new) >= REBUILD * m["records"]:
            why = f"the records added since reach {REBUILD:.0%} of it"
        if why is not None:
            return {**_build(ws, s, p, now), "added": 0, "moved": 0, "rebuilt": why}
        if now == m["stamp"]:  # nothing changed since the last write
            return dict(index=str(ws / INDEX), records=m["records"] + m["added"], added=m["added"], moved=m["moved"], seconds=0.0, rebuilt=None)
        fitted, n = _pipeline(ws, s, p, m["columns"]), m["updates"] + 1
        _scorable(ws)
        con, _ = connect(s.compute)
        tmp, delta = _scratch(ws), f"{m['id']}-{n}.duckdb"
        try:
            con.execute(f"ATTACH {lit(ws / INDEX / m['files']['keys'])} AS ix (READ_ONLY)")
            con.execute(f"ATTACH {lit(ws / INDEX / m['files']['records'])} AS ixr (READ_ONLY)")
            con.execute(f"ATTACH {lit(tmp / delta)} AS dx (ROW_GROUP_SIZE {ROWS})")
            stored = {c: t for c, t, *_ in con.execute("DESCRIBE ixr.records").fetchall() if c not in ("h", "entity", "resolved")}
            src = f"read_parquet([{', '.join(lit(x) for x in new)}], union_by_name = true)"
            there = {c: t for c, t, *_ in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()} if new else {}
            if retyped := sorted(c for c, t in there.items() if c in stored and t != stored[c]):  # a key hashed as another type meets none of the index's
                why = f"{', '.join(retyped[:3])} read as another type"
            else:
                con.execute(f"CREATE TEMP TABLE src AS SELECT {', '.join(q(c) if c in there else f'NULL::{t} AS {q(c)}' for c, t in stored.items())} FROM {src}" if new
                            else "CREATE TEMP TABLE src AS SELECT * EXCLUDE (h, entity, resolved) FROM ixr.records LIMIT 0")  # the base's columns, in its order
                _write(con, "dx", "src", fitted, ws, uid, m["searched"])
                u = q(uid)
                con.execute(f"""CREATE TABLE dx.moved AS SELECT b.{u}, e.entity, coalesce(e.resolved, FALSE) AS resolved FROM ixr.records b
                    LEFT JOIN {_entities(ws, uid)} e USING ({u}) WHERE e.entity IS DISTINCT FROM b.entity OR coalesce(e.resolved, FALSE) <> b.resolved""")
                added, moved = (con.execute(f"SELECT count(*) FROM dx.{t}").fetchall()[0][0] for t in ("records", "moved"))
                if added + moved >= REBUILD * m["records"]:  # every read joins what moved: kept small
                    why = f"the records added or moved since reach {REBUILD:.0%} of it"
                else:
                    for db in ("ix", "ixr", "dx"):
                        con.execute(f"DETACH {db}")
                    _publish(ws, tmp, {**m, "stamp": now, "added": added, "moved": moved, "files": {**m["files"], "delta": delta}, "updates": n,
                                       "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        finally:
            con.close()
            shutil.rmtree(tmp, ignore_errors=True)
        if why is not None:
            return {**_build(ws, s, p, now), "added": 0, "moved": 0, "rebuilt": why}
    return dict(index=str(ws / INDEX), records=m["records"] + added, added=added, moved=moved, seconds=round(time.perf_counter() - t0, 2), rebuilt=None)


def _since(m: dict | None, now: dict) -> str | None:
    """Why the run as stamped `now` needs its index built again, rather than what changed since written, or None: what
    changed carries records added (new parts) and the files in MOVES; anything else changed is a full run, the mapping,
    the method's keys, people's answers."""
    if m is None:
        return "no index yet"
    if m.get("indexing") != INDEXING:
        return "built by another version of nayose"
    was = m["built_on"]
    changed = sorted(f for f in set(was) | set(now) if f not in MOVES and was.get(f) != now.get(f) and not (f.startswith("state/records/") and f not in was))
    return f"{', '.join(changed[:3])}{' …' if len(changed) > 3 else ''} changed" if changed else None


def _rule_reads(x: tuple, have: list[str]) -> list[str]:  # the columns a rule's SQL reads, of those the records hold
    st, rule = x
    sql = st.sql(rule)
    return [c for c in have if f'l."{c}"' in sql or f'r."{c}"' in sql]


def manifest(ws: Path) -> dict | None:  # the index's manifest, or None without one
    f = Path(ws) / INDEX / "manifest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def status(ws: Path, s: Settings) -> dict:
    """The index as a page shows it: when it was built, on how many records (of them, added since), what changed since
    (None: up to date), and the columns a lookup reads, each with its field and whether it is in the field's first
    alternative (main), in the mapping's order. O(files)."""
    m, parts = manifest(ws), sorted((Path(ws) / "state" / "records").glob("part-*.parquet"))
    have = m["columns"] if m else pq.read_schema(parts[0]).names if parts else []
    folded = {c.casefold() for c in have}  # a source column named as its field but for case gave way to it (standardize.prepare)
    present = present_fields(s, [*have, *(c for alts in s.columns.values() for alt in alts for c in alt if c.casefold() in folded)])
    seen, columns = set(), []
    for field, alts in present.items():
        for k, alt in enumerate(alts):
            for c in alt:
                if field not in ("id", "entity") and c not in seen:
                    seen.add(c)
                    columns.append(dict(column=c, field=field, main=k == 0 and field != "kind_flag"))
    return dict(built_at=m and m["built_at"], records=m and m["records"] + m.get("added", 0), added=m and m.get("added", 0),
                stale=stale(ws, m) if m else None, columns=columns)


def stale(ws: Path, m: dict | None = None) -> str | None:
    """What changed in the run since its index was last written (a file of it, the method, the mapping, people's
    answers, the code that reads it), or None. O(files)."""
    m = m or manifest(ws)
    if m is None:
        return "no index yet"
    if m.get("indexing") != INDEXING:
        return "built by another version of nayose"
    now = _stamp(Path(ws))
    changed = sorted(set(now) ^ set(m["stamp"]) | {f for f in now if f in m["stamp"] and now[f] != m["stamp"][f]})
    return f"{', '.join(changed[:3])}{' …' if len(changed) > 3 else ''} changed since it was built" if changed else None


def _attach(con: duckdb.DuckDBPyConnection, ws: Path, m: dict) -> None:  # the index the manifest names: its keys as ix, its records as ixr, what changed since as dx
    for db, f in (("ix", "keys"), ("ixr", "records"), ("dx", "delta")):
        con.execute(f"ATTACH {lit(Path(ws) / INDEX / m['files'][f])} AS {db} (READ_ONLY)")


def _classifier(ws: Path, s: Settings, p: Pipeline, m: dict) -> Classifier | None:  # the run's, as the index keeps it, with the name model loaded again
    return Classifier(**pickle.loads((Path(ws) / INDEX / m["files"]["kind"]).read_bytes()), names=name_model(s, p.kind)) if m["files"]["kind"] and p.kind else None


def _open(ws: Path, s: Settings, p: Pipeline) -> tuple[dict, Pipeline, duckdb.DuckDBPyConnection, Classifier | None, threading.Lock]:
    """The index of `ws` as its manifest names it now, refused when out of date: the manifest, the fitted pipeline, a
    connection with both databases attached and the classifier, kept open for the next call (OPEN at most). Each
    caller reads through a cursor of its own, and prepares under the lock: the classifier's name model holds a
    connection of its own. Files a write removed between reading the manifest and opening them: the manifest read again."""
    for again in (True, False):
        m = manifest(ws)
        if (why := stale(ws, m)) is not None:
            raise InputError(f"the index of {ws}: {why}", fix=f"build it: nayose build index --workspace {ws}")
        fitted, key = _pipeline(ws, s, p, m["columns"]), str(Path(ws).resolve())
        try:
            with _OPENING:
                o = _OPENED[key] = _OPENED.pop(key, None)  # the last asked, last: the least asked goes first
                if o is None or o[0]["files"] != m["files"]:
                    _OPENED.pop(key, None)
                    while len(_OPENED) >= OPEN:
                        _OPENED.pop(next(iter(_OPENED)))
                    con, _ = connect(s.compute)
                    _attach(con, ws, m)
                    o = _OPENED[key] = (m, con, _classifier(ws, s, fitted, m), threading.Lock())
            return m, fitted, o[1], o[2], o[3]
        except (duckdb.IOException, FileNotFoundError):
            if not again:
                raise


@contextlib.contextmanager
def _asking(ws: Path, s: Settings, p: Pipeline, values: dict | None, record: str | None):
    """The index opened, and the record asked about prepared into the cursor's table qry: the manifest, the fitted
    pipeline, the run's model, the cursor and the record."""
    m, fitted, con, kind, lock = _open(ws, s, p)
    cur = con.cursor()
    try:
        with lock:
            query = _query(cur, s, fitted, values, record, kind)
        stored = ws / "state" / "placeholders.json"
        for f, held in (json.loads(stored.read_text(encoding="utf-8")) if stored.exists() else {}).items():  # read as missing, as the run read them
            if f in query and pd.notna(v := query[f].iloc[0]) and v in held:  # a field not typed is missing already
                query.loc[:, [c for c in query.columns if c == f or c.startswith(f"{f}__")]] = pd.NA
        cur.register("er_q", query)
        cur.execute("CREATE TEMP TABLE qry AS SELECT * FROM er_q")
        cur.unregister("er_q")
        yield m, fitted, run_model(ws), cur, query
    finally:
        cur.close()


def _both(t: str, where: str, cols: str = "*") -> str:  # a table's rows that hold `where`, of the index and of what changed since
    return f"(SELECT {cols} FROM {'ixr' if t == 'records' else 'ix'}.{q(t)} WHERE {where} UNION ALL BY NAME SELECT {cols} FROM dx.{q(t)} WHERE {where})"


def _records(where: str, uid: str) -> str:  # the records that hold `where` as the run holds them now: those added since, each entity and rule cluster where it moved
    u = q(uid)
    return (f"(SELECT r.* REPLACE (CASE WHEN m.{u} IS NULL THEN r.entity ELSE m.entity END AS entity, CASE WHEN m.{u} IS NULL THEN r.resolved ELSE m.resolved END AS resolved) "
            f"FROM {_both('records', where)} r LEFT JOIN dx.moved m ON m.{u} = r.{u})")


def look_up(ws: Path, s: Settings, p: Pipeline, values: dict[str, str] | None = None, record: str | None = None,
            at_least: float | None = None, most: int = 20) -> dict:
    """_look_up on the values as given; when none reaches `at_least`, on them as people type what records hold otherwise
    (_folded: a name in hiragana, full-width or hyphenated digits, where the mapping doesn't prepare them so), kept if
    it finds more or comes closer, and then said (read_as: each value so read). Each looked up as given first, as a file
    holds it."""
    found = _look_up(ws, s, p, values, record, at_least, most)
    if values and not found["found"] and (folded := _folded(s, values)) != values:
        try:
            again = _look_up(ws, s, p, folded, None, at_least, most)
        except InputError:  # read so, it says nothing (ＮＵＬＬ as NULL): the answer as given
            return found
        if again["found"] or (again["closest"] and (not found["closest"] or again["closest"]["points"] > found["closest"]["points"])):
            return {**again, "read_as": {c: v for c, v in folded.items() if v != values[c]}}
    return found


def _look_up(ws: Path, s: Settings, p: Pipeline, values: dict[str, str] | None = None, record: str | None = None,
             at_least: float | None = None, most: int = 20) -> dict:
    """The entities a record would be compared with, as an increment of it alone compares it, best first: `values` by
    the file's column names, or `record`, a stored record's ID, looked up as if it were new (itself left out). Each
    entity at `at_least` points or more (default: the review floor) with its best record, its points, each comparison's
    level, the rule that would join it, and the keys that listed it; at most `most`. Also the record as compared, and
    what was looked up, how, and how long each part took. O(G·(log N + b) + C·K·L²)."""
    ws, uid, clock, t = Path(ws), s.data.unique_id, {}, time.perf_counter()
    with _asking(ws, s, p, values, record) as (m, fitted, model, con, query):
        me, extra = query[uid].iloc[0], 0 if record is not None else 1  # a stored record as new: the store holds it once already
        n = m["records"] + m["added"] + extra
        clock["prepare"] = time.perf_counter() - t
        t = time.perf_counter()
        found, checked = _candidates(con, fitted, uid, me, extra)
        clock["keys"] = time.perf_counter() - t
        t = time.perf_counter()
        found = {**found, **_gate(con, fitted, model, uid, me, found, checked, n)}
        rules = _rules(con, fitted, uid, me, checked, extra)
        clock["rules"] = time.perf_counter() - t
        t = time.perf_counter()
        ids = sorted({*found, *rules} - {me})
        scored = _scored(con, model, uid, me, ids, n)
        typed = {c: v for c in m["searched"] if c in query and pd.notna(v := query[c].iloc[0])}
        agree = _agree(con, uid, typed) if len(scored) and typed else {}  # the values that start alike: of records tied, the nearest
        clock["score"] = time.perf_counter() - t
    floor, rows = review_floor(fitted) if at_least is None else at_least, []
    if len(scored):
        scored = scored.assign(likely=_likely(scored, fitted), keys=[sorted(found.get(x, ())) for x in scored["uid"]])
        joins, size = {}, scored["entity"].value_counts()  # each entity's rule: one that joins any of its records, the first in order (a dict: a frame column would hold a truthy NaN)
        for x in scored.itertuples():
            if x.uid in rules and (x.entity not in joins or rules[x.uid][0] < joins[x.entity][0]):
                joins[x.entity] = rules[x.uid]
        for x in scored.sort_values(["weight", "uid"], ascending=[False, True]).drop_duplicates("entity").itertuples():
            rule = joins[x.entity][1] if x.entity in joins else None
            if x.weight < floor and not rule:
                continue
            rows.append(dict(entity=x.entity, record=x.uid, points=round(float(x.weight), 2), likely=bool(x.likely) or rule is not None,
                             rule=rule, keys=x.keys, compared=x.compared, records=int(size[x.entity]), shown=x.shown))
    rows.sort(key=lambda r: (-(r["rule"] is not None), -r["points"]))
    said = next((v for k in ("full_name", "person_name", "company_name") if (v := _view(query, uid).get(k))), None)  # the name as typed, prepared
    named = lambda x: bool(said) and (x.get("full_name") or x.get("person_name") or x.get("company_name") or "").startswith(said)
    near = (scored.assign(alike=[-len(agree.get(u, [])) - named(x) for u, x in zip(scored["uid"], scored["shown"])])  # none reaches it: how near the nearest came,
            .sort_values(["weight", "alike", "uid"], ascending=[False, True, True]).iloc[0] if len(scored) and not rows else None)  # of those tied, one named as typed
    closest = dict(record=near["uid"], entity=near["entity"], points=round(float(near["weight"]), 2), shown=near["shown"]) if near is not None else None
    return dict(record=_view(query, uid), entities=rows[:most], found=len(rows), at_least=floor, closest=closest, candidates=len(ids), likely=sum(r["likely"] for r in rows),
                checked=checked, seconds={k: round(v, 4) for k, v in clock.items()}, index=dict(built_at=m["built_at"], records=n - extra))


def search(ws: Path, s: Settings, p: Pipeline, values: dict[str, str], at_least: float | None = None, most: int = 10) -> dict:
    """_search on the values as given, and on them as people type what records hold otherwise (_folded: full-width
    digits, 100-0001, a name in hiragana) when that reads them otherwise: the answer whose best agree on more of what was
    typed, as given when alike, a file holding them as typed; the other said (read_as). Blanks
    and placeholders alone (-, NULL: [input] nulls) are nothing to search by, as nothing typed is."""
    nulls = frozenset(s.input.nulls)
    if all(tidy(str(v), nulls, False)[0] is None for v in values.values()):
        m, fitted = _open(ws, s, p)[:2]
        _sources(fitted, values)
        return dict(record={}, entities=[], found=0, listed=0, candidates=0, typed=[], missing=sorted(values), over=[], unsearched=[], seconds={},
                    index=dict(built_at=m["built_at"], records=m["records"] + m["added"]))
    found, folded = _search(ws, s, p, values, at_least, most), _folded(s, values)
    if folded == values:
        return found
    try:
        again = _search(ws, s, p, folded, at_least, most)  # as records hold them most often: kept if its best agree on more of what was typed, else lists where as given lists none
    except InputError:  # read so, it says nothing: the answer as given
        return found
    agreed = lambda r: (max((len(e["fields"]) for e in r["entities"]), default=0), bool(r["listed"]))
    return {**again, "read_as": {c: v for c, v in folded.items() if v != values[c]}} if agreed(again) > agreed(found) else found


def _search(ws: Path, s: Settings, p: Pipeline, values: dict[str, str], at_least: float | None = None, most: int = 10) -> dict:
    """The stored records whose values start with what was typed, any of the file's columns, best first: by how many of
    the searched fields agree (a name also by its end), then by the run's points for the two, a field not typed being
    missing. Each entity at `at_least` points or more (default: any) with its best record, its points, the fields that
    agree and each comparison's level; at most `most`, ties in the order the values were read. A value that starts CAP
    records or more is said (over: how many) and lists the first SCORED of them by value, to be narrowed; of the records
    listed, the SCORED sharing the most values are scored.
    O(F·(log N + CAP) + SCORED·K·L²)."""
    ws, uid, clock, t = Path(ws), s.data.unique_id, {}, time.perf_counter()
    with _asking(ws, s, p, values, None) as (m, fitted, model, con, query):
        typed = {c: v for c in m["searched"] if c in query and pd.notna(v := query[c].iloc[0])}
        feeds = {c: {d.name for d in fitted.fs.standardize.derived if any(c in alt for alt in d.sources)} for c in values}  # the fields each column typed fills
        held, nulls = {c.split("__")[0] for c in m["searched"]}, frozenset(s.input.nulls)  # the fields the index searches, by their columns' names
        unsearched = sorted({f for c, v in values.items() if tidy(str(v), nulls, False)[0] is not None and not feeds[c] & held for f in feeds[c]})  # typed, no column searched: said
        clock["prepare"] = time.perf_counter() - t
        t = time.perf_counter()
        listed, over, first = {}, {}, {}  # first: each record's place in the order its value was read (by value): ties go by it
        for c, v in typed.items():
            field = SEARCHED[c]
            if field in over:
                continue
            reads = [(f"f_{c}", v), *(((f"f_{c}_reverse", con.execute(f"SELECT reverse({q(c)}) FROM qry").fetchall()[0][0]),) if c in REVERSED else ())]
            for table, x in reads:
                within = _both(table, f"v >= {lit(x)} AND v < {lit(x + LAST)}", "v, uid")
                rows = con.execute(f"SELECT uid FROM {within} ORDER BY v, uid LIMIT {CAP}").fetchall()
                if len(rows) == CAP and table == f"f_{c}" and field not in listed:  # its field's first value starts too many: how many, and the first by value
                    n = con.execute(f"SELECT count(*) FROM (SELECT 1 FROM {within} LIMIT {COUNTED})").fetchall()[0][0]
                    over[field] = dict(value=v, records=n, more=n >= COUNTED)
                    rows = rows[:SCORED]
                elif len(rows) == CAP:  # another read of a field listed already: too many to add to it
                    continue
                listed.setdefault(field, set()).update(u for (u,) in rows)
                for (u,) in rows:
                    first.setdefault(u, len(first))
                if field in over:
                    break
        if any(us for f, us in listed.items() if f not in over):  # another value lists its own: the common one only agrees, its first by value left out
            listed = {f: us for f, us in listed.items() if f not in over}
        for f in over:
            over[f]["listed"] = f in listed
        shared = Counter(u for us in listed.values() for u in us)
        ids = sorted(shared, key=lambda u: (-shared[u], first[u]))[:SCORED]
        clock["values"] = time.perf_counter() - t
        t = time.perf_counter()
        scored = _scored(con, model, uid, QUERY, ids, m["records"] + m["added"] + 1)
        agree = _agree(con, uid, typed) if len(scored) else {}
        clock["score"] = time.perf_counter() - t
    rows = []
    if len(scored):
        scored = scored.assign(likely=_likely(scored, fitted), fields=[agree.get(u, []) for u in scored["uid"]])
        scored["agreed"], size = scored["fields"].map(len), scored["entity"].value_counts()
        scored["first"] = scored["uid"].map(first)
        for x in scored.sort_values(["agreed", "weight", "first"], ascending=[False, False, True]).drop_duplicates("entity").itertuples():
            if at_least is None or x.weight >= at_least:
                rows.append(dict(entity=x.entity, record=x.uid, points=round(float(x.weight), 2), likely=bool(x.likely), fields=x.fields,
                                 compared=x.compared, records=int(size[x.entity]), shown=x.shown))
    return dict(record=_view(query, uid), entities=rows[:most], found=len(rows), listed=len(shared), candidates=len(ids),
                typed=sorted({SEARCHED[c] for c in typed}), over=[dict(field=f, **v) for f, v in over.items()], unsearched=unsearched,
                seconds={k: round(v, 4) for k, v in clock.items()}, index=dict(built_at=m["built_at"], records=m["records"] + m["added"]))


def _folded(s: Settings, values: dict[str, str]) -> dict[str, str]:
    """Values as people type them, read as records hold them most often (_typed), by each column's field: only a column
    some field reading it doesn't prepare so already (its normalize lacks katakana, or strip_separators), as a
    workspace mapped before those steps; else the run prepares them alike, and a second reading would change nothing."""
    steps = {d.name: d.normalize for d in s.standardize.derived}
    kind, lacks = {}, set()
    for f, alts in s.columns.items():
        k = "name" if f.rstrip("_0123456789").endswith("name") else "digits" if f in DIGITS else None
        for c in (c for alt in alts for c in alt):
            kind.setdefault(c, k)
            if k and ("katakana" if k == "name" else "strip_separators") not in steps.get(f, ()):
                lacks.add(c)
    return {c: _typed(v, kind.get(c)) if c in lacks else v for c, v in values.items()}


def _typed(v: str, kind: str | None) -> str:
    """A value as a person types it, as records hold it most often: a name (kind "name") full-width as half-width and
    half-width kana as full (NFKC), hiragana as katakana; a phone, postal code or customer ID ("digits") NFKC and
    without what is written between characters (03-1234-5678, 〒100-0001), as the project's mapping prepares them. Any
    other value as it is: a birth date keeps its separators (1993-1-12 isn't 1993-11-2)."""
    if kind is None:
        return v
    w = unicodedata.normalize("NFKC", str(v))
    return w.translate(KATAKANA) if kind == "name" else re.sub(SEPARATORS, "", w) or v  # 〒 alone: as typed, not nothing


def _view(query: pd.DataFrame, uid: str) -> dict:  # the record asked about, as compared: its fields and kind
    view = query.iloc[0]
    return {k: (None if pd.isna(view.get(k)) else str(view.get(k))) for k in (uid, *SHOWN, "kind") if k in view}


def _likely(scored: pd.DataFrame, p: Pipeline) -> np.ndarray:  # at the line or above, a name compared on both sides (match.named_sql)
    named = np.zeros(len(scored), dtype=bool) if p.fs.needs else np.ones(len(scored), dtype=bool)
    for c in p.fs.needs:
        named |= (scored[f"gamma_{c}"] >= 0).to_numpy()
    return (scored["weight"] >= p.fs.min_match_weight).to_numpy() & named


def _agree(con: duckdb.DuckDBPyConnection, uid: str, typed: dict[str, str]) -> dict[str, list[str]]:
    """Each record _scored read (er_c), with the searched fields whose value starts with what was typed (a name also:
    ends with it)."""
    checks = [*((SEARCHED[c], f"starts_with(c.{q(c)}, q.{q(c)})") for c in typed), *((SEARCHED[c], f"suffix(c.{q(c)}, q.{q(c)})") for c in typed if c in REVERSED)]
    rows = con.execute(f"SELECT c.{q(uid)}, {', '.join(f'coalesce({x}, FALSE)' for _, x in checks)} FROM er_c c, qry q").fetchall()
    return {r[0]: sorted({f for (f, _), ok in zip(checks, r[1:]) if ok}) for r in rows}


def _query(con: duckdb.DuckDBPyConnection, s: Settings, p: Pipeline, values: dict | None, record: str | None, kind: Classifier | None) -> pd.DataFrame:
    """The record looked up, as a run prepares it: a stored one's row as the index holds it, or the values given, by the
    file's column names, read as the reader reads a value and prepared with the run's classifier `kind`."""
    uid = s.data.unique_id
    if record is not None:
        row = con.execute(f"SELECT * EXCLUDE (h, entity, resolved) FROM {_both('records', f'h = hash({lit(record)}::VARCHAR) AND {q(uid)} = {lit(record)}')}").df()
        if row.empty:
            raise InputError(f"{record}: no record of the run has that ID", fix="give a record ID the run holds, or the record's values")
        return row.astype("string")
    sources = _sources(p, values)
    nulls = frozenset(s.input.nulls)
    row = pd.DataFrame({uid: [QUERY], **{c: [tidy(str(v), nulls, False)[0] if (v := (values or {}).get(c)) not in (None, "") else None] for c in sources}}, dtype="string")
    if row.drop(columns=uid).isna().all(axis=1).iloc[0]:
        given = [f"{c}={v}" for c, v in (values or {}).items() if v not in (None, "")]
        raise InputError(f"{', '.join(given)}: read as missing, as a file's would be" if given else "no value given",
                         fix="give a value a record holds: a name, a phone, a postal code")
    rules, fs, probe = p.rules, p.fs, p.probe
    normalized, used = [*rules.normalized(), *fs.normalized(), *probe.normalized()], rules.used() | fs.used() | probe.used()
    return prepare(fs.standardize, row, normalized, used, kind=kind).astype("string")


def _sources(p: Pipeline, values: dict | None) -> list[str]:  # the columns a field reads; a value given for another refused
    sources = sorted({c for d in p.fs.standardize.derived for alt in d.sources for c in alt})
    if unknown := sorted(set(values or {}) - set(sources)):
        raise InputError(f"{', '.join(unknown)}: no field reads that column", fix=f"the columns a field reads: {', '.join(sources)}")
    return sources


def _candidates(con: duckdb.DuckDBPyConnection, p: Pipeline, uid: str, me: str, extra: int = 1) -> tuple[dict[str, set[str]], list[dict]]:
    """The stored records each generator lists with the record (its blocks and windows), and per generator what was
    looked up: rows found, or why none (a key the record lacks, a block too big). `extra`: what the record adds to a
    block, 1 for a new one, 0 for a stored one looked up as new. O(G·(log N + b))."""
    found: dict[str, set[str]] = {}
    checked, hashes = [], {}
    tables = dict(_tables(p))
    for name, x in tables.items():
        if isinstance(x, (KeyBlocker, DeletionKeys)):
            hashes[name] = [h for (h,) in con.execute(f"SELECT DISTINCT h FROM ({_rows(x, 'qry', uid)})").fetchall()]
    sizes = {(t, h): n for t, hs in hashes.items() if hs  # each block's records, counted in its sorted rows: a block too big is gated
             for h, n in con.execute(f"SELECT h, count(*) FROM {_both(t, f'h IN ({', '.join(map(str, hs))})', 'h')} GROUP BY h").fetchall()}
    m = p.fs.budget.min_oversized()
    for name, x in tables.items():
        if isinstance(x, tuple):
            continue
        if isinstance(x, SortedNeighbourhood):
            near = _window(con, name, x, me, con.execute(f"SELECT {q(x.key.name)} FROM qry").fetchall()[0][0])
            for v in near:
                found.setdefault(v, set()).add(x.name)
            checked.append(dict(key=x.name, found=len(near)) if near or _held(con, x) else dict(key=x.name, found=0, why="the record has no value for it"))
            continue
        hs = hashes.get(name, [])
        if not hs:
            checked.append(dict(key=x.name, found=0, why="the record has no value for it"))
            continue
        normal = [h for h in hs if sizes.get((name, h), 0) + extra < m]
        big = [h for h in hs if sizes.get((name, h), 0) + extra >= m]
        rows = con.execute(f"SELECT DISTINCT uid FROM {_both(name, f'h IN ({', '.join(map(str, normal))})', 'uid')}").fetchall() if normal else []
        for (v,) in rows:
            if v != me:
                found.setdefault(v, set()).add(x.name)
        checked.append(dict(key=x.name, found=len(rows), **({"big": [dict(h=h, records=sizes[(name, h)] + extra) for h in big]} if big else {})))
    return found, checked


def _held(con: duckdb.DuckDBPyConnection, x: SortedNeighbourhood) -> bool:  # whether the record has a value for the window's key
    return con.execute(f"SELECT {q(x.key.name)} IS NOT NULL FROM qry").fetchall()[0][0]


def _window(con: duckdb.DuckDBPyConnection, name: str, x: SortedNeighbourhood, me: str, key: str | None) -> list[str]:
    """The window-1 records on each side of the record in (key, uid) order, as the run's window places it among them:
    the nearest of the index's and of what changed since, merged. O(log N + SPARSE)."""
    if key is None or x.window < 2:
        return []
    w, before, after = x.window - 1, [], []
    for db in ("ix", "dx"):
        b, a = _near(con, db, name, me, key, w)
        before += b
        after += a
    return [u for _, u in sorted(before)[-w:]] + [u for _, u in sorted(after)[:w]]


def _near(con: duckdb.DuckDBPyConnection, db: str, name: str, me: str, key: str, w: int) -> tuple[list[tuple], list[tuple]]:
    """The w (key, uid) rows of one database's window table before the record and the w after it: a bisect in the
    sparse table, then one read of the rows between two of its keys. O(log N + SPARSE)."""
    sparse = con.execute(f"SELECT pos, key, uid FROM {db}.{name}_sparse ORDER BY pos").fetchall()
    at = bisect_left([(k, u) for _, k, u in sparse], (key, me))  # the first sparse row at or after the record
    lo = sparse[at - 1][0] if at else 1
    hi = sparse[at][0] if at < len(sparse) else lo + SPARSE
    block = con.execute(f"SELECT pos, key, uid FROM {db}.{name} WHERE pos BETWEEN {lo} AND {hi} ORDER BY pos").fetchall()
    start = next((pos for pos, k, u in block if (k, u) >= (key, me)), block[-1][0] + 1 if block else lo)  # its place: before the first row past it, else after the last
    rows = con.execute(f"SELECT key, uid FROM {db}.{name} WHERE pos BETWEEN {start - w - 1} AND {start + w} ORDER BY pos").fetchall()
    rows = [(k, u) for k, u in rows if u != me]  # a stored record looked up as new: the window as if it weren't there
    return [r for r in rows if r < (key, me)][-w:], [r for r in rows if r > (key, me)][:w]


def _gate(con: duckdb.DuckDBPyConnection, p: Pipeline, model: dict, uid: str, me: str, found: dict[str, set[str]],
          checked: list[dict], n: int) -> dict[str, set[str]]:  # n: the records with it, for the prior
    """Each oversized block the record falls in, as a run gates it (er.candidates._gate): the record against the block's
    records of lowest hash(uid), it among them, less the pairs other keys list; the block joined in full only if one of
    those reaches the review floor. O(sampled + b) a block."""
    m, floor, added = p.fs.budget.min_oversized(), review_floor(p), {}
    names = {x.name: name for name, x in _tables(p) if not isinstance(x, tuple)}
    mine = con.execute("SELECT hash(?::VARCHAR)", [me]).fetchall()[0][0]
    for c in checked:
        for b in c.get("big", ()):
            block = _both(names[c["key"]], f"h = {b['h']}", "uid")
            rows = con.execute(f"SELECT DISTINCT uid, hash(uid) AS hu FROM {block} ORDER BY hu LIMIT {m}").fetchall()
            ranked = sorted([*(r for r in rows if r[0] != me), (me, mine)], key=lambda r: r[1])[:m]  # the block's lowest hashes, the record among them once
            sample = [u for u, hu in ranked if u != me and u not in found]
            scored = _scored(con, model, uid, me, sample, n)
            b.update(sampled=len(sample), best=round(float(scored["weight"].max()), 2) if len(scored) else None)
            if len(sample) and (scored["weight"] >= floor).any():
                b["decision"] = "kept"
                for (v,) in con.execute(f"SELECT DISTINCT uid FROM {block}").fetchall():
                    if v != me:
                        added.setdefault(v, set()).add(c["key"])
            else:
                b["decision"] = "skipped: no sampled pair reaches the floor" if len(sample) else "skipped: other keys list its sampled pairs"
    return {v: keys | found.get(v, set()) for v, keys in added.items()}


def _rules(con: duckdb.DuckDBPyConnection, p: Pipeline, uid: str, me: str, checked: list[dict], extra: int = 1) -> dict[str, tuple[int, str]]:
    """Each stored record a rule joins the record to, with the rule's place in order and name: as er.match.rule_edges
    finds them (the rule's keys looked up, a value on too many records left out as Run._untrusted leaves it, its
    conditions checked; the first rule in order winning a pair), then the stages' cascade as Run._rules keeps them: a
    later stage's pair goes when both its records are already in a rule cluster of two or more."""
    m, out, order = p.fs.budget.min_oversized(), {}, {n: i for i, (n, x) in enumerate(t for t in _tables(p) if isinstance(t[1], tuple))}
    for name, (st, rule) in ((n, x) for n, x in _tables(p) if isinstance(x, tuple)):
        h = con.execute(f"SELECT {_hashed((st, rule))} FROM qry WHERE {_filled(st.keys(rule))}").fetchall()
        if not h:
            continue
        size = con.execute(f"SELECT count(*) FROM {_both(name, f'h = {h[0][0]}', 'h')}").fetchall()[0][0]
        if size + extra >= m:
            checked.append(dict(key=f"rule {rule.name}", found=0, why=f"its value is on {size + extra:,} records: the rule doesn't trust it"))
            continue
        hus = [hu for (hu,) in con.execute(f"SELECT DISTINCT hash(uid) FROM {_both(name, f'h = {h[0][0]}', 'uid')}").fetchall()]  # literals: the records table read by its zone maps
        hits = con.execute(f"""SELECT r.{q(uid)}, r.resolved FROM qry l JOIN {_records(f"h IN ({', '.join(map(str, hus))})", uid)} r
            ON {st.sql(rule)} AND r.{q(uid)} <> l.{q(uid)}""").fetchall() if hus else []
        for v, resolved in hits:
            out.setdefault(v, (order[name], rule.name, st.name, bool(resolved)))
    kept, joined, done = {}, set(), False  # the record starts alone; each stage's kept pairs put it in a cluster of two or more
    for st in p.rules.stages:
        here = {v: x for v, x in out.items() if x[2] == st.name and not (done and (x[3] or v in joined))}
        kept |= {v: (x[0], x[1]) for v, x in here.items()}
        joined |= set(here)
        done = done or bool(here)
    return kept


def _scored(con: duckdb.DuckDBPyConnection, model: dict, uid: str, me: str, ids: list[str], n: int) -> pd.DataFrame:
    """The record against each of these stored records, scored as er.match.score_fs scores a pair with the run's
    model: each comparison's level by its own SQL, the pair oriented uid_l < uid_r, its bits summed with the prior at
    n records. With each its entity, its levels in words, and the fields a person reads; the records read stay in
    er_c. O(|ids|·K·L²)."""
    if not ids:
        return pd.DataFrame(columns=["uid", "entity", "weight", "compared", "shown"])
    cols, u = sorted(read_by(model)), q(uid)
    hashes = [h for (h,) in con.execute("SELECT hash(x) FROM unnest(?::VARCHAR[]) t(x)", [ids]).fetchall()]
    con.execute(f"CREATE OR REPLACE TEMP TABLE er_c AS SELECT * EXCLUDE (h) FROM {_records(f'h IN ({', '.join(map(str, hashes))})', uid)}")
    side = lambda c, a, b: f"CASE WHEN q.{u} < c.{u} THEN {a}.{q(c)} ELSE {b}.{q(c)} END"
    pairs = ", ".join(f'{side(c, "q", "c")} AS {q(c + "_l")}, {side(c, "c", "q")} AS {q(c + "_r")}' for c in cols)
    by = levels(model)
    gammas = []
    for comp in model["comparisons"]:
        ordered = [lv for lv in comp["comparison_levels"] if not lv.get("is_null_level")][::-1]
        when = [f"WHEN {lv['sql_condition']} THEN -1" for lv in comp["comparison_levels"] if lv.get("is_null_level")]
        when += [f"WHEN {lv['sql_condition']} THEN {g}" for g, lv in reversed(list(enumerate(ordered))) if lv["sql_condition"] != "ELSE"]
        gammas.append(f"CASE {' '.join(when)} ELSE 0 END AS {q('gamma_' + comp['output_column_name'])}")
    shown = ", ".join(f"c.{q(x)} AS {q('shown_' + x)}" for x in SHOWN if x in {c for c, *_ in con.execute("DESCRIBE er_c").fetchall()})
    frame = con.execute(f"""SELECT x.*, {', '.join(gammas)} FROM (SELECT c.{u} AS uid, c.entity, {pairs}{', ' + shown if shown else ''}
        FROM qry q, er_c c WHERE c.{u} <> q.{u}) x""").df()
    lam = scaled_prior(model, n)
    names = [c["output_column_name"] for c in model["comparisons"]]
    bits = np.array([[by[c][int(g)][1] for c, g in zip(names, row)] for row in frame[[f"gamma_{c}" for c in names]].to_numpy()]).reshape(len(frame), len(names))
    frame["weight"] = np.log2(lam / (1 - lam)) + bits.sum(axis=1)
    frame["compared"] = [{c: by[c][int(g)][0] for c, g in zip(names, row)} for row in frame[[f"gamma_{c}" for c in names]].to_numpy()]
    frame["shown"] = [{x: (None if pd.isna(r.get(f"shown_{x}")) else str(r.get(f"shown_{x}"))) for x in SHOWN if f"shown_{x}" in r} for r in frame.to_dict("records")]
    return frame
