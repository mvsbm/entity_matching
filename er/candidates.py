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

from er.config import Blocker, Budget, DeletionKeys, KeyBlocker, SortedNeighbourhood, TfidfNeighbours, keys_of

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
        self.touching = False                 # the query is a batch joined against all (an increment), not most of the file
        self.dk: dict[tuple, str] = {}        # deletion-key rows per (key, within), built once (variants)

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


def deletions_sql(col: str) -> str:  # the value and each one-character deletion of it, distinct
    return f"list_distinct(list_prepend({col}, list_transform(range(1, length({col}) + 1), lambda i: {col}[:i - 1] || {col}[i + 1:])))"


def _filled(cols: Iterable[str], alias: str = "") -> str:
    return " AND ".join(f"{alias}{q(c)} IS NOT NULL" for c in cols) or "TRUE"


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
                return (f"SELECT DISTINCT least(a.{u}, b.{u}) AS l, greatest(a.{u}, b.{u}) AS r FROM {r.asked(t)} a JOIN {t} b "
                        f"ON {on} AND a.{u} <> b.{u} WHERE {r.filters('a', 'b', query=False)} AND {_in(bcols, 'a', blocks, keep)}")
            return (f"SELECT a.{u} AS l, b.{u} AS r FROM {t} a JOIN {t} b ON {on} AND a.{u} < b.{u} "
                    f"WHERE {r.filters('a', 'b')} AND {_in(bcols, 'a', blocks, keep)}")
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
                "SELECT NULL::VARCHAR AS l, NULL::VARCHAR AS r WHERE FALSE"
        case DeletionKeys():
            v = r.variants(b)
            same = " AND ".join(["a.__dk = b.__dk", *(f"a.{q(w.name)} = b.{q(w.name)}" for w in b.within)])
            if r.query and r.touching:  # a batch against all: O(|Q|·b), whatever N
                return (f"SELECT DISTINCT least(a.{u}, b.{u}) AS l, greatest(a.{u}, b.{u}) AS r FROM {_rows(b, r, asked=True)} a "
                        f"JOIN {v} b ON {same} AND a.{u} <> b.{u} WHERE {r.filters('a', 'b', query=False)} AND {_in(bcols, 'a', blocks, keep)}")
            return (f"SELECT DISTINCT a.{u} AS l, b.{u} AS r FROM {v} a JOIN {v} b ON {same} AND a.{u} < b.{u} "  # one pass, the query a filter
                    f"WHERE {r.filters('a', 'b')} AND {_in(bcols, 'a', blocks, keep)}")
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
             uid: str | None = None, oversized_from: int = 2**62) -> dict[str, object]:
    """Work before any join: candidate pairs (an upper bound) and the largest block, by group-by; and the blocks of
    `oversized_from` records or more: how many, their records and their pairs. O(N)."""
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
                return dict(big_o="O(N + P)", filled=f"O({n:,} + {int(p):,})", est_pairs=int(p), largest_block=int(big), **dict(zip(none, map(int, o))))
            case SortedNeighbourhood():
                m = r.con.execute(f"SELECT count({q(b.key.name)}) FROM {t}").fetchall()[0][0]
                return dict(big_o="O(N log N + N·w)", filled=f"O({m:,}·log {m:,} + {m:,}·{b.window})",
                            est_pairs=m * (b.window - 1), largest_block=b.window, **none)
            case DeletionKeys():  # Σ C(k,2) over the key blocks, less the repeats: identical values share all their d keys
                v, within = r.variants(b), [q(w.name) for w in b.within]
                p, big, *o = r.con.execute(f"""
                    WITH blocks AS (SELECT count(*) AS c FROM {v} GROUP BY {', '.join(['__dk', *within])}),
                         same AS (SELECT count(*) AS c, count(DISTINCT __dk) AS d FROM {v} GROUP BY {', '.join(['__v', *within])}),
                         agg AS (SELECT coalesce(sum(c * (c - 1) // 2), 0) AS p, coalesce(max(c), 0) AS big, {over} FROM blocks)
                    SELECT agg.p - (SELECT coalesce(sum((d - 1) * (c // d) * (c // d - 1) // 2), 0) FROM same), agg.* EXCLUDE (p) FROM agg""").fetchall()[0]
                return dict(big_o="O(N·L + P)", filled=f"O({n:,}·L + {int(p):,})", est_pairs=int(p), largest_block=int(big), **dict(zip(none, map(int, o))))
            case TfidfNeighbours():
                m, length = r.con.execute(f"SELECT count({q(b.key.name)}), avg(length({q(b.key.name)})) FROM {t}").fetchall()[0]
                per = (length or 0) * (b.ngram[1] - b.ngram[0] + 1)  # n-grams per record, roughly
                return dict(big_o="O(N·L + U·N·q)", filled=f"O({m:,}·L + {n_query:,}·{m:,}·{per:.0f})",
                            est_pairs=n_query * b.k, largest_block=b.k + 1, **none)
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
               into: str | None = None, touching: bool = False, gate: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
               floor: float = 0.0, capacity: int | None = None) -> tuple[pd.DataFrame | str, pd.DataFrame]:
    """The union of all generators, with the generators that found each pair in `sources`, and a per-generator report.
    With `into`, the union is written to that table in `con` and its name returned instead of a frame, so nothing of
    size C reaches pandas. `touching` (an increment, with `query` the batch): the estimates count only the blocks the
    batch reaches. Oversized blocks (budget.min_oversized() records or more) are left out of each generator's join.
    With a `gate` (it scores a frame of pairs, uid_l / uid_r, and returns them with match_weight), a sample of each such
    block's pairs that no other block listed is scored, and the block joined only if a sampled pair reaches `floor`;
    with `capacity`, at most that many pairs in all, the highest-yield blocks first. Without a gate they are joined in
    full. report.attrs["gated"] has one row per oversized block: its value, records, pairs, sample and decision."""
    if not blockers:
        raise ValueError("no candidate generator")
    assert len(blockers) < 63, "one bit per generator"
    assert query is not None or not touching, "touching needs the batch as the query"
    r = Records(records, uid, con, query, clusters, columns=[k.name for b in blockers for k in keys_of(b)])
    r.touching = touching
    l, rr = f"{uid}_l", f"{uid}_r"
    try:
        n_query = r.con.execute(f"SELECT count(*) FROM {r.query or r.table}").fetchall()[0][0]
        m = budget.min_oversized()
        report, parts, big = [], [], {}
        for i, b in enumerate(blockers):
            est = estimate_touching(b, r) if touching else estimate(b, r, n_query, oversized_from=m)
            t = time.perf_counter()
            if isinstance(b, TfidfNeighbours):
                pairs = _tfidf(b, r)
                if r.cluster:  # TF-IDF is computed in Python, so the cluster filter is applied here
                    cl = r.con.sql(f"SELECT {q(uid)}, __cluster FROM {r.table}").df().set_index(uid)["__cluster"]
                    pairs = pairs[pairs["l"].map(cl).to_numpy() != pairs["r"].map(cl).to_numpy()]
                table = r._temp(f"SELECT * FROM {r._view(pairs)}")
            else:
                if blocks := oversized(b, r, m):
                    big[i] = blocks
                table = r._temp(pairs_sql(b, r, skip=big.get(i)))
            n = r.con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
            report.append(dict(generator=b.name, **est, pairs=n, seconds=round(time.perf_counter() - t, 3)))
            parts.append(f"SELECT l, r, {1 << i}::BIGINT AS bit FROM {table}")
        gated, added = _gate(blockers, r, big, parts, gate, floor, capacity, m, (l, rr)) if big else (pd.DataFrame(), {})
        for i, extra in added.items():
            report[i]["pairs"] += extra
        union = f"SELECT l, r, bit_or(bit) AS bits FROM ({' UNION ALL '.join(parts)}) GROUP BY l, r"
        bits = r._temp(union)
        names = {m: "+".join(g.name for i, g in enumerate(blockers) if m >> i & 1)
                 for (m,) in r.con.execute(f"SELECT DISTINCT bits FROM {bits}").fetchall()}
        cases = " ".join(f"WHEN {m} THEN '{s}'" for m, s in names.items())
        out = f"SELECT l AS {q(l)}, r AS {q(rr)}, CASE bits {cases} END AS sources FROM {bits}"
        if into:  # unordered: whoever reads the table joins it or orders it
            r.con.execute(f"CREATE OR REPLACE TABLE {q(into)} AS {out}")
            result = into
        else:
            result = r.con.sql(f"{out} ORDER BY l, r").df().astype("string")
    finally:
        r.close()
    report = pd.DataFrame(report)
    report.attrs["gated"] = gated.to_dict("records")  # plain records: pandas compares attrs when it combines frames
    return result, report


