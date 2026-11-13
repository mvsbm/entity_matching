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
import math
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from er.candidates import Records, estimate
from er.config import Blocker, DeletionKeys, EditKeys, Key, KeyBlocker, LearnKeys, Pipeline, keys_of, q
from er.match import _bits, _ranked, bound_tests, review_floor, scaled_prior, score_fs

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
    fs, k = p.fs, (p.keys or LearnKeys()).edits
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


@dataclass
class Found:
    """What discover() drew: the sampled pairs the model accepts at the review floor (targets: uid_l, uid_r, match_weight,
    listed, and a{i} / b{i} each atom's value on either side), the atoms, each counting for `weight` of the file's."""
    atoms: list[Atom]
    targets: pd.DataFrame
    weight: float
    facts: dict
    rec: Records
    sampled: dict


def reachable(run, floor: float, into: str = "er_kl_ok") -> int:
    """The records some pair of theirs could score `floor` with (a table of uids): the prior and, for each comparison any
    column of which the record holds, its best level's weight, or 0 if that is less. A pair scores at most what either of
    its records could, so a pair of a record outside it never reaches the floor. O(N). Returns how many."""
    p, have = run.pipeline, set(run.columns())
    lam = scaled_prior(run.scoring, run.n)
    terms = []
    for c, j in zip(p.fs.model.comparisons, run.scoring["comparisons"]):
        best = max([0.0, *(_bits(g, lv) for g, lv in _ranked(j) if g >= 0)])
        cols = sorted({x for lv in c.levels for col, comp in lv.any_of for x in (col, comp.column(col)) if x in have})
        if best > 0 and cols:
            terms.append(f"CASE WHEN {' OR '.join(f'{q(x)} IS NOT NULL' for x in cols)} THEN {best} ELSE 0 END")
    run.con.execute(f"CREATE OR REPLACE TABLE {into} AS SELECT {q(run.uid)} FROM records WHERE {math.log2(lam / (1 - lam))} + {' + '.join(terms) or '0'} >= {floor}")
    return run._count(into)


