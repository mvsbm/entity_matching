"""Candidate generation (blocking): which pairs are worth scoring, as SQL on a columnar engine (DuckDB). The records
are a pandas frame (registered, zero-copy) or the name of a table in `con`, so the same code serves any size.
Only pairs that touch a query record (one an earlier stage left unresolved) are produced, so leftovers can still join
existing clusters. `query=None` makes every record a query; with `clusters`, pairs already inside one cluster are
then dropped, so two clusters can join too.

KeyBlocker            all keys equal                                      self-join             O(N + P)
SortedNeighbourhood   sort by key, pair records within `window` places    window lead()         O(N log N + N·w)
DeletionKeys          the value or a one-character deletion of it equal   UNNEST + self-join    O(N·L + P)
TfidfNeighbours       char n-gram TF-IDF, k nearest by cosine (N²: development only, in Python)   O(N·L + U·N·q)

Two values one edit apart (a substitution, an insertion, a deletion or an adjacent swap) always share a deletion key.
"""
import re
import time
import uuid
from collections.abc import Iterable

import duckdb
import numpy as np
import pandas as pd

from er.config import Blocker, Budget, DeletionKeys, KeyBlocker, OverBudget, SortedNeighbourhood, TfidfNeighbours, keys_of

_CON: duckdb.DuckDBPyConnection | None = None  # for pandas input when the caller passes no connection


def q(name: str) -> str:  # a quoted SQL identifier
    return '"' + name.replace('"', '""') + '"'


class Records:
    """The records as a relation in `con`: a registered pandas frame or an existing table; `cluster` adds a column
    holding each record's previous cluster, `query` a table of the query ids."""

    def __init__(self, records: pd.DataFrame | str, uid: str, con: duckdb.DuckDBPyConnection | None = None,
                 query: Iterable[str] | None = None, clusters: pd.Series | str | None = None, columns: Iterable[str] | None = None):
        global _CON
        self.con = con or (_CON := _CON or duckdb.connect())
        self.uid, self.views = uid, []
        self.frame = records if isinstance(records, pd.DataFrame) else None
        base = self._view(records) if isinstance(records, pd.DataFrame) else q(records)
        if clusters is not None:  # a Series uid → cluster, or a table with columns uid and cluster_id
            c = (self._view(pd.DataFrame({uid: clusters.index.to_numpy(), "cluster_id": clusters.to_numpy()}).astype("string"))
                 if isinstance(clusters, pd.Series) else q(clusters))
            cols = ", ".join(f"t.{q(x)}" for x in dict.fromkeys([uid, *columns])) if columns else "t.*"  # the copy holds only what is read
            base = self._temp(f"SELECT {cols}, c.cluster_id AS __cluster FROM {base} t JOIN {c} c USING ({q(uid)})")
        self.table, self.cluster = base, clusters is not None
        self.query = (None if query is None else q(query) if isinstance(query, str)  # a table of query ids, or the ids
                      else self._view(pd.DataFrame({uid: list(query)}, dtype="string")))

    def _view(self, df: pd.DataFrame) -> str:
        name = f"er_{uuid.uuid4().hex[:12]}"
        self.con.register(name, df)
        self.views.append(("view", name))
        return name

    def _temp(self, sql: str) -> str:
        name = f"er_{uuid.uuid4().hex[:12]}"
        self.con.execute(f"CREATE TEMP TABLE {name} AS {sql}")
        self.views.append(("table", name))
        return name

    def close(self) -> None:
        for kind, name in reversed(self.views):
            self.con.unregister(name) if kind == "view" else self.con.execute(f"DROP TABLE IF EXISTS {name}")

    def asked(self, t: str) -> str:  # the query's rows of t
        return f"(SELECT * FROM {t} WHERE {q(self.uid)} IN (SELECT {q(self.uid)} FROM {self.query}))"

    def filters(self, a: str, b: str, query: bool = True) -> str:  # the query and cluster conditions on a pair (a, b)
        u = q(self.uid)
        out = [f"({a}.{u} IN (SELECT {u} FROM {self.query}) OR {b}.{u} IN (SELECT {u} FROM {self.query}))"] if self.query and query else []
        return " AND ".join(out + ([f"{a}.__cluster <> {b}.__cluster"] if self.cluster else [])) or "TRUE"


