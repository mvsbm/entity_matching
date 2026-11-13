"""The keys learned on each file, with no labels: the pairs the run's model accepts are found by sampling, and the
keys that list most of them for the fewest pairs are chosen (Michelson & Knoblock's and Bilenko et al.'s learned
blocking, with the run's own model, fitted before any key is used, as the judge of what a pair is worth).

1. Atoms, from the method: every column its keys, rules and comparisons read, equal; within one edit (deletion keys)
   for a column it compares by an edit distance or a similarity; within `edits` edits (PassJoin) for one it compares by
   a similarity. A value held by an oversized block's worth of records (a placeholder) pairs by none of them.
2. Targets: a hash-stable share f of the records, each paired with every record sharing an atom with it (or, where
   both of two atoms' blocks are oversized alone, both), scored through the bound at the review floor. A pair is drawn
   when either record is, so each counts for 1 / (1 − (1 − f)²) of the file's (the probe's estimator).
3. Coverage: which keys of up to `max_atoms` atoms (one of them at most within edits) list each target, as boolean
   vectors over them; cost: the pairs each lists, counted as the budget counts them (er.candidates.estimate).
4. The cover: while the budget lasts, the key that lists the most targets no key chosen lists, per pair it costs.

O(A·N) for the atoms' blocks, O(f·N·b) pairs scored, O(K·T) for coverage and O(K'·N) for the costs of the K' keys
that list a target.
"""
import itertools
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from er.candidates import Records, deletions_sql, estimate
from er.config import Blocker, DeletionKeys, EditKeys, Key, KeyBlocker, Pipeline, keys_of, q
from er.match import bound_tests, review_floor, score_fs

SIMILAR = ("jaro", "jaro_winkler", "jaccard", "levenshtein_similarity")  # similarities: one and `edits` edits apart are atoms
EDITS = ("levenshtein", "damerau_levenshtein", "hamming")                # edit distances: one edit apart is an atom
EXTEND = 0.1  # pairs per record above which a key is tried one atom longer
SETS = 16     # equality keys counted in one scan (GROUPING SETS): one hash table each


@dataclass(frozen=True)
class Atom:
    key: Key       # a field and its normalization
    edits: int     # 0: equal; 1: within one edit (deletion keys); k: within k edits (PassJoin)

    @property
    def column(self) -> str:  # as the records hold it
        return self.key.name

    @property
    def name(self) -> str:
        return self.column if not self.edits else f"{self.column}~{self.edits}"


def atoms(p: Pipeline, have: set[str]) -> list[Atom]:
    """Every column the method reads as a key, a rule or a comparison, equal; and within edits where it compares that
    column by an edit distance (one) or a similarity (one, and p.keys.edits). Only the columns the records hold."""
    fs, k = p.fs, p.keys.edits
    eq = {x for b in fs.blockers for x in keys_of(b)} | {x for b in p.rules.blockers() for x in keys_of(b)}
    near: dict[Key, set[int]] = {}
    for c in fs.model.comparisons:
        for lv in c.levels:
            for col, comp in lv.any_of:
                eq.add(key := Key(col, comp.normalize))
                if comp.function in SIMILAR:
                    near.setdefault(key, set()).update({1, k})
                elif comp.function in EDITS and (comp.threshold or 0) >= 1:
                    near.setdefault(key, set()).add(1)
    one = {}  # a column a key and a comparison both read: one atom
    for x in sorted(eq, key=lambda x: (x.name, len(x.normalize))):
        one.setdefault(x.name, x)
    return sorted([Atom(x, 0) for c, x in one.items() if c in have] + [Atom(x, e) for x, es in near.items() if x.name in have for e in es],
                  key=lambda a: (a.edits, a.column))


def blocker(combo: tuple[Atom, ...]) -> Blocker:  # the generator a key of these atoms runs as
    eq, near = [a.key for a in combo if not a.edits], [a for a in combo if a.edits]
    name = "learned:" + "+".join(a.name for a in combo)
    if not near:
        return KeyBlocker(name=name, keys=tuple(eq))
    a = near[0]
    return (DeletionKeys(name=name, key=a.key, within=tuple(eq)) if a.edits == 1
            else EditKeys(name=name, key=a.key, within=tuple(eq), edits=a.edits))


