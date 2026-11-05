"""Entity matching: candidate pairs → decided / scored pairs.

rules           a pair is accepted when every condition of one rule holds (score 1.0); each rule is a Splink
                deterministic link, so its work is the pairs inside its equi-join blocks
fellegi_sunter  Splink's Fellegi–Sunter model: λ from near-certain rules, u by random sampling, m by EM or from
                labels; scores any registered candidate table, so candidates and scoring stay independent
"""
import copy
import logging
import math
import time
from dataclasses import replace
from itertools import combinations

import pandas as pd
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator

from er.config import Comparison, FSModel, RulesSpec, keys_sql
from er.evaluate import fp_upper


def rule_edges_table(spec: RulesSpec, records: str, db: DuckDBAPI, uid: str, into: str) -> dict[str, float]:
    """rule_edges on a table, into a table: columns uid_l, uid_r, rule, stage, score; the first rule wins."""
    l, r, con = f"{uid}_l", f"{uid}_r", db.duckdb_con
    sdf, seconds, parts = db.register(records), {}, []
    for i, (s, rule) in enumerate((s, rule) for s in spec.stages for rule in s.rules):
        t = time.perf_counter()
        settings = SettingsCreator(link_type="dedupe_only", unique_id_column_name=uid, blocking_rules_to_generate_predictions=[s.sql(rule)])
        pairs = Linker(sdf, settings, log_level=logging.WARNING).inference.deterministic_link()
        table = f"er_rule_{i}"
        con.execute(f"DROP TABLE IF EXISTS {table}")
        pairs.as_duckdbpyrelation().project(f'"{l}", "{r}"').to_table(table)
        pairs.drop_table_from_database_and_remove_from_cache()
        seconds[rule.name] = time.perf_counter() - t
        parts.append(f"SELECT \"{l}\", \"{r}\", '{rule.name}' AS rule, '{s.name}' AS stage, {i} AS i FROM {table}")
    con.execute(f'CREATE OR REPLACE TABLE "{into}" AS SELECT DISTINCT ON ("{l}", "{r}") "{l}", "{r}", rule, stage, 1.0 AS score '
                f'FROM ({" UNION ALL ".join(parts)}) ORDER BY "{l}", "{r}", i')
    for i in range(len(parts)):
        con.execute(f"DROP TABLE IF EXISTS er_rule_{i}")
    return seconds


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


Records = pd.DataFrame | str  # a frame, or the name of a table in the DuckDB connection behind `db`


def rows(records: Records, db: DuckDBAPI) -> int:
    return len(records) if isinstance(records, pd.DataFrame) else db.duckdb_con.execute(f'SELECT count(*) FROM "{records}"').fetchall()[0][0]


def fill_share(records: Records, col: str, db: DuckDBAPI) -> float:  # the share of records with col filled
    if isinstance(records, pd.DataFrame):
        return float(records[col].notna().mean())
    return float(db.duckdb_con.execute(f'SELECT avg(("{col}" IS NOT NULL)::INT) FROM "{records}"').fetchall()[0][0] or 0)


