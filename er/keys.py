"""The keys learned on each file, with no labels: the pairs the run's model accepts are found by sampling, and the
keys that list most of them for the fewest pairs are chosen (Michelson & Knoblock's and Bilenko et al.'s learned
blocking, with the run's own model, fitted before any key is used, as the judge of what a pair is worth).

1. Atoms (er.sample), from the method: every column its keys, rules and comparisons read, equal; within one edit (deletion keys)
   for a column it compares by an edit distance or a similarity; within `edits` edits (PassJoin) for one it compares by
   a similarity. A value held by an oversized block's worth of records (a placeholder) pairs by none of them.
2. Targets (er.sample.discover): a hash-stable share f of the records, each paired with every record sharing an atom with it (or, where
   both of two atoms' blocks are oversized alone, both), scored through the bound at the review floor. A pair is drawn
   when either record is, so each counts for 1 / (1 − (1 − f)²) of the file's (the probe's estimator).
3. Coverage: which keys of up to `max_atoms` atoms (one of them at most within edits) list each target, as boolean
   vectors over them; cost: the pairs each lists, counted as the budget counts them (er.candidates.estimate).
4. The cover: while the budget lasts, the key that lists the most targets no key chosen lists, per pair it costs.

O(A·N) for the atoms' blocks, O(f·N·b) pairs scored, O(K·T) for coverage and O(K'·N) for the costs of the K' keys
that list a target.
"""
import time

import numpy as np
import pandas as pd

from er.candidates import estimate
from er.config import Blocker, DeletionKeys, EditKeys, KeyBlocker, keys_of, q
from er.match import _bits, _ranked, review_floor
from er.sample import Atom, agrees, discover, frame, generator_atoms, in_normal, key_lists, listed_by, poisson

EXTEND = 0.1  # pairs per record above which a key is tried one atom longer
SETS = 16     # equality keys counted in one scan (GROUPING SETS): one hash table each


def blocker(combo: tuple[Atom, ...]) -> Blocker:  # the generator a key of these atoms runs as
    eq, near = [a.key for a in combo if not a.edits], [a for a in combo if a.edits]
    name = "learned:" + "+".join(a.name for a in combo)
    if not near:
        return KeyBlocker(name=name, keys=tuple(eq))
    a = near[0]
    return (DeletionKeys(name=name, key=a.key, within=tuple(eq)) if a.edits == 1
            else EditKeys(name=name, key=a.key, within=tuple(eq), edits=a.edits))


GAP_RECORDS = 20_000  # records the gap report samples, whatever the file's size
IDLE_LOSS = 0.01      # an idle key is dropped only where the pairs at the floor it alone may list are, at 95%, at most this share of them


def gap_records(p) -> int:  # the records the gap's sample draws
    return p.keys.records if p.keys else GAP_RECORDS


def thresholds(p) -> list[float]:  # where the gap counts: the review floor, the model's line, 20 bits
    return sorted({review_floor(p), p.fs.min_match_weight, 20.0})


def agree_counts(atoms: list[Atom], lost: pd.DataFrame, w: float) -> list[dict]:  # how many of these pairs agree on each atom, scaled by w, the most first
    by = sorted(((a.name, int(agrees(a, lost[f"a{i}"], lost[f"b{i}"]).sum())) for i, a in enumerate(atoms)), key=lambda x: -x[1]) if len(lost) else []
    return [dict(atom=a, pairs=round(k * w)) for a, k in by if k]


def gap(run) -> dict:
    """The pairs the run's model would accept that no key or rule listed, estimated by sampling (discover): per
    threshold (the review floor, the model's line, 20 bits), the file's pairs at it and those missed, with 95% Poisson
    intervals (the probe's); and for those missed at the floor, how many agree on each atom, the keys that would reach them. O(f·N·b)."""
    t0 = time.perf_counter()
    reused = getattr(run, "found", None)  # drawn by the keys step, its time there: listed now
    d = reused or discover(run, gap_records(run.pipeline))
    d.rec.close()
    t, w = listed_by(run, d.targets), d.weight
    rows = []
    for at in thresholds(run.pipeline):
        x = t[t["match_weight"] >= at]
        missed = int((~x["listed"]).sum())
        lo, hi = poisson(missed)
        rows.append(dict(bits=at, pairs=round(len(x) * w), missed=round(missed * w), missed_lo=round(lo * w), missed_hi=round(hi * w), sampled_missed=missed))
    lost = t[~t["listed"]]
    alone = t[(t["match_weight"] >= review_floor(run.pipeline)) & ~t["ruled"]]["sources"].dropna()
    alone = alone[~alone.str.contains("+", regex=False)].value_counts()  # listed by one key and no rule: lost without it
    facts = {k: v for k, v in d.facts.items() if not (reused and k in ("draw_seconds", "score_seconds", "drawn_seconds"))}
    return {**facts, "reused": bool(reused), "thresholds": rows, "missed_agree": agree_counts(d.atoms, lost, w),
            "only": {k: round(v * w) for k, v in alone.items()}, "seconds": round(time.perf_counter() - t0, 2)}


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
    d = run.found = discover(run, gap_records(p))
    t, m = listed_by(run, d.targets), p.fs.budget.min_oversized()
    col = {a.column: i for i, a in reversed(list(enumerate(d.atoms)))}
    kept, dropped = list(p.fs.blockers), []
    for z in idle_:
        if any(a.column not in col for a in generator_atoms(z)):
            continue
        combo = generator_atoms(z)
        f = frame(t, combo, col)
        mine = t[np.logical_and.reduce([agrees(a, f[f"a{i}"], f[f"b{i}"]) for i, a in enumerate(combo)]) & ~t["ruled"].to_numpy()].reset_index(drop=True)
        others = np.zeros(len(mine), bool)
        for b in (b for b in kept if b not in idle_):  # the keys that stay whatever is dropped
            if not others.all():
                others |= key_lists(b, mine, col, d.rec, m)
        if others.all() and (d.weight == 1 or 3 <= IDLE_LOSS * len(t)):  # none of its own seen: in every record, or a sample large enough that what it may hold unseen (3 at 95%) is few
            kept.remove(z)
            dropped.append(z.name)
    d.rec.close()
    return tuple(kept), dropped


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

    agree = {a: agrees(a, targets[f"a{i}"], targets[f"b{i}"]) for i, a in enumerate(found)}
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
                               "normal": in_normal(combo, b, targets, found, rec, m)}
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


