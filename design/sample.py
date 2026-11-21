"""The pairs the run's model accepts, found by sampling, with no labels (design.gap measures the gap the keys leave by
them; er.sizes sizes a fit by them). Atoms, from the method: every column its keys, rules and
comparisons read, equal, or within edits (atoms). A hash-stable share of the records, each paired with every record
sharing an atom with it, scored through the bound at the search floor (discover); which of them a key or rule listed
(listed_by), and which a generator lists (key_lists). O(A·N) for the atoms' blocks, O(f·N·b) pairs scored."""
import itertools
import math
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from er.candidates import KEEP_SLICE, Records, deletions_sql
from er.config import EditKeys, hashed, Key, keys_of, Pipeline, q
from er.match import DISTANCES, SIMILARITIES, _bits, _ranked, bound_tests, scaled_prior, search_floor, score_fs
from er.steps.candidates import reaching
from er.steps.rules import alone

EDITS = 2  # a column compared by a similarity is an atom within one edit and within this many (PassJoin)


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
    column by an edit distance (one) or a similarity (one, and EDITS). Only the columns the records hold."""
    fs, k = p.fs, EDITS
    eq = {x for b in fs.blockers for x in keys_of(b)} | {x for b in p.rules.blockers() for x in keys_of(b)}
    near: dict[Key, set[int]] = {}
    for c in fs.model.comparisons:
        for lv in c.levels:
            for col, comp in lv.any_of:
                eq.add(key := Key(col, comp.normalize))
                if comp.function in SIMILARITIES:  # one and `edits` edits apart are atoms
                    near.setdefault(key, set()).update({1, k})
                elif comp.function in DISTANCES and (comp.threshold or 0) >= 1:
                    near.setdefault(key, set()).add(1)
    one = {}  # a column a key and a comparison both read: one atom
    for x in sorted(eq, key=lambda x: (x.name, len(x.normalize))):
        one.setdefault(x.name, x)
    return sorted([Atom(x, 0) for c, x in one.items() if c in have] + [Atom(x, e) for x, es in near.items() if x.name in have for e in es],
                  key=lambda a: (a.edits, a.column))



@dataclass
class Found:
    """What discover() drew: the sampled pairs the model accepts at the floor (targets: uid_l, uid_r, match_weight,
    listed, and a{i} / b{i} each atom's value on either side), the atoms, each counting for `weight` of the file's."""
    atoms: list[Atom]
    targets: pd.DataFrame
    weight: float
    facts: dict
    rec: Records


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
    run.engine.run(f"CREATE OR REPLACE TABLE {into} AS SELECT {q(run.uid)} FROM records WHERE {math.log2(lam / (1 - lam))} + {' + '.join(terms) or '0'} >= {floor}")
    return run.job.count(into)


def discover(run, records: int, floor: float | None = None) -> Found:
    """The pairs the run's model accepts at `floor` (default: the search floor), by sampling: about `records` records drawn by a hash of
    their ID, each paired with every record sharing an atom with it (or two atoms, where both have blocks too big alone),
    those that can reach 0 scored. Only records that could reach the floor at all (reachable) are drawn or paired, and
    blocks are counted among them: a pair of another can't be a target, and a block can only be smaller, so no target
    is drawn less. `listed`: whether a key or a rule listed the pair (once the run's candidates exist), and `sources`, the
    keys that did. Each target counts for 1 / (1 − (1 − f)²) of the file's: a pair is drawn when either record is."""
    t0, p, engine, uid, n = time.perf_counter(), run.pipeline, run.engine, run.uid, run.n
    fs, m, floor = p.fs, p.fs.budget.min_oversized(), search_floor(p) if floor is None else floor
    found = atoms(p, run.columns())
    f = min(1.0, records / max(n, 1))
    u, l, r = q(uid), q(run.l), q(run.r)
    ok = reachable(run, floor)
    cols = list(dict.fromkeys(a.column for a in found))
    engine.run(f"CREATE OR REPLACE TABLE er_kl_r AS SELECT {u}, {', '.join(map(q, cols))} FROM records SEMI JOIN er_kl_ok USING ({u})")  # narrow
    engine.run(f"CREATE OR REPLACE TABLE er_kl_s AS SELECT {u} FROM er_kl_r WHERE {hashed(u)} % 1000000000 < {int(f * 1e9)}")
    engine.run("CREATE OR REPLACE TABLE er_kl_p (l VARCHAR, r VARCHAR); CREATE OR REPLACE TABLE er_kl_q (l VARCHAR, r VARCHAR)")
    def bounded() -> None:  # the pairs listed so far, distinct, only those that can reach 0 (the run's two-stage bound): one pass, not one per atom
        engine.run(f"INSERT INTO er_kl_p SELECT l, r FROM ({reaching(run.job, run.scoring, run.n, 'SELECT DISTINCT l, r FROM er_kl_q')}); DELETE FROM er_kl_q")
    def pair(a: str, b: str, rest: str) -> None:  # the pairs drawn, bounded KEEP_SLICE at a time
        engine.run(f"INSERT INTO er_kl_q SELECT least({a}, {b}) AS l, greatest({a}, {b}) AS r FROM {rest}")
        if run.job.count("er_kl_q") >= KEEP_SLICE:
            bounded()
    eq = [a for a in found if not a.edits]
    crowd = {}  # each atom's values held by m records or more: its oversized blocks
    for i, a in enumerate(eq):
        engine.run(f"CREATE OR REPLACE TABLE er_kl_c{i} AS SELECT {q(a.column)} FROM er_kl_r WHERE {q(a.column)} IS NOT NULL GROUP BY 1 HAVING count(*) >= {m}")
        if run.job.count(f"er_kl_c{i}"):
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
        engine.run(f"CREATE OR REPLACE TEMP VIEW er_kl_two AS SELECT {u}, {x}, {y} FROM er_kl_r WHERE {x} IN (SELECT * FROM {crowd[a.column]}) AND {y} IN (SELECT * FROM {crowd[b.column]})")
        through([a.column, b.column], "er_kl_two")  # in both crowds: the only records such a pair can hold
    took["two equal"], t = time.perf_counter() - t, time.perf_counter()
    near_of = {}  # each column's farthest near atom: PassJoin draws its values of 2(k + 1) characters or more
    for a in found:
        near_of[a.column] = max(near_of.get(a.column, 0), a.edits)
    rec = Records("er_kl_r", uid, engine)
    rec.most = m
    for a in (a for a in found if a.edits):
        k = q(a.column)
        if a.edits == 1:  # sharing a one-deletion key, in a normal deletion block; where PassJoin draws the long values, the short ones only
            far = near_of[a.column]
            if far >= 2:
                engine.run(f"CREATE OR REPLACE TEMP VIEW er_kl_short AS SELECT * FROM er_kl_r WHERE length({k}) <= {2 * (far + 1)}")
            src, dk = "er_kl_r" if far < 2 else "er_kl_short", f"unnest({deletions_sql(k)}) AS __dk"
            # the sampled records' deletion keys, then every record's rows of those keys alone: a block no sampled record is in
            # is never made, so memory follows the sample, not every record's L deletions of L characters
            engine.run(f"""CREATE OR REPLACE TEMP TABLE er_kl_x AS SELECT {u}, {dk} FROM {src} WHERE {k} IS NOT NULL AND {u} IN (SELECT {u} FROM er_kl_s);
                CREATE OR REPLACE TEMP TABLE er_kl_y AS SELECT * FROM (SELECT {u}, {dk} FROM {src} WHERE {k} IS NOT NULL) WHERE __dk IN (SELECT __dk FROM er_kl_x)""")
            pair('x.' + u, 'y.' + u, f"""(SELECT * FROM er_kl_x WHERE __dk IN (SELECT __dk FROM er_kl_y GROUP BY 1 HAVING count(*) < {m})) x
                JOIN er_kl_y y ON x.__dk = y.__dk AND x.{u} <> y.{u}""")
        else:
            near = rec.near_values(EditKeys(name="x", key=Key(a.column), edits=a.edits), m, probe="er_kl_s")  # the sample's values against all
            rest = f"""{near} z JOIN er_kl_r x ON x.{k} = z.v JOIN er_kl_r y ON y.{k} = z.x
                WHERE x.{u} IN (SELECT {u} FROM er_kl_s) OR y.{u} IN (SELECT {u} FROM er_kl_s)"""
            pair('x.' + u, 'y.' + u, rest)
        took[a.name] = time.perf_counter() - t
        t = time.perf_counter()
    rec.close()
    bounded()
    took["bound"] = time.perf_counter() - t
    apart = "" if fs.bridge else f" AND {alone(f'a.{u}', f'b.{u}', run.uid)}"  # without bridging, two rule entities are never compared: the probe counts those pairs
    engine.run(f"""CREATE OR REPLACE TABLE er_kl_d AS SELECT DISTINCT p.l AS {l}, p.r AS {r} FROM er_kl_p p JOIN rule_clusters a ON a.{u} = p.l
        JOIN rule_clusters b ON b.{u} = p.r WHERE a.cluster_id <> b.cluster_id{apart}""")  # a pair inside one rule cluster is the rules'
    drawn, t_drawn = run.job.count("er_kl_d"), time.perf_counter()
    score_fs(run.scoring, "records", "er_kl_d", run.engine, uid, into="er_kl_t", n_records=n, floor=floor, bound=bound_tests(fs.model))
    engine.run(f"DELETE FROM er_kl_t WHERE match_weight < {floor}")
    targets = engine.frame(f"""SELECT t.{l}, t.{r}, t.match_weight,
        {', '.join(f'a.{q(a.column)} AS {q("a" + str(i))}, b.{q(a.column)} AS {q("b" + str(i))}' for i, a in enumerate(found))}
        FROM er_kl_t t JOIN records a ON a.{u} = t.{l} JOIN records b ON b.{u} = t.{r} ORDER BY 1, 2""")
    targets = listed_by(run, targets)
    engine.run("DROP VIEW IF EXISTS er_kl_two; DROP VIEW IF EXISTS er_kl_short; " + "; ".join(f"DROP TABLE IF EXISTS {x}" for x in ("er_kl_s", "er_kl_p", "er_kl_q", "er_kl_d", "er_kl_t", "er_kl_x", "er_kl_y", "er_kl_r", "er_kl_ok", *crowd.values()))
                + "; " + "; ".join(f"DROP TABLE IF EXISTS er_kl_c{i}" for i in range(len(eq))))
    weight = 1 / (1 - (1 - f) ** 2)
    facts = dict(atoms=[a.name for a in found], share=round(f, 4), sampled_records=round(f * n), reachable=ok, drawn=drawn, targets=len(targets),
                 estimated=round(len(targets) * weight), draw_seconds=round(t_drawn - t0, 2), score_seconds=round(time.perf_counter() - t_drawn, 2),
                 drawn_seconds={k: round(v, 2) for k, v in took.items()})
    full = Records("records", uid, engine)
    full.most = m
    return Found(found, targets, weight, facts, full)


def listed_by(run, targets: pd.DataFrame) -> pd.DataFrame:
    """The targets with `listed` (a key listed the pair or a rule kept it), `ruled` (a rule kept it) and `sources` (the keys that
    did, as candidates names them), from the run's candidates and rules' edges as they stand: none listed before the candidates step."""
    engine, l, r = run.engine, q(run.l), q(run.r)
    have = {t for (t,) in engine.rows("SELECT table_name FROM duckdb_tables()")}
    engine.register("er_kl_tg", targets[[run.l, run.r]])
    try:
        cands = f"(SELECT {l}, {r}, sources FROM cands)" if "cands" in have else f"(SELECT NULL::VARCHAR AS {l}, NULL::VARCHAR AS {r}, NULL::VARCHAR AS sources WHERE FALSE)"
        rules = f"EXISTS (SELECT 1 FROM rule_kept e WHERE e.{l} = t.{l} AND e.{r} = t.{r})" if "rule_kept" in have else "FALSE"  # the pairs the rules kept: one found and dropped is no one's
        got = engine.frame(f"""SELECT c.sources, {rules} AS ruled, c.{l} IS NOT NULL OR {rules} AS listed FROM er_kl_tg t LEFT JOIN {cands} c USING ({l}, {r})
            ORDER BY t.{l}, t.{r}""")
    finally:
        engine.unregister("er_kl_tg")
    return targets.assign(listed=got["listed"].astype(bool).to_numpy(), ruled=got["ruled"].astype(bool).to_numpy(), sources=got["sources"].to_numpy())



def poisson(k: int) -> tuple[float, float]:  # about 95% for a count of k, as the probe gives it: none, the rule of three
    return (max(k - 1.96 * math.sqrt(k), 0.0), k + 1.96 * math.sqrt(k)) if k else (0.0, 3.0)



def agrees(a: Atom, x: pd.Series, y: pd.Series) -> np.ndarray:
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
