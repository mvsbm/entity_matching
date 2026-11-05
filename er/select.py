"""Choosing the configuration on labelled data: design analyses, paired A/B on val, the threshold rule on out-of-fold
train scores, decisions by rule (er.evaluate.adopt), the scale and coverage checks, and test scored once.
scripts/choose.py runs both stages in order; each step returns its tables for reports/choose.md.

The rules stage fits nothing, so train is a clean selection set. The Fellegi–Sunter stage is fitted on train, so its
choices are judged on out-of-fold scores (entity k-fold CV). Every configuration gets its threshold from one rule.
"""
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

import optuna
import pandas as pd
from splink import DuckDBAPI

from er.candidates import candidates, estimate, found_by
from er.config import (Data, FSSpec, FSTune, KeyBlocker, OverBudget, Pipeline, RulesSpec, ThresholdRule, Tune, with_comparators,
                       with_level)
from er.evaluate import adopt, c2, candidate_metrics, missed_pairs, paired_test, predicted_pairs, true_pairs
from er.io import append_leaderboard, assert_test_scored_once, load, test_evaluations, write_final
from er.match import parameters, train_fs, u_values, waterfall
from er.pipeline import (FSResult, Result, accept_curve, complexity_summary, cross_validate_fs, cv_threshold_curve, entity_folds,
                         pattern_coverage, preflight, run_fs, run_rules, scale_check, select_threshold, summed, threshold_curve,
                         window_only)
from er.standardize import prepare
from er.tune import new_study, pick_within_noise, plain, start_dashboard, suggest_comparators

SHOW = ["stage", "TP", "FP", "recall", "recall_lo", "recall_hi", "fp_rate_hi", "pairs_FP", "overmerged", "dup_unresolved"]
Section = tuple[str, str, pd.DataFrame | None]  # heading, text, table


def truth_set(truth: pd.DataFrame, data: Data) -> set[tuple[str, str]]:
    return set(map(tuple, true_pairs(truth.set_index(data.unique_id)[data.entity_id], data.unique_id).to_numpy()))


def verdict(name: str, kind: str, on_sel: dict, on_val: dict, p_max: float, prefix: str) -> dict:
    return dict(change=name, kind=kind, adopted=adopt(kind, on_sel, on_val, p_max), **{f"{prefix}_{x}": v for x, v in on_sel.items()},
                val_TP_gains=on_val["TP_gains"], val_TP_losses=on_val["TP_losses"], val_FP_added=on_val["FP_added"])


# ---------- stage 1: rules ----------

