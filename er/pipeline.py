"""Stage cascade, preflight (time complexity before any join), and the rule-based run.

Cascade semantics: stages run in order. A stage's accepted pairs are kept only if at least one record is still
unresolved (in a singleton cluster), then everything kept so far is resolved again. Metrics after each stage are
cumulative: matching metrics on the accepted pairs, resolution metrics on the clusters.
"""
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyarrow as pa
from splink import DuckDBAPI

from er.candidates import candidates
from er.config import (Budget, Data, KeyBlocker, OverBudget, ProbSpec, RulesSpec, SortedNeighbourhood, TfidfNeighbours,
                       ThresholdRule)
from er.evaluate import (average_precision, candidate_metrics, cluster_metrics, edge_metrics, fp_upper, missed_pairs,
                         wilson)
from er.match import rule_edges, score_fs
from er.resolve import resolve
from er.standardize import prepare
from er.strings import FUNCTIONS, udf

BENCH: dict[tuple[str, str], float] = {}  # seconds per pair, by (column, function)


def pair_seconds(values: pd.Series, column: str, function: str, n: int) -> float:
    if (column, function) not in BENCH:
        v = values.dropna().to_numpy()
        rng = np.random.default_rng(0)
        a, b = pa.array(rng.choice(v, n).tolist()), pa.array(rng.choice(v, n).tolist())
        t = time.perf_counter()
        udf(function)(a, b)
        BENCH[column, function] = (time.perf_counter() - t) / n
    return BENCH[column, function]