def exact_u(model: FSModel, records: Records, db: DuckDBAPI) -> U:
    """u of each comparison's leading exact levels, computed exactly from value counts: the share of all distinct record
    pairs that land in the level, among the pairs outside the comparison's null level. A level that ORs several exact
    conditions is counted by inclusion–exclusion. O(N) per set of conditions; unlike a sample, it can't miss an agreement
    rarer than one in a billion pairs."""
    con, name = db.duckdb_con, None
    if isinstance(records, pd.DataFrame):
        name = f"er_u_{abs(hash(id(records)))}"
        con.register(name, records)
    t = f'"{name or records}"'
    try:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]
        pairs = n * (n - 1) / 2
        agree_cache: dict[frozenset, float] = {}

        def agree(cols: frozenset) -> float:  # distinct pairs equal on every one of these columns (all filled)
            if cols not in agree_cache:
                c = ", ".join(f'"{x}"' for x in sorted(cols))
                filled = " AND ".join(f'"{x}" IS NOT NULL' for x in sorted(cols))
                agree_cache[cols] = float(con.execute(f"SELECT coalesce(sum(c * (c - 1) / 2), 0) FROM (SELECT count(*) AS c FROM {t} "
                                                      f"WHERE {filled} GROUP BY {c})").fetchall()[0][0])
            return agree_cache[cols]

        def union(conds: list[str]) -> float:  # pairs equal on at least one of these columns
            return sum((-1) ** (k + 1) * agree(frozenset(sub)) for k in range(1, len(conds) + 1) for sub in combinations(conds, k))

        out: U = {}
        for c in model.comparisons:
            cols = list(c.null_if_missing)
            pattern = ", ".join(f'("{x}" IS NOT NULL)::INT' for x in cols)
            counts = con.execute(f"SELECT {pattern}, count(*) FROM {t} GROUP BY ALL").fetchall()
            null = 0.0  # pairs in the null level: for every column, at least one side empty
            for i, (*p, cp) in enumerate(counts):
                for j, (*q_, cq) in enumerate(counts[i:], start=i):
                    if all(not (a and b) for a, b in zip(p, q_)):
                        null += cp * (cp - 1) / 2 if i == j else cp * cq
            outside = pairs - null
            prev: list[str] = []
            for lv in c.levels:
                if any(comp.function != "exact" for _, comp in lv.any_of):
                    break
                conds = [comp.column(col) for col, comp in lv.any_of]
                u = (union(prev + conds) - union(prev)) / outside if outside else 0.0
                if u > 0:
                    out.setdefault(c.name, {})[lv.label] = u
                prev += conds
        return out
    finally:
        if name:
            con.unregister(name)


def u_bound(model: FSModel, c: Comparison, records: Records, db: DuckDBAPI) -> float:
    """95% upper bound on u for a level no sampled pair reached: zero hits among the sampled pairs where the comparison
    is filled, of which there are at least (largest fill share of its columns)² of the sample."""
    n = rows(records, db)
    sampled = min(model.u_max_pairs, n * (n - 1) / 2)
    return fp_upper(0, max(1, int(sampled * max(fill_share(records, col, db) for col in c.null_if_missing) ** 2)))


SCORED_U: dict[tuple[str, int], dict[str, float]] = {}  # (FSModel.u_keys() value, scored records' fingerprint) → u per level


def fingerprint(records: Records, cols: list[str], db: DuckDBAPI) -> int:  # the same set of records and values, in any order
    if isinstance(records, pd.DataFrame):
        return int(pd.util.hash_pandas_object(records[cols], index=False).sum())
    return int(db.duckdb_con.execute(f'SELECT bit_xor(hash({", ".join(chr(34) + c + chr(34) for c in cols)})) FROM "{records}"').fetchall()[0][0])


