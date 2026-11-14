"""Candidate generation (blocking): which pairs are worth scoring, as SQL on a columnar engine (DuckDB). The records
are a pandas frame (registered, zero-copy) or the name of a table in `con`, so the same code serves any size.
Only pairs that touch a query record (one an earlier stage left unresolved) are produced, so leftovers can still join
existing clusters. `query=None` makes every record a query; with `clusters`, pairs already inside one cluster are
then dropped, so two clusters can join too.

KeyBlocker            all keys equal                                      self-join             O(N + P)
SortedNeighbourhood   sort by key, pair records within `window` places    window lead()         O(N log N + N·w)
DeletionKeys          the value or a one-character deletion of it equal   UNNEST + self-join    O(N·L + P)
EditKeys              values 1 to k edits apart (Levenshtein)             PassJoin + cpdist     O(U·k³ + S + P)
TfidfNeighbours       char n-gram TF-IDF, k nearest by cosine (N²: development only, in Python)   O(N·L + U·N·q)

Two values one edit apart (a substitution, an insertion, a deletion or an adjacent swap) always share a deletion key.

A block is the records sharing one key value (for deletion keys, one deletion variant within its area). A block with
more pairs than Budget.sample_pairs (64+ records) is oversized: given a `gate`, candidates() first scores a sample of
its pairs that no other block listed, and joins it in full only if a sampled pair reaches the floor; otherwise it is
skipped and reported. Yield falls as blocks grow, and a placeholder's block (a dummy phone) yields nothing, so this
spends the work where matches are, with no fixed cap.
"""
import re
import time
import uuid
from collections.abc import Callable, Iterable

import duckdb
import numpy as np
import pandas as pd

from er.config import Blocker, Budget, DeletionKeys, EditKeys, InputError, KeyBlocker, SortedNeighbourhood, TfidfNeighbours, keys_of, q
from er.strings import connect

_CON: duckdb.DuckDBPyConnection | None = None  # for pandas input when the caller passes no connection


