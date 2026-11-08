"""Design time's measurements: preflight (the work per rule before any join), projections to a target size, and the
pipeline measured against the truth. Every measured run is er.run.Run, the run nayose resolve records makes: run_rules and
run_fs read its tables and join them to the truth, so design time judges exactly what runs. Metrics after each stage
are cumulative: matching metrics on the accepted pairs, resolution metrics on the clusters.
"""
import math
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
from splink import DuckDBAPI

from er.candidates import estimate, found_by, generate
from er.cluster import merge
from er.config import q
from er.config import (Blocker, Budget, Data, DeletionKeys, FSSpec, Key, KeyBlocker, OverBudget, Pipeline, RulesSpec,
                       SortedNeighbourhood, TfidfNeighbours, ThresholdRule, keys_of)
from er.evaluate import (average_precision, candidate_metrics, cluster_metrics, edge_metrics, fp_upper, missed_pairs,
                         true_pairs, wilson)
from er.match import scaled_prior, score_fs, scored_sample
from er.run import Run
from er.settings import Settings
from er.standardize import prepare
from er.strings import FUNCTIONS, connect, udf

BENCH: dict[tuple[str, str], float] = {}  # seconds per pair, by (column, function); bounded: one per column and function compared


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
                est_fuzzy_ms=round(1000 * est, 2)))
    return pd.DataFrame(rows)


def entity_rank(entity: pd.Series, seed: int = 0) -> np.ndarray:  # each record's entity's place in a random entity order
    order = np.random.default_rng(seed).permutation(entity.unique())
    return entity.map(pd.Series(np.arange(len(order)), index=order)).to_numpy()


def grown_pairs(df: pd.DataFrame, entity: pd.Series, uid: str, b: KeyBlocker | DeletionKeys, target_rows: int) -> tuple[float, int]:
    """A key's pairs P (as `estimate` counts them) at target_rows, and their growth α = d log P / d log N here. P splits
    into T pairs of one entity, which grow like N (a bigger population of the same kind has more duplicated entities,
    each duplicated as often), and C chance pairs between entities, which grow like N² (two entities share a value
    with the same probability at any size): P(n) = T·n/N + C·n(n − 1)/(N(N − 1)), and α = (T + 2C)/(T + C). It is the
    expectation of keeping a share of the entities, without the sampling. Pairs between two members of a household
    count as chance: the safe side, for a population that grows by whole households. O(N)."""
    n, p = len(df), int(estimate(b, df, 0)["est_pairs"])
    own = Key("__entity")
    same = replace(b, keys=b.keys + (own,)) if isinstance(b, KeyBlocker) else replace(b, within=b.within + (own,))
    t = min(p, int(estimate(same, df.assign(__entity=df[uid].map(entity).astype("string").to_numpy()), 0)["est_pairs"]))
    alpha = (t + 2 * (p - t)) / p if p else 1.0
    return alpha, int(t * target_rows / n + (p - t) * target_rows * (target_rows - 1) / max(n * (n - 1), 1))


def scale_check(spec: RulesSpec | FSSpec, records: pd.DataFrame, truth: pd.DataFrame, data: Data) -> pd.DataFrame:
    """Every join key of a configuration, with its pairs projected to budget.target_rows. Keys are counted
    (grown_pairs); a sorted neighbourhood makes at most N·(w − 1) pairs; TF-IDF neighbours compare each query
    with every record, so up to N² similarities. `within_budget` is False where the projection exceeds
    budget.max_pairs(target_rows): such a configuration would stop with OverBudget at that size."""
    uid, budget = data.unique_id, spec.budget
    df = prepare(spec.standardize, records, spec.normalized(), spec.used())
    entity = truth.set_index(uid)[data.entity_id]
    blockers: list[Blocker] = spec.blockers() if isinstance(spec, RulesSpec) else list(spec.blockers)
    rows = []
    for b in blockers:
        cols = " + ".join(k.name for k in keys_of(b))
        if isinstance(b, SortedNeighbourhood):
            rows.append(dict(key=b.name, columns=cols, alpha=1.0, projected_pairs=budget.target_rows * (b.window - 1)))
        elif isinstance(b, TfidfNeighbours):
            rows.append(dict(key=b.name, columns=cols, alpha=2.0, projected_pairs=budget.target_rows ** 2))
        else:
            alpha, projected = grown_pairs(df, entity, uid, b, budget.target_rows)
            rows.append(dict(key=b.name, columns=cols, alpha=round(alpha, 2), projected_pairs=projected))
    return pd.DataFrame(rows).assign(per_record=lambda t: (t["projected_pairs"] / budget.target_rows).round(3),
                                     within_budget=lambda t: t["projected_pairs"] <= budget.max_pairs(budget.target_rows))