def _deletions_sql(col: str) -> str:  # the value and each one-character deletion of it, distinct
    return f"list_distinct(list_prepend({col}, list_transform(range(1, length({col}) + 1), lambda i: {col}[:i - 1] || {col}[i + 1:])))"


def _filled(cols: Iterable[str], alias: str = "") -> str:
    return " AND ".join(f"{alias}{q(c)} IS NOT NULL" for c in cols) or "TRUE"


def pairs_sql(b: Blocker, r: Records) -> str:
    """One generator's pairs as SQL: columns l < r (uid strings), each pair once."""
    t, u = r.table, q(r.uid)
    cl = ", __cluster" if r.cluster else ""
    match b:
        case KeyBlocker():
            on = " AND ".join(f"a.{q(k.name)} = b.{q(k.name)}" for k in b.keys)
            if r.query:  # the query's rows against all: O(|Q|·b) plus a scan, whatever N
                return (f"SELECT DISTINCT least(a.{u}, b.{u}) AS l, greatest(a.{u}, b.{u}) AS r FROM {r.asked(t)} a JOIN {t} b "
                        f"ON {on} AND a.{u} <> b.{u} WHERE {r.filters('a', 'b', query=False)}")
            return f"SELECT a.{u} AS l, b.{u} AS r FROM {t} a JOIN {t} b ON {on} AND a.{u} < b.{u} WHERE {r.filters('a', 'b')}"
        case SortedNeighbourhood():
            k = q(b.key.name)
            leads = ", ".join(f"lead({u}, {o}) OVER w AS b{o}" + (f", lead(__cluster, {o}) OVER w AS c{o}" if r.cluster else "")
                              for o in range(1, b.window))
            arms = " UNION ALL ".join(f"SELECT {u} AS a, b{o} AS b" + (f", __cluster AS ca, c{o} AS cb" if r.cluster else "") +
                                      f" FROM s WHERE b{o} IS NOT NULL" for o in range(1, b.window))
            touch = [f"(x.a IN (SELECT {u} FROM {r.query}) OR x.b IN (SELECT {u} FROM {r.query}))"] if r.query else []
            cond = " AND ".join(touch + (["x.ca <> x.cb"] if r.cluster else [])) or "TRUE"
            return (f"WITH s AS (SELECT {u}{cl}, {leads} FROM {t} WHERE {k} IS NOT NULL WINDOW w AS (ORDER BY {k}, {u})) "
                    f"SELECT DISTINCT least(x.a, x.b) AS l, greatest(x.a, x.b) AS r FROM ({arms}) x WHERE {cond}") if b.window > 1 else \
                f"SELECT NULL::VARCHAR AS l, NULL::VARCHAR AS r WHERE FALSE"
        case DeletionKeys():
            k, within = q(b.key.name), [q(w.name) for w in b.within]
            cols = ", ".join([u, *within]) + cl
            filled = _filled([b.key.name, *(w.name for w in b.within)])
            variants = lambda src: f"(SELECT {cols}, unnest({_deletions_sql(k)}) AS __dk FROM {src} WHERE {filled})"
            same = " AND ".join(["a.__dk = b.__dk", *(f"a.{w} = b.{w}" for w in within)])
            if r.query:  # the query's rows against all
                return (f"SELECT DISTINCT least(a.{u}, b.{u}) AS l, greatest(a.{u}, b.{u}) AS r FROM {variants(r.asked(t))} a "
                        f"JOIN {variants(t)} b ON {same} AND a.{u} <> b.{u} WHERE {r.filters('a', 'b', query=False)}")
            return (f"WITH v AS {variants(t)} "
                    f"SELECT DISTINCT a.{u} AS l, b.{u} AS r FROM v a JOIN v b ON {same} AND a.{u} < b.{u} WHERE {r.filters('a', 'b')}")
    raise TypeError(f"{b.name}: no SQL generator for {type(b).__name__}")