@dataclass
class RulesChooser:
    spec: RulesSpec
    data: Data
    db: DuckDBAPI
    changes: Mapping[str, Callable[[RulesSpec], RulesSpec]]
    decisions: tuple[tuple[str, str], ...]
    decision_p: float
    tune: Tune
    final: RulesSpec | None = None
    adopted: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.train, self.train_truth = load(self.data, "train")
        self.val_records, self.val_truth = load(self.data, "val")
        self.train_true, self.val_true = truth_set(self.train_truth, self.data), truth_set(self.val_truth, self.data)

    def run(self, spec: RulesSpec, records: pd.DataFrame, truth: pd.DataFrame) -> Result:
        return run_rules(spec, records, truth, self.db, self.data)

    def joined(self, res: Result) -> set[tuple[str, str]]:  # every pair the clusters put together
        return predicted_pairs(res.records.set_index(self.data.unique_id)["CLUSTER_ID"])

    def design(self) -> list[Section]:
        """Why no rule uses a single key: per field and per rule's keys, the share of same-entity pairs that agree
        against the number of different-entity pairs that agree. Train only."""
        uid, ent, s = self.data.unique_id, self.data.entity_id, self.spec
        df = prepare(s.standardize, self.train, s.normalized(), s.used()).merge(self.train_truth[[uid, ent]], on=uid)
        n_true, rows = c2(df.groupby(ent).size()), []
        for keys in [[c] for c in sorted(s.used())] + [list(st.keys(r)) for st in s.stages for r in st.rules]:
            d = df.dropna(subset=keys)
            agree, same = c2(d.groupby(keys).size()), c2(d.groupby(keys + [ent]).size())
            rows.append(dict(keys=" + ".join(keys), same_entity_agree=same / n_true, different_entity_pairs=agree - same))
        return [("Design analysis on train", "", pd.DataFrame(rows).drop_duplicates("keys").round(4))]

    def ab(self) -> list[Section]:
        """Each change applied to the configuration as written, compared pair by pair on val (informational)."""
        base, rows = self.joined(self.run(self.spec, self.val_records, self.val_truth)), []
        for name, change in self.changes.items():
            spec = change(self.spec)
            res = self.run(spec, self.val_records, self.val_truth)
            m = res.metrics.iloc[-1]
            row = dict(recall=m["recall"], FP=m["FP"], fp_rate_hi=m["fp_rate_hi"], **paired_test(base, self.joined(res), self.val_true),
                       P=int(res.plan["P"].sum()), seconds=round(res.seconds, 1))
            append_leaderboard(self.data, f"deterministic:{name}", spec, "val", row)
            rows.append(dict(variant=name, **row))
        return [("A/B on val, paired against the rules as written", "", pd.DataFrame(rows).round(4))]

    def decide(self) -> list[Section]:
        """Each decision on top of the choice so far: paired on train (rules fit nothing), and no paired loss on val."""
        final, rows = self.spec, []
        for name, kind in self.decisions:
            variant = self.changes[name](final)
            on_train = paired_test(self.joined(self.run(final, self.train, self.train_truth)),
                                   self.joined(self.run(variant, self.train, self.train_truth)), self.train_true)
            on_val = paired_test(self.joined(self.run(final, self.val_records, self.val_truth)),
                                 self.joined(self.run(variant, self.val_records, self.val_truth)), self.val_true)
            rows.append(verdict(name, kind, on_train, on_val, self.decision_p, "train"))
            if rows[-1]["adopted"]:
                final = variant
        self.final, self.adopted = final, [v["change"] for v in rows if v["adopted"]]
        comps = {c: f"{x.function} {x.threshold or ''} {'+'.join(x.normalize)}".strip() for c, x in final.stages[-1].comparators.items()}
        return [("Decisions", f"FINAL fuzzy comparators: {comps} · {final.resolver.method}", pd.DataFrame(rows).round(4))]

    def cost(self) -> list[Section]:
        """Per rule: P = Σ C(k, 2) over its key blocks now, and projected to budget.target_rows from its pairs of one
        entity (× N) and by chance (× N²), er.pipeline.grown_pairs. Stops if a rule would exceed the budget there."""
        f = self.final
        grows = scale_check(f, self.train, self.train_truth, self.data).rename(columns={"key": "rule"})[["rule", "alpha", "projected_pairs", "per_record", "within_budget"]]
        plan = preflight(f, prepare(f.standardize, self.train, f.normalized(), f.used())).merge(grows, on="rule")
        assert plan["within_budget"].all(), f"over budget at {f.budget.target_rows:,} rows: {plan.loc[~plan['within_budget'], 'rule'].tolist()}"
        text = f"train: N = {len(self.train):,} · total P = {plan['P'].sum():,} → {plan['projected_pairs'].sum():,} at {f.budget.target_rows:,} rows"
        return [("Cost of FINAL: every rule now and at target_rows", text,
                 plan[["stage", "rule", "keys", "big_o", "filled", "P", "largest_block", "est_fuzzy_ms", "alpha", "projected_pairs", "per_record", "within_budget"]])]

    def evaluate(self) -> list[Section]:
        val = self.run(self.final, self.val_records, self.val_truth)
        fp = int((val.edges["kept"] & val.edges["fp"]).sum())
        return [("Evaluation on val", f"{complexity_summary(val)} · false-positive pairs: {fp}", val.metrics[SHOW].round(4)),
                ("Rules on val", "", val.plan[["rule", "P", "actual_ms"]].merge(val.rules, on="rule"))]

    def output(self) -> list[Section]:
        """Train, val and test through FINAL: leaderboard rows; test is the report."""
        rows = []
        for dataset in self.data.datasets:
            records, truth = load(self.data, dataset)
            res = self.run(self.final, records, truth)
            append_leaderboard(self.data, "deterministic:FINAL", self.final, dataset, res.metrics.iloc[-1].drop("stage").to_dict())
            rows.append(dict(dataset=dataset, records=len(records), **res.metrics.iloc[-1][SHOW[1:]].to_dict(), seconds=round(res.seconds, 1)))
        write_final(self.data, "deterministic_final", self.final, adopted=self.adopted)
        assert_test_scored_once(self.data)
        return [("FINAL on train, val and test", "", pd.DataFrame(rows).round(4))]

    def search(self) -> list[Section]:
        """Optuna over the fuzzy comparators on train (off unless tune.enabled), then the Pareto front judged by the rule."""
        if not self.tune.enabled:
            return []
        storage = start_dashboard(self.tune)

        def objective(trial: optuna.Trial) -> tuple[float, float]:
            comps = suggest_comparators(trial, self.tune.space)
            trial.set_user_attr("comparators", repr(comps))
            spec = with_comparators(self.final, self.tune.stage, comps)
            if not scale_check(spec, self.train, self.train_truth, self.data)["within_budget"].all():
                raise optuna.TrialPruned("over budget at target_rows")
            try:
                res = self.run(spec, self.train, self.train_truth)
            except OverBudget as e:
                raise optuna.TrialPruned(str(e))
            m = res.metrics.iloc[-1]
            for k, v in dict(P=res.plan["P"].sum(), recall_lo=m["recall_lo"], recall_hi=m["recall_hi"], fp_rate_hi=m["fp_rate_hi"],
                             seconds=round(res.seconds, 2)).items():
                trial.set_user_attr(k, plain(v))
            return float(m["FP"]), float(m["recall"])

        study = new_study(self.tune, storage, ["FP", "recall"], ["minimize", "maximize"])
        study.optimize(objective, n_trials=self.tune.n_trials, show_progress_bar=True)
        front, seen = [], set()
        for t in sorted(study.best_trials, key=lambda t: (t.values[0], -t.values[1])):
            comps = suggest_comparators(optuna.trial.FixedTrial(t.params), self.tune.space)
            if repr(comps) in seen:
                continue
            seen.add(repr(comps))
            v = self.run(with_comparators(self.final, self.tune.stage, comps), self.val_records, self.val_truth)
            m = v.metrics.iloc[-1]
            front.append(dict(trial=t.number, train_FP=t.values[0], train_recall=t.values[1], train_recall_lo=t.user_attrs["recall_lo"],
                              train_recall_hi=t.user_attrs["recall_hi"], train_zero_fp=t.values[0] == 0, val_FP=m["FP"],
                              val_recall=m["recall"], P=int(v.plan["P"].sum()), comparators=comps))
        front = pd.DataFrame(front)
        # picked on the selection set (train), so val stays an independent check in adopt
        best = pick_within_noise(front, "train_recall", "train_recall_lo", "train_recall_hi", "train_zero_fp", "P") if len(front) else None
        text = "no Pareto point has 0 FP on train: FINAL stays"
        if best is not None:
            spec = with_comparators(self.final, self.tune.stage, front.at[best, "comparators"])
            on_train = paired_test(self.joined(self.run(self.final, self.train, self.train_truth)), self.joined(self.run(spec, self.train, self.train_truth)), self.train_true)
            on_val = paired_test(self.joined(self.run(self.final, self.val_records, self.val_truth)), self.joined(self.run(spec, self.val_records, self.val_truth)), self.val_true)
            text = (f"suggested: trial {front.at[best, 'trial']} → adopt by rule ('better' vs FINAL): "
                    f"{adopt('better', on_train, on_val, self.decision_p)} · train {on_train} · val {on_val}")
        return [("Optuna: the Pareto front, re-scored on val", text, front.drop(columns="comparators").round(4))]


