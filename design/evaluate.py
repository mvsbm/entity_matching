"""Evaluation against truth. Every metric is a group-by over records or pairs: O(N) or O(P), no pair enumeration.

pair_metrics counts the pairs the engine's entities make, entity_metrics adds recall's interval and the false-pair
rate's bound, and false_pairs judges single pairs (scripts/benchmark.py reads all three). Each record has its engine entity
(the run's) and its true entity (the labels').

Where the labels name each record's household, a pair of two people of one household is neither true nor false: it
is counted apart (`household`), and people decide it. A false pair joins two households.
"""
import math

import numpy as np
import pandas as pd
from scipy.stats import beta


def c2(counts: pd.Series) -> int:  # pairs inside groups of these sizes
    return int((counts * (counts - 1) // 2).sum())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion k/n (recall, precision)."""
    if n == 0:
        return 0.0, 1.0
    p, d = k / n, 1 + z * z / n
    centre, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def fp_upper(fp: int, n: int, confidence: float = 0.95) -> float:
    """One-sided Clopper–Pearson upper bound on the FP rate after seeing fp false among n decisions.
    With fp = 0 this is ≈ 3/n (the rule of three): zero observed errors only bounds the rate."""
    return 1.0 if n == 0 or fp >= n else float(beta.ppf(confidence, fp + 1, n - fp))


def pair_metrics(engine_entity: pd.Series, true_entity: pd.Series, household: pd.Series | None = None) -> dict[str, float]:
    """Pairwise TP/FP/FN of the engine's entities vs the true ones, from engine entity × true entity counts; with
    `household` (aligned to true_entity), the pairs of one household's people counted apart."""
    tp = c2(pd.DataFrame({"c": engine_entity.to_numpy(), "e": true_entity.to_numpy()}).value_counts())
    hh = c2(pd.DataFrame({"c": engine_entity.to_numpy(), "h": household.to_numpy()}).value_counts()) - tp if household is not None else 0
    predicted, actual = c2(engine_entity.value_counts()), c2(true_entity.value_counts())
    fp = predicted - tp - hh
    return dict(TP=tp, FP=fp, FN=actual - tp, household=hh, recall=tp / actual if actual else 1.0)


def entity_metrics(engine_entity: pd.Series, true_entity: pd.Series, household: pd.Series | None = None) -> dict[str, float]:
    """pair_metrics, with recall's Wilson interval and the false-pair rate's upper bound."""
    m = pair_metrics(engine_entity, true_entity, household)
    lo, hi = wilson(m["TP"], m["TP"] + m["FN"])
    return dict(**m, recall_lo=lo, recall_hi=hi, fp_rate_hi=fp_upper(m["FP"], m["TP"] + m["FP"]))


def false_pairs(left: pd.Series, right: pd.Series, true_entity: pd.Series, household: pd.Series | None = None) -> np.ndarray:
    """Whether each pair (its uids on the left and the right) is false: two true entities, or with `household`, two
    households."""
    by = true_entity if household is None else household
    return left.map(by).to_numpy() != right.map(by).to_numpy()


def labelled(truth: pd.DataFrame, data) -> tuple[pd.Series, pd.Series | None]:
    """uid → true entity, and uid → household where the labels name one (data.household_id)."""
    t = truth.set_index(data.unique_id)
    return t[data.entity_id], t[data.household_id] if data.household_id and data.household_id in t else None