def _tfidf(b: TfidfNeighbours, r: Records) -> pd.DataFrame:  # N² by design: development files only
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    uid = r.uid
    base = (r.frame if r.frame is not None else r.con.sql(f"SELECT * FROM {r.table}").df()).dropna(subset=[b.key.name])
    base = base[[uid, b.key.name]].reset_index(drop=True)
    query = set(r.con.sql(f"SELECT {q(uid)} FROM {r.query}").df()[uid]) if r.query else None
    qi = np.arange(len(base)) if query is None else np.flatnonzero(base[uid].isin(query).to_numpy())
    if not len(qi) or len(base) < 2:
        return pd.DataFrame({"l": pd.Series(dtype="string"), "r": pd.Series(dtype="string")})
    x = TfidfVectorizer(analyzer="char", ngram_range=b.ngram).fit_transform(base[b.key.name].astype(str))
    dist, idx = NearestNeighbors(n_neighbors=min(b.k + 1, len(base)), metric="cosine").fit(x).kneighbors(x[qi])
    ids = base[uid].to_numpy(dtype=object)
    keep = ((1 - dist) >= b.min_cosine).ravel()
    a, c = np.repeat(ids[qi], idx.shape[1])[keep], ids[idx.ravel()][keep]
    lo, hi = np.where(a < c, a, c), np.where(a < c, c, a)
    out = pd.DataFrame({"l": lo, "r": hi}).astype("string")
    return out[out["l"] != out["r"]].drop_duplicates(ignore_index=True)


def estimate(b: Blocker, records: pd.DataFrame | str, n_query: int, con: duckdb.DuckDBPyConnection | None = None,
             uid: str | None = None) -> dict[str, object]:
    """Work before any join: candidate pairs (an upper bound) and the largest block, by group-by. O(N)."""
    r = records if isinstance(records, Records) else Records(records, uid or "", con)
    t, n = r.table, r.con.execute(f"SELECT count(*) FROM {r.table}").fetchall()[0][0]
    try:
        match b:
            case KeyBlocker():
                cols = ", ".join(q(k.name) for k in b.keys)
                p, big = r.con.execute(f"SELECT coalesce(sum(c * (c - 1) // 2), 0), coalesce(max(c), 0) FROM "
                                       f"(SELECT count(*) AS c FROM {t} WHERE {_filled(k.name for k in b.keys)} GROUP BY {cols})").fetchall()[0]
                return dict(big_o="O(N + P)", filled=f"O({n:,} + {int(p):,})", est_pairs=int(p), largest_block=int(big))
            case SortedNeighbourhood():
                m = r.con.execute(f"SELECT count({q(b.key.name)}) FROM {t}").fetchall()[0][0]
                return dict(big_o="O(N log N + N·w)", filled=f"O({m:,}·log {m:,} + {m:,}·{b.window})",
                            est_pairs=m * (b.window - 1), largest_block=b.window)
            case DeletionKeys():  # Σ C(k,2) over the key blocks, less the repeats: identical values share all their keys
                k, within = q(b.key.name), [q(w.name) for w in b.within]
                filled = _filled([b.key.name, *(w.name for w in b.within)])
                group = ", ".join(["__dk", *within])
                p, big = r.con.execute(f"""
                    WITH v AS (SELECT {', '.join(within + ['unnest(' + _deletions_sql(k) + ') AS __dk']) } FROM {t} WHERE {filled}),
                         blocks AS (SELECT count(*) AS c FROM v GROUP BY {group}),
                         same AS (SELECT count(*) AS n, any_value(len({_deletions_sql(k)})) - 1 AS extra FROM {t} WHERE {filled}
                                  GROUP BY {', '.join([k, *within])})
                    SELECT (SELECT coalesce(sum(c * (c - 1) // 2), 0) FROM blocks) - (SELECT coalesce(sum(extra * n * (n - 1) // 2), 0) FROM same),
                           (SELECT coalesce(max(c), 0) FROM blocks)""").fetchall()[0]
                return dict(big_o="O(N·L + P)", filled=f"O({n:,}·L + {int(p):,})", est_pairs=int(p), largest_block=int(big))
            case TfidfNeighbours():
                m, length = r.con.execute(f"SELECT count({q(b.key.name)}), avg(length({q(b.key.name)})) FROM {t}").fetchall()[0]
                per = (length or 0) * (b.ngram[1] - b.ngram[0] + 1)  # n-grams per record, roughly
                return dict(big_o="O(N·L + U·N·q)", filled=f"O({m:,}·L + {n_query:,}·{m:,}·{per:.0f})",
                            est_pairs=n_query * b.k, largest_block=b.k + 1)
    finally:
        if r is not records:
            r.close()