# ---------- stage 2: Fellegi–Sunter ----------

@dataclass
class FSChooser:
    """The caches skip repeated work without changing any result: models by (config, fitting set); u per comparison
    by FSModel.u_keys(), so models that share a comparison reuse its u; runs by (config, dataset, threshold)."""
    spec: FSSpec
    pipeline: Pipeline
    rules: RulesSpec                          # the rules stage as chosen: its results are this stage's starting point
    data: Data
    db: DuckDBAPI
    changes: Mapping[str, Callable[[FSSpec], FSSpec]]
    decisions: tuple[tuple[str, str], ...]
    tune: FSTune
    final: FSSpec | None = None
    tuned: FSSpec | None = None
    adopted: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        p = self.pipeline
        self.rule: ThresholdRule = p.threshold
        self.train_records, self.train_truth = load(self.data, "train")
        self.val_records, self.val_truth = load(self.data, "val")
        self.prev: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        self.train_prev_pairs, self.train_prev_resolved = self.previous("train")
        self.folds = entity_folds(self.train_truth, self.data, p.cv_folds, p.cv_seed)
        self.train_true, self.val_true = truth_set(self.train_truth, self.data), truth_set(self.val_truth, self.data)
        self.models, self.u, self.runs, self.cvs = {}, {}, {}, {}
        self.growth: pd.DataFrame | None = None

    def previous(self, dataset: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """The chosen rules on a dataset, as this stage starts from them: their pairs (and which were kept), and each
        record's cluster, stage and rule. O(N + Σ P_r·L²), once per dataset."""
        if dataset not in self.prev:
            uid = self.data.unique_id
            res = run_rules(self.rules, *load(self.data, dataset), self.db, self.data)
            pairs = res.edges[[f"{uid}_l", f"{uid}_r", "stage", "rule", "score", "kept"]].sort_values([f"{uid}_l", f"{uid}_r"], kind="stable")
            resolved = res.records[[uid, "CLUSTER_ID", "MATCH_STAGE", "MATCH_RULE"]].set_axis([uid, "cluster_id", "resolved_stage", "resolved_by"], axis=1)
            self.prev[dataset] = pairs.reset_index(drop=True).astype("string"), resolved.astype("string")
        return self.prev[dataset]

    def fit(self, spec: FSSpec, records: pd.DataFrame, truth: pd.DataFrame, key: object) -> dict:
        uid = self.data.unique_id
        if (repr(spec.model), key) not in self.models:
            df = prepare(spec.standardize, records, spec.normalized(), spec.used())
            u_keys = spec.model.u_keys()
            model_json = train_fs(spec.model, df, self.db, uid, labels=truth.set_index(uid)[self.data.entity_id],
                                  u={c: self.u[k, key] for c, k in u_keys.items() if (k, key) in self.u})
            for c, u in u_values(model_json).items():
                self.u.setdefault((u_keys[c], key), u)
            self.models[repr(spec.model), key] = model_json
        return self.models[repr(spec.model), key]

    def run(self, spec: FSSpec, dataset: str) -> FSResult:  # model fitted on all of train
        key = (repr(spec), dataset)
        if key not in self.runs:
            records, truth = load(self.data, dataset)
            self.runs[key] = run_fs(spec, self.fit(spec, self.train_records, self.train_truth, "train"), records, truth,
                                    *self.previous(dataset), self.db, self.data)
        return self.runs[key]

    def cv(self, spec: FSSpec) -> list[FSResult]:  # out-of-fold results on train
        if repr(spec) not in self.cvs:
            self.cvs[repr(spec)] = cross_validate_fs(spec, self.fit, self.train_records, self.train_truth, self.train_prev_pairs,
                                                     self.train_prev_resolved, self.folds, self.db, self.data)
        return self.cvs[repr(spec)]

    def threshold_of(self, spec: FSSpec) -> float:  # the threshold rule on this configuration's out-of-fold scores
        return select_threshold(accept_curve(self.cv(spec), list(self.rule.grid)), self.rule)[0]

    def joined(self, results: FSResult | list[FSResult]) -> set[tuple[str, str]]:
        return set().union(*(predicted_pairs(x.records.set_index(self.data.unique_id)["CLUSTER_ID"])
                             for x in (results if isinstance(results, list) else [results])))

    def candidates_on_train(self) -> list[Section]:
        """Every generator defined, on train only: its work, the share of the true pairs the rules missed that it
        finds (alone, then cumulatively), the different-entity pairs it also makes, its pairs at target_rows."""
        uid = self.data.unique_id
        pool = replace(self.spec, blockers=tuple(self.pipeline.generators.values()))
        df = prepare(pool.standardize, self.train_records, pool.normalized(), pool.used())
        entity = self.train_truth.set_index(uid)[self.data.entity_id]
        prev = self.train_prev_resolved.set_index(uid)["cluster_id"].reindex(df[uid].to_numpy())
        targets = missed_pairs(prev, entity.reindex(prev.index), uid)
        cands, report = candidates(pool.blockers, df, uid, set(prev.index[prev.map(prev.value_counts()).eq(1).to_numpy()]), pool.budget)
        reach = lambda names: candidate_metrics(cands[found_by(cands, names)], entity, uid, targets)
        alone = pd.DataFrame([reach({b.name}) for b in pool.blockers])
        self.growth = scale_check(pool, self.train_records, self.train_truth, self.data).set_index("key")
        report = report.assign(finds=alone["completeness_on_targets"],
                               cumulative=[reach({b.name for b in pool.blockers[: i + 1]})["completeness_on_targets"] for i in range(len(pool.blockers))],
                               different_entity_pairs=alone["candidates"] - alone["true_in_candidates"]).join(self.growth[["alpha", "projected_pairs", "per_record"]], on="generator")
        self.t_df = df
        return [("Candidates on train: reach and cost of every generator", f"train: {len(targets):,} true pairs missed by the rules",
                 report[["generator", "big_o", "filled", "pairs", "seconds", "finds", "cumulative", "different_entity_pairs", "alpha", "projected_pairs", "per_record"]].round(4))]

    def training(self) -> list[Section]:
        """EM (unsupervised) against labels (the supervised reference): the weight log2(m/u) of every level."""
        s, k = self.spec, len(self.spec.model.comparisons)
        em_p = sum(estimate(KeyBlocker(name="em", keys=rule), self.t_df, len(self.t_df))["est_pairs"] for rule in s.model.em_rules)
        weights, notes = {}, [f"cost: u O(max_pairs·C) = O({s.model.u_max_pairs:,.0f}·{k}) · EM O(iterations·P·C), P = {em_p:,}"]
        for method in ("em", "labels"):
            spec, t = replace(s, model=replace(s.model, m_method=method)), time.perf_counter()
            model_json = self.fit(spec, self.train_records, self.train_truth, "train")
            weights[method] = parameters(model_json).set_index(["comparison", "level"])[["m", "u", "weight"]]
            filled = model_json["er"]["filled"]
            notes.append(f"{method}: fitted in {time.perf_counter() - t:.1f}s · no estimate: u {filled['u'] or '-'} · m {filled['m'] or '-'}")
        table = pd.concat(weights, axis=1).round(3)
        table.columns = [f"{a} {b}" for a, b in table.columns]
        return [("Training on train: EM against labels", " · ".join(notes), table.reset_index())]

    def threshold(self) -> list[Section]:
        t = time.perf_counter()
        weight, curve = select_threshold(cv_threshold_curve(self.cv(self.spec), self.spec, self.train_prev_pairs, self.train_truth,
                                                            self.folds, self.db, self.data, list(self.rule.grid)), self.rule)
        assert weight == self.threshold_of(self.spec)  # the full curve and the pair counts the rule reads pick the same weight
        self.tuned = replace(self.spec, min_match_weight=weight)
        return [("Threshold: chosen on cross-validated train", f"{self.pipeline.cv_folds}-fold CV in {time.perf_counter() - t:.1f}s → min_match_weight = {weight}",
                 curve[["min_match_weight", "accepted", "pairs_FP", "stage_fp_rate_hi", "TP", "FP", "recall", "recall_lo", "recall_hi", "eligible"]].round(4))]

    def ab(self) -> list[Section]:
        base, rows = self.joined(self.run(self.tuned, "val")), []
        for name, change in self.changes.items():
            spec = change(self.tuned)
            res = self.run(spec, "val")
            m = res.metrics.iloc[-1]
            row = dict(recall=m["recall"], FP=m["FP"], fp_rate_hi=m["fp_rate_hi"], **paired_test(base, self.joined(res), self.val_true),
                       candidates=res.stage_metrics["candidates"])
            append_leaderboard(self.data, f"probabilistic:{name}", spec, "val", row)
            rows.append(dict(variant=name, **row))
        return [("A/B on val, paired against the tuned configuration as written", "", pd.DataFrame(rows).round(4))]

    def decide(self) -> list[Section]:
        """Each decision on top of the choice so far, at its own threshold-rule threshold: paired on cross-validated
        train, plus no paired loss on val."""
        final, rows = self.tuned, []
        for name, kind in self.decisions:
            variant = self.changes[name](final)
            variant = replace(variant, min_match_weight=self.threshold_of(variant))
            on_cv = paired_test(self.joined(self.cv(final)), self.joined(self.cv(variant)), self.train_true)
            on_val = paired_test(self.joined(self.run(final, "val")), self.joined(self.run(variant, "val")), self.val_true)
            rows.append(verdict(name, kind, on_cv, on_val, self.pipeline.decision_p, "cv"))
            if rows[-1]["adopted"]:
                final = variant
        self.final, self.adopted = final, [v["change"] for v in rows if v["adopted"]]
        text = (f"FINAL: {len(final.blockers)} generators · term frequency {'on' if any(c.tf for c in final.model.comparisons) else 'off'} · "
                f"m by {final.model.m_method} · min_match_weight {final.min_match_weight} · {final.resolver.method}")
        return [("Decisions", text, pd.DataFrame(rows).round(4))]

    def will_it_scale(self) -> list[Section]:
        """FINAL's generators projected to target_rows, and the potential matches on train that share no key at that
        size (λ and u moved to it). Stops if either check fails."""
        f = self.final
        plan = self.growth.loc[[b.name for b in f.blockers]].reset_index()
        assert plan["within_budget"].all(), f"over budget at {f.budget.target_rows:,} rows: {plan.loc[~plan['within_budget'], 'key'].tolist()}"
        cover = window_only(f, self.fit(f, self.train_records, self.train_truth, "train"), self.train_records, self.train_truth,
                            self.db, self.data, [len(self.train_records), f.budget.target_rows])
        assert cover["window_only"].eq(0).all(), "a potential match is left to a sorted window, whose reach shrinks as the file grows"
        patterns = pattern_coverage(f, self.fit(f, self.train_records, self.train_truth, "train"), f.budget.target_rows)
        text = (f"{len(patterns)} patterns that can reach the threshold at {f.budget.target_rows:,} records have no guaranteed key; "
                f"the model puts their share of matches at {patterns['share_of_matches'].sum():.3%} at most (Jaro–Winkler implies no key)")
        return [("Will it scale? FINAL's generators at target_rows", "", plan),
                ("Potential matches that share no key (train)", "", cover),
                ("Patterns without a guaranteed key, at target_rows (label-free)", text, patterns.head(10))]

    def evaluate(self) -> list[Section]:
        uid, f = self.data.unique_id, self.final
        res = self.run(f, "val")
        val_curve = threshold_curve(res, f, self.previous("val")[0], self.val_truth, self.db, self.data, list(self.rule.grid))
        cv_at = cv_threshold_curve(self.cv(f), f, self.train_prev_pairs, self.train_truth, self.folds, self.db, self.data, [f.min_match_weight]).iloc[0]
        val_at = val_curve.set_index("min_match_weight").loc[f.min_match_weight]
        val_rate = val_at["pairs_FP"] / max(val_at["accepted"], 1)
        transfer = (f"transfer at weight {f.min_match_weight}: CV {cv_at['pairs_FP']:.0f} false of {cv_at['accepted']:.0f} accepted pairs "
                    f"(rate ≤ {cv_at['stage_fp_rate_hi']:.2%}) · val {val_at['pairs_FP']:.0f} of {val_at['accepted']:.0f} ({val_rate:.2%})")
        assert val_rate <= cv_at["stage_fp_rate_hi"], "the threshold does not transfer from cross-validated train to val"
        cands = f"candidates {res.stage_metrics['candidates']:,} · they contain {res.stage_metrics['completeness_on_targets']:.1%} of the true pairs the rules missed"
        return [("FINAL's candidates on val", cands, res.report[["generator", "big_o", "filled", "pairs", "completeness_on_targets", "seconds"]].round(4)),
                ("Evaluation on val", transfer, res.metrics[SHOW].round(4)),
                ("Threshold curve on val", "", val_curve[["min_match_weight", "accepted", "pairs_FP", "TP", "FP", "recall", "fp_rate_hi"]].round(4))]

    def why(self) -> list[Section]:
        """The accepted true match with a typo closest to the threshold, and the rejected non-match closest to it, in bits."""
        uid, f, p = self.data.unique_id, self.final, self.pipeline
        res = self.run(f, "val")
        accepted = res.scored["match_weight"] >= f.min_match_weight
        shown = res.records.set_index(uid)[list(p.explain_show)]
        left, right = shown.loc[res.scored[f"{uid}_l"]].set_index(res.scored.index), shown.loc[res.scored[f"{uid}_r"]].set_index(res.scored.index)
        filled = (left[list(p.explain_filled)].notna() & right[list(p.explain_filled)].notna()).all(axis=1)
        differs = left[p.explain_filled[0]].ne(right[p.explain_filled[0]]).fillna(False)
        out = []
        for title, pair in {"An accepted true match with a typo": res.scored[accepted & ~res.scored["fp"] & filled & differs].nsmallest(1, "match_weight"),
                            "The rejected non-match closest to the threshold": res.scored[~accepted & res.scored["fp"]].nlargest(1, "match_weight")}.items():
            row = pair.iloc[0]
            bits = waterfall(res.model, {c.name: row[f"gamma_{c.name}"] for c in f.model.comparisons}, len(res.records)).round(2)
            text = f"{row['match_weight']:.2f} bits → match probability {row['match_probability']:.4f} · found by {row['sources']}"
            out += [(title, text, shown.loc[[row[f"{uid}_l"], row[f"{uid}_r"]]].reset_index()), (f"{title}: bits", "", bits)]
        return out

    def output(self) -> list[Section]:
        """Train, val and test through FINAL: leaderboard rows; test is the report."""
        f, rows = self.final, []
        for dataset in self.data.datasets:
            res, records = self.run(f, dataset), load(self.data, dataset)[0]
            acc = res.scored[res.scored["match_weight"] >= f.min_match_weight]
            m = res.metrics.iloc[-1]
            append_leaderboard(self.data, "probabilistic:FINAL", f, dataset, {**m.drop("stage").to_dict(), **{f"stage_{x}": v for x, v in res.stage_metrics.items()}})
            rows.append(dict(dataset=dataset, records=len(records), recall_before=res.metrics.iloc[0]["recall"], **m[SHOW[1:]].to_dict(),
                             accepted=len(acc), seconds=round(res.seconds, 1)))
        write_final(self.data, "probabilistic_final", f, self.fit(f, self.train_records, self.train_truth, "train"),
                    adopted=self.adopted, min_match_weight=f.min_match_weight)
        assert_test_scored_once(self.data)
        return [("FINAL on train, val and test", "", pd.DataFrame(rows).round(4)),
                ("Configurations scored on test, per stage", "", test_evaluations(self.data))]

    def search(self) -> list[Section]:
        """Optuna over whole components (off unless tune.enabled), with a cross-validated objective, then the Pareto
        front judged by the rule."""
        tune, final = self.tune, self.final
        if not tune.enabled:
            return []

        def spec_for(trial: optuna.Trial | optuna.trial.FixedTrial) -> FSSpec:
            on = {b for b in tune.toggle_blockers if trial.suggest_categorical(f"use:{b}", [True, False])}
            fixed = {b.name for b in final.blockers} - set(tune.toggle_blockers)
            m_method = trial.suggest_categorical("m_method", list(tune.m_methods))
            tf = {c.name: c.tf for c in self.spec.model.comparisons} if trial.suggest_categorical("term_frequency", list(tune.tf_options)) else {}
            model = replace(final.model, m_method=m_method, comparisons=tuple(replace(c, tf=tf.get(c.name)) for c in final.model.comparisons))
            for (comparison, label), (lo, hi, step) in tune.level_thresholds.items():
                model = with_level(model, comparison, label, threshold=trial.suggest_float(f"{comparison}|{label}", lo, hi, step=step))
            return replace(final, blockers=tuple(b for name, b in self.pipeline.generators.items() if name in fixed | on), model=model,
                           resolver=tune.resolvers[trial.suggest_categorical("resolver", list(tune.resolvers))])

        def objective(trial: optuna.Trial) -> tuple[float, float]:
            spec = spec_for(trial)
            if not self.growth.loc[[b.name for b in spec.blockers], "within_budget"].all():
                raise optuna.TrialPruned("over budget at target_rows")
            try:
                weight = self.threshold_of(spec)
            except OverBudget as e:
                raise optuna.TrialPruned(str(e))
            at = cv_threshold_curve(self.cv(spec), spec, self.train_prev_pairs, self.train_truth, self.folds, self.db, self.data, [weight]).iloc[0]
            for x, v in dict(min_match_weight=weight, recall_lo=at["recall_lo"], recall_hi=at["recall_hi"], candidates=summed(self.cv(spec))["candidates"]).items():
                trial.set_user_attr(x, plain(v))
            return float(at["FP"]), float(at["recall"])

        storage = start_dashboard(tune)
        study = new_study(tune, storage, ["FP", "recall"], ["minimize", "maximize"])
        study.optimize(objective, n_trials=tune.n_trials, show_progress_bar=True)
        front, seen = [], set()
        for t in sorted(study.best_trials, key=lambda t: (t.values[0], -t.values[1])):
            spec = replace(spec_for(optuna.trial.FixedTrial(t.params)), min_match_weight=t.user_attrs["min_match_weight"])
            if repr(spec) in seen:
                continue
            seen.add(repr(spec))
            v = self.run(spec, "val").metrics.iloc[-1]
            front.append(dict(trial=t.number, cv_FP=t.values[0], cv_recall=t.values[1], cv_recall_lo=t.user_attrs["recall_lo"],
                              cv_recall_hi=t.user_attrs["recall_hi"], cv_zero_fp=t.values[0] == 0, val_FP=v["FP"], val_recall=v["recall"],
                              candidates=t.user_attrs["candidates"], min_match_weight=t.user_attrs["min_match_weight"], spec=spec))
        front = pd.DataFrame(front)
        # picked on the selection set (out-of-fold train), so val stays an independent check in adopt
        best = pick_within_noise(front, "cv_recall", "cv_recall_lo", "cv_recall_hi", "cv_zero_fp", "candidates") if len(front) else None
        text = "no Pareto point has 0 FP out-of-fold: FINAL stays"
        if best is not None:
            spec = front.at[best, "spec"]
            on_cv = paired_test(self.joined(self.cv(final)), self.joined(self.cv(spec)), self.train_true)
            on_val = paired_test(self.joined(self.run(final, "val")), self.joined(self.run(spec, "val")), self.val_true)
            text = (f"suggested: trial {front.at[best, 'trial']} → adopt by rule ('better' vs FINAL): "
                    f"{adopt('better', on_cv, on_val, self.pipeline.decision_p)} · cross-validated train {on_cv} · val {on_val}")
        return [("Optuna: the Pareto front, re-scored on val", text, front.drop(columns="spec").round(4))]