def with_scored_u(model: FSModel, model_json: dict, df: Records, db: DuckDBAPI, uid: str) -> dict:
    """model_json with u re-sampled on the records to be scored. In a bigger file, a field whose value set grows with it
    (address, CIF ID) agrees by chance less often, so u fixed from the fitting set under-credits it. Needs no labels and
    costs u_max_pairs whatever the file's size; cached per comparison and set of records. m and λ stay as fitted (score_fs
    rescales λ). Levels without an estimate keep their rules: no sampled pair → the bound on these records; never seen in
    training → m = u, 0 bits."""
    cols = sorted({comp.column(col) for c in model.comparisons for lv in c.levels for col, comp in lv.any_of}
                  | {col for c in model.comparisons for col in c.null_if_missing})
    records = fingerprint(df, [uid, *cols], db)
    keys, by_name = model.u_keys(), {c.name: c for c in model.comparisons}
    todo = [c for c in model.comparisons if (keys[c.name], records) not in SCORED_U]
    for name, u in sample_u(model, todo, df, db, uid).items():
        SCORED_U[keys[name], records] = u
    exact = exact_u(model, df, db) if model.u_exact_by_counts else {}
    filled_m = {tuple(x) for x in model_json["er"]["filled"]["m"]}
    out = copy.deepcopy(model_json)
    for c in out["comparisons"]:
        name = c["output_column_name"]
        for lv in (lv for lv in c["comparison_levels"] if not lv.get("is_null_level")):
            label = lv["label_for_charts"]
            lv["u_probability"] = exact.get(name, {}).get(label) or SCORED_U[keys[name], records].get(label) or u_bound(model, by_name[name], df, db)
            if (name, lv["label_for_charts"]) in filled_m:
                lv["m_probability"] = lv["u_probability"]
    return out


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
    if model.u_exact_by_counts:  # the leading exact levels, exactly
        u = {c: {**levels, **exact_u(model, t, db).get(c, {})} for c, levels in u.items()}
    labels_of = {c.name: [*(lv.label for lv in c.levels), ELSE] for c in model.comparisons}
    filled_u = [[c.name, lv] for c in model.comparisons for lv in labels_of[c.name] if lv not in u[c.name]]
    u = {c.name: {lv: u[c.name].get(lv) or u_bound(model, c, t, db) for lv in labels_of[c.name]} for c in model.comparisons}
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


def score_fs(model_json: dict, df: Records, pairs: pd.DataFrame | str, db: DuckDBAPI, uid: str,
             into: str | None = None, n_records: int | None = None) -> pd.DataFrame | str:
    """Score exactly these candidate pairs (uid_l < uid_r) with a model from train_fs, so that a score doesn't depend
    on the size of the scored set: term frequencies come from the fitting records (a value unseen there gets no
    adjustment), and λ is rescaled to this set's size (scaled_prior). Records and pairs may be tables in db's
    connection; with `into`, the scores are written to that table and its name returned, so nothing of size C
    reaches pandas. `n_records`: the size λ is rescaled to, when df holds only the records the pairs touch."""
    l, r = f"{uid}_l", f"{uid}_r"
    fit = model_json["er"]
    lam = scaled_prior(model_json, n_records or rows(df, db))
    settings = {k: v for k, v in model_json.items() if k != "er"} | {"probability_two_random_records_match": lam}
    linker = Linker(db.register(df), settings, log_level=logging.WARNING)
    linker.table_management.invalidate_cache()  # the cache lives on the shared db, keyed by table name only
    for col, tf in fit["tf"].items():
        lookup = pd.DataFrame({col: list(tf), f"tf_{col}": list(tf.values())})
        linker.table_management.register_term_frequency_lookup(db.register(lookup), col)
    con = db.duckdb_con
    if isinstance(pairs, pd.DataFrame):
        if pairs.empty:
            empty = pairs.assign(match_weight=pd.Series(dtype=float), match_probability=pd.Series(dtype=float))
            if into is None:
                return empty
            con.register("er_empty_scores", empty)
            con.execute(f'CREATE OR REPLACE TABLE "{into}" AS SELECT * FROM er_empty_scores')
            con.unregister("er_empty_scores")
            return into
        blocked = db.register(pd.DataFrame({"match_key": "0", "join_key_l": pairs[l].to_numpy(), "join_key_r": pairs[r].to_numpy()}))
    else:
        blocked = db.register(con.sql(f'SELECT \'0\' AS match_key, "{l}" AS join_key_l, "{r}" AS join_key_r FROM "{pairs}"'))
    linker.table_management.register_blocked_pairs_for_predict(blocked)
    predictions = linker.inference.predict()
    rel = predictions.as_duckdbpyrelation()
    keep = [l, r, "match_weight", "match_probability", *(c for c in rel.columns if c.startswith("gamma_"))]
    projected = rel.project(", ".join(f'"{c}"' for c in keep))  # memory: the matching columns never reach pandas
    if into is not None:
        con.execute(f'DROP TABLE IF EXISTS "{into}"')
        projected.to_table(into)
        predictions.drop_table_from_database_and_remove_from_cache()
        return into
    out = projected.df()
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