class Records:
    """The records as a relation in `con`: a registered pandas frame or an existing table; `cluster` adds a column
    holding each record's previous cluster, `query` a table of the query ids."""

    def __init__(self, records: pd.DataFrame | str, uid: str, con: duckdb.DuckDBPyConnection | None = None,
                 query: Iterable[str] | None = None, clusters: pd.Series | str | None = None, columns: Iterable[str] | None = None):
        global _CON
        self.con = con or (_CON := _CON or connect()[0])
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
        self.touching = False                 # the query is a batch joined against all (an increment), not most of the file
        self.dk: dict[tuple, str] = {}        # deletion-key rows per (key, within), built once (variants)
        self.near: dict[tuple, str] = {}      # value pairs within k edits per (key, within, k), verified once (near_values)
        self.most = 2**62                     # a value held by this many records or more pairs by no edit key (candidates: the oversized size)
        self.only: str | None = None          # SQL on a pair's l and r: a pair it is false for is never listed (candidates)

    def variants(self, b: DeletionKeys) -> str:
        """b's rows, one per deletion key (__dk) of its value (__v), with the uid, the within columns and the cluster:
        unnested once, then read by every count, join and sample of these records. O(N·L) once. When touching (an
        increment), only the blocks the batch's keys reach are kept, all an increment reads, so memory follows the batch."""
        at = (b.key.name, tuple(w.name for w in b.within))
        if at not in self.dk:
            k, within, u = q(b.key.name), [q(w.name) for w in b.within], q(self.uid)
            cols = [u] * bool(self.uid) + within + ["__cluster"] * self.cluster + [f"{k} AS __v", f"unnest({deletions_sql(k)}) AS __dk"]
            rows = lambda where="": f"SELECT {', '.join(cols)} FROM {self.table} WHERE {_filled([b.key.name, *(w.name for w in b.within)])}{where}"
            sql = rows()
            if self.touching and self.query:
                keys = ", ".join(["__dk", *within])
                sql = (f"SELECT x.* FROM ({sql}) x SEMI JOIN (SELECT DISTINCT {keys} FROM ({rows(f' AND {u} IN (SELECT {u} FROM {self.query})')})) z "
                       f"USING ({keys})")
            self.dk[at] = self._temp(sql)
        return self.dk[at]

    def near_values(self, b: EditKeys, most: int, probe: str | None = None) -> str:
        """b's distinct value pairs (with their within values) 1 to b.edits edits apart, as a table (w…, v, x, nv, nx):
        the values and their records. PassJoin (Li et al., VLDB 2011): a value cut into k + 1 segments keeps one of them
        whole through k edits, at a position at most k from its own, in a value at most k longer or shorter; so the
        values sharing such a segment are every candidate, and rapidfuzz's cpdist checks them on all cores. A value of
        fewer than 2(k + 1) characters (k edits in so short a value make another word, and its one-letter segments would
        pair it with nearly every value), or held by `most` records or more (a placeholder's block), pairs with none. With
        `probe` (a table of uids), only the pairs with a value one of its records holds. O(U·k³) segment rows, plus the
        candidates S checked."""
        at = (b.key.name, tuple(w.name for w in b.within), b.edits, probe)
        if at not in self.near:
            from rapidfuzz.distance import Levenshtein
            from rapidfuzz.process import cpdist
            k, parts, within = b.edits, b.edits + 1, [q(w.name) for w in b.within]
            w_ = "".join(f"{w}, " for w in within)
            values = self._temp(f"""SELECT *, row_number() OVER () AS id FROM (SELECT {w_}{q(b.key.name)} AS v, count(*) AS n, length({q(b.key.name)}) AS len FROM {self.table}
                WHERE {_filled([b.key.name, *(w.name for w in b.within)])} GROUP BY ALL HAVING count(*) < {most} AND length({q(b.key.name)}) >= {2 * parts})""")  # an id per value: only ids cross into Python
            seg = lambda length, i: (f"({length}) // {parts} + ({i} >= {parts} - ({length}) % {parts})::INT",  # segment i of a value this long: its length, its start
                                     f"1 + {i} * (({length}) // {parts}) + greatest(0, {i} - ({parts} - ({length}) % {parts}))")
            index = f"SELECT {w_}v, id, len AS l, i, v[{seg('len', 'i')[1]} : {seg('len', 'i')[1]} + {seg('len', 'i')[0]} - 1] AS s FROM (SELECT *, unnest(range({parts})) AS i FROM {values})"
            # multi-match-aware starts (Li et al., §4.2): segment i of a value l long, in one len − l longer, only from
            # max(start − i, start + len − l − (k − i)) to min(start + i, start + len − l + (k − i)); each a complete window
            lo, hi = f"greatest(st - i, st + len - l - ({k} - i))", f"least(st + i, st + len - l + ({k} - i))"
            asked = (f"(SELECT * FROM {values} WHERE ({w_}v) IN (SELECT ({w_}{q(b.key.name)}) FROM {self.table} WHERE {q(self.uid)} IN "
                     f"(SELECT {q(self.uid)} FROM {probe})))" if probe else values)
            probe_sql = (f"SELECT {w_}v AS x, id AS ix, l, i, x[p : p + sl - 1] AS s FROM (SELECT *, unnest(range({lo}, {hi} + 1)) AS p FROM "
                     f"(SELECT *, {seg('l', 'i')[1]} AS st, {seg('l', 'i')[0]} AS sl FROM (SELECT *, unnest(range({parts})) AS i FROM "  # nested: unnests in one SELECT are zipped
                     f"(SELECT {w_}v, id, len, unnest(range(greatest({parts}, len - {k}), len + {k + 1})) AS l FROM {asked})))) "
                     f"WHERE p >= 1 AND p + sl - 1 <= length(x)")
            on = " AND ".join([*(f"a.{w} = c.{w}" for w in within), "a.l = c.l", "a.i = c.i", "a.s = c.s"])
            ids = self.con.execute(f"""SELECT DISTINCT least(a.id, c.ix) AS a, greatest(a.id, c.ix) AS c
                FROM ({index}) a JOIN ({probe_sql}) c ON {on} AND a.v <> c.x""").fetchnumpy()
            a, c = ids["a"].astype(np.int64), ids["c"].astype(np.int64)
            if len(a):
                vs = np.array([None, *(v for v, in self.con.execute(f"SELECT v FROM {values} ORDER BY id").fetchall())], dtype=object)  # vs[id]
                d = np.concatenate([cpdist(vs[a[i:i + 1_000_000]].tolist(), vs[c[i:i + 1_000_000]].tolist(), scorer=Levenshtein.distance,
                                           score_cutoff=k, workers=-1) for i in range(0, len(a), 1_000_000)])
                a, c = a[d <= k], c[d <= k]
            kept = self._view(pd.DataFrame({"a": a, "c": c}))
            first = "x.v < y.v"  # each pair as before: its values in order, each with its records
            self.near[at] = self._temp(f"""SELECT {"".join(f"x.{w}, " for w in within)}least(x.v, y.v) AS v, greatest(x.v, y.v) AS x,
                CASE WHEN {first} THEN x.n ELSE y.n END AS nv, CASE WHEN {first} THEN y.n ELSE x.n END AS nx
                FROM {kept} p JOIN {values} x ON x.id = p.a JOIN {values} y ON y.id = p.c""")
        return self.near[at]

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

    def close(self, keep: frozenset[str] = frozenset()) -> None:  # every view and table made, but those kept: freed
        for kind, name in reversed([x for x in self.views if x[1] not in keep]):
            self.con.unregister(name) if kind == "view" else self.con.execute(f"DROP TABLE IF EXISTS {name}")
        self.views = [x for x in self.views if x[1] in keep]

    def asked(self, t: str) -> str:  # the query's rows of t
        return f"(SELECT * FROM {t} WHERE {q(self.uid)} IN (SELECT {q(self.uid)} FROM {self.query}))"

    def filters(self, a: str, b: str, query: bool = True) -> str:  # the query and cluster conditions on a pair (a, b)
        u = q(self.uid)
        out = [f"({a}.{u} IN (SELECT {u} FROM {self.query}) OR {b}.{u} IN (SELECT {u} FROM {self.query}))"] if self.query and query else []
        return " AND ".join(out + ([f"{a}.__cluster <> {b}.__cluster"] if self.cluster else [])) or "TRUE"


