"""Entity matching: candidate pairs → decided / scored pairs.

rules           a pair is accepted when every condition of one rule holds (score 1.0); each rule is a Splink
                deterministic link, so its work is the pairs inside its equi-join blocks
fellegi_sunter  Splink's Fellegi–Sunter model: λ from near-certain rules, u by random sampling, m by EM or from
                labels; scores any registered candidate table, so candidates and scoring stay independent
"""
import logging
import math
import time
from dataclasses import replace

import pandas as pd
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator

from er.config import Comparison, FSModel, RulesSpec, keys_sql
from er.evaluate import fp_upper


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
U = dict[str, dict[str, float]]  # comparison → level label → u probability


def comparison(c: Comparison, u: dict[str, float] | None = None) -> cl.CustomComparison:
    def with_u(level: cll.ComparisonLevelCreator, label: str) -> cll.ComparisonLevelCreator:
        return level.configure(u_probability=u[label]) if u and label in u else level
    null = " AND ".join(f'("{col}_l" IS NULL OR "{col}_r" IS NULL)' for col in c.null_if_missing)
    levels = [cll.CustomLevel(null, "missing").configure(is_null_level=True)]
    for lv in c.levels:
        level = cll.CustomLevel(" OR ".join(f"({comp.sql(col, level=True)})" for col, comp in lv.any_of), lv.label)
        levels.append(with_u(level.configure(tf_adjustment_column=c.tf.name) if lv.tf and c.tf else level, lv.label))
    return cl.CustomComparison(comparison_levels=[*levels, with_u(cll.ElseLevel().configure(label_for_charts=ELSE), ELSE)],
                               output_column_name=c.name)


def fs_settings(model: FSModel, uid: str, u: U | None = None) -> SettingsCreator:
    return SettingsCreator(link_type="dedupe_only", unique_id_column_name=uid,
                           comparisons=[comparison(c, (u or {}).get(c.name)) for c in model.comparisons],
                           blocking_rules_to_generate_predictions=[keys_sql(r) for r in model.em_rules])


def u_values(model_json: dict) -> U:
    """Estimated u per comparison and level, to reuse for comparisons with the same FSModel.u_keys(). Levels filled with
    a bound (no sampled pair reached them) are left out: the reusing model recomputes the same bound."""
    filled = {tuple(x) for x in model_json.get("er", {}).get("filled", {}).get("u", [])}
    return {c["output_column_name"]: {lv["label_for_charts"]: lv["u_probability"] for lv in c["comparison_levels"]
                                      if not lv.get("is_null_level") and "u_probability" in lv
                                      and (c["output_column_name"], lv["label_for_charts"]) not in filled}
            for c in model_json["comparisons"]}


def sample_u(model: FSModel, comparisons: list[Comparison], df: pd.DataFrame, db: DuckDBAPI, uid: str) -> U:
    """Splink's random sampling for just these comparisons. The sample depends only on the records, the size and the
    seed, so this equals sampling them inside the full model (tests/). O(max_pairs · comparisons)."""
    if not comparisons:
        return {}
    linker = Linker(db.register(df), fs_settings(replace(model, comparisons=tuple(comparisons)), uid), log_level=logging.ERROR)
    linker.training.estimate_u_using_random_sampling(max_pairs=model.u_max_pairs, seed=model.seed)
    return u_values(linker.misc.save_model_to_json())


def u_bound(model: FSModel, c: Comparison, df: pd.DataFrame) -> float:
    """95% upper bound on u for a level no sampled pair reached: zero hits among the sampled pairs where the comparison
    is filled, of which there are at least (largest fill share of its columns)² of the sample."""
    sampled = min(model.u_max_pairs, len(df) * (len(df) - 1) / 2)
    return fp_upper(0, max(1, int(sampled * max(df[col].notna().mean() for col in c.null_if_missing) ** 2)))