def learn(run, f: float | None = None) -> tuple[tuple[Blocker, ...], dict, dict[str, dict]]:
    """The keys for this run's records (run: an er.run.Run fitted, its rules run), what was found, and each chosen key's
    estimate as er.candidates.estimate gives it (the candidates step reads them, not the records again)."""
    t0, p, con, uid, n = time.perf_counter(), run.pipeline, run.con, run.uid, run.n
    spec, fs, m = p.keys, p.fs, p.fs.budget.min_oversized()
    have = run.columns()
    found = atoms(p, have)
    f = f or min(1.0, spec.records / max(n, 1))
    u, l, r = q(uid), q(run.l), q(run.r)
    con.execute(f"CREATE OR REPLACE TABLE er_kl_s AS SELECT {u} FROM records WHERE hash({u}) % 1000000000 < {int(f * 1e9)}")
    con.execute("CREATE OR REPLACE TABLE er_kl_p (l VARCHAR, r VARCHAR)")
    def pair(a: str, b: str, rest: str) -> None:  # the pairs drawn, only those that can reach 0 (the run's two-stage bound): few, made distinct after every atom
        con.execute(f"INSERT INTO er_kl_p SELECT l, r FROM ({run._reaching(f'SELECT least({a}, {b}) AS l, greatest({a}, {b}) AS r FROM {rest}')})")
    eq = [a for a in found if not a.edits]
    big = {a.column: con.execute(f"SELECT count(*) FROM (SELECT 1 FROM records WHERE {q(a.column)} IS NOT NULL GROUP BY 1 HAVING count(*) >= {m})"
                                 ).fetchall()[0][0] > 0 for a in eq}  # does the atom alone have oversized blocks?

    def through(cols: list[str]) -> None:  # each sampled record with every record of its block on these columns, normal blocks only
        c, filled = ", ".join(q(x) for x in cols), " AND ".join(f"{q(x)} IS NOT NULL" for x in cols)
        pair('a.' + u, 'b.' + u, f"""(SELECT a.{u}, {', '.join(f'a.{q(x)}' for x in cols)} FROM records a
            SEMI JOIN (SELECT {c} FROM records WHERE {filled} GROUP BY ALL HAVING count(*) < {m}) z USING ({c}) SEMI JOIN er_kl_s s USING ({u})) a
            JOIN records b USING ({c}) WHERE a.{u} <> b.{u}""")
    for a in eq:
        through([a.column])
    for a, b in itertools.combinations(eq, 2):
        if big[a.column] and big[b.column]:  # both with blocks too big alone: the records equal on both (an atom with normal ones drew them)
            through([a.column, b.column])
    rec = Records("records", uid, con)
    rec.most, sampled = m, {}
    for a in (a for a in found if a.edits):
        if a.edits == 1:  # sharing a one-deletion key, in a normal deletion block
            v = rec.variants(DeletionKeys(name="x", key=Key(a.column)))
            pair('x.' + u, 'y.' + u, f"""(SELECT * FROM {v} WHERE __dk IN (SELECT __dk FROM {v} GROUP BY 1 HAVING count(*) < {m})) x
                SEMI JOIN er_kl_s s USING ({u}) JOIN {v} y ON x.__dk = y.__dk AND x.{u} <> y.{u}""")
        else:
            near, k = rec.near_values(EditKeys(name="x", key=Key(a.column), edits=a.edits), m, probe="er_kl_s"), q(a.column)  # the sample's values against all
            rest = f"""{near} z JOIN records x ON x.{k} = z.v JOIN records y ON y.{k} = z.x
                WHERE x.{u} IN (SELECT {u} FROM er_kl_s) OR y.{u} IN (SELECT {u} FROM er_kl_s)"""
            sampled[a] = con.execute(f"SELECT count(*) FROM {rest}").fetchall()[0][0]  # the pairs it lists touching the sample: its pairs, scaled
            pair('x.' + u, 'y.' + u, rest)
    con.execute(f"""CREATE OR REPLACE TABLE er_kl_d AS SELECT DISTINCT p.l AS {l}, p.r AS {r} FROM er_kl_p p JOIN rule_clusters a ON a.{u} = p.l
        JOIN rule_clusters b ON b.{u} = p.r WHERE a.cluster_id <> b.cluster_id""")  # a pair inside one rule cluster is the rules'
    drawn, t_drawn = run._count("er_kl_d"), time.perf_counter()
    floor = review_floor(p)
    score_fs(run.scoring, "records", "er_kl_d", run.db, uid, into="er_kl_t", n_records=n, floor=floor, bound=bound_tests(fs.model))
    con.execute(f"DELETE FROM er_kl_t WHERE match_weight < {floor}")
    weight, t_scored = 1 / (1 - (1 - f) ** 2), time.perf_counter()
    targets = con.execute(f"""SELECT t.{l}, t.{r}, {', '.join(f'a.{q(a.column)} AS {q("a" + str(i))}, b.{q(a.column)} AS {q("b" + str(i))}' for i, a in enumerate(found))}
        FROM er_kl_t t JOIN records a ON a.{u} = t.{l} JOIN records b ON b.{u} = t.{r}""").df()
    facts = dict(atoms=[a.name for a in found], share=round(f, 4), drawn=drawn, targets=len(targets), estimated=round(len(targets) * weight))
    if targets.empty:
        run.con.execute("DROP TABLE IF EXISTS er_kl_s; DROP TABLE IF EXISTS er_kl_p; DROP TABLE IF EXISTS er_kl_d; DROP TABLE IF EXISTS er_kl_t")
        rec.close()
        return fs.blockers, {**facts, "learned": False, "seconds": round(time.perf_counter() - t0, 2)}, {}

    agree = {a: _agrees(a, targets[f"a{i}"], targets[f"b{i}"]) for i, a in enumerate(found)}
    cost: dict[tuple, dict] = {}

    def priced(combo: tuple[Atom, ...]) -> float:  # its pairs per record, counted once as the budget counts them (outside oversized blocks)
        if combo not in cost and not any(a.edits for a in combo):
            price_all([combo])
        if combo not in cost and len(combo) == 1 and combo[0] in sampled and (scaled := sampled[combo[0]] * weight) > fs.budget.max_pairs(n):
            return scaled / n  # over the budget by the sample alone: never run, so never counted in full
        if combo not in cost:
            b = blocker(combo)
            e = estimate(b, rec, n, oversized_from=m)
            cost[combo] = e | {"blocker": b, "pairs": e["normal_pairs"] if e["normal_pairs"] is not None else e["est_pairs"],
                               "normal": _normal(combo, b, targets, found, rec, m)}
        return cost[combo]["pairs"] / n
    def price_all(combos: list[tuple[Atom, ...]]) -> None:  # every equality key of these in one scan per batch (GROUPING SETS), as estimate counts one
        todo = [c for c in combos if c not in cost and not any(a.edits for a in c)]
        for i in range(0, len(todo), SETS):
            batch = todo[i:i + SETS]
            cols = sorted({a.column for c in batch for a in c}, key=lambda x: [a.column for a in found].index(x))
            sets = ", ".join("(" + ", ".join(q(a.column) for a in c) + ")" for c in batch)
            gid = lambda c: sum(1 << (len(cols) - 1 - j) for j, x in enumerate(cols) if x not in {a.column for a in c})  # grouping_id: the columns rolled up
            grouped = (f"SELECT grouping_id({', '.join(q(x) for x in cols)}) AS g, {', '.join(f'{q(x)}, grouping({q(x)}) AS {q(x + chr(1))}' for x in cols)}, "
                       f"count(*) AS c FROM records GROUP BY GROUPING SETS ({sets})")
            kept = " AND ".join(f"({q(x + chr(1))} = 1 OR {q(x)} IS NOT NULL)" for x in cols)  # a block of a filled value on every column of its set
            con.execute(f"CREATE OR REPLACE TEMP TABLE er_kl_g AS SELECT * FROM ({grouped}) WHERE {kept}")
            sums = {g: x for g, *x in con.execute(f"""SELECT g, coalesce(sum(c * (c - 1) // 2), 0), max(c), count(*) FILTER (WHERE c >= {m}),
                coalesce(sum(c) FILTER (WHERE c >= {m}), 0), coalesce(sum(c * (c - 1) // 2) FILTER (WHERE c >= {m}), 0) FROM er_kl_g GROUP BY g""").fetchall()}
            big = {}
            for g, *v in con.execute(f"SELECT g, {', '.join(q(x) for x in cols)} FROM er_kl_g WHERE c >= {m}").fetchall():
                big.setdefault(g, set()).add(tuple(v))
            for c in batch:
                p, top, ob, orec, op = map(int, sums.get(gid(c), (0, 0, 0, 0, 0)))
                e = dict(big_o="O(N + P)", filled=f"O({n:,} + {p:,})", est_pairs=p, largest_block=top, oversized_blocks=ob, oversized_records=orec,
                         oversized_pairs=op, normal_pairs=p - op)
                at = [cols.index(a.column) for a in c]
                over = {tuple(v[j] for j in at) for v in big.get(gid(c), ())}
                normal = np.array([tuple(v) not in over for v in zip(*(targets[f"a{found.index(a)}"] for a in c))], bool) if over else np.ones(len(targets), bool)
                cost[c] = e | {"blocker": blocker(c), "pairs": p - op, "normal": normal}
            con.execute("DROP TABLE IF EXISTS er_kl_g")
    keys, level = [], [(a,) for a in found]
    for size in range(1, spec.max_atoms + 1):  # a key is made one atom longer only where each key one shorter costs too much (BSL)
        hits = {c: np.logical_and.reduce([agree[a] for a in c]) for c in level}
        level = [c for c in level if hits[c].sum() >= spec.min_gain]
        keys += [(c, hits[c]) for c in level]
        price_all(level)
        if size == spec.max_atoms:
            break
        dear = {c for c in level if priced(c) > EXTEND}
        level = sorted({tuple(sorted({*c, a}, key=found.index)) for c in dear for a in found if a not in c and a.column not in {x.column for x in c}
                        and sum(x.edits > 0 for x in (*c, a)) <= 1}, key=lambda c: [found.index(a) for a in c])
        level = [c for c in level if all(tuple(x for x in c if x is not y) in dear for y in c)]
    chosen, known, covered, left, rows = [], {}, np.zeros(len(targets), bool), fs.budget.max_pairs(n), []
    while True:
        best = None
        for combo, raw in keys:
            if int((raw & ~covered).sum()) < spec.min_gain or combo in (c for c, _ in chosen):
                continue
            pairs = priced(combo) * n
            if combo not in cost:  # over the budget alone
                continue
            hit = raw & cost[combo]["normal"]  # a pair in one of its oversized blocks is listed only if the gate keeps the block: not counted
            gain = int((hit & ~covered).sum())
            if gain < spec.min_gain or pairs > left:
                continue
            score = (gain / (pairs / n + 1e-3), -len(combo), -sum(a.edits for a in combo))
            if best is None or score > best[0]:
                best = (score, combo, hit, gain, pairs)
        if best is None:
            break
        _, combo, hit, gain, pairs = best
        chosen.append((combo, hit))
        covered |= hit
        left -= pairs
        b = cost[combo]["blocker"]
        known[b.name] = {k: v for k, v in cost[combo].items() if k not in ("blocker", "pairs")}
        rows.append(dict(key=b.name, targets=round(gain * weight), pairs=int(pairs), per_record=round(pairs / n, 3)))
    run.con.execute("DROP TABLE IF EXISTS er_kl_s; DROP TABLE IF EXISTS er_kl_p; DROP TABLE IF EXISTS er_kl_d; DROP TABLE IF EXISTS er_kl_t")
    rec.close()
    left_out = int((~covered).sum())
    facts |= dict(learned=True, keys=rows, uncovered=round(left_out * weight), uncovered_sampled=left_out, seconds=round(time.perf_counter() - t0, 2),
                  draw_seconds=round(t_drawn - t0, 2), score_seconds=round(t_scored - t_drawn, 2), cover_seconds=round(time.perf_counter() - t_scored, 2))
    return tuple(cost[c]["blocker"] for c, _ in chosen), facts, known


