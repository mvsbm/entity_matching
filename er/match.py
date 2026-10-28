"""Entity matching: candidate pairs → decided / scored pairs.

rules           a pair is accepted when every condition of one rule holds (score 1.0); each rule is a Splink
                deterministic link, so its work is the pairs inside its equi-join blocks
fellegi_sunter  Splink's Fellegi–Sunter model: λ from near-certain rules, u by random sampling, m by EM or from
                labels; scores any registered candidate table, so candidates and scoring stay independent
"""
import logging
import math
import time

import pandas as pd
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator

from er.config import Comparison, FSModel, RulesSpec, keys_sql


def rule_edges(spec: RulesSpec, df: pd.DataFrame, db: DuckDBAPI, uid: str) -> tuple[pd.DataFrame, dict[str, float]]:
    l, r = f"{uid}_l", f"{uid}_r"
    sdf = db.register(df)
    found, seconds = [], {}
    for s in spec.stages:
        for rule in s.rules:
            t = time.perf_counter()
            settings = SettingsCreator(link_type="dedupe_only", unique_id_column_name=uid,
                                       blocking_rules_to_generate_predictions=[s.sql(rule)])
            linker = Linker(sdf, settings, log_level=logging.WARNING)  # the default (INFO) logs every rule
            pairs = linker.inference.deterministic_link().as_pandas_dataframe()[[l, r]]
            seconds[rule.name] = time.perf_counter() - t
            found.append(pairs.astype("string").assign(rule=rule.name, stage=s.name, score=1.0))
    return pd.concat(found, ignore_index=True).drop_duplicates([l, r], keep="first"), seconds  # first rule wins


ELSE = "else"
U = dict[tuple[str, str], float]  # (comparison, level label) → u probability


def comparison(c: Comparison, u: U | None = None) -> cl.CustomComparison:
    def with_u(level: cll.ComparisonLevelCreator, label: str) -> cll.ComparisonLevelCreator:
        return level.configure(u_probability=u[c.name, label]) if u and (c.name, label) in u else level
    null = " AND ".join(f'("{col}_l" IS NULL OR "{col}_r" IS NULL)' for col in c.null_if_missing)
    levels = [cll.CustomLevel(null, "missing").configure(is_null_level=True)]
    for lv in c.levels:
        level = cll.CustomLevel(" OR ".join(f"({comp.sql(col, level=True)})" for col, comp in lv.any_of), lv.label)
        levels.append(with_u(level.configure(tf_adjustment_column=c.tf.name) if lv.tf and c.tf else level, lv.label))
    return cl.CustomComparison(comparison_levels=[*levels, with_u(cll.ElseLevel().configure(label_for_charts=ELSE), ELSE)],
                               output_column_name=c.name)


def fs_settings(model: FSModel, uid: str, u: U | None = None) -> SettingsCreator:
    return SettingsCreator(link_type="dedupe_only", unique_id_column_name=uid,
                           comparisons=[comparison(c, u) for c in model.comparisons],
                           blocking_rules_to_generate_predictions=[keys_sql(r) for r in model.em_rules])


def u_values(model_json: dict) -> U:
    """u per (comparison, level) of a trained model, to reuse in models with the same comparisons (FSModel.u_signature).
    A level no random pair reached (e.g. a lower JW level shadowed by a higher one at the same threshold) has no u;
    it is left out, so the reused model falls back to Splink's default exactly as a fresh one does."""
    return {(c["output_column_name"], lv["label_for_charts"]): lv["u_probability"]
            for c in model_json["comparisons"] for lv in c["comparison_levels"]
            if not lv.get("is_null_level") and "u_probability" in lv}


def train_fs(model: FSModel, df: pd.DataFrame, db: DuckDBAPI, uid: str, labels: pd.Series | None = None,
             u: U | None = None) -> dict:
    """Train on df; `labels` (entity per uid) is required for m_method="labels". Returns the Splink model JSON.
    u-sampling is ~97% of training time and depends only on the comparisons and the records (FSModel.u_signature),
    not on the m method or term-frequency adjustment. Pass `u` from such a model to skip it."""
    t = df.copy()
    if model.m_method == "labels":
        assert labels is not None, "m_method='labels' needs truth labels"
        t["__label__"] = t[uid].map(labels)
    linker = Linker(db.register(t), fs_settings(model, uid, u), log_level=logging.WARNING)
    linker.training.estimate_probability_two_random_records_match([keys_sql(r) for r in model.prior_rules],
                                                                  recall=model.prior_recall)
    if u is None:
        linker.training.estimate_u_using_random_sampling(max_pairs=model.u_max_pairs, seed=model.seed)
    if model.m_method == "em":
        for rule in model.em_rules:
            linker.training.estimate_parameters_using_expectation_maximisation(keys_sql(rule))
    else:
        linker.training.estimate_m_from_label_column("__label__")
    return linker.misc.save_model_to_json()


def score_fs(model_json: dict, df: pd.DataFrame, pairs: pd.DataFrame, db: DuckDBAPI, uid: str) -> pd.DataFrame:
    """Score exactly these candidate pairs (uid_l < uid_r) with a trained model."""
    l, r = f"{uid}_l", f"{uid}_r"
    linker = Linker(db.register(df), model_json, log_level=logging.WARNING)
    if pairs.empty:
        return pairs.assign(match_weight=pd.Series(dtype=float), match_probability=pd.Series(dtype=float))
    blocked = db.register(pd.DataFrame({"match_key": "0", "join_key_l": pairs[l].to_numpy(), "join_key_r": pairs[r].to_numpy()}))
    linker.table_management.register_blocked_pairs_for_predict(blocked)
    out = linker.inference.predict().as_pandas_dataframe()
    gammas = [c for c in out.columns if c.startswith("gamma_")]
    return out[[l, r, "match_weight", "match_probability", *gammas]].astype({l: "string", r: "string"})


def parameters(model_json: dict) -> pd.DataFrame:
    """One row per comparison level: m, u and the match weight log2(m/u) it contributes."""
    rows = []
    for c in model_json["comparisons"]:
        for lv in c["comparison_levels"]:
            if lv.get("is_null_level"):
                continue
            m, u = lv.get("m_probability"), lv.get("u_probability")
            rows.append(dict(comparison=c["output_column_name"], level=lv.get("label_for_charts"), m=m, u=u,
                             weight=math.log2(m / u) if m and u else None, tf=lv.get("tf_adjustment_column")))
    return pd.DataFrame(rows)