def train_fs(model: FSModel, df: pd.DataFrame, db: DuckDBAPI, uid: str, labels: pd.Series | None = None,
             u: U | None = None) -> dict:
    """Train on df; `labels` (entity per uid) is required for m_method="labels". Returns the Splink model JSON plus
    "er": what scoring needs (fitting-set size, term frequencies) and which levels had no estimate.
    u-sampling is ~97% of training time and depends only on each comparison and the records (FSModel.u_keys), not on
    the m method or term-frequency adjustment: pass `u` (u_values of such a model) to skip those comparisons.
    A level without an estimate never falls back to Splink's defaults: no sampled pair → u at its upper bound (the
    weight is a lower bound on the evidence); never seen in training → m = u (0 bits)."""
    t = df.copy()
    if model.m_method == "labels":
        assert labels is not None, "m_method='labels' needs truth labels"
        t["__label__"] = t[uid].map(labels)
    u = {**(u or {}), **sample_u(model, [c for c in model.comparisons if c.name not in (u or {})], t, db, uid)}
    labels_of = {c.name: [*(lv.label for lv in c.levels), ELSE] for c in model.comparisons}
    filled_u = [[c.name, lv] for c in model.comparisons for lv in labels_of[c.name] if lv not in u[c.name]]
    u = {c.name: {lv: u[c.name].get(lv) or u_bound(model, c, t) for lv in labels_of[c.name]} for c in model.comparisons}
    linker = Linker(db.register(t), fs_settings(model, uid, u), log_level=logging.ERROR)  # unestimated levels: handled here
    linker.training.estimate_probability_two_random_records_match([keys_sql(r) for r in model.prior_rules],
                                                                  recall=model.prior_recall)
    if model.m_method == "em":
        for rule in model.em_rules:
            linker.training.estimate_parameters_using_expectation_maximisation(keys_sql(rule))
    else:
        linker.training.estimate_m_from_label_column("__label__")
    model_json = linker.misc.save_model_to_json()
    filled_m = []
    for c in model_json["comparisons"]:
        for lv in c["comparison_levels"]:
            if not lv.get("is_null_level") and "m_probability" not in lv:
                lv["m_probability"] = lv["u_probability"]
                filled_m.append([c["output_column_name"], lv["label_for_charts"]])
    tf = {c.tf.name: (t[c.tf.name].value_counts() / t[c.tf.name].notna().sum()).to_dict()  # Splink's own formula
          for c in model.comparisons if c.tf and any(lv.tf for lv in c.levels)}
    return {**model_json, "er": dict(fit_rows=len(t), tf=tf, filled=dict(u=filled_u, m=filled_m))}


def scaled_prior(model_json: dict, n_records: int) -> float:
    """λ for a set of n_records: a per-pair rate (true pairs grow with N, pairs with N²), rescaled from the fitting set."""
    prior = model_json["probability_two_random_records_match"] * (model_json["er"]["fit_rows"] - 1) / max(n_records - 1, 1)
    return min(prior, 1 - 1e-9)


def score_fs(model_json: dict, df: pd.DataFrame, pairs: pd.DataFrame, db: DuckDBAPI, uid: str) -> pd.DataFrame:
    """Score exactly these candidate pairs (uid_l < uid_r) with a model from train_fs, so that a score doesn't depend
    on the size of the scored set: term frequencies come from the fitting records (a value unseen there gets no
    adjustment), and λ is rescaled to this set's size (scaled_prior)."""
    l, r = f"{uid}_l", f"{uid}_r"
    fit = model_json["er"]
    settings = {k: v for k, v in model_json.items() if k != "er"} | {"probability_two_random_records_match": scaled_prior(model_json, len(df))}
    linker = Linker(db.register(df), settings, log_level=logging.WARNING)
    linker.table_management.invalidate_cache()  # the cache lives on the shared db, keyed by table name only
    for col, tf in fit["tf"].items():
        lookup = pd.DataFrame({col: list(tf), f"tf_{col}": list(tf.values())})
        linker.table_management.register_term_frequency_lookup(db.register(lookup), col)
    if pairs.empty:
        return pairs.assign(match_weight=pd.Series(dtype=float), match_probability=pd.Series(dtype=float))
    blocked = db.register(pd.DataFrame({"match_key": "0", "join_key_l": pairs[l].to_numpy(), "join_key_r": pairs[r].to_numpy()}))
    linker.table_management.register_blocked_pairs_for_predict(blocked)
    predictions = linker.inference.predict()
    rel = predictions.as_duckdbpyrelation()
    keep = [l, r, "match_weight", "match_probability", *(c for c in rel.columns if c.startswith("gamma_"))]
    out = rel.project(", ".join(f'"{c}"' for c in keep)).df()  # memory: the matching columns never reach pandas
    predictions.drop_table_from_database_and_remove_from_cache()  # else every call keeps its predictions in the shared db
    return out.astype({l: "string", r: "string"})


def waterfall(model_json: dict, gammas: dict[str, int], n_records: int) -> pd.DataFrame:
    """One scored pair's match weight as evidence: the prior, then per comparison the bits log2(m/u) of the level the
    pair landed in (gamma, as score_fs returns it; a missing side adds 0). The bits sum to Splink's match_weight."""
    assert not model_json["er"]["tf"], "term-frequency adjustments are per value and not shown here"
    lam = scaled_prior(model_json, n_records)
    rows = [dict(evidence="prior", level="two random records match", bits=math.log2(lam / (1 - lam)))]
    for c in model_json["comparisons"]:
        levels = [lv for lv in c["comparison_levels"] if not lv.get("is_null_level")]  # gamma counts down to else = 0
        g = int(gammas[c["output_column_name"]])
        lv = levels[len(levels) - 1 - g] if g >= 0 else None
        rows.append(dict(evidence=c["output_column_name"], level=lv["label_for_charts"] if lv else "missing",
                         bits=math.log2(lv["m_probability"] / lv["u_probability"]) if lv else 0.0))
    return pd.DataFrame(rows)


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