def _normal(combo: tuple[Atom, ...], b: Blocker, targets: pd.DataFrame, found: list[Atom], rec: Records, m: int) -> np.ndarray:
    """Whether each target's block under this key holds fewer than m records, so the key's join lists it: the blocks
    of m or more (few) are found by a group-by, and each target looked up in them."""
    con, side = rec.con, lambda a, s: targets[f"{s}{found.index(a)}"]
    eq = [a for a in combo if not a.edits]
    if isinstance(b, KeyBlocker):
        cols = ", ".join(q(a.column) for a in eq)
        big = set(con.execute(f"SELECT {cols} FROM records WHERE {' AND '.join(f'{q(a.column)} IS NOT NULL' for a in eq)} "
                              f"GROUP BY ALL HAVING count(*) >= {m}").fetchall())
        return np.array([tuple(v) not in big for v in zip(*(side(a, "a") for a in eq))], bool) if big else np.ones(len(targets), bool)
    near = next(a for a in combo if a.edits)
    within = list(zip(*(side(a, "a") for a in eq))) if eq else [()] * len(targets)
    if isinstance(b, DeletionKeys):  # some deletion key the two share, in a normal block
        v = rec.variants(b)
        big = set(con.execute(f"SELECT __dk, {''.join(f'{q(a.column)}, ' for a in eq)}1 FROM {v} GROUP BY ALL HAVING count(*) >= {m}").fetchall())
        dels = lambda s: {s, *(s[:i] + s[i + 1:] for i in range(len(s)))} if isinstance(s, str) else set()
        return np.array([any((k, *w, 1) not in big for k in dels(x) & dels(y)) for x, y, w in zip(side(near, "a"), side(near, "b"), within)], bool)
    big = set(con.execute(f"SELECT {''.join(f'{q(a.column)}, ' for a in eq)}{q(near.column)} FROM records WHERE {q(near.column)} IS NOT NULL "
                          f"GROUP BY ALL HAVING count(*) >= {m}").fetchall())  # an edit key leaves out a value held by m records or more
    return np.array([(*w, x) not in big and (*w, y) not in big for x, y, w in zip(side(near, "a"), side(near, "b"), within)], bool)


def _agrees(a: Atom, x: pd.Series, y: pd.Series) -> np.ndarray:
    """Whether each pair (x, y) agrees on this atom, as its key would list them: equal, both filled; one deletion
    key shared (the value or one character deleted, from each); 1 to `edits` edits apart, each value at least edits + 1
    characters long."""
    filled = (x.notna() & y.notna()).to_numpy()
    if not a.edits:
        return filled & (x.fillna("\0x") == y.fillna("\0y")).to_numpy()
    out = np.zeros(len(x), bool)
    if a.edits == 1:
        dels = lambda v: {v, *(v[:i] + v[i + 1:] for i in range(len(v)))}
        out[filled] = [bool(dels(v) & dels(w)) for v, w in zip(x[filled], y[filled])]
        return out
    from rapidfuzz.distance import Levenshtein
    long = filled & (x.str.len().fillna(0) > a.edits).to_numpy() & (y.str.len().fillna(0) > a.edits).to_numpy()
    out[long] = [0 < Levenshtein.distance(v, w) <= a.edits for v, w in zip(x[long], y[long])]
    return out