def discover(run, records: int) -> Found:
    """The pairs the run's model accepts at the review floor, by sampling: about `records` records drawn by a hash of
    their ID, each paired with every record sharing an atom with it (or two atoms, where both have blocks too big alone),
    those that can reach 0 scored. Only records that could reach the floor at all (reachable) are drawn or paired, and
    blocks are counted among them: a pair of another can't be a target, and a block can only be smaller, so no target
    is drawn less. `listed`: whether a key or a rule listed the pair (once the run's candidates exist), and `sources`, the
    keys that did. Each target counts for 1 / (1 − (1 − f)²) of the file's: a pair is drawn when either record is."""
    t0, p, con, uid, n = time.perf_counter(), run.pipeline, run.con, run.uid, run.n
    fs, m, floor = p.fs, p.fs.budget.min_oversized(), review_floor(p)
    found = atoms(p, run.columns())
    f = min(1.0, records / max(n, 1))
    u, l, r = q(uid), q(run.l), q(run.r)
    ok = reachable(run, floor)
    cols = list(dict.fromkeys(a.column for a in found))
    con.execute(f"CREATE OR REPLACE TABLE er_kl_r AS SELECT {u}, {', '.join(map(q, cols))} FROM records SEMI JOIN er_kl_ok USING ({u})")  # narrow
    con.execute(f"CREATE OR REPLACE TABLE er_kl_s AS SELECT {u} FROM er_kl_r WHERE hash({u}) % 1000000000 < {int(f * 1e9)}")
    con.execute("CREATE OR REPLACE TABLE er_kl_p (l VARCHAR, r VARCHAR)")
    def pair(a: str, b: str, rest: str) -> None:  # the pairs drawn, only those that can reach 0 (the run's two-stage bound): few, made distinct after every atom
        con.execute(f"INSERT INTO er_kl_p SELECT l, r FROM ({run._reaching(f'SELECT least({a}, {b}) AS l, greatest({a}, {b}) AS r FROM {rest}')})")
    eq = [a for a in found if not a.edits]
    crowd = {}  # each atom's values held by m records or more: its oversized blocks
    for i, a in enumerate(eq):
        con.execute(f"CREATE OR REPLACE TABLE er_kl_c{i} AS SELECT {q(a.column)} FROM er_kl_r WHERE {q(a.column)} IS NOT NULL GROUP BY 1 HAVING count(*) >= {m}")
        if run._count(f"er_kl_c{i}"):
            crowd[a.column] = f"er_kl_c{i}"

    def through(cols: list[str], src: str = "er_kl_r") -> None:  # each sampled record with every record of its block on these columns, normal blocks only
        c, filled = ", ".join(q(x) for x in cols), " AND ".join(f"{q(x)} IS NOT NULL" for x in cols)
        mine = f"(SELECT {u}, {c} FROM {src} WHERE {filled} AND {u} IN (SELECT {u} FROM er_kl_s))"  # the sampled records' blocks only are counted
        pair('a.' + u, 'b.' + u, f"""{mine} a JOIN (SELECT {c} FROM {src} SEMI JOIN (SELECT DISTINCT {c} FROM {mine}) k USING ({c})
            GROUP BY ALL HAVING count(*) < {m}) z USING ({c}) JOIN {src} b USING ({c}) WHERE a.{u} <> b.{u}""")
    took, t = {}, time.perf_counter()
    for a in eq:
        through([a.column])
    took["equal"], t = time.perf_counter() - t, time.perf_counter()
    for a, b in itertools.combinations([a for a in eq if a.column in crowd], 2):  # both with blocks too big alone: the records equal on both (an atom with normal ones drew them)
        x, y = q(a.column), q(b.column)
        con.execute(f"CREATE OR REPLACE TEMP VIEW er_kl_two AS SELECT {u}, {x}, {y} FROM er_kl_r WHERE {x} IN (SELECT * FROM {crowd[a.column]}) AND {y} IN (SELECT * FROM {crowd[b.column]})")
        through([a.column, b.column], "er_kl_two")  # in both crowds: the only records such a pair can hold
    took["two equal"], t = time.perf_counter() - t, time.perf_counter()
    near_of = {}  # each column's farthest near atom: PassJoin draws its values of 2(k + 1) characters or more
    for a in found:
        near_of[a.column] = max(near_of.get(a.column, 0), a.edits)
    rec = Records("er_kl_r", uid, con)
    rec.most, sampled = m, {}
    for a in (a for a in found if a.edits):
        k = q(a.column)
        if a.edits == 1:  # sharing a one-deletion key, in a normal deletion block; where PassJoin draws the long values, the short ones only
            far = near_of[a.column]
            if far >= 2:
                con.execute(f"CREATE OR REPLACE TEMP VIEW er_kl_short AS SELECT * FROM er_kl_r WHERE length({k}) <= {2 * (far + 1)}")
            src = rec if far < 2 else Records("er_kl_short", uid, con)
            v = src.variants(DeletionKeys(name="x", key=Key(a.column)))
            pair('x.' + u, 'y.' + u, f"""(SELECT * FROM {v} WHERE __dk IN (SELECT __dk FROM {v} GROUP BY 1 HAVING count(*) < {m})) x
                SEMI JOIN er_kl_s s USING ({u}) JOIN {v} y ON x.__dk = y.__dk AND x.{u} <> y.{u}""")
            if src is not rec:
                src.close()
        else:
            near = rec.near_values(EditKeys(name="x", key=Key(a.column), edits=a.edits), m, probe="er_kl_s")  # the sample's values against all
            rest = f"""{near} z JOIN er_kl_r x ON x.{k} = z.v JOIN er_kl_r y ON y.{k} = z.x
                WHERE x.{u} IN (SELECT {u} FROM er_kl_s) OR y.{u} IN (SELECT {u} FROM er_kl_s)"""
            sampled[a] = con.execute(f"SELECT count(*) FROM {rest}").fetchall()[0][0]  # the pairs it lists touching the sample: its pairs, scaled
            pair('x.' + u, 'y.' + u, rest)
        took[a.name] = time.perf_counter() - t
        t = time.perf_counter()
    rec.close()
    con.execute(f"""CREATE OR REPLACE TABLE er_kl_d AS SELECT DISTINCT p.l AS {l}, p.r AS {r} FROM er_kl_p p JOIN rule_clusters a ON a.{u} = p.l
        JOIN rule_clusters b ON b.{u} = p.r WHERE a.cluster_id <> b.cluster_id""")  # a pair inside one rule cluster is the rules'
    drawn, t_drawn = run._count("er_kl_d"), time.perf_counter()
    score_fs(run.scoring, "records", "er_kl_d", run.db, uid, into="er_kl_t", n_records=n, floor=floor, bound=bound_tests(fs.model))
    con.execute(f"DELETE FROM er_kl_t WHERE match_weight < {floor}")
    targets = con.execute(f"""SELECT t.{l}, t.{r}, t.match_weight,
        {', '.join(f'a.{q(a.column)} AS {q("a" + str(i))}, b.{q(a.column)} AS {q("b" + str(i))}' for i, a in enumerate(found))}
        FROM er_kl_t t JOIN records a ON a.{u} = t.{l} JOIN records b ON b.{u} = t.{r} ORDER BY 1, 2""").df()
    targets = listed_by(run, targets)
    con.execute("DROP VIEW IF EXISTS er_kl_two; DROP VIEW IF EXISTS er_kl_short; " + "; ".join(f"DROP TABLE IF EXISTS {x}" for x in ("er_kl_s", "er_kl_p", "er_kl_d", "er_kl_t", "er_kl_r", "er_kl_ok", *crowd.values()))
                + "; " + "; ".join(f"DROP TABLE IF EXISTS er_kl_c{i}" for i in range(len(eq))))
    weight = 1 / (1 - (1 - f) ** 2)
    facts = dict(atoms=[a.name for a in found], share=round(f, 4), sampled_records=round(f * n), reachable=ok, drawn=drawn, targets=len(targets),
                 estimated=round(len(targets) * weight), draw_seconds=round(t_drawn - t0, 2), score_seconds=round(time.perf_counter() - t_drawn, 2),
                 drawn_seconds={k: round(v, 2) for k, v in took.items()})
    full = Records("records", uid, con)
    full.most = m
    return Found(found, targets, weight, facts, full, sampled)


