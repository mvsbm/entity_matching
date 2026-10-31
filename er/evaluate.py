"""Evaluation against truth. Every metric is a group-by over records or pairs: O(N) or O(P), no pair enumeration.

Two levels:
  pairs (entity matching)    — the accepted pairs themselves, before transitive closure
  clusters (entity resolution) — pairwise after closure, B-cubed, over-merged and split entities
"""
import math

import numpy as np
import pandas as pd
from scipy.stats import beta, binomtest


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


def pair_metrics(cluster_id: pd.Series, entity: pd.Series) -> dict[str, float]:
    """Pairwise TP/FP/FN of clusters vs entities, from cluster × entity counts."""
    tp = c2(pd.DataFrame({"c": cluster_id.to_numpy(), "e": entity.to_numpy()}).value_counts())
    predicted, actual = c2(cluster_id.value_counts()), c2(entity.value_counts())
    size = cluster_id.map(cluster_id.value_counts()).to_numpy()
    has_dup = entity.map(entity.value_counts()).to_numpy() > 1
    precision, recall = (tp / predicted if predicted else 1.0), (tp / actual if actual else 1.0)
    return dict(TP=tp, FP=predicted - tp, FN=actual - tp, precision=precision, recall=recall,
                f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                FP_per_1k=1000 * (predicted - tp) / len(entity), resolved=int((size > 1).sum()),
                dup_unresolved=int((has_dup & (size == 1)).sum()))


def cluster_metrics(cluster_id: pd.Series, entity: pd.Series) -> dict[str, float]:
    """pair_metrics + B-cubed precision/recall + over-merged clusters + split entities."""
    frame = pd.DataFrame({"c": cluster_id.to_numpy(), "e": entity.to_numpy()})
    both = frame.groupby(["c", "e"])["c"].transform("size")
    c_size, e_size = frame.groupby("c")["c"].transform("size"), frame.groupby("e")["e"].transform("size")
    per_cluster, per_entity = frame.groupby("c")["e"].nunique(), frame.groupby("e")["c"].nunique()
    m = pair_metrics(cluster_id, entity)
    lo, hi = wilson(m["TP"], m["TP"] + m["FN"])
    return dict(**m, recall_lo=lo, recall_hi=hi, fp_rate_hi=fp_upper(m["FP"], m["TP"] + m["FP"]),
                bcubed_precision=float((both / c_size).mean()), bcubed_recall=float((both / e_size).mean()),
                overmerged=int((per_cluster > 1).sum()), split=int((per_entity > 1).sum()))


def edge_metrics(edges: pd.DataFrame, entity: pd.Series, uid: str) -> dict[str, float]:
    """The accepted pairs as decisions: how many are right, and what share of all true pairs they are."""
    same = edges[f"{uid}_l"].map(entity).to_numpy() == edges[f"{uid}_r"].map(entity).to_numpy()
    actual = c2(entity.value_counts())
    return dict(pairs=len(edges), pairs_TP=int(same.sum()), pairs_FP=int((~same).sum()),
                pairs_precision=float(same.mean()) if len(edges) else 1.0,
                pairs_recall=float(same.sum() / actual) if actual else 1.0,
                pairs_fp_rate_hi=fp_upper(int((~same).sum()), len(edges)))


def candidate_metrics(pairs: pd.DataFrame, entity: pd.Series, uid: str, targets: pd.DataFrame | None = None) -> dict[str, float]:
    """Pair completeness (share of true pairs among candidates), on all true pairs and on `targets` (e.g. the pairs
    an earlier stage missed), and reduction ratio (1 − candidates / all possible pairs)."""
    l, r = f"{uid}_l", f"{uid}_r"
    same = pairs[l].map(entity).to_numpy() == pairs[r].map(entity).to_numpy()
    n = len(entity)
    out = dict(candidates=len(pairs), true_in_candidates=int(same.sum()),
               completeness=float(same.sum() / c2(entity.value_counts())) if c2(entity.value_counts()) else 1.0,
               reduction_ratio=1 - len(pairs) / (n * (n - 1) / 2))
    if targets is not None:
        hit = targets.merge(pairs[[l, r]], on=[l, r], how="inner")
        out["completeness_on_targets"] = len(hit) / len(targets) if len(targets) else 1.0
    return out


def true_pairs(entity: pd.Series, uid: str) -> pd.DataFrame:
    """Every true pair, uid_l < uid_r. O(Σ k²) over entity sizes k: small, entities hold a few records."""
    frame = entity.rename("e").rename_axis(uid).reset_index()
    pairs = frame.merge(frame, on="e", suffixes=("_l", "_r"))
    return pairs[pairs[f"{uid}_l"] < pairs[f"{uid}_r"]][[f"{uid}_l", f"{uid}_r"]].reset_index(drop=True)


def missed_pairs(cluster_id: pd.Series, entity: pd.Series, uid: str) -> pd.DataFrame:
    """True pairs that the clusters do not join."""
    t = true_pairs(entity, uid)
    return t[t[f"{uid}_l"].map(cluster_id).to_numpy() != t[f"{uid}_r"].map(cluster_id).to_numpy()].reset_index(drop=True)


def predicted_pairs(cluster_id: pd.Series) -> set[tuple[str, str]]:
    """Every pair the clusters put together (uid_l < uid_r). O(Σ k²) over cluster sizes k; clusters are small."""
    out = set()
    for members in cluster_id.groupby(cluster_id.to_numpy()).groups.values():
        ids = sorted(map(str, members))
        out.update((a, b) for i, a in enumerate(ids) for b in ids[i + 1:])
    return out


def paired_test(base: set[tuple[str, str]], variant: set[tuple[str, str]], truth: set[tuple[str, str]]) -> dict[str, float]:
    """Compare two configurations on the same records, pair by pair. Gains / losses count true pairs one joins and
    the other doesn't; p is an exact two-sided sign test on them. Far more sensitive than comparing two recalls whose
    intervals overlap, because pairs both configurations agree on carry no information."""
    gains, losses = len((variant - base) & truth), len((base - variant) & truth)
    return dict(TP_gains=gains, TP_losses=losses, p=binomtest(gains, gains + losses, 0.5).pvalue if gains + losses else 1.0,
                FP_added=len((variant - base) - truth), FP_removed=len((base - variant) - truth))


def adopt(kind: str, selection: dict[str, float], val: dict[str, float], p_max: float) -> bool:
    """The decision rule, on paired_test results against the current choice. "better" needs a significant paired gain
    on the selection set, "cheaper" no paired loss there; both need no FP added there and no paired loss on val."""
    assert kind in ("better", "cheaper"), kind
    gain = (selection["TP_gains"] > selection["TP_losses"] and selection["p"] < p_max if kind == "better"
            else selection["TP_losses"] == 0)
    return gain and selection["FP_added"] == 0 and val["TP_gains"] >= val["TP_losses"] and val["FP_added"] <= val["FP_removed"]


def average_precision(scores: np.ndarray, same: np.ndarray) -> float:
    """Area under the precision–recall curve of a ranking (higher score first), over candidate pairs."""
    order = np.argsort(-scores, kind="stable")
    hits = same[order].astype(float)
    if not hits.sum():
        return 0.0
    precision_at = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float((precision_at * hits).sum() / hits.sum())
