"""Look up: one record against a workspace's run, in well under a second, whatever the number of records stored.

build() reads the written run once (state/records, already standardized; gold; the model it scored with) and writes
<workspace>/index/: a DuckDB database holding every key of every record, each table sorted by a hash of its key so a
lookup reads one row group of it; the person/company classifier's fitted part; and a manifest of what it rests on.
look_up() prepares a record as a run prepares one, looks each of its keys up, gates an oversized block as a run does,
scores the candidates with the run's model and groups them by entity. It writes nothing.

    build      O(N·(G + R + D·L) + N log N)   every key of every record, hashed, sorted: DuckDB, in parallel
    look_up    O(G·(log N + b) + C·K·L²)      N only in log N: a key's rows are one row group of its sorted table

N stored records, G generators, R rules, D deletion generators, L a value's length, b a block's size, C candidates,
K comparisons. A lookup lists the pairs an increment of that one record lists (er.candidates) and scores them as
er.match.score_fs scores them with the run's model; an increment, unlike it, counts u again on every record.
"""
import hashlib
import json
import os
import pickle
import shutil
import time
from bisect import bisect_left
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn

from er import folder
from er.candidates import deletions_sql
from er.config import DeletionKeys, InputError, KeyBlocker, Pipeline, SortedNeighbourhood, lit, q
from er.folder import Busy
from er.intake import tidy
from er.kind import Classifier, classifier, merge_answers, name_model
from er.match import levels, read_by, review_floor, scaled_prior
from er.report import run_model
from er.run import run_config
from er.settings import COLUMNS, Settings, fit_to_file, present_fields
from er.standardize import prepare
from er.strings import connect

INDEX = "index"
SPARSE = 1024  # a sorted generator keeps every this many keys apart: a bisect there, then one read of at most this many rows
SHOWN = ("full_name", "company_name", "address", "postal_code", "phone", "birth_date", "customer_id")  # a record, as a person reads it
QUERY = "\x7flookup"  # the ID of a record typed in: no record's, and after every one in order
INDEXING = hashlib.sha256(b"".join((Path(__file__).parent / f"{m}.py").read_bytes() for m in ("index", "candidates", "config", "standardize", "match", "kind"))
                          + duckdb.__version__.encode() + sklearn.__version__.encode()).hexdigest()[:12]  # what reads and writes an index (kind.pkl pickles a scikit-learn model): another version builds it again


def _stamp(ws: Path) -> dict[str, list[int]]:  # what an index rests on: each file of the run, the method and the mapping, by size and time
    files = [*sorted((ws / "state" / "records").glob("part-*.parquet")), ws / "gold.parquet", ws / "state" / "scoring.json", ws / "state" / "model.json",
             ws / "state" / "config.txt", ws / folder.METHOD, ws / COLUMNS, *folder.answer_parts(ws)]
    return {f.relative_to(ws).as_posix(): [f.stat().st_size, f.stat().st_mtime_ns] for f in files if f.exists()}


def _pipeline(ws: Path, s: Settings, p: Pipeline, columns: list[str]) -> Pipeline:  # the pipeline the run ran, fitted to its records' columns
    config = ws / "state" / "config.txt"
    if config.exists() and config.read_text(encoding="utf-8") != run_config(p, s):
        raise InputError(f"the pipeline or the column mapping changed since the run in {ws}: its records would be looked up otherwise",
                         fix=f"run it again first: nayose rerun records --workspace {ws}")
    folded = {c.casefold() for c in columns}  # a source column named as its field but for case (BIRTH_DATE) gave way to it (standardize.prepare)
    return fit_to_file(p, s, [*columns, *(c for alts in s.columns.values() for alt in alts for c in alt if c not in columns and c.casefold() in folded)])[0]


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