def estimate_touching(b: Blocker, r: Records) -> dict[str, object]:
    """For an increment: the pairs a generator would make that touch the query records (an upper bound), and the
    largest block they fall in. Only the blocks the query's keys reach are counted: a join against the query's distinct
    keys, then a group-by. O(N) to scan the key columns, plus the touched blocks; no group-by of the whole file."""
    t, u = r.table, q(r.uid)
    asked = f"sum(({u} IN (SELECT {u} FROM {r.query}))::INT)"
    total = "SELECT coalesce(sum(c * (c - 1) // 2 - (c - qn) * (c - qn - 1) // 2), 0), coalesce(max(c), 0) FROM b"
    match b:
        case KeyBlocker():
            cols = ", ".join(q(k.name) for k in b.keys)
            filled = _filled(k.name for k in b.keys)
            sql = (f"WITH k AS (SELECT DISTINCT {cols} FROM {r.asked(t)} WHERE {filled}), "
                   f"b AS (SELECT count(*) AS c, {asked} AS qn FROM {t} JOIN k USING ({cols}) GROUP BY {cols}) {total}")
        case DeletionKeys():
            k, within = q(b.key.name), [q(w.name) for w in b.within]
            filled, keys = _filled([b.key.name, *(w.name for w in b.within)]), ", ".join(["__dk", *within])
            variants = lambda src, uid: f"(SELECT {uid}{', '.join(within + [f'unnest({_deletions_sql(k)}) AS __dk'])} FROM {src} WHERE {filled})"
            sql = (f"WITH k AS (SELECT DISTINCT {keys} FROM {variants(r.asked(t), '')}), "
                   f"b AS (SELECT count(*) AS c, {asked} AS qn FROM {variants(t, u + ', ')} v JOIN k USING ({keys}) GROUP BY {keys}) {total}")
        case SortedNeighbourhood():  # each query record pairs with up to window − 1 records on either side
            m = r.con.execute(f"SELECT count({q(b.key.name)}) FROM {r.asked(t)}").fetchall()[0][0]
            return dict(big_o="O(N log N + Δ·w)", filled=f"O(N log N + {m:,}·{b.window})", est_pairs=2 * m * (b.window - 1), largest_block=b.window)
        case _:
            m = r.con.execute(f"SELECT count(*) FROM {r.query}").fetchall()[0][0]
            return estimate(b, r, m)
    p, big = r.con.execute(sql).fetchall()[0]
    return dict(big_o="O(N + Δ·b)", filled=f"O(N + {int(p):,})", est_pairs=int(p), largest_block=int(big))