def deletions_sql(col: str) -> str:  # the value and each one-character deletion of it, distinct
    return f"list_distinct(list_prepend({col}, list_transform(range(1, length({col}) + 1), lambda i: {col}[:i - 1] || {col}[i + 1:])))"


def _filled(cols: Iterable[str]) -> str:
    return " AND ".join(f"{q(c)} IS NOT NULL" for c in cols) or "TRUE"


def block_cols(b: Blocker) -> list[str]:  # the columns naming a generator's block; none for windows and TF-IDF
    return ([q(k.name) for k in b.keys] if isinstance(b, KeyBlocker)
            else ["__dk", *(q(w.name) for w in b.within)] if isinstance(b, DeletionKeys) else [])


def _rows(b: Blocker, r: Records, asked: bool = False) -> str:  # a generator's rows (the query's only, if asked), each with its block columns
    if isinstance(b, DeletionKeys):
        return f"(SELECT * FROM {r.variants(b)} WHERE {q(r.uid)} IN (SELECT {q(r.uid)} FROM {r.query}))" if asked else r.variants(b)
    return f"(SELECT * FROM {r.asked(r.table) if asked else r.table} WHERE {_filled(k.name for k in b.keys)})"


def oversized(b: Blocker, r: Records, from_records: int) -> str | None:
    """The generator's blocks of `from_records` records or more (with a query: those holding a query record), as a
    table of their block columns, `__b` (an id) and `__n` (records); None if there is none. O(N), a group-by."""
    cols = block_cols(b)
    if not cols:
        return None
    asked = f" AND count(*) FILTER (WHERE {q(r.uid)} IN (SELECT {q(r.uid)} FROM {r.query})) > 0" if r.query else ""
    table = r._temp(f"""SELECT {', '.join(cols)}, count(*) AS __n, row_number() OVER () AS __b FROM {_rows(b, r)}
                       GROUP BY {', '.join(cols)} HAVING count(*) >= {from_records}{asked}""")
    return table if r.con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0] else None


def _in(cols: list[str], alias: str, blocks: str | None, keep: bool) -> str:  # is alias's block one of these blocks?
    if blocks is None:
        return "TRUE"
    test = f"EXISTS (SELECT 1 FROM {blocks} z WHERE {' AND '.join(f'z.{c} = {alias}.{c}' for c in cols)})"
    return test if keep else f"NOT {test}"