def _rows(x: object, table: str, uid: str) -> str:  # the rows a table of keys holds, from records in `table`: hash, uid, the uid's hash
    u = q(uid)
    if isinstance(x, DeletionKeys):
        within = ", ".join(q(w.name) for w in x.within)
        return (f"SELECT {_hashed(x)} AS h, {u} AS uid, hash({u}) AS hu FROM (SELECT {u}{', ' + within if within else ''}, "
                f"unnest({deletions_sql(q(x.key.name))}) AS __dk FROM {table} WHERE {_filled(_keys(x))})")
    return f"SELECT {_hashed(x)} AS h, {u} AS uid, hash({u}) AS hu FROM {table} WHERE {_filled(_keys(x))}"


def build(ws: Path, s: Settings, p: Pipeline) -> dict:
    """The index of the run in `ws`, written to ws/index/ under the workspace's lock: built in a folder of its own,
    then renamed into place, so one cut short leaves the last whole. O(N·(G + R + D·L) + N log N)."""
    ws, t0, uid = Path(ws), time.perf_counter(), s.data.unique_id
    with folder.run_lock(ws):
        folder.finish_writes(ws)
        parts = sorted((ws / "state" / "records").glob("part-*.parquet"))
        if not parts or not (ws / "gold.parquet").exists():
            raise InputError(f"{ws} holds no run to index", fix=f"find matches first: nayose resolve records <file> --workspace {ws}")
        con, _ = connect(s.compute)
        src = f"read_parquet([{', '.join(lit(x) for x in parts)}], union_by_name = true)"
        have = [c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
        fitted, model = _pipeline(ws, s, p, have), run_model(ws)
        if model["er"]["tf"]:
            raise InputError(f"the model of the run in {ws} adjusts levels by term frequency, which a lookup doesn't",
                             fix="index a run of config/final.toml's method, which adjusts none")
        tables = _tables(fitted)
        reads = {uid, *read_by(model), *(c for _, x in tables for c in _keys(x)), *(c for c in SHOWN if c in have),
                 *(c for _, x in tables if isinstance(x, tuple) for c in _rule_reads(x, have))}
        tmp, dest = ws / INDEX / f".build-{os.getpid()}", ws / INDEX
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        seconds, rows = {}, {}

        def table(name: str, sql: str) -> None:
            t = time.perf_counter()
            con.execute(f"CREATE TABLE ix.{q(name)} AS {sql}")
            seconds[name], rows[name] = round(time.perf_counter() - t, 3), con.execute(f"SELECT count(*) FROM ix.{q(name)}").fetchall()[0][0]

        try:
            con.execute(f"ATTACH {lit(tmp / 'index.duckdb')} AS ix")
            t = time.perf_counter()
            con.execute(f"CREATE TEMP TABLE src AS SELECT {', '.join(q(c) for c in have if c in reads)} FROM {src}")  # read once: every table reads it
            seconds["read"] = round(time.perf_counter() - t, 3)
            rc = ws / "state" / "rule_clusters.parquet"  # a record the rules joined to another: a later stage's rule pair of two such is left out
            table("records", f"SELECT hash(s.{q(uid)}) AS h, s.*, g.cluster_id AS entity, coalesce(c.n >= 2, FALSE) AS resolved FROM src s "
                             f"LEFT JOIN read_parquet({lit(ws / 'gold.parquet')}) g USING ({q(uid)}) "
                             f"LEFT JOIN (SELECT {q(uid)}, count(*) OVER (PARTITION BY cluster_id) AS n FROM read_parquet({lit(rc)})) c USING ({q(uid)}) ORDER BY h")
            m = fitted.fs.budget.min_oversized()
            big = []
            for name, x in tables:
                if isinstance(x, SortedNeighbourhood):  # positions in the run's own window order: key, then uid
                    k = q(x.key.name)
                    table(name, f"SELECT row_number() OVER (ORDER BY {k}, {q(uid)}) AS pos, {k} AS key, {q(uid)} AS uid FROM src WHERE {k} IS NOT NULL ORDER BY pos")
                    table(f"{name}_sparse", f"SELECT pos, key, uid FROM ix.{name} WHERE (pos - 1) % {SPARSE} = 0 ORDER BY pos")
                else:
                    table(name, f"{_rows(x, 'src', uid)} ORDER BY h")
                    big.append(f"SELECT '{name}' AS t, h, count(*) AS n FROM ix.{name} GROUP BY h HAVING count(*) >= {m - 1}")  # with the record looked up: m
            table("big", f"{' UNION ALL '.join(big) or 'SELECT NULL AS t, NULL::UBIGINT AS h, 0 AS n WHERE FALSE'} ORDER BY t, h")
            con.execute("DETACH ix")
            spec, present = fitted.kind, present_fields(s, have)
            if spec and spec.name_field in present:  # its fitted part: the name model, which holds a connection, is loaded again by a lookup
                answers = [pd.read_parquet(f).astype({uid: "string"}) for f in folder.answer_parts(ws)]
                c = classifier(s, spec, merge_answers(pd.concat(answers, ignore_index=True) if answers else None, None, uid))
                (tmp / "kind.pkl").write_bytes(pickle.dumps({k: v for k, v in vars(c).items() if k != "names"}))
            of = {n: f"rule {x[1].name}" if isinstance(x, tuple) else x.name for n, x in tables} | {f"{n}_sparse": f"{x.name}, every {SPARSE:,}th" for n, x in tables
                                                                                                 if isinstance(x, SortedNeighbourhood)}
            manifest = dict(built_at=time.strftime("%Y-%m-%dT%H:%M:%S"), records=rows["records"], columns=have, indexing=INDEXING,
                            stamp=_stamp(ws), tables={k: dict(of=of.get(k, k), rows=rows.get(k), seconds=v) for k, v in seconds.items()},
                            seconds=round(time.perf_counter() - t0, 2))
            (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
            try:  # the database first, the manifest last: an index with a manifest is whole
                os.replace(tmp / "index.duckdb", dest / "index.duckdb")
            except PermissionError:  # Windows: a lookup holds the old one open
                raise Busy(f"a lookup is reading the index of {ws}", fix="try again in a moment") from None
            if (tmp / "kind.pkl").exists():
                os.replace(tmp / "kind.pkl", dest / "kind.pkl")
            else:  # a run that tells no kind: none kept from before
                (dest / "kind.pkl").unlink(missing_ok=True)
            os.replace(tmp / "manifest.json", dest / "manifest.json")
        finally:
            con.close()
            shutil.rmtree(tmp, ignore_errors=True)
    return dict(index=str(dest), records=manifest["records"], tables=manifest["tables"], seconds=manifest["seconds"])


def _rule_reads(x: tuple, have: list[str]) -> list[str]:  # the columns a rule's SQL reads, of those the records hold
    st, rule = x
    sql = st.sql(rule)
    return [c for c in have if f'l."{c}"' in sql or f'r."{c}"' in sql]


def manifest(ws: Path) -> dict | None:  # the index's manifest, or None without one
    f = Path(ws) / INDEX / "manifest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def status(ws: Path, s: Settings) -> dict:
    """The index as a page shows it: when it was built, on how many records, what changed since (None: up to date),
    and the columns a lookup reads, each with its field and whether it is in the field's first alternative (main),
    in the mapping's order. O(files)."""
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
    return dict(built_at=m and m["built_at"], records=m and m["records"], stale=stale(ws, m) if m else None, columns=columns)


def stale(ws: Path, m: dict | None = None) -> str | None:
    """What changed in the run since its index was built (a file of it, the method, the mapping, people's answers, the
    code that reads it), or None. O(files)."""
    m = m or manifest(ws)
    if m is None:
        return "no index yet"
    if m.get("indexing") != INDEXING:
        return "built by another version of nayose"
    now = _stamp(Path(ws))
    changed = sorted(set(now) ^ set(m["stamp"]) | {f for f in now if f in m["stamp"] and now[f] != m["stamp"][f]})
    return f"{', '.join(changed[:3])}{' …' if len(changed) > 3 else ''} changed since it was built" if changed else None


def _classifier(ws: Path, s: Settings, p: Pipeline) -> Classifier | None:  # the run's, as the index keeps it, with the name model loaded again
    f = Path(ws) / INDEX / "kind.pkl"
    return Classifier(**pickle.loads(f.read_bytes()), names=name_model(s, p.kind)) if f.exists() and p.kind else None


def look_up(ws: Path, s: Settings, p: Pipeline, values: dict[str, str] | None = None, record: str | None = None,
            at_least: float | None = None, most: int = 20) -> dict:
    """The entities a record would be compared with, as an increment of it alone compares it, best first: `values` by
    the file's column names, or `record`, a stored record's ID, looked up as if it were new (itself left out). Each
    entity at `at_least` points or more (default: the review floor) with its best record, its points, each comparison's
    level, the rule that would join it, and the keys that listed it; at most `most`. Also the record as compared, and
    what was looked up, how, and how long each part took. O(G·(log N + b) + C·K·L²)."""
    ws, uid, clock = Path(ws), s.data.unique_id, {}
    m = manifest(ws)
    if (why := stale(ws, m)) is not None:
        raise InputError(f"the index of {ws}: {why}", fix=f"build it: nayose build index --workspace {ws}")
    t = time.perf_counter()
    fitted, model = _pipeline(ws, s, p, m["columns"]), run_model(ws)
    con, _ = connect(s.compute)
    try:
        con.execute(f"ATTACH {lit(ws / INDEX / 'index.duckdb')} AS ix (READ_ONLY)")
        clock["open"] = time.perf_counter() - t
        t = time.perf_counter()
        query = _query(con, ws, s, fitted, values, record)
        con.register("er_q", query)
        con.execute("CREATE TEMP TABLE qry AS SELECT * FROM er_q")
        con.unregister("er_q")
        me, extra = query[uid].iloc[0], 0 if record is not None else 1  # a stored record as new: the store holds it once already
        clock["prepare"] = time.perf_counter() - t
        t = time.perf_counter()
        found, checked = _candidates(con, fitted, uid, me, extra)
        clock["keys"] = time.perf_counter() - t
        t = time.perf_counter()
        gated = _gate(con, fitted, model, uid, me, found, checked, m["records"] + extra)
        found = {**found, **gated}
        rules = _rules(con, fitted, uid, me, checked, extra)
        clock["rules"] = time.perf_counter() - t
        t = time.perf_counter()
        ids = sorted({*found, *rules} - {me})
        scored = _scored(con, model, uid, me, ids, m["records"] + extra)
        clock["score"] = time.perf_counter() - t
    finally:
        con.close()
    line, floor = fitted.fs.min_match_weight, review_floor(fitted) if at_least is None else at_least
    rows = []
    if len(scored):
        named = np.zeros(len(scored), dtype=bool) if fitted.fs.needs else np.ones(len(scored), dtype=bool)
        for c in fitted.fs.needs:  # the name check (named_sql): a name compared on both sides
            named |= (scored[f"gamma_{c}"] >= 0).to_numpy()
        scored = scored.assign(named=named, keys=[sorted(found.get(x, ())) for x in scored["uid"]])
        joins = {}  # each entity's rule: one that joins any of its records, the first in order (a dict: a frame column would hold a truthy NaN)
        for x in scored.itertuples():
            if x.uid in rules and (x.entity not in joins or rules[x.uid][0] < joins[x.entity][0]):
                joins[x.entity] = rules[x.uid]
        best = scored.sort_values(["weight", "uid"], ascending=[False, True]).drop_duplicates("entity")
        for x in best.itertuples():
            rule = joins[x.entity][1] if x.entity in joins else None
            if x.weight < floor and not rule:
                continue
            rows.append(dict(entity=x.entity, record=x.uid, points=round(float(x.weight), 2), likely=bool(x.weight >= line and x.named) or rule is not None,
                             rule=rule, keys=x.keys, compared=x.compared, records=int((scored["entity"] == x.entity).sum()), shown=x.shown))
    rows.sort(key=lambda r: (-(r["rule"] is not None), -r["points"]))
    view = query.iloc[0]
    return dict(record={k: (None if pd.isna(view.get(k)) else str(view.get(k))) for k in (uid, *SHOWN, "kind") if k in view},
                entities=rows[:most], found=len(rows), candidates=len(ids), likely=sum(r["likely"] for r in rows),
                checked=checked, seconds={k: round(v, 4) for k, v in clock.items()},
                index=dict(built_at=m["built_at"], records=m["records"]))


def _query(con: duckdb.DuckDBPyConnection, ws: Path, s: Settings, p: Pipeline, values: dict | None, record: str | None) -> pd.DataFrame:
    """The record looked up, as a run prepares it: a stored one's row as the index holds it, or the values given, by the
    file's column names, read as the reader reads a value and prepared with the run's classifier."""
    uid = s.data.unique_id
    if record is not None:
        row = con.execute(f"SELECT * EXCLUDE (h, entity, resolved) FROM ix.records WHERE h = hash(?::VARCHAR) AND {q(uid)} = ?", [record, record]).df()
        if row.empty:
            raise InputError(f"{record}: no record of the run has that ID", fix="give a record ID the run holds, or the record's values")
        return row.astype("string")
    sources = sorted({c for d in p.fs.standardize.derived for alt in d.sources for c in alt})
    if unknown := sorted(set(values or {}) - set(sources)):
        raise InputError(f"{', '.join(unknown)}: no field reads that column", fix=f"the columns a field reads: {', '.join(sources)}")
    nulls = frozenset(s.input.nulls)
    row = pd.DataFrame({uid: [QUERY], **{c: [tidy(str(v), nulls, False)[0] if (v := (values or {}).get(c)) not in (None, "") else None] for c in sources}}, dtype="string")
    if row.drop(columns=uid).isna().all(axis=1).iloc[0]:
        raise InputError("no value given", fix="give at least a name or a phone, as COLUMN=VALUE")
    rules, fs, probe = p.rules, p.fs, p.probe
    normalized, used = [*rules.normalized(), *fs.normalized(), *probe.normalized()], rules.used() | fs.used() | probe.used()
    return prepare(fs.standardize, row, normalized, used, kind=_classifier(ws, s, p)).astype("string")


def _candidates(con: duckdb.DuckDBPyConnection, p: Pipeline, uid: str, me: str, extra: int = 1) -> tuple[dict[str, set[str]], list[dict]]:
    """The stored records each generator lists with the record (its blocks and windows), and per generator what was
    looked up: rows found, or why none (a key the record lacks, a block too big). `extra`: what the record adds to a
    block, 1 for a new one, 0 for a stored one looked up as new. O(G·(log N + b))."""
    found: dict[str, set[str]] = {}
    checked, hashes = [], {}
    tables = dict(_tables(p))
    for name, x in tables.items():
        if isinstance(x, (KeyBlocker, DeletionKeys)):
            sql = _rows(x, "qry", uid)
            hashes[name] = [h for (h,) in con.execute(f"SELECT DISTINCT h FROM ({sql})").fetchall()]
    sizes = {(t, h): n for t, h, n in con.execute(f"SELECT t, h, n FROM ix.big WHERE {' OR '.join(f'(t = {lit(t)} AND h IN ({', '.join(map(str, hs))}))' for t, hs in hashes.items() if hs) or 'FALSE'}").fetchall()}
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
        rows = con.execute(f"SELECT DISTINCT uid FROM ix.{name} WHERE h IN ({', '.join(map(str, normal))})").fetchall() if normal else []
        for (v,) in rows:
            if v != me:
                found.setdefault(v, set()).add(x.name)
        checked.append(dict(key=x.name, found=len(rows), **({"big": [dict(h=h, records=sizes[(name, h)] + extra) for h in big]} if big else {})))
    return found, checked


def _held(con: duckdb.DuckDBPyConnection, x: SortedNeighbourhood) -> bool:  # whether the record has a value for the window's key
    return con.execute(f"SELECT {q(x.key.name)} IS NOT NULL FROM qry").fetchall()[0][0]


def _window(con: duckdb.DuckDBPyConnection, name: str, x: SortedNeighbourhood, me: str, key: str | None) -> list[str]:
    """The window-1 records on each side of the record in (key, uid) order, as the run's window places it among them:
    a bisect in the sparse table, then one read of the rows between two of its keys. O(log N + SPARSE)."""
    if key is None or x.window < 2:
        return []
    sparse = con.execute(f"SELECT pos, key, uid FROM ix.{name}_sparse ORDER BY pos").fetchall()
    at = bisect_left([(k, u) for _, k, u in sparse], (key, me))  # the first sparse row at or after the record
    lo = sparse[at - 1][0] if at else 1
    hi = sparse[at][0] if at < len(sparse) else lo + SPARSE
    block = con.execute(f"SELECT pos, key, uid FROM ix.{name} WHERE pos BETWEEN {lo} AND {hi} ORDER BY pos").fetchall()
    start = next((pos for pos, k, u in block if (k, u) >= (key, me)), block[-1][0] + 1 if block else lo)  # its place: before the first row past it, else after the last
    w = x.window - 1
    rows = con.execute(f"SELECT key, uid FROM ix.{name} WHERE pos BETWEEN {start - w - 1} AND {start + w} ORDER BY pos").fetchall()
    rows = [(k, u) for k, u in rows if u != me]  # a stored record looked up as new: the window as if it weren't there
    before = [u for k, u in rows if (k, u) < (key, me)][-w:]
    after = [u for k, u in rows if (k, u) > (key, me)][:w]
    return before + after


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
            t = names[c["key"]]
            rows = con.execute(f"SELECT DISTINCT uid, hu FROM ix.{t} WHERE h = {b['h']} ORDER BY hu LIMIT {m}").fetchall()
            ranked = sorted([*(r for r in rows if r[0] != me), (me, mine)], key=lambda r: r[1])[:m]  # the block's lowest hashes, the record among them once
            sample = [u for u, hu in ranked if u != me and u not in found]
            scored = _scored(con, model, uid, me, sample, n)
            b.update(sampled=len(sample), best=round(float(scored["weight"].max()), 2) if len(scored) else None)
            if len(sample) and (scored["weight"] >= floor).any():
                b["decision"] = "kept"
                for (v,) in con.execute(f"SELECT DISTINCT uid FROM ix.{t} WHERE h = {b['h']}").fetchall():
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
        size = con.execute(f"SELECT coalesce(max(n), 0) FROM ix.big WHERE t = {lit(name)} AND h = {h[0][0]}").fetchall()[0][0]
        if size + extra >= m:
            checked.append(dict(key=f"rule {rule.name}", found=0, why=f"its value is on {size + extra:,} records: the rule doesn't trust it"))
            continue
        hus = [hu for (hu,) in con.execute(f"SELECT hu FROM ix.{name} WHERE h = {h[0][0]}").fetchall()]  # literals: the records table read by its zone maps
        hits = con.execute(f"""SELECT r.{q(uid)}, r.resolved FROM qry l JOIN (SELECT * FROM ix.records WHERE h IN ({', '.join(map(str, hus))})) r
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
    n records. With each its entity, its levels in words, and the fields a person reads. O(|ids|·K·L²)."""
    if not ids:
        return pd.DataFrame(columns=["uid", "entity", "weight", "compared", "shown"])
    cols, u = sorted(read_by(model)), q(uid)
    hashes = [h for (h,) in con.execute("SELECT hash(x) FROM unnest(?::VARCHAR[]) t(x)", [ids]).fetchall()]
    con.execute(f"CREATE OR REPLACE TEMP TABLE er_c AS SELECT * EXCLUDE (h) FROM ix.records WHERE h IN ({', '.join(map(str, hashes))})")
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