def generate(b: Blocker, records: pd.DataFrame | str, uid: str, query: Iterable[str] | None,
             con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """One generator's pairs, uid_l < uid_r, as pandas (small files and tests)."""
    r = Records(records, uid, con, query)
    try:
        out = _tfidf(b, r) if isinstance(b, TfidfNeighbours) else r.con.sql(pairs_sql(b, r)).df()
    finally:
        r.close()
    return out.set_axis([f"{uid}_l", f"{uid}_r"], axis=1).astype("string")


def found_by(cands: pd.DataFrame, names: Iterable[str]) -> np.ndarray:  # the pairs any of these generators found
    whole = "(?:^|\\+)(?:" + "|".join(map(re.escape, names)) + ")(?:\\+|$)"  # whole names: person_name ≠ sn_person_name
    return cands["sources"].str.contains(whole, regex=True).to_numpy(bool)


def candidates(blockers: tuple[Blocker, ...], records: pd.DataFrame | str, uid: str, query: Iterable[str] | str | None,
               budget: Budget, clusters: pd.Series | str | None = None, con: duckdb.DuckDBPyConnection | None = None,
               into: str | None = None, touching: bool = False) -> tuple[pd.DataFrame | str, pd.DataFrame]:
    """The union of all generators, with the generators that found each pair in `sources`, and a per-generator report.
    Stops before any join if a generator is over budget. With `into`, the union is written to that table in `con` and
    its name returned instead of a frame, so nothing of size C reaches pandas. `touching` (an increment, with `query` the
    batch): the budget counts only the pairs touching the batch, against the same allowance per record as a full run.
    A pair has two records, so a full run within budget gives a record 2 × max_pairs_per_record pairs on average."""
    if not blockers:
        raise ValueError("no candidate generator")
    assert len(blockers) < 63, "one bit per generator"
    assert query is not None or not touching, "touching needs the batch as the query"
    r = Records(records, uid, con, query, clusters, columns=[k.name for b in blockers for k in keys_of(b)])
    l, rr = f"{uid}_l", f"{uid}_r"
    try:
        n_query = r.con.execute(f"SELECT count(*) FROM {r.query or r.table}").fetchall()[0][0]
        n_records = r.con.execute(f"SELECT count(*) FROM {r.table}").fetchall()[0][0]
        report, parts = [], []
        limit = budget.max_pairs(2 * n_query if touching else n_records)
        for i, b in enumerate(blockers):
            est = estimate_touching(b, r) if touching else estimate(b, r, n_query)
            if est["est_pairs"] > limit or est["largest_block"] > budget.max_block_size:
                raise OverBudget(f"{b.name}: {est}")
            t = time.perf_counter()
            if isinstance(b, TfidfNeighbours):
                pairs = _tfidf(b, r)
                if r.cluster:  # TF-IDF is computed in Python, so the cluster filter is applied here
                    cl = r.con.sql(f"SELECT {q(uid)}, __cluster FROM {r.table}").df().set_index(uid)["__cluster"]
                    pairs = pairs[pairs["l"].map(cl).to_numpy() != pairs["r"].map(cl).to_numpy()]
                table = r._temp(f"SELECT * FROM {r._view(pairs)}")
            else:
                table = r._temp(pairs_sql(b, r))
            n = r.con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
            report.append(dict(generator=b.name, **est, pairs=n, seconds=round(time.perf_counter() - t, 3)))
            parts.append(f"SELECT l, r, {1 << i}::BIGINT AS bit FROM {table}")
        union = f"SELECT l, r, bit_or(bit) AS bits FROM ({' UNION ALL '.join(parts)}) GROUP BY l, r"
        bits = r._temp(union)
        names = {m: "+".join(g.name for i, g in enumerate(blockers) if m >> i & 1)
                 for (m,) in r.con.execute(f"SELECT DISTINCT bits FROM {bits}").fetchall()}
        cases = " ".join(f"WHEN {m} THEN '{s}'" for m, s in names.items())
        out = f"SELECT l AS {q(l)}, r AS {q(rr)}, CASE bits {cases} END AS sources FROM {bits} ORDER BY l, r"
        if into:
            r.con.execute(f"CREATE OR REPLACE TABLE {q(into)} AS {out}")
            result = into
        else:
            result = r.con.sql(out).df().astype("string")
    finally:
        r.close()
    return result, pd.DataFrame(report)