def _gate(blockers: tuple[Blocker, ...], r: Records, big: dict[int, str], parts: list[str], gate: Callable | None, floor: float,
          capacity: int | None, rows: int, names: tuple[str, str]) -> tuple[pd.DataFrame, dict[int, int]]:
    """Decide each oversized block, and add the pairs of those kept to `parts`; returns the decisions and the pairs added
    per generator. O(sampled pairs) to decide."""
    info = pd.concat([r.con.execute(f"SELECT {i} AS g, __b AS b, __n AS records, concat_ws(' · ', {', '.join(block_cols(blockers[i]))}) AS value "
                                    f"FROM {table}").df() for i, table in big.items()], ignore_index=True)
    info.insert(0, "generator", info["g"].map(lambda i: blockers[i].name))
    info["pairs"] = info["records"] * (info["records"] - 1) // 2
    if gate is None:
        info = info.assign(sampled=0, best=float("nan"), hits=0, decision="joined in full")
    else:
        listed = r._temp(f"SELECT DISTINCT l, r FROM ({' UNION ALL '.join(parts)})")
        sample = r._temp(" UNION ALL ".join(
            f"SELECT s.l, s.r, s.__b AS b, {i} AS g FROM ({sample_sql(blockers[i], r, table, rows)}) s "
            f"WHERE NOT EXISTS (SELECT 1 FROM {listed} x WHERE x.l = s.l AND x.r = s.r)" for i, table in big.items()))
        pairs = r.con.execute(f"SELECT DISTINCT l, r FROM {sample}").df().set_axis(list(names), axis=1).astype("string")
        scored = gate(pairs)[[*names, "match_weight"]].set_axis(["l", "r", "w"], axis=1) if len(pairs) else pd.DataFrame(columns=["l", "r", "w"])
        stats = r.con.execute(f"""SELECT s.g, s.b, count(*) AS sampled, max(w.w) AS best, count(*) FILTER (WHERE w.w >= {floor}) AS hits
                                  FROM {sample} s JOIN {r._view(scored)} w USING (l, r) GROUP BY 1, 2""").df()
        info = info.merge(stats, on=["g", "b"], how="left").fillna({"sampled": 0, "hits": 0})
        info["decision"] = np.where(info["hits"] > 0, "kept", np.where(info["sampled"] == 0, "skipped: other keys list its sampled pairs",
                                                                         "skipped: no sampled pair reaches the floor"))
        if capacity is not None:  # the highest-yield blocks first, while they fit
            left = capacity - r.con.execute(f"SELECT count(*) FROM {listed}").fetchall()[0][0]
            for k in info[info["decision"] == "kept"].assign(y=lambda d: d["hits"] / d["sampled"]).sort_values("y", ascending=False).index:
                if info.at[k, "pairs"] > left:
                    info.at[k, "decision"] = "skipped: over capacity"
                else:
                    left -= info.at[k, "pairs"]
    added = {}
    for i, table in big.items():
        ids = info.loc[(info["g"] == i) & info["decision"].isin(["kept", "joined in full"]), "b"].tolist()
        if ids:
            kept = r._temp(f"SELECT * FROM {table} WHERE __b IN ({', '.join(map(str, ids))})")
            pairs_table = r._temp(pairs_sql(blockers[i], r, only=kept))
            added[i] = r.con.execute(f"SELECT count(*) FROM {pairs_table}").fetchall()[0][0]
            parts.append(f"SELECT l, r, {1 << i}::BIGINT AS bit FROM {pairs_table}")
    return info.drop(columns=["g", "b"]), added