def pairs_sql(b: Blocker, r: Records, skip: str | None = None, only: str | None = None) -> str:
    """One generator's pairs as SQL: columns l < r (uid strings), each pair once. `skip`: blocks left out (a table from
    oversized()); `only`: the only blocks joined."""
    t, u = r.table, q(r.uid)
    cl = ", __cluster" if r.cluster else ""
    bcols, blocks, keep = block_cols(b), only or skip, only is not None
    match b:
        case KeyBlocker():
            on = " AND ".join(f"a.{q(k.name)} = b.{q(k.name)}" for k in b.keys)
            if r.query:  # the query's rows against all: O(|Q|·b) plus a scan, whatever N
                once = f"(a.{u} < b.{u} OR b.{u} NOT IN (SELECT {u} FROM {r.query} WHERE {u} IS NOT NULL))"  # a pair of two asked records: once, not both ways round
                return (f"SELECT least(a.{u}, b.{u}) AS l, greatest(a.{u}, b.{u}) AS r FROM {r.asked(t)} a JOIN {t} b "
                        f"ON {on} AND a.{u} <> b.{u} AND {once} WHERE {r.filters('a', 'b', query=False)} AND {_in(bcols, 'a', blocks, keep)}")
            x = f"(SELECT * FROM {t} y WHERE {_in(bcols, 'y', blocks, keep)})"  # both sides' blocks chosen before the join, not its pairs after
            return f"SELECT a.{u} AS l, b.{u} AS r FROM {x} a JOIN {x} b ON {on} AND a.{u} < b.{u} WHERE {r.filters('a', 'b')}"
        case SortedNeighbourhood():
            k = q(b.key.name)
            leads = ", ".join(f"lead({u}, {o}) OVER w AS b{o}" + (f", lead(__cluster, {o}) OVER w AS c{o}" if r.cluster else "")
                              for o in range(1, b.window))
            arms = " UNION ALL ".join(f"SELECT {u} AS a, b{o} AS b" + (f", __cluster AS ca, c{o} AS cb" if r.cluster else "") +
                                      f" FROM s WHERE b{o} IS NOT NULL" for o in range(1, b.window))
            touch = [f"(x.a IN (SELECT {u} FROM {r.query}) OR x.b IN (SELECT {u} FROM {r.query}))"] if r.query else []
            cond = " AND ".join(touch + (["x.ca <> x.cb"] if r.cluster else [])) or "TRUE"
            return (f"WITH s AS (SELECT {u}{cl}, {leads} FROM {t} WHERE {k} IS NOT NULL WINDOW w AS (ORDER BY {k}, {u})) "
                    f"SELECT least(x.a, x.b) AS l, greatest(x.a, x.b) AS r FROM ({arms}) x WHERE {cond}") if b.window > 1 else \
                "SELECT NULL::VARCHAR AS l, NULL::VARCHAR AS r WHERE FALSE"
        case EditKeys():
            near, k = r.near_values(b, r.most), q(b.key.name)
            on = lambda x, side: " AND ".join([f"{x}.{k} = p.{side}", *(f"{x}.{q(w.name)} = p.{q(w.name)}" for w in b.within)])
            return (f"SELECT least(a.{u}, b.{u}) AS l, greatest(a.{u}, b.{u}) AS r FROM {near} p JOIN {t} a ON {on('a', 'v')} "
                    f"JOIN {t} b ON {on('b', 'x')} WHERE {r.filters('a', 'b')}")
        case DeletionKeys():
            v = r.variants(b)
            same = " AND ".join(["a.__dk = b.__dk", *(f"a.{q(w.name)} = b.{q(w.name)}" for w in b.within)])
            if r.query and r.touching:  # a batch against all: O(|Q|·b), whatever N
                return (f"SELECT DISTINCT least(a.{u}, b.{u}) AS l, greatest(a.{u}, b.{u}) AS r FROM {_rows(b, r, asked=True)} a "
                        f"JOIN {v} b ON {same} AND a.{u} <> b.{u} WHERE {r.filters('a', 'b', query=False)} AND {_in(bcols, 'a', blocks, keep)}")
            x = f"(SELECT * FROM {v} y WHERE {_in(bcols, 'y', blocks, keep)})"
            return f"SELECT DISTINCT a.{u} AS l, b.{u} AS r FROM {x} a JOIN {x} b ON {same} AND a.{u} < b.{u} WHERE {r.filters('a', 'b')}"  # one pass, the query a filter
    raise TypeError(f"{b.name}: no SQL generator for {type(b).__name__}")


def sample_sql(b: Blocker, r: Records, blocks: str, rows: int) -> str:
    """Pairs among up to `rows` records of each of these blocks, chosen by hash (with a query: up to `rows` query
    records against up to `rows` of the block), with the block's `__b`: about rows²/2 pairs per block, whatever its size."""
    cols, u = block_cols(b), q(r.uid)
    ranked = lambda asked: (f"(SELECT x.*, z.__b, row_number() OVER (PARTITION BY z.__b ORDER BY hash(x.{u})) AS __k "
                            f"FROM {_rows(b, r, asked)} x JOIN {blocks} z USING ({', '.join(cols)}))")
    a, c = ranked(bool(r.query)), ranked(False)
    order = f"a.{u} <> c.{u}" if r.query else f"a.{u} < c.{u}"
    return (f"SELECT DISTINCT least(a.{u}, c.{u}) AS l, greatest(a.{u}, c.{u}) AS r, a.__b FROM {a} a JOIN {c} c "
            f"ON a.__b = c.__b AND {order} AND a.__k <= {rows} AND c.__k <= {rows} WHERE {r.filters('a', 'c', query=False)}")