def window_only(spec: FSSpec, model_json: dict, records: pd.DataFrame, truth: pd.DataFrame, db: DuckDBAPI, data: Data,
                sizes: list[int]) -> pd.DataFrame:
    """Per file size: the potential matches (true pairs whose fields would reach min_match_weight at that size) and how
    many of them share no equality key (KeyBlocker, DeletionKeys). Only a window (sorted neighbourhood, TF-IDF) can find
    those, and a window's reach shrinks as the file grows. λ moves to each size; with model.u_from_scored, so does u:
    per level u ∝ N^γ, γ measured between half and all of the entities, so a pair agreeing on a field whose value set
    grows with the file keeps its weight at scale. O(N + P + T·C) for T true pairs, plus two u samples."""
    assert not model_json["er"]["tf"], "the weights at other sizes are summed from the levels, without term frequencies"
    uid = data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    df = prepare(spec.standardize, records, spec.normalized(), spec.used())
    scored = score_fs(model_json, df, true_pairs(truth.set_index(uid)[data.entity_id], uid).astype("string"), db, uid)
    u_here, growth = {}, {}
    if spec.model.u_from_scored:
        entity = df[uid].map(truth.set_index(uid)[data.entity_id])
        half = df[entity_rank(entity) < entity.nunique() // 2]  # whole entities, as the population would grow
        u_here, u_half = (scored_sample(spec.model, d, db, uid) for d in (df, half))  # df: the fit's own sample of train
        growth = {(c, lv): math.log(u / u_half[c][lv]) / math.log(len(df) / len(half))
                  for c in u_here for lv, u in u_here[c].items() if u_half[c].get(lv)}
    keyed = pd.concat([generate(b, df, uid, None) for b in spec.blockers if isinstance(b, KeyBlocker | DeletionKeys)]
                      + [pd.DataFrame(columns=[l, r], dtype="string")])
    on_key = scored.merge(keyed.drop_duplicates().assign(keyed=True), on=[l, r], how="left")["keyed"].fillna(False).to_numpy(bool)
    filled_m = {tuple(x) for x in model_json["er"]["filled"]["m"]}  # never seen in training: m = u, 0 bits at any size
    rows = []
    for n in sizes:
        lam = scaled_prior(model_json, n)
        weight = np.full(len(scored), math.log2(lam / (1 - lam)))
        for c in model_json["comparisons"]:  # the bits of each level at size n, picked by each pair's gamma (else = 0)
            name, levels = c["output_column_name"], [lv for lv in c["comparison_levels"] if not lv.get("is_null_level")][::-1]
            u = [min(1.0, u_here.get(name, {}).get(lv["label_for_charts"], lv["u_probability"])
                     * (n / len(df)) ** growth.get((name, lv["label_for_charts"]), 0.0)) for lv in levels]
            m = [u_i if (name, lv["label_for_charts"]) in filled_m else lv["m_probability"] for lv, u_i in zip(levels, u)]
            per_level = np.log2(np.array(m) / np.array(u))
            gamma = scored[f"gamma_{name}"].to_numpy(int)
            weight += np.where(gamma >= 0, per_level[np.clip(gamma, 0, None)], 0.0)
        potential = weight >= spec.min_match_weight
        rows.append(dict(records=n, potential=int(potential.sum()), window_only=int((potential & ~on_key).sum())))
    return pd.DataFrame(rows)


def check_budget(plan: pd.DataFrame, budget: Budget, n: int) -> None:
    over = plan[(plan["P"] > budget.max_pairs(n)) | (plan["largest_block"] > budget.max_block_size)]
    if len(over):
        raise OverBudget(f"over budget: {over[['rule', 'P', 'largest_block']].to_dict('records')}")


def table(run: Run, sql: str) -> pd.DataFrame:  # a query on a run's tables, its text columns as pandas strings
    df = run.con.sql(sql).df()
    return df.astype({c: "string" for c in df.columns if df[c].dtype == object})


def clustered(con, db: DuckDBAPI, base: pd.DataFrame, edges: pd.DataFrame, ids: pd.Series, uid: str) -> pd.Series:
    """`base` (uid, cluster_id) with `edges` added (er.cluster.merge, the run's own clustering), in the order of ids."""
    con.register("er_base_df", base)
    con.register("er_edges_df", edges[[f"{uid}_l", f"{uid}_r"]])
    con.execute("CREATE OR REPLACE TABLE er_base AS SELECT * FROM er_base_df")
    con.execute("CREATE OR REPLACE TABLE er_edges AS SELECT * FROM er_edges_df")
    merge(con, db, "er_base", "er_edges", "er_clusters", uid)
    out = con.sql("SELECT * FROM er_clusters").df().set_index(uid)["cluster_id"]
    return out.astype("string").reindex(ids.to_numpy())


@dataclass
class Result:
    plan: pd.DataFrame        # preflight + actual time per rule
    rules: pd.DataFrame       # edges and edge FP per rule
    metrics: pd.DataFrame     # per stage, cumulative
    records: pd.DataFrame     # prepared records + CLUSTER_ID, MATCH_STAGE, MATCH_RULE
    edges: pd.DataFrame       # every accepted pair: rule, stage, score, fp, kept
    seconds: float


def run_rules(pipeline: Pipeline, settings: Settings, path: Path, truth: pd.DataFrame) -> Result:
    """The pipeline's rules on the file at `path`, run by er.run.Run, measured against the truth. The preflight comes
    first and stops an over-budget configuration (OverBudget) before any join. O(N + Σ P_r·L²) + O(N) per stage."""
    t0, spec, uid = time.perf_counter(), pipeline.rules, settings.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    run = Run(pipeline, settings)
    run.load(path)
    df = table(run, "SELECT * FROM records")
    plan = preflight(spec, df)
    check_budget(plan, spec.budget, len(df))
    run.rules()
    entity = truth.set_index(uid)[settings.data.entity_id]
    edges = table(run, f"""SELECT e.*, k.{q(l)} IS NOT NULL AS kept FROM rule_edges e
        LEFT JOIN rule_kept k ON k.{q(l)} = e.{q(l)} AND k.{q(r)} = e.{q(r)} ORDER BY e.{q(l)}, e.{q(r)}""")
    edges["fp"] = edges[l].map(entity).to_numpy() != edges[r].map(entity).to_numpy()
    kept_edges = edges[edges["kept"]]

    ids = df[uid]
    base = pd.DataFrame({uid: ids.to_numpy(), "cluster_id": ids.to_numpy()})
    resolved = pd.Series(False, index=ids.to_numpy())
    stage_of = pd.Series(pd.NA, index=ids.to_numpy(), dtype="string")
    metrics, names = [], []
    for st in spec.stages:  # the clusters after each stage: the kept pairs of the stages so far, merged as the run merges them
        names.append(st.name)
        upto = edges["stage"].isin(names).to_numpy()
        clusters = clustered(run.con, run.db, base, edges[upto & edges["kept"].to_numpy()], ids, uid)
        now = clusters.map(clusters.value_counts()) > 1
        stage_of[now & ~resolved] = st.name
        resolved = now
        metrics.append(dict(stage=st.name, edges=int((upto & edges["kept"].to_numpy()).sum()), **cluster_metrics(clusters, ids.map(entity)),
                            **edge_metrics(edges[upto], entity, uid)))

    order = {rule.name: i for i, _, rule in spec.each()}
    touch = pd.concat([kept_edges[[l, "rule"]].set_axis([uid, "rule"], axis=1), kept_edges[[r, "rule"]].set_axis([uid, "rule"], axis=1)])
    first_rule = touch.assign(o=touch["rule"].map(order)).sort_values("o").drop_duplicates(uid).set_index(uid)["rule"]
    out = df.assign(CLUSTER_ID=clusters.to_numpy(), MATCH_STAGE=stage_of.to_numpy(),
                    MATCH_RULE=df[uid].map(first_rule).where(stage_of.notna().to_numpy()))

    rules = (edges.groupby("rule", sort=False).agg(edges=("fp", "size"), edge_FP=("fp", "sum"), kept=("kept", "sum"),
                                                   kept_FP=("fp", lambda f: int((f & edges.loc[f.index, "kept"]).sum())))
             .reindex(plan["rule"]).fillna(0).astype(int).reset_index())
    plan = plan.assign(actual_ms=(1000 * plan["rule"].map(run.rule_seconds)).round(1))  # includes Splink's per-rule overhead
    run.con.close()  # its tables are read: free its memory now, not when the collector finds the run
    return Result(plan, rules, pd.DataFrame(metrics), out, edges, time.perf_counter() - t0)


@dataclass
class FSResult:
    report: pd.DataFrame      # per candidate generator: Big-O, estimated and actual pairs, completeness, seconds
    candidates: pd.DataFrame  # union of candidate pairs with the generators that found them
    scored: pd.DataFrame      # candidates + match_weight, match_probability, gamma levels, named, keep, fp
    metrics: pd.DataFrame     # cascade: previous stage, then this one (cumulative)
    stage_metrics: dict       # this stage alone: candidates, accepted pairs, average precision
    records: pd.DataFrame     # prepared records + CLUSTER_ID, MATCH_STAGE, MATCH_RULE
    seconds: float
    model: dict               # the model that scored: the fitted one, with u from these records if model.u_from_scored
    rule_clusters: pd.DataFrame  # uid → cluster_id after the rules: where threshold_curve starts
    rule_pairs: pd.DataFrame     # the rules' kept pairs


def stage_rows(res: FSResult, spec: FSSpec, accepted: pd.DataFrame, clusters: pd.Series, entity: pd.Series, uid: str) -> list[dict]:
    """The cascade's metrics: after the rules, then after this stage's accepted pairs (kept where the run keeps them)."""
    ids = res.records[uid]
    before = res.rule_clusters.set_index(uid)["cluster_id"].reindex(ids.to_numpy())
    return [dict(stage=spec.previous_stage, edges=len(res.rule_pairs), **cluster_metrics(before, ids.map(entity)),
                 **edge_metrics(res.rule_pairs, entity, uid)),
            dict(stage=spec.stage, edges=len(res.rule_pairs) + int(accepted["keep"].sum()), **cluster_metrics(clusters, ids.map(entity)),
                 **edge_metrics(pd.concat([res.rule_pairs, accepted]), entity, uid))]


def run_fs(pipeline: Pipeline, settings: Settings, path: Path, truth: pd.DataFrame, model_json: dict,
           min_match_weight: float | None = None) -> FSResult:
    """The pipeline on the file at `path` with this fitted model, run by er.run.Run (u measured on the file when the
    model asks), accepting at min_match_weight (default the pipeline's), measured against the truth."""
    t0, uid = time.perf_counter(), settings.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    spec = pipeline.fs if min_match_weight is None else replace(pipeline.fs, min_match_weight=min_match_weight)
    run = Run(replace(pipeline, fs=spec), settings, model=model_json)
    run.load(path)
    run.fit()
    run.rules()
    report = run.candidates()
    run.score()
    run.cluster()
    entity = truth.set_index(uid)[settings.data.entity_id]
    df = table(run, "SELECT * FROM records")
    rule_clusters = table(run, "SELECT * FROM rule_clusters")
    prev = rule_clusters.set_index(uid)["cluster_id"].reindex(df[uid].to_numpy())
    targets = missed_pairs(prev, entity.reindex(prev.index), uid)
    cands = table(run, f"SELECT * FROM cands ORDER BY {q(l)}, {q(r)}")
    report = report.assign(**pd.DataFrame([candidate_metrics(cands[found_by(cands, [b.name])], entity, uid, targets)
                                           for b in spec.blockers]))
    scored = table(run, f"SELECT * FROM ({run.scored()}) ORDER BY {q(l)}, {q(r)}")
    scored["fp"] = scored[l].map(entity).to_numpy() != scored[r].map(entity).to_numpy()
    accepted = scored[automatic(scored, spec.min_match_weight)].assign(stage=spec.stage, rule=spec.model.name,
                                                                       score=lambda s: s["match_probability"])
    gold = table(run, "SELECT * FROM gold").set_index(uid).reindex(df[uid].to_numpy())
    out = df.assign(CLUSTER_ID=gold["cluster_id"].to_numpy(), MATCH_STAGE=gold["resolved_stage"].to_numpy(),
                    MATCH_RULE=gold["resolved_by"].to_numpy())
    rule_pairs = table(run, "SELECT * FROM rule_kept")
    run.con.close()  # its tables are read: free its memory now, not when the collector finds the run
    res = FSResult(report, cands, scored, pd.DataFrame(), {}, out, 0.0, run.scoring, rule_clusters, rule_pairs)
    res.metrics = pd.DataFrame(stage_rows(res, spec, accepted, gold["cluster_id"], entity, uid))
    res.stage_metrics = dict(**candidate_metrics(cands, entity, uid, targets), **edge_metrics(accepted, entity, uid),
                             average_precision=average_precision(scored["match_weight"].to_numpy(), ~scored["fp"].to_numpy()),
                             min_match_weight=spec.min_match_weight)
    res.seconds = time.perf_counter() - t0
    return res


def automatic(scored: pd.DataFrame, weight: float) -> pd.Series:  # the pairs merged without people at this weight
    return (scored["match_weight"] >= weight) & scored["named"]


def threshold_curve(res: FSResult, spec: FSSpec, truth: pd.DataFrame, data: Data, weights: list[float]) -> pd.DataFrame:
    """FP / recall after resolution at each min_match_weight; scores stay fixed, only the decision and the clusters are
    redone, by the run's own clustering from the rules' clusters. O(|weights| · (E·d + N))."""
    uid = data.unique_id
    ids, entity = res.records[uid], truth.set_index(uid)[data.entity_id]
    con, db = connect()
    rows = []
    for w in weights:
        accepted = res.scored[automatic(res.scored, w)]
        m = stage_rows(res, spec, accepted, clustered(con, db, res.rule_clusters, accepted[accepted["keep"]], ids, uid), entity, uid)[-1]
        rows.append(dict(min_match_weight=w, probability=1 / (1 + 2 ** -w), accepted=len(accepted),
                         pairs_FP=int(accepted["fp"].sum()), stage_fp_rate_hi=fp_upper(int(accepted["fp"].sum()), len(accepted)),
                         TP=m["TP"], FP=m["FP"], FN=m["FN"], recall=m["recall"], recall_lo=m["recall_lo"],
                         recall_hi=m["recall_hi"], precision=m["precision"], fp_rate_hi=m["fp_rate_hi"], f1=m["f1"],
                         overmerged=m["overmerged"], dup_unresolved=m["dup_unresolved"]))
    con.close()
    return pd.DataFrame(rows)


def entity_folds(truth: pd.DataFrame, data: Data, k: int, seed: int) -> pd.Series:
    """uid → fold, assigned per entity so a duplicate group never spans two folds."""
    entities = np.random.default_rng(seed).permutation(truth[data.entity_id].unique())
    fold_of = {e: i % k for i, e in enumerate(entities)}
    return truth.set_index(data.unique_id)[data.entity_id].map(fold_of)


def cross_validate_fs(pipeline: Pipeline, settings: Settings, train_model: Callable[[FSSpec, pd.DataFrame, pd.DataFrame, int], dict],
                      records: pd.DataFrame, truth: pd.DataFrame, folds: pd.Series, min_match_weight: float | None = None) -> list[FSResult]:
    """Out-of-fold results: for each fold, fit FS on the other folds and run only the held-out fold, so tuning never
    scores a model on the records it was fitted on. O(k · (fit + run on N/k records))."""
    uid, spec = settings.data.unique_id, pipeline.fs
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in sorted(folds.unique()):
            hold = set(folds.index[folds == f])
            fit_rec, fit_truth = records[~records[uid].isin(hold)], truth[~truth[uid].isin(hold)]
            model = train_model(spec, fit_rec, fit_truth, int(f))
            path = Path(tmp) / f"fold_{f}.parquet"
            records[records[uid].isin(hold)].to_parquet(path, index=False)
            out.append(run_fs(pipeline, settings, path, truth[truth[uid].isin(hold)], model, min_match_weight))
    return out


def accept_curve(results: list[FSResult], weights: list[float]) -> pd.DataFrame:
    """Accepted and false accepted pairs per min_match_weight, summed over (fold) results, with the stage FP-rate bound:
    all a ThresholdRule reads, so the same weight as cv_threshold_curve without resolving clusters. O(|weights| · P)."""
    scored = pd.concat([r.scored[["match_weight", "fp", "named"]] for r in results])
    out = pd.DataFrame([dict(min_match_weight=w, accepted=int(a.sum()), pairs_FP=int((a & scored["fp"]).sum()))
                        for w in weights for a in [automatic(scored, w)]])
    return out.assign(stage_fp_rate_hi=[fp_upper(int(f), int(n)) for f, n in zip(out["pairs_FP"], out["accepted"])])


def cv_threshold_curve(results: list[FSResult], spec: FSSpec, truth: pd.DataFrame, folds: pd.Series, data: Data,
                       weights: list[float]) -> pd.DataFrame:
    """threshold_curve per fold (out-of-fold scores), summed over folds; bounds recomputed on the totals."""
    uid = data.unique_id
    curves = [threshold_curve(res, spec, truth[truth[uid].isin(set(folds.index[folds == f]))], data, weights)
              for f, res in zip(sorted(folds.unique()), results)]
    total = pd.concat(curves).groupby("min_match_weight")[["accepted", "pairs_FP", "TP", "FP", "FN", "overmerged",
                                                           "dup_unresolved"]].sum().reset_index()
    ci = [wilson(int(tp), int(tp + fn)) for tp, fn in zip(total["TP"], total["FN"])]
    return total.assign(probability=1 / (1 + 2.0 ** -total["min_match_weight"]),
                        recall=total["TP"] / (total["TP"] + total["FN"]), recall_lo=[c[0] for c in ci], recall_hi=[c[1] for c in ci],
                        fp_rate_hi=[fp_upper(int(fp), int(tp + fp)) for tp, fp in zip(total["TP"], total["FP"])],
                        stage_fp_rate_hi=[fp_upper(int(fp), int(n)) for n, fp in zip(total["accepted"], total["pairs_FP"])])


def summed(results: list[FSResult]) -> dict[str, float]:
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
