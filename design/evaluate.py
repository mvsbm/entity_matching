"""Evaluation against truth. Every metric is a group-by over records or pairs: O(N) or O(P), no pair enumeration.

pair_metrics counts the pairs the clusters make, cluster_metrics adds B-cubed, over-merged and split entities, and
false_pairs judges single pairs (scripts/benchmark.py reads all three).

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


def pair_metrics(cluster_id: pd.Series, entity: pd.Series, household: pd.Series | None = None) -> dict[str, float]:
    """Pairwise TP/FP/FN of clusters vs entities, from cluster × entity counts; with `household` (aligned to entity),
    the pairs of one household's people counted apart."""
    tp = c2(pd.DataFrame({"c": cluster_id.to_numpy(), "e": entity.to_numpy()}).value_counts())
    hh = c2(pd.DataFrame({"c": cluster_id.to_numpy(), "h": household.to_numpy()}).value_counts()) - tp if household is not None else 0
    predicted, actual = c2(cluster_id.value_counts()), c2(entity.value_counts())
    fp = predicted - tp - hh
    size = cluster_id.map(cluster_id.value_counts()).to_numpy()
    has_dup = entity.map(entity.value_counts()).to_numpy() > 1
    precision, recall = (tp / (tp + fp) if tp + fp else 1.0), (tp / actual if actual else 1.0)
    return dict(TP=tp, FP=fp, FN=actual - tp, household=hh, precision=precision, recall=recall,
                f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                FP_per_1k=1000 * fp / len(entity), resolved=int((size > 1).sum()),
                dup_unresolved=int((has_dup & (size == 1)).sum()))


def cluster_metrics(cluster_id: pd.Series, entity: pd.Series, household: pd.Series | None = None) -> dict[str, float]:
    """pair_metrics + B-cubed precision/recall + over-merged clusters + split entities."""
    frame = pd.DataFrame({"c": cluster_id.to_numpy(), "e": entity.to_numpy()})
    both = frame.groupby(["c", "e"])["c"].transform("size")
    c_size, e_size = frame.groupby("c")["c"].transform("size"), frame.groupby("e")["e"].transform("size")
    per_cluster, per_entity = frame.groupby("c")["e"].nunique(), frame.groupby("e")["c"].nunique()
    m = pair_metrics(cluster_id, entity, household)
    lo, hi = wilson(m["TP"], m["TP"] + m["FN"])
    return dict(**m, recall_lo=lo, recall_hi=hi, fp_rate_hi=fp_upper(m["FP"], m["TP"] + m["FP"]),
                bcubed_precision=float((both / c_size).mean()), bcubed_recall=float((both / e_size).mean()),
                overmerged=int((per_cluster > 1).sum()), split=int((per_entity > 1).sum()))


def false_pairs(left: pd.Series, right: pd.Series, entity: pd.Series, household: pd.Series | None = None) -> np.ndarray:
    """Whether each pair (its uids on the left and the right) is false: two entities, or with `household`, two households."""
    by = entity if household is None else household
    return left.map(by).to_numpy() != right.map(by).to_numpy()


def labelled(truth: pd.DataFrame, data) -> tuple[pd.Series, pd.Series | None]:
    """uid → entity, and uid → household where the labels name one (data.household_id)."""
    t = truth.set_index(data.unique_id)
    return t[data.entity_id], t[data.household_id] if data.household_id and data.household_id in t else None