def _tfidf(b: TfidfNeighbours, r: Records) -> pd.DataFrame:  # N² by design: development files only
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    uid = r.uid
    base = (r.frame if r.frame is not None else r.con.sql(f"SELECT * FROM {r.table}").df()).dropna(subset=[b.key.name])
    base = base[[uid, b.key.name]].sort_values(uid, kind="stable").reset_index(drop=True)  # by ID: the neighbours a tie gives don't follow the rows' order
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
             uid: str | None = None, oversized_from: int = 2**62, normal: bool = True) -> dict[str, object]:
    """Work before any join: candidate pairs (an upper bound) and the largest block, by group-by; and the blocks of
    `oversized_from` records or more: how many, their records and their pairs; and normal_pairs, those the join lists
    with the oversized blocks left out (an upper bound too; a deletion key's only with `normal`, a scan more). O(N)."""
    m = oversized_from
    over = f"count(*) FILTER (WHERE c >= {m}), coalesce(sum(c) FILTER (WHERE c >= {m}), 0), coalesce(sum(c * (c - 1) // 2) FILTER (WHERE c >= {m}), 0)"
    none = dict(oversized_blocks=0, oversized_records=0, oversized_pairs=0)
    r = records if isinstance(records, Records) else Records(records, uid or "", con)
    t, n = r.table, r.con.execute(f"SELECT count(*) FROM {r.table}").fetchall()[0][0]
    try:
        match b:
            case KeyBlocker():
                cols = ", ".join(q(k.name) for k in b.keys)
                p, big, *o = r.con.execute(f"SELECT coalesce(sum(c * (c - 1) // 2), 0), coalesce(max(c), 0), {over} FROM "
                                           f"(SELECT count(*) AS c FROM {t} WHERE {_filled(k.name for k in b.keys)} GROUP BY {cols})").fetchall()[0]
                return dict(big_o="O(N + P)", filled=f"O({n:,} + {int(p):,})", est_pairs=int(p), largest_block=int(big), **dict(zip(none, map(int, o))),
                            normal_pairs=int(p) - int(o[2]))
            case SortedNeighbourhood():
                m = r.con.execute(f"SELECT count({q(b.key.name)}) FROM {t}").fetchall()[0][0]
                return dict(big_o="O(N log N + N·w)", filled=f"O({m:,}·log {m:,} + {m:,}·{b.window})",
                            est_pairs=m * (b.window - 1), largest_block=b.window, **none, normal_pairs=m * (b.window - 1))
            case DeletionKeys():  # Σ C(k,2) over the key blocks, less the repeats: identical values share all their d keys
                v, within = r.variants(b), [q(w.name) for w in b.within]
                p, big, *o = r.con.execute(f"""
                    WITH blocks AS (SELECT count(*) AS c FROM {v} GROUP BY {', '.join(['__dk', *within])}),
                         same AS (SELECT count(*) AS c, count(DISTINCT __dk) AS d FROM {v} GROUP BY {', '.join(['__v', *within])}),
                         agg AS (SELECT coalesce(sum(c * (c - 1) // 2), 0) AS p, coalesce(max(c), 0) AS big, {over} FROM blocks)
                    SELECT agg.p - (SELECT coalesce(sum((d - 1) * (c // d) * (c // d - 1) // 2), 0) FROM same), agg.* EXCLUDE (p) FROM agg""").fetchall()[0]
                pairs = int(p) if not o[0] else None
                if o[0] and normal:  # the repeats taken off only where they are joined: a value's pairs once, if one of its d blocks is normal
                    keys = ", ".join(["__dk", *within])
                    pairs = r.con.execute(f"""
                        WITH blocks AS (SELECT {keys}, count(*) AS __c FROM {v} GROUP BY {keys}),
                             same AS (SELECT count(*) AS __c, count(DISTINCT __dk) AS d, count(DISTINCT __dk) FILTER (WHERE b.__c < {m}) AS dn
                                      FROM {v} JOIN blocks b USING ({keys}) GROUP BY {', '.join(['__v', *within])})
                        SELECT (SELECT coalesce(sum(__c * (__c - 1) // 2) FILTER (WHERE __c < {m}), 0) FROM blocks)
                             - (SELECT coalesce(sum(greatest(dn - 1, 0) * (__c // d) * (__c // d - 1) // 2), 0) FROM same)""").fetchall()[0][0]
                return dict(big_o="O(N·L + P)", filled=f"O({n:,}·L + {int(p):,})", est_pairs=int(p), largest_block=int(big), **dict(zip(none, map(int, o))),
                            normal_pairs=pairs)
            case EditKeys():  # exactly the pairs it lists: its value pairs' records multiplied
                r.most = min(r.most, oversized_from)
                p = int(r.con.execute(f"SELECT coalesce(sum(nv * nx), 0) FROM {r.near_values(b, r.most)}").fetchall()[0][0])
                return dict(big_o="O(U·k³ + S + P)", filled=f"O({n:,}·k³ + {p:,})", est_pairs=p, largest_block=0, **none, normal_pairs=p)
            case TfidfNeighbours():
                m, length = r.con.execute(f"SELECT count({q(b.key.name)}), avg(length({q(b.key.name)})) FROM {t}").fetchall()[0]
                per = (length or 0) * (b.ngram[1] - b.ngram[0] + 1)  # n-grams per record, roughly
                return dict(big_o="O(N·L + U·N·q)", filled=f"O({m:,}·L + {n_query:,}·{m:,}·{per:.0f})",
                            est_pairs=n_query * b.k, largest_block=b.k + 1, **none, normal_pairs=n_query * b.k)
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
            keys = ", ".join(["__dk", *(q(w.name) for w in b.within)])
            sql = (f"WITH k AS (SELECT DISTINCT {keys} FROM {_rows(b, r, asked=True)}), "
                   f"b AS (SELECT count(*) AS c, {asked} AS qn FROM {r.variants(b)} v JOIN k USING ({keys}) GROUP BY {keys}) {total}")
        case EditKeys():  # the batch's records' pairs, of the value pairs (an upper bound: both records of a pair may be old)
            p = r.con.execute(f"SELECT count(*) FROM ({pairs_sql(b, r)})").fetchall()[0][0]
            return dict(big_o="O(U·k³ + S + Δ·b)", filled=f"O(N·k³ + {int(p):,})", est_pairs=int(p), largest_block=0)
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
               into: str | None = None, touching: bool = False, gate: Callable[[str], str] | None = None,
               floor: float = 0.0, capacity: int | None = None, told: Callable[..., None] | None = None,
               known: dict[str, dict] | None = None, keep: Callable[[str], str] | None = None,
               only: str | None = None) -> tuple[pd.DataFrame | str, pd.DataFrame]:
    """The union of all generators, with the generators that found each pair in `sources`, and a per-generator report.
    With `into`, the union is written to that table in `con` and its name returned instead of a frame, so nothing of
    size C reaches pandas. `touching` (an increment, with `query` the batch): the estimates count only the blocks the
    batch reaches. Oversized blocks (budget.min_oversized() records or more) are left out of each generator's join.
    With a `gate` (it scores a table of pairs, uid_l / uid_r, into a table it names, with match_weight), a sample of each such
    block's pairs that no other block listed is scored, and the block joined only if a sampled pair reaches `floor`;
    with `capacity`, at most that many pairs in all, the highest-yield blocks first. Without a gate they are joined in
    full. report.attrs["gated"] has one row per oversized block: its value, records, pairs, sample and decision.
    `told(done, total, "keys")` as the joins begin and after each generator: how far they are. `known`: generators'
    estimates made already on these records (er.run's budget), by name, not counted again. `keep(pairs SQL)`: the SQL
    of those of a generator's pairs worth keeping (er.match.reaching_sql), applied a slice at a time (_kept), so only
    one generator's pairs are ever held in full. Each listed pair leaves its hash, so what the gate reads of the pairs
    other keys listed, each generator's pairs and report.attrs["listed"] (the distinct pairs listed) are as without it.
    `only`: SQL on a pair's l and r; a pair it is false for is never listed, so not counted (an increment without bridging).
    shortcut: a pair is known by a 64-bit hash, so two pairs in 10^8 share one about once in 3,000 runs (one count, one
    sampled pair off); a 128-bit key (two hashes) if that ever matters."""
    if not blockers:
        raise ValueError("no candidate generator")
    if len(blockers) > 63:  # one bit per generator in a BIGINT
        raise InputError(f"{len(blockers)} candidate generators: a run takes at most 63", fix="add fewer name features: each adds its own")
    assert query is not None or not touching, "touching needs the batch as the query"
    r = Records(records, uid, con, query, clusters, columns=[k.name for b in blockers for k in keys_of(b)])
    r.touching, r.most, r.only = touching, budget.min_oversized(), only
    l, rr = f"{uid}_l", f"{uid}_r"
    try:
        n_query = r.con.execute(f"SELECT count(*) FROM {r.query or r.table}").fetchall()[0][0]
        m = budget.min_oversized()
        report, parts, big, pending = [], [], {}, {}
        listed = r._temp("SELECT NULL::UBIGINT AS h WHERE FALSE") if keep else None  # each listed pair's hash, before keep()
        if told:
            told(0, len(blockers), "keys")
        for i, b in enumerate(blockers):
            est = estimate_touching(b, r) if touching else (known or {}).get(b.name) or estimate(b, r, n_query, oversized_from=m, normal=False)  # the budget's count: not made again
            t = time.perf_counter()
            if isinstance(b, TfidfNeighbours):
                pairs = _tfidf(b, r)
                if r.cluster:  # TF-IDF is computed in Python, so the cluster filter is applied here
                    cl = r.con.sql(f"SELECT {q(uid)}, __cluster FROM {r.table}").df().set_index(uid)["__cluster"]
                    pairs = pairs[pairs["l"].map(cl).to_numpy() != pairs["r"].map(cl).to_numpy()]
                table, n = _kept(r, f"SELECT * FROM {r._view(pairs)}", keep, listed, pending)
            else:
                if blocks := oversized(b, r, m):
                    big[i] = blocks
                table, n = _kept(r, pairs_sql(b, r, skip=big.get(i)), keep, listed, pending)
            if sum(pending.values()) >= KEEP_SLICE:
                _bound(r, pending, keep)
            report.append(dict(generator=b.name, **est, pairs=n, seconds=round(time.perf_counter() - t, 3)))
            parts.append(f"SELECT l, r, {1 << i}::BIGINT AS bit FROM {table}")
            if told:
                told(i + 1, len(blockers), "keys")
        _bound(r, pending, keep)
        gated, added = _gate(blockers, r, big, parts, gate, floor, capacity, m, (l, rr), keep, listed) if big else (pd.DataFrame(), {})
        for i, extra in added.items():
            report[i]["pairs"] += extra
        union = f"SELECT l, r, bit_or(bit) AS bits FROM ({' UNION ALL '.join(parts)}) GROUP BY l, r"
        bits = r._temp(union)
        distinct = r.con.execute(f"SELECT count(DISTINCT h) FROM {listed}").fetchall()[0][0] if listed else None
        r.close(keep=frozenset({bits}))  # the parts, blocks and samples the union was made of: freed before the result is written
        names = {m: "+".join(g.name for i, g in enumerate(blockers) if m >> i & 1)
                 for (m,) in r.con.execute(f"SELECT DISTINCT bits FROM {bits}").fetchall()}
        cases = " ".join(f"WHEN {m} THEN '{s}'" for m, s in names.items())
        out = f"SELECT l AS {q(l)}, r AS {q(rr)}, {f'CASE bits {cases} END' if cases else 'NULL::VARCHAR'} AS sources FROM {bits}"  # no pair: no case
        if into:  # unordered: whoever reads the table joins it or orders it
            r.con.execute(f"CREATE OR REPLACE TABLE {q(into)} AS {out}")
            result = into
        else:
            result = r.con.sql(f"{out} ORDER BY l, r").df().astype("string")
    finally:
        r.close()
    report = pd.DataFrame(report)
    report.attrs["gated"] = gated.to_dict("records")
    report.attrs["listed"] = distinct  # the distinct pairs the keys listed, with keep(): more than those it stored  # plain records: pandas compares attrs when it combines frames
    return result, report


