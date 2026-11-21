"""The gap: the pairs the run's model would accept that no key or rule listed, estimated without labels, at design
time (scripts/benchmark.py), on a Run that has clustered.

1. Atoms (design.sample), from the method: every column its keys, rules and comparisons read, equal; within one edit (deletion keys)
   for a column it compares by an edit distance or a similarity; within EDITS edits (PassJoin) for one it compares by
   a similarity. A value held by an oversized block's worth of records (a placeholder) pairs by none of them.
2. Targets (design.sample.discover): a hash-stable share f of the records, each paired with every record sharing an atom with it (or, where
   both of two atoms' blocks are oversized alone, both), scored with the run's model. A pair is drawn
   when either record is, so each counts for 1 / (1 − (1 − f)²) of the file's (the probe's estimator).
3. Per threshold, the targets at it and those no key or rule lists, with 95% Poisson intervals; for those missed, the
   atoms they agree on: the keys that would reach them.

O(A·N) for the atoms' blocks, O(f·N·b) pairs scored.
"""
import time

import pandas as pd

from er.match import review_floor, search_floor
from design.sample import Atom, agrees, discover, listed_by, poisson

GAP_RECORDS = 20_000  # records the gap samples, whatever the file's size


def thresholds(p) -> list[float]:  # where the gap counts: the search floor, the review floor, the model's line, 20 bits
    return sorted({search_floor(p), review_floor(p), p.fs.min_match_weight, 20.0})


def agree_counts(atoms: list[Atom], lost: pd.DataFrame, w: float) -> list[dict]:  # how many of these pairs agree on each atom, scaled by w, the most first
    by = sorted(((a.name, int(agrees(a, lost[f"a{i}"], lost[f"b{i}"]).sum())) for i, a in enumerate(atoms)), key=lambda x: -x[1]) if len(lost) else []
    return [dict(atom=a, pairs=round(k * w)) for a, k in by if k]


def gap(run) -> dict:
    """The pairs the run's model would accept that no key or rule listed, estimated by sampling (discover): per
    threshold (the search floor, the review floor, the model's line, 20 bits), the file's pairs at it and those missed, with 95% Poisson
    intervals (the probe's); for those missed at the floor, how many agree on each atom, the keys that would reach them;
    and the pairs at the review floor only one key lists, by key. O(f·N·b)."""
    t0 = time.perf_counter()
    d = discover(run, GAP_RECORDS)
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
    return {**d.facts, "thresholds": rows, "missed_agree": agree_counts(d.atoms, lost, w),
            "only": {k: round(v * w) for k, v in alone.items()}, "seconds": round(time.perf_counter() - t0, 2)}