def listed_by(run, targets: pd.DataFrame) -> pd.DataFrame:
    """The targets with `listed` (a key or a rule listed the pair), `ruled` (a rule did) and `sources` (the keys that
    did, as candidates names them), from the run's candidates and rules' edges as they stand: none listed before the candidates step."""
    con, l, r = run.con, q(run.l), q(run.r)
    have = {t for (t,) in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    con.register("er_kl_tg", targets[[run.l, run.r]])
    try:
        cands = f"(SELECT {l}, {r}, sources FROM cands)" if "cands" in have else f"(SELECT NULL::VARCHAR AS {l}, NULL::VARCHAR AS {r}, NULL::VARCHAR AS sources WHERE FALSE)"
        rules = f"EXISTS (SELECT 1 FROM rule_edges e WHERE e.{l} = t.{l} AND e.{r} = t.{r})" if "rule_edges" in have else "FALSE"
        got = con.execute(f"""SELECT c.sources, {rules} AS ruled, c.{l} IS NOT NULL OR {rules} AS listed FROM er_kl_tg t LEFT JOIN {cands} c USING ({l}, {r})
            ORDER BY t.{l}, t.{r}""").df()
    finally:
        con.unregister("er_kl_tg")
    return targets.assign(listed=got["listed"].astype(bool).to_numpy(), ruled=got["ruled"].astype(bool).to_numpy(), sources=got["sources"].to_numpy())


GAP_RECORDS = 20_000  # records the gap report samples, whatever the file's size


def gap(run) -> dict:
    """The pairs the run's model would accept that no key or rule listed, estimated by sampling (discover): per
    threshold (the review floor, the model's line, 20 bits), the file's pairs at it and those missed, with 95% Poisson
    intervals (the probe's); and for those missed at the floor, how many agree on each atom, the keys that would reach them. O(f·N·b)."""
    t0 = time.perf_counter()
    d = getattr(run, "found", None) or discover(run, run.pipeline.keys.records if run.pipeline.keys else GAP_RECORDS)  # drawn by the keys step: listed now
    d.rec.close()
    t, w = listed_by(run, d.targets), d.weight
    rows = []
    for at in sorted({review_floor(run.pipeline), run.pipeline.fs.min_match_weight, 20.0}):
        x = t[t["match_weight"] >= at]
        missed = int((~x["listed"]).sum())
        lo, hi = _poisson(missed)
        rows.append(dict(bits=at, pairs=round(len(x) * w), missed=round(missed * w), missed_lo=round(lo * w), missed_hi=round(hi * w), sampled_missed=missed))
    lost = t[~t["listed"]]
    by = sorted(((a.name, int(_agrees(a, lost[f"a{i}"], lost[f"b{i}"]).sum())) for i, a in enumerate(d.atoms)), key=lambda x: -x[1]) if len(lost) else []
    alone = t[(t["match_weight"] >= review_floor(run.pipeline)) & ~t["ruled"]]["sources"].dropna()
    alone = alone[~alone.str.contains("+", regex=False)].value_counts()  # listed by one key and no rule: lost without it
    return {**d.facts, "thresholds": rows, "missed_agree": [dict(atom=a, pairs=round(k * w)) for a, k in by if k],
            "only": {k: round(v * w) for k, v in alone.items()}, "seconds": round(time.perf_counter() - t0, 2)}


def generator_atoms(b: Blocker) -> tuple[Atom, ...] | None:  # the atoms a generator lists by, all of them: None for one that lists otherwise (sorted, TF-IDF)
    if isinstance(b, KeyBlocker):
        return tuple(Atom(k, 0) for k in b.keys)
    if isinstance(b, DeletionKeys):
        return (*(Atom(w, 0) for w in b.within), Atom(b.key, 1))
    if isinstance(b, EditKeys):
        return (*(Atom(w, 0) for w in b.within), Atom(b.key, b.edits))
    return None


def idle(run) -> tuple[tuple[Blocker, ...], list[str]]:
    """The generators to run: each but those whose agreement is no evidence (every comparison reading its fields, if
    any, weighs at most 0 bits at its best level: an ID handed out in sequence, one digit off) and that list no sampled
    pair at the review floor no other generator or rule lists. Such a key's pairs reach the floor on other fields alone,
    so another key that reads them lists them, and it costs its pairs for nothing; one with a pair of its own stays. The
    sample is the gap step's (discover), kept for it: run.found. Returns the generators kept and those dropped."""
    p = run.pipeline
    best = {c.name: max([0.0, *(_bits(g, lv) for g, lv in _ranked(j) if g >= 0)]) for c, j in zip(p.fs.model.comparisons, run.scoring["comparisons"])}
    reads = {c.name: {col for lv in c.levels for col, _ in lv.any_of} | set(c.null_if_missing) for c in p.fs.model.comparisons}
    idle_ = [b for b in p.fs.blockers if generator_atoms(b) and all(best[c] <= 0 for c, cols in reads.items() if cols & {k.column for k in keys_of(b)})]
    if not idle_:
        return p.fs.blockers, []
    d = run.found = discover(run, p.keys.records if p.keys else GAP_RECORDS)
    t, m = listed_by(run, d.targets), p.fs.budget.min_oversized()
    col = {a.column: i for i, a in reversed(list(enumerate(d.atoms)))}

    def frame(rows: pd.DataFrame, combo: tuple[Atom, ...]) -> pd.DataFrame:  # these targets' values on each atom of the combo, as _agrees and _normal read them
        return pd.DataFrame({f"{s}{i}": rows[f"{s}{col[a.column]}"].to_numpy() for i, a in enumerate(combo) for s in "ab"})

    def lists(b: Blocker, rows: pd.DataFrame) -> np.ndarray:  # whether the generator lists each of these targets
        combo = generator_atoms(b)
        if combo is None or any(a.column not in col for a in combo):
            return np.zeros(len(rows), bool)
        f = frame(rows, combo)
        hit = np.logical_and.reduce([_agrees(a, f[f"a{i}"], f[f"b{i}"]) for i, a in enumerate(combo)])
        if hit.any():
            hit[hit] = _normal(combo, b, f[hit].reset_index(drop=True), list(combo), d.rec, m)
        return hit
    kept, dropped = list(p.fs.blockers), []
    for z in idle_:
        if any(a.column not in col for a in generator_atoms(z)):
            continue
        combo = generator_atoms(z)
        f = frame(t, combo)
        mine = t[np.logical_and.reduce([_agrees(a, f[f"a{i}"], f[f"b{i}"]) for i, a in enumerate(combo)]) & ~t["ruled"].to_numpy()].reset_index(drop=True)
        others = np.zeros(len(mine), bool)
        for b in (b for b in kept if b not in idle_):  # the keys that stay whatever is dropped
            if not others.all():
                others |= lists(b, mine)
        if others.all():
            kept.remove(z)
            dropped.append(z.name)
    d.rec.close()
    return tuple(kept), dropped


def _poisson(k: int) -> tuple[float, float]:  # about 95% for a count of k, as the probe gives it: none, the rule of three
    return (max(k - 1.96 * math.sqrt(k), 0.0), k + 1.96 * math.sqrt(k)) if k else (0.0, 3.0)


def learn(run, f: float | None = None) -> tuple[tuple[Blocker, ...], dict, dict[str, dict]]:
    """The keys for this run's records (run: an er.run.Run fitted, its rules run), what was found, and each chosen key's
    estimate as er.candidates.estimate gives it (the candidates step reads them, not the records again)."""
    t0, p, con, n = time.perf_counter(), run.pipeline, run.con, run.n
    spec, fs, m = p.keys, p.fs, p.fs.budget.min_oversized()
    d = discover(run, spec.records)
    found, targets, weight, rec, sampled, facts = d.atoms, d.targets, d.weight, d.rec, d.sampled, d.facts
    t_scored = time.perf_counter()
    if targets.empty:
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
    rec.close()
    left_out = int((~covered).sum())
    facts |= dict(learned=True, keys=rows, uncovered=round(left_out * weight), uncovered_sampled=left_out, seconds=round(time.perf_counter() - t0, 2),
                  cover_seconds=round(time.perf_counter() - t_scored, 2))
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
    long = filled & (x.str.len().fillna(0) >= 2 * (a.edits + 1)).to_numpy() & (y.str.len().fillna(0) >= 2 * (a.edits + 1)).to_numpy()  # as an edit key pairs them
    out[long] = [0 < Levenshtein.distance(v, w) <= a.edits for v, w in zip(x[long], y[long])]
    return out