KEEP_SLICE = 10_000_000  # pairs a keep filter reads at once: past a few tens of millions, its joins spill and slow tenfold


def _kept(r: Records, sql: str, keep: Callable[[str], str] | None, listed: str | None, pending: dict[str, int] | None = None) -> tuple[str, int]:
    """The pairs of `sql` (l, r) as a table, only those keep() keeps if given, and how many it listed: listed, each
    pair's hash added to the table `listed`, then filtered KEEP_SLICE at a time, so the filter's join never holds more
    than a slice. With `pending`, a listing under a slice waits there for _bound, with the others: filtered then."""
    table = r._temp(f"SELECT * FROM ({sql}) WHERE {r.only}" if r.only else sql)
    n = r.con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
    if keep is None:
        return table, n
    r.con.execute(f"INSERT INTO {listed} SELECT hash(l, r) FROM {table}")
    if pending is not None and n < KEEP_SLICE:
        pending[table] = n
        return table, n
    out = r._temp(keep(f"SELECT l, r FROM {table} WHERE rowid < {KEEP_SLICE}"))
    for start in range(KEEP_SLICE, n, KEEP_SLICE):
        r.con.execute(f"INSERT INTO {out} {keep(f'SELECT l, r FROM {table} WHERE rowid >= {start} AND rowid < {start + KEEP_SLICE}')}")
    r.con.execute(f"DROP TABLE {table}")  # the listing: freed as soon as it is read
    return out, n