def preflight(spec: RulesSpec, df: pd.DataFrame) -> pd.DataFrame:
    """Work per rule before any join: P = Σ C(k,2) over the blocks of its equi-join columns (a group-by, O(N))."""
    n, rows = len(df), []
    for s in spec.stages:
        for r in s.rules:
            keys = s.keys(r)
            blocks = df.dropna(subset=keys).groupby(keys).size()
            p = int((blocks * (blocks - 1) // 2).sum())
            fuzzy = [(c, s.comparators[c]) for c in r.fuzzy if s.comparators[c].function != "exact"]
            per_pair = sum(FUNCTIONS[comp.function].ops(df[comp.column(c)].dropna().str.len().mean()) for c, comp in fuzzy)
            est = sum(p * pair_seconds(df[comp.column(c)], comp.column(c), comp.function, spec.budget.benchmark_pairs)
                      for c, comp in fuzzy)
            rows.append(dict(
                stage=s.name, rule=r.name, keys=" + ".join(keys),
                fuzzy=", ".join(f"{c}: {comp.function}" for c, comp in fuzzy) or "—",
                big_o=f"O(N + P·({' + '.join(FUNCTIONS[comp.function].big_o for _, comp in fuzzy)}))" if fuzzy else "O(N + P)",
                filled=f"O({n:,} + {p:,}·{per_pair:,.0f})" if fuzzy else f"O({n:,} + {p:,})",
                ops=n + p * max(per_pair, 1), P=p, largest_block=int(blocks.max()) if len(blocks) else 0,
                est_fuzzy_ms=round(1000 * est, 2), projected_P=int(p * (spec.budget.target_rows / n) ** 2)))
    return pd.DataFrame(rows)


def grown_pairs(df: pd.DataFrame, entity: pd.Series, uid: str, cols: list[str], target_rows: int,
                fractions: tuple[float, ...] = (0.25, 0.5, 1.0), seed: int = 0) -> tuple[float, int]:
    """How a key's block pairs P grow with the population (P ∝ N^α), and P projected to target_rows.
    Measured by keeping whole entities, which mimics a smaller population of the same kind: on a key with few
    distinct values (the last four phone digits) chance collisions shrink with the square, true duplicates only
    linearly. A key whose value pool grows with the population (addresses) comes out a little steeper than it
    really is, which is the safe side. O(N) per fraction."""
    ent = df[uid].map(entity)
    order = np.random.default_rng(seed).permutation(ent.unique())
    rank = ent.map(pd.Series(np.arange(len(order)), index=order)).to_numpy()  # an entity's place in a random order
    sizes, pairs = [], []
    for f in fractions:
        keep = rank < max(1, int(len(order) * f))
        blocks = df[keep].dropna(subset=cols).groupby(cols).size()
        sizes.append(int(keep.sum()))
        pairs.append(max(int((blocks * (blocks - 1) // 2).sum()), 1))
    alpha = float(np.polyfit(np.log(sizes), np.log(pairs), 1)[0])
    return alpha, int(pairs[-1] * (target_rows / sizes[-1]) ** alpha)


def scale_check(spec: RulesSpec | ProbSpec, records: pd.DataFrame, truth: pd.DataFrame, data: Data) -> pd.DataFrame:
    """Every join key of a configuration, with its pairs projected to budget.target_rows. Key blocks are measured
    (grown_pairs); a sorted neighbourhood makes at most N·(w − 1) pairs; TF-IDF neighbours compare each query
    with every record, so up to N² similarities. `within_budget` is False where the projection exceeds
    budget.max_candidate_pairs: such a configuration would stop with OverBudget at that size."""
    uid, budget = data.unique_id, spec.budget
    df = prepare(spec.standardize, records, spec.normalized(), spec.used())
    entity = truth.set_index(uid)[data.entity_id]
    rows = []
    if isinstance(spec, RulesSpec):
        keyed = [(r.name, s.keys(r)) for s in spec.stages for r in s.rules]
    else:
        keyed = [(b.name, [k.name for k in b.keys]) for b in spec.blockers if isinstance(b, KeyBlocker)]
        for b in spec.blockers:
            if isinstance(b, SortedNeighbourhood):
                rows.append(dict(key=b.name, columns=b.key.name, alpha=1.0, projected_pairs=budget.target_rows * (b.window - 1)))
            elif isinstance(b, TfidfNeighbours):
                rows.append(dict(key=b.name, columns=b.key.name, alpha=2.0, projected_pairs=budget.target_rows ** 2))
    for name, cols in keyed:
        alpha, projected = grown_pairs(df, entity, uid, cols, budget.target_rows)
        rows.append(dict(key=name, columns=" + ".join(cols), alpha=round(alpha, 2), projected_pairs=projected))
    return pd.DataFrame(rows).assign(within_budget=lambda t: t["projected_pairs"] <= budget.max_candidate_pairs)


def check_budget(plan: pd.DataFrame, budget: Budget) -> None:
    over = plan[(plan["P"] > budget.max_candidate_pairs) | (plan["largest_block"] > budget.max_block_size)]
    if len(over):
        raise OverBudget(f"over budget: {over[['rule', 'P', 'largest_block']].to_dict('records')}")


def cascade(ids: pd.Series, stages: list[tuple[str, pd.DataFrame]], resolve_edges: Callable[[pd.DataFrame], pd.Series],
            entity: pd.Series, uid: str) -> tuple[pd.Series, pd.Series, pd.DataFrame, list[dict]]:
    """→ final clusters, the stage that first resolved each record, the kept edges, metrics after each stage."""
    l, r = f"{uid}_l", f"{uid}_r"
    resolved = pd.Series(False, index=ids.to_numpy())
    stage_of = pd.Series(pd.NA, index=ids.to_numpy(), dtype="string")
    kept, accepted, metrics = [], [], []
    clusters = pd.Series(ids.to_numpy(), index=ids.to_numpy(), dtype="string")
    for name, e in stages:
        accepted.append(e)
        e = e[~(e[l].map(resolved).to_numpy() & e[r].map(resolved).to_numpy())]  # skip pairs already resolved on both sides
        kept.append(e)
        clusters = resolve_edges(pd.concat(kept))
        now = clusters.map(clusters.value_counts()) > 1
        stage_of[now & ~resolved] = name
        resolved = now
        metrics.append(dict(stage=name, edges=len(pd.concat(kept)), **cluster_metrics(clusters, ids.map(entity)),
                            **edge_metrics(pd.concat(accepted), entity, uid)))
    return clusters, stage_of, pd.concat(kept), metrics


@dataclass
class Result:
    plan: pd.DataFrame        # preflight + actual time per rule
    rules: pd.DataFrame       # edges and edge FP per rule
    metrics: pd.DataFrame     # per stage, cumulative
    records: pd.DataFrame     # prepared records + CLUSTER_ID, MATCH_STAGE, MATCH_RULE
    edges: pd.DataFrame       # every accepted pair: rule, stage, score, fp, kept
    seconds: float


def run_rules(spec: RulesSpec, records: pd.DataFrame, truth: pd.DataFrame, db: DuckDBAPI, data: Data) -> Result:
    t0, uid = time.perf_counter(), data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    df = prepare(spec.standardize, records, spec.normalized(), spec.used())
    plan = preflight(spec, df)
    check_budget(plan, spec.budget)
    edges, actual = rule_edges(spec, df, db, uid)
    entity = truth.set_index(uid)[data.entity_id]
    edges["fp"] = edges[l].map(entity).to_numpy() != edges[r].map(entity).to_numpy()

    ids = df[uid]
    clusters, stage_of, kept_edges, metrics = cascade(
        ids, [(s.name, edges[edges["stage"] == s.name]) for s in spec.stages],
        lambda e: resolve(spec.resolver, ids, e, df, db, uid), entity, uid)
    edges["kept"] = edges.index.isin(kept_edges.index)

    order = {rule.name: i for i, rule in enumerate(rule for s in spec.stages for rule in s.rules)}
    touch = pd.concat([kept_edges[[l, "rule"]].set_axis([uid, "rule"], axis=1), kept_edges[[r, "rule"]].set_axis([uid, "rule"], axis=1)])
    first_rule = touch.assign(o=touch["rule"].map(order)).sort_values("o").drop_duplicates(uid).set_index(uid)["rule"]
    resolved = stage_of.notna().to_numpy()
    out = df.assign(CLUSTER_ID=clusters.to_numpy(), MATCH_STAGE=stage_of.to_numpy(),
                    MATCH_RULE=df[uid].map(first_rule).where(resolved))

    rules = (edges.groupby("rule", sort=False).agg(edges=("fp", "size"), edge_FP=("fp", "sum"), kept=("kept", "sum"),
                                                   kept_FP=("fp", lambda f: int((f & edges.loc[f.index, "kept"]).sum())))
             .reindex(plan["rule"]).fillna(0).astype(int).reset_index())
    plan = plan.assign(actual_ms=(1000 * plan["rule"].map(actual)).round(1))  # includes Splink's per-rule overhead
    return Result(plan, rules, pd.DataFrame(metrics), out, edges, time.perf_counter() - t0)


@dataclass
class ProbResult:
    report: pd.DataFrame      # per candidate generator: Big-O, estimated and actual pairs, completeness, seconds
    candidates: pd.DataFrame  # union of candidate pairs with the generators that found them
    scored: pd.DataFrame      # candidates + match_weight, match_probability, gamma levels, fp
    metrics: pd.DataFrame     # cascade: previous stage, then this one (cumulative)
    stage_metrics: dict       # this stage alone: candidates, accepted pairs, average precision
    records: pd.DataFrame     # prepared records + CLUSTER_ID, MATCH_STAGE, MATCH_RULE
    seconds: float


def run_fs(spec: ProbSpec, model_json: dict, records: pd.DataFrame, truth: pd.DataFrame, prev_pairs: pd.DataFrame,
           prev_clusters: pd.DataFrame, db: DuckDBAPI, data: Data, min_match_weight: float | None = None) -> ProbResult:
    """Candidates for the previous stage's singletons (against all records) → FS scores → threshold → cascade."""
    t0, uid = time.perf_counter(), data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    weight = spec.min_match_weight if min_match_weight is None else min_match_weight
    df = prepare(spec.standardize, records, spec.normalized(), spec.used())
    entity = truth.set_index(uid)[data.entity_id]
    prev = prev_clusters.set_index(uid)["cluster_id"].reindex(df[uid].to_numpy())
    query = set(prev.index[prev.map(prev.value_counts()).eq(1).to_numpy()])  # singletons after the previous stage

    cands, report = candidates(spec.blockers, df, uid, query, spec.budget)
    targets = missed_pairs(prev, entity.reindex(prev.index), uid)
    found_by = cands["sources"].str.split("+")
    report = report.assign(**pd.DataFrame([candidate_metrics(cands[found_by.map(lambda s, n=b.name: n in s)],
                                                             entity, uid, targets) for b in spec.blockers]))
    scored = score_fs(model_json, df, cands[[l, r]], db, uid).merge(cands, on=[l, r])
    scored["fp"] = scored[l].map(entity).to_numpy() != scored[r].map(entity).to_numpy()
    accepted = scored[scored["match_weight"] >= weight].assign(stage=spec.stage, rule=spec.model.name,
                                                                score=lambda s: s["match_probability"])

    prev_kept = prev_pairs[prev_pairs["kept"].astype(str).eq("True")].assign(score=1.0)
    ids = df[uid]
    clusters, stage_of, kept, metrics = cascade(
        ids, [(spec.previous_stage, prev_kept), (spec.stage, accepted)],
        lambda e: resolve(spec.resolver, ids, e, df, db, uid), entity, uid)
    resolved_by = pd.concat([kept[[l, "rule"]].set_axis([uid, "rule"], axis=1), kept[[r, "rule"]].set_axis([uid, "rule"], axis=1)])
    first = resolved_by.drop_duplicates(uid).set_index(uid)["rule"]
    out = df.assign(CLUSTER_ID=clusters.to_numpy(), MATCH_STAGE=stage_of.to_numpy(),
                    MATCH_RULE=df[uid].map(first).where(stage_of.notna().to_numpy()))
    stage_metrics = dict(**candidate_metrics(cands, entity, uid, targets), **edge_metrics(accepted, entity, uid),
                         average_precision=average_precision(scored["match_weight"].to_numpy(), ~scored["fp"].to_numpy()),
                         min_match_weight=weight)
    return ProbResult(report, cands, scored, pd.DataFrame(metrics), stage_metrics, out, time.perf_counter() - t0)


def threshold_curve(res: ProbResult, spec: ProbSpec, prev_pairs: pd.DataFrame, truth: pd.DataFrame, db: DuckDBAPI,
                    data: Data, weights: list[float]) -> pd.DataFrame:
    """FP / recall after resolution at each min_match_weight; scores stay fixed, only the decision and the
    resolution are redone. O(|weights| · (N + E)·d)."""
    uid = data.unique_id
    ids, entity = res.records[uid], truth.set_index(uid)[data.entity_id]
    prev_kept = prev_pairs[prev_pairs["kept"].astype(str).eq("True")].assign(score=1.0)
    rows = []
    for w in weights:
        accepted = res.scored[res.scored["match_weight"] >= w].assign(stage=spec.stage, rule=spec.model.name,
                                                                       score=lambda s: s["match_probability"])
        *_, metrics = cascade(ids, [(spec.previous_stage, prev_kept), (spec.stage, accepted)],
                              lambda e: resolve(spec.resolver, ids, e, res.records, db, uid), entity, uid)
        m = metrics[-1]
        rows.append(dict(min_match_weight=w, probability=1 / (1 + 2 ** -w), accepted=len(accepted),
                         pairs_FP=int(accepted["fp"].sum()), stage_fp_rate_hi=fp_upper(int(accepted["fp"].sum()), len(accepted)),
                         TP=m["TP"], FP=m["FP"], FN=m["FN"], recall=m["recall"], recall_lo=m["recall_lo"],
                         recall_hi=m["recall_hi"], precision=m["precision"], fp_rate_hi=m["fp_rate_hi"], f1=m["f1"],
                         overmerged=m["overmerged"], dup_unresolved=m["dup_unresolved"]))
    return pd.DataFrame(rows)


def entity_folds(truth: pd.DataFrame, data: Data, k: int, seed: int) -> pd.Series:
    """uid → fold, assigned per entity so a duplicate group never spans two folds."""
    entities = np.random.default_rng(seed).permutation(truth[data.entity_id].unique())
    fold_of = {e: i % k for i, e in enumerate(entities)}
    return truth.set_index(data.unique_id)[data.entity_id].map(fold_of)


def cross_validate_fs(spec: ProbSpec, train_model: Callable[[ProbSpec, pd.DataFrame, pd.DataFrame, int], dict],
                      records: pd.DataFrame, truth: pd.DataFrame, prev_pairs: pd.DataFrame, prev_clusters: pd.DataFrame,
                      folds: pd.Series, db: DuckDBAPI, data: Data, min_match_weight: float | None = None) -> list[ProbResult]:
    """Out-of-fold results: for each fold, fit FS on the other folds and score only the held-out fold, so tuning
    never scores a model on the records it was fitted on. O(k · (fit + candidates + score + resolve))."""
    uid = data.unique_id
    out = []
    for f in sorted(folds.unique()):
        hold = set(folds.index[folds == f])
        fit_rec, fit_truth = records[~records[uid].isin(hold)], truth[~truth[uid].isin(hold)]
        model = train_model(spec, fit_rec, fit_truth, int(f))
        both = prev_pairs[f"{uid}_l"].isin(hold) & prev_pairs[f"{uid}_r"].isin(hold)
        out.append(run_fs(spec, model, records[records[uid].isin(hold)], truth[truth[uid].isin(hold)], prev_pairs[both],
                          prev_clusters[prev_clusters[uid].isin(hold)], db, data, min_match_weight))
    return out


def accept_curve(results: list[ProbResult], weights: list[float]) -> pd.DataFrame:
    """Accepted and false accepted pairs per min_match_weight, summed over (fold) results, with the stage FP-rate bound:
    all a ThresholdRule reads, so the same weight as cv_threshold_curve without resolving clusters. O(|weights| · P)."""
    scored = pd.concat([r.scored[["match_weight", "fp"]] for r in results])
    out = pd.DataFrame([dict(min_match_weight=w, accepted=int(a.sum()), pairs_FP=int((a & scored["fp"]).sum()))
                        for w in weights for a in [scored["match_weight"] >= w]])
    return out.assign(stage_fp_rate_hi=[fp_upper(int(f), int(n)) for f, n in zip(out["pairs_FP"], out["accepted"])])


def cv_threshold_curve(results: list[ProbResult], spec: ProbSpec, prev_pairs: pd.DataFrame, truth: pd.DataFrame,
                       folds: pd.Series, db: DuckDBAPI, data: Data, weights: list[float]) -> pd.DataFrame:
    """threshold_curve per fold (out-of-fold scores), summed over folds; bounds recomputed on the totals."""
    uid = data.unique_id
    curves = []
    for f, res in zip(sorted(folds.unique()), results):
        hold = set(folds.index[folds == f])
        both = prev_pairs[f"{uid}_l"].isin(hold) & prev_pairs[f"{uid}_r"].isin(hold)
        curves.append(threshold_curve(res, spec, prev_pairs[both], truth[truth[uid].isin(hold)], db, data, weights))
    total = pd.concat(curves).groupby("min_match_weight")[["accepted", "pairs_FP", "TP", "FP", "FN", "overmerged",
                                                           "dup_unresolved"]].sum().reset_index()
    ci = [wilson(int(tp), int(tp + fn)) for tp, fn in zip(total["TP"], total["FN"])]
    return total.assign(probability=1 / (1 + 2.0 ** -total["min_match_weight"]),
                        recall=total["TP"] / (total["TP"] + total["FN"]), recall_lo=[c[0] for c in ci], recall_hi=[c[1] for c in ci],
                        fp_rate_hi=[fp_upper(int(fp), int(tp + fp)) for tp, fp in zip(total["TP"], total["FP"])],
                        stage_fp_rate_hi=[fp_upper(int(fp), int(n)) for n, fp in zip(total["accepted"], total["pairs_FP"])])


def summed(results: list[ProbResult]) -> dict[str, float]:
    """Final-stage counts summed over folds, with recall interval and FP-rate bounds recomputed on the totals."""
    tp, fp, fn = (sum(int(r.metrics.iloc[-1][k]) for r in results) for k in ("TP", "FP", "FN"))
    acc, acc_fp = sum(r.stage_metrics["pairs"] for r in results), sum(r.stage_metrics["pairs_FP"] for r in results)
    lo, hi = wilson(tp, tp + fn)
    return dict(TP=tp, FP=fp, FN=fn, recall=tp / (tp + fn) if tp + fn else 1.0, recall_lo=lo, recall_hi=hi,
                precision=tp / (tp + fp) if tp + fp else 1.0, fp_rate_hi=fp_upper(fp, tp + fp), accepted=acc,
                accepted_FP=acc_fp, stage_fp_rate_hi=fp_upper(acc_fp, acc),
                candidates=sum(r.stage_metrics["candidates"] for r in results))


def select_threshold(curve: pd.DataFrame, rule: ThresholdRule) -> tuple[float, pd.DataFrame]:
    """Apply a ThresholdRule to a (cross-validated) threshold curve; returns the weight and the curve with an
    `eligible` flag. Falls back to the strictest grid weight when nothing qualifies."""
    c = curve.sort_values("min_match_weight").reset_index(drop=True)
    c["eligible"] = (c["pairs_FP"] <= rule.max_fp) & (c["stage_fp_rate_hi"] <= rule.max_fp_rate_hi)
    if not c["eligible"].any():
        return float(c["min_match_weight"].iloc[-1]), c
    i = min(int(c.index[c["eligible"]][0]) + rule.margin_steps, len(c) - 1)
    return float(c["min_match_weight"].iloc[i]), c


def complexity_summary(res: Result) -> str:
    n, e, ops = len(res.records), int(res.edges["kept"].sum()), res.plan["ops"].sum()
    return (f"rules: Σ ops ≈ {ops:,.0f} (see big_o per rule) · normalize: O(N·L), N = {n:,} · "
            f"cluster: O((N + E)·d), N = {n:,}, E = {e:,} · evaluate: O(N) · total {res.seconds:.1f}s")