def _bound(r: Records, pending: dict[str, int], keep: Callable[[str], str] | None) -> None:
    """The listings waiting in `pending`, filtered by keep() in one pass over their distinct pairs, a slice at a time:
    each keeps its pairs that pass. keep() reads a pair alone, so as each filtered on its own, without a join of the
    records per generator."""
    if not pending:
        return
    both = r._temp(" UNION ".join(f"SELECT l, r FROM {t}" for t in pending))
    n = r.con.execute(f"SELECT count(*) FROM {both}").fetchall()[0][0]
    out = r._temp(keep(f"SELECT l, r FROM {both} WHERE rowid < {KEEP_SLICE}"))
    for start in range(KEEP_SLICE, n, KEEP_SLICE):
        r.con.execute(f"INSERT INTO {out} {keep(f'SELECT l, r FROM {both} WHERE rowid >= {start} AND rowid < {start + KEEP_SLICE}')}")
    for t in pending:
        r.con.execute(f"DELETE FROM {t} WHERE NOT EXISTS (SELECT 1 FROM {out} k WHERE k.l = {t}.l AND k.r = {t}.r)")
    r.con.execute(f"DROP TABLE {both}; DROP TABLE {out}")
    pending.clear()


def _gate(blockers: tuple[Blocker, ...], r: Records, big: dict[int, str], parts: list[str], gate: Callable | None, floor: float,
          capacity: int | None, rows: int, names: tuple[str, str], keep: Callable[[str], str] | None,
          listed: str | None) -> tuple[pd.DataFrame, dict[int, int]]:
    """Decide each oversized block, and add the pairs of those kept to `parts`; returns the decisions and the pairs added
    per generator (as listed, before keep()). The pairs other keys listed are read from `listed` (their hashes) when
    keep() filtered them, else from `parts`. O(sampled pairs) to decide."""
    info = pd.concat([r.con.execute(f"SELECT {i} AS g, __b AS b, __n AS records, concat_ws(' · ', {', '.join(block_cols(blockers[i]))}) AS value "
                                    f"FROM {table}").df() for i, table in big.items()], ignore_index=True)
    info.insert(0, "generator", info["g"].map(lambda i: blockers[i].name))
    info["pairs"] = info["records"] * (info["records"] - 1) // 2
    if gate is None:
        info = info.assign(sampled=0, best=float("nan"), hits=0, decision="joined in full")
    else:
        if listed:  # filtered: the pairs as listed, by their hashes
            seen, same = r._temp(f"SELECT DISTINCT h FROM {listed}"), "x.h = hash(s.l, s.r)"
        else:
            seen, same = r._temp(f"SELECT DISTINCT l, r FROM ({' UNION ALL '.join(parts)})"), "x.l = s.l AND x.r = s.r"
        sample = r._temp(" UNION ALL ".join(
            f"SELECT s.l, s.r, s.__b AS b, {i} AS g FROM ({sample_sql(blockers[i], r, table, rows)}) s "
            f"WHERE NOT EXISTS (SELECT 1 FROM {seen} x WHERE {same})" for i, table in big.items()))
        pairs = r._temp(f'SELECT DISTINCT l AS "{names[0]}", r AS "{names[1]}" FROM {sample}')  # scored in DuckDB, a slice at a time: never all at once through pandas
        scored = gate(pairs)
        stats = r.con.execute(f"""SELECT s.g, s.b, count(*) AS sampled, max(w.w) AS best, count(*) FILTER (WHERE w.w >= {floor}) AS hits
                                  FROM {sample} s LEFT JOIN (SELECT "{names[0]}" AS l, "{names[1]}" AS r, match_weight AS w FROM {scored}) w USING (l, r)
                                  GROUP BY 1, 2""").df()  # every sampled pair counted; the gate's scores hold only those that could reach the floor
        r.con.execute(f"DROP TABLE IF EXISTS {scored}")
        info = info.merge(stats, on=["g", "b"], how="left").fillna({"sampled": 0, "hits": 0})
        info["decision"] = np.where(info["hits"] > 0, "kept", np.where(info["sampled"] == 0, "skipped: other keys list its sampled pairs",
                                                                         "skipped: no sampled pair reaches the floor"))
        if capacity is not None:  # the highest-yield blocks first, while they fit
            left = capacity - r.con.execute(f"SELECT count(*) FROM {seen}").fetchall()[0][0]
            for k in info[info["decision"] == "kept"].assign(y=lambda d: d["hits"] / d["sampled"]).sort_values(["y", "generator", "value"], ascending=[False, True, True]).index:  # ties in a fixed order: the same blocks every run
                if info.at[k, "pairs"] > left:
                    info.at[k, "decision"] = "skipped: over capacity"
                else:
                    left -= info.at[k, "pairs"]
    added = {}
    for i, table in big.items():
        ids = info.loc[(info["g"] == i) & info["decision"].isin(["kept", "joined in full"]), "b"].tolist()
        if ids:
            kept = r._temp(f"SELECT * FROM {table} WHERE __b IN ({', '.join(map(str, ids))})")
            pairs_table, added[i] = _kept(r, pairs_sql(blockers[i], r, only=kept), keep, listed)
            parts.append(f"SELECT l, r, {1 << i}::BIGINT AS bit FROM {pairs_table}")
    return info.drop(columns=["g", "b"]), added
