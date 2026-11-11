"""Entity matching: candidate pairs → decided / scored pairs.

rules           a pair is accepted when every condition of one rule holds (score 1.0); each rule is one SQL
                equi-join, so its work is the pairs inside its blocks
fellegi_sunter  Splink's Fellegi–Sunter model: λ from near-certain rules, u counted on the file where a level can be
                (exact_u) and sampled where it can't, m by EM or from labels; scores any registered candidate table, so candidates and scoring stay independent
"""
import contextlib
import copy
import hashlib
import json
import logging
import math
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from itertools import combinations, product
from pathlib import Path

import duckdb
import pandas as pd
import splink
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator

from er.candidates import deletions_sql
from er.config import Comparator, Comparison, DeletionKeys, FSModel, FSSpec, InputError, Key, KeyBlocker, Pipeline, RulesSpec, keys_sql, q


def rule_edges(spec: RulesSpec, records: "Records", db: DuckDBAPI, uid: str, batch: str | None = None,
               trust: Mapping[int, str] | None = None, into: str | None = None, told: Callable[..., None] | None = None) -> tuple[pd.DataFrame | str, dict[str, float]]:
    """Every rule's pairs, uid_l < uid_r, with the rule and stage that found it (the first rule in order wins a pair)
    and score 1.0: one equi-join per rule, its fuzzy conditions checked on the joined pairs only. `batch`: a table of
    records joined against all of them (an increment), O(|batch|·b) instead of every pair; `trust`: per rule (its index
    in order), a condition its record `l` must meet (values it doesn't trust left out: the keys are equal on both
    sides). With `into`, a table in db's connection, else a frame. Also returns each rule's seconds. `told(done, total,
    "rules")` after each rule: how far it is.
    Plain SQL, not Splink's deterministic_link, which joins every column of both records back only for us to drop them."""
    l, r, u, con = q(f"{uid}_l"), q(f"{uid}_r"), q(uid), db.duckdb_con
    name = records if isinstance(records, str) else f"er_rules_{abs(hash(id(records)))}"
    if not isinstance(records, str):  # a frame not prepared by er.standardize has no one-byte copy: the Python function compares its pairs
        copies = {comp.copy(c) for s in spec.stages for c, comp in s.comparators.items() if comp.copy(c)} - set(records.columns)
        con.register(name, records.assign(**{c: pd.Series(pd.NA, index=records.index, dtype="string") for c in copies}))
    left, order = (batch, "<>") if batch else (name, "<")  # a batch pair can come both ways round: DISTINCT ON keeps one
    seconds, parts, every = {}, [], list(spec.each())
    if told:
        told(0, len(every), "rules")
    try:
        for i, s, rule in every:
            t = time.perf_counter()
            keep = f" WHERE {trust[i]}" if trust and i in trust else ""  # in WHERE, tested before the join: in ON, after it, a placeholder's whole block joined and compared first
            con.execute(f'CREATE OR REPLACE TEMP TABLE er_rule_{i} AS SELECT least(l.{u}, r.{u}) AS {l}, greatest(l.{u}, r.{u}) AS {r} '
                        f'FROM "{left}" l JOIN "{name}" r ON {s.sql(rule)} AND l.{u} {order} r.{u}{keep}')
            seconds[rule.name] = time.perf_counter() - t
            parts.append(f"SELECT {l}, {r}, '{rule.name}' AS rule, '{s.name}' AS stage, {i} AS i FROM er_rule_{i}")
            if told:
                told(len(parts), len(every), "rules")
        sql = f'SELECT DISTINCT ON ({l}, {r}) {l}, {r}, rule, stage, 1.0 AS score FROM ({" UNION ALL ".join(parts)}) ORDER BY {l}, {r}, i'
        if into:
            con.execute(f'CREATE OR REPLACE TABLE "{into}" AS {sql}')
            return into, seconds
        return con.sql(sql).df().astype({f"{uid}_l": "string", f"{uid}_r": "string"}), seconds
    finally:
        for i in range(len(parts)):
            con.execute(f"DROP TABLE IF EXISTS er_rule_{i}")
        if not isinstance(records, str):
            con.unregister(name)


ELSE = "else"
U = dict[str, dict[str, float]]  # comparison → level label → u probability


def comparison(c: Comparison, u: dict[str, float] | None = None) -> cl.CustomComparison:
    def with_u(level: cll.CustomLevel, label: str) -> cll.CustomLevel:
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


def read_by(settings: dict | SettingsCreator, *rules: str) -> set[str]:
    """The columns a linker reads: each comparison level's ("x_l", "x_r"), each blocking rule's (l."x"), each term
    frequency's: all its records need to hold."""
    s = settings.create_settings_dict("duckdb") if isinstance(settings, SettingsCreator) else settings
    levels = [lv for c in s["comparisons"] for lv in c["comparison_levels"]]
    blocking = [b["blocking_rule"] if isinstance(b, dict) else b for b in s.get("blocking_rules_to_generate_predictions", [])]
    text = " ".join([*(lv.get("sql_condition", "") for lv in levels), *blocking, *rules])
    return set(re.findall(r'"([^"]+)_[lr]"', text)) | set(re.findall(r'\b[lr]\."([^"]+)"', text)) | {lv["tf_adjustment_column"] for lv in levels if lv.get("tf_adjustment_column")}


@contextlib.contextmanager
def narrowed(df: "Records", db: DuckDBAPI, keep: set[str]):
    """The records as a linker reads them, registered: only the columns in `keep`, so a wide file's others never travel
    with each pair through its joins (the same scores; a column it reads and lacks fails loudly, but a one-byte copy:
    records not prepared by er.standardize lack it, and the Python function then compares every pair). Released after,
    the db's cache first (it may name them)."""
    if isinstance(df, pd.DataFrame):
        x = db.register(df[[c for c in df.columns if c in keep]].assign(**{c: pd.Series(pd.NA, index=df.index, dtype="string")
                                                                           for c in keep - set(df.columns) if c.endswith("one_byte")}))
    else:
        have = [c for c, *_ in db.duckdb_con.execute(f'DESCRIBE "{df}"').fetchall()]
        cols = [q(c) for c in have if c in keep] + [f"NULL::VARCHAR AS {q(c)}" for c in sorted(keep - set(have)) if c.endswith("one_byte")]
        x = db.register(db.duckdb_con.sql(f'SELECT {", ".join(cols)} FROM "{df}"'))
    try:
        yield x
    finally:
        db.duckdb_con.unregister(x.physical_name)


def sample_u(model: FSModel, comparisons: list[Comparison], df: pd.DataFrame, db: DuckDBAPI, uid: str) -> U:
    """Splink's random sampling for just these comparisons. The sample depends only on the records, the size and the
    seed, so this equals sampling them inside the full model (tests/). O(max_pairs · comparisons)."""
    if not comparisons:
        return {}
    settings = fs_settings(replace(model, comparisons=tuple(comparisons)), uid)
    with narrowed(df, db, read_by(settings) | {uid}) as records:
        linker = Linker(records, settings, log_level=logging.ERROR)
        # every one of max_pairs: Splink would stop once each level has 100 hits, while u_basis and u_bound count on them all;
        # in chunks of about CHUNK_BYTES compared: the same pairs (the same counts, summed), so long values never spike the memory
        cols = [c for c in read_by(settings) if c != uid]
        size = db.duckdb_con.execute(f'SELECT {" + ".join(f"coalesce(avg(strlen({q(c)})), 0)" for c in cols) or "0"} FROM "{records.physical_name}"').fetchall()[0][0]
        chunks = min(40, max(1, math.ceil(model.u_max_pairs * 2 * (size or 0) / CHUNK_BYTES)))
        linker.training.estimate_u_using_random_sampling(max_pairs=model.u_max_pairs, seed=model.seed, min_count_per_level=None, num_chunks=chunks)
        model_json = linker.misc.save_model_to_json()
        linker.table_management.invalidate_cache()
    return u_values(model_json)


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
    t = q(name or records)
    try:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]
        pairs = n * (n - 1) / 2
        agree_cache: dict[frozenset, float] = {}

        def agree(cols: frozenset) -> float:  # distinct pairs equal on every one of these columns (all filled)
            if cols not in agree_cache:
                c = ", ".join(q(x) for x in sorted(cols))
                filled = " AND ".join(f"{q(x)} IS NOT NULL" for x in sorted(cols))
                agree_cache[cols] = float(con.execute(f"SELECT coalesce(sum(c * (c - 1) / 2), 0) FROM (SELECT count(*) AS c FROM {t} "
                                                      f"WHERE {filled} GROUP BY {c})").fetchall()[0][0])
            return agree_cache[cols]

        def union(conds: list[str]) -> float:  # pairs equal on at least one of these columns
            return sum((-1) ** (k + 1) * agree(frozenset(sub)) for k in range(1, len(conds) + 1) for sub in combinations(conds, k))

        def near(col: str, comp: Comparator) -> float:
            """Distinct pairs of records whose values differ but pass comp (an edit distance ≤ 1): two such values always
            share a one-deletion key, so the distinct values are joined on their keys and only those pairs are checked.
            O(U·L + value pairs sharing a key), U distinct values."""
            return float(con.execute(f"""
                WITH v AS (SELECT "{col}" AS x, count(*) AS n FROM {t} WHERE "{col}" IS NOT NULL GROUP BY 1),
                     k AS (SELECT x, n, unnest({deletions_sql('x')}) AS dk FROM v),
                     p AS (SELECT DISTINCT a.x AS x, b.x AS y, a.n * b.n AS nn FROM k a JOIN k b ON a.dk = b.dk AND a.x < b.x)
                SELECT coalesce(sum(nn), 0) FROM p WHERE {comp.test("x", "y")}""").fetchall()[0][0])

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
                    (col, comp), *more = lv.any_of
                    if (model.u_near_by_keys and not more and comp.function in ONE_EDIT and comp.threshold <= 1
                            and set(prev) == {comp.column(col)}):  # after exact levels on its own column: unequal values only
                        if (u := near(comp.column(col), comp) / outside if outside else 0.0) > 0:
                            out.setdefault(c.name, {})[lv.label] = u
                    break
                conds = [comp.column(col) for col, comp in lv.any_of]
                u = (union(prev + conds) - union(prev)) / outside if outside else 0.0
                if u > 0:
                    out.setdefault(c.name, {})[lv.label] = u
                prev += conds
            got = out.get(c.name, {})
            if model.u_near_by_keys and all(lv.label in got for lv in c.levels) and (rest := 1 - sum(got.values())) > 0:
                got[ELSE] = rest  # every level counted: nothing left to sample
        return out
    finally:
        if name:
            con.unregister(name)


ONE_EDIT = ("levenshtein", "damerau_levenshtein", "hamming")  # distances under which one edit apart shares a deletion key


def counted(model: FSModel, exact: U) -> set[str]:  # the comparisons exact_u counted level by level, else included: none to sample
    return {name for name, u in exact.items() if ELSE in u} if model.u_exact_by_counts and model.u_near_by_keys else set()


def u_bound(model: FSModel, c: Comparison, records: Records, db: DuckDBAPI) -> float:
    """95% upper bound on u for a level no sampled pair reached: zero hits among the sampled pairs where the comparison
    is filled, of which there are at least (largest fill share of its columns)² of the sample."""
    n = rows(records, db)
    sampled = min(model.u_max_pairs, n * (n - 1) / 2)
    n_filled = max(1, int(sampled * max(fill_share(records, col, db) for col in c.null_if_missing) ** 2))
    return 1 - 0.05 ** (1 / n_filled)  # the one-sided 95% Clopper–Pearson bound at zero hits (er.evaluate.fp_upper(0, n))


SCORED_U: dict[tuple[str, int], dict[str, float]] = {}  # (FSModel.u_keys() value, fingerprint of what it reads) → u per level
# shortcut: one entry per comparison and file this process scores, never dropped; fine for a run or choose.py, a
# process that scores file after file needs a limit (nayose open ui runs those in processes of their own)
CHUNK_BYTES = 1 << 28  # what one chunk of the u sample compares at most, about: its pairs' values, both sides
U_KEPT = 64  # sampled u a workspace keeps (folder.U_SAMPLED), the newest: one per comparison, sample and file, and a few of each
U_CODE = hashlib.sha256(b"".join((Path(__file__).parent / f).read_bytes() for f in ("match.py", "strings.py", "config.py"))).hexdigest()[:16]


def fingerprint(records: Records, cols: list[str], db: DuckDBAPI) -> int:
    """The same set of records and values, in any order, a frame or a table alike: hashed by DuckDB either way."""
    con, name = db.duckdb_con, records if isinstance(records, str) else f"er_fp_{abs(hash(id(records)))}"
    if not isinstance(records, str):
        con.register(name, records)
    try:
        return int(con.execute(f'SELECT coalesce(bit_xor(hash({", ".join(chr(34) + c + chr(34) for c in cols)})), 0) FROM "{name}"').fetchall()[0][0])
    finally:
        if not isinstance(records, str):
            con.unregister(name)


def scored_sample(model: FSModel, df: Records, db: DuckDBAPI, uid: str, comparisons: Iterable[Comparison] | None = None, kept: Path | None = None) -> U:
    """u by random sampling on these records, per comparison (all, or these), cached (SCORED_U) by the comparison and
    the values it reads, within this process. Splink picks the sampled pairs by a hash of the record ID, so nothing else
    changes them: a model and its variant share one sample, and so do a fit on a whole small file and the run's u on it
    when both sample as many pairs (fit_u_max_pairs unset). O(N) per comparison for
    the fingerprint, plus u_max_pairs per comparison not cached yet. With `kept` (a workspace's folder.U_SAMPLED), across
    processes too: a rerun, or a trial of another method comparing the same way, reads its u, never samples it again,
    while the comparison, the values, this code and Splink's and DuckDB's versions are as they were."""
    keys, wanted = model.u_keys(), list(model.comparisons if comparisons is None else comparisons)
    reads = {c.name: [uid, *sorted({comp.column(col) for lv in c.levels for col, comp in lv.any_of} | set(c.null_if_missing))] for c in wanted}
    prints = {c.name: fingerprint(df, reads[c.name], db) for c in wanted}
    stable = lambda name: hashlib.sha256(repr((keys[name], prints[name], splink.__version__, duckdb.__version__, U_CODE)).encode()).hexdigest()
    try:  # a copy kept never fails a run: unreadable, sampled again
        on_disk = json.loads(kept.read_text(encoding="utf-8")) if kept and kept.is_file() else {}
    except (OSError, ValueError):
        on_disk = {}
    for c in wanted:
        if (keys[c.name], prints[c.name]) not in SCORED_U and stable(c.name) in on_disk:
            SCORED_U[keys[c.name], prints[c.name]] = on_disk[stable(c.name)]
    todo = [c for c in wanted if (keys[c.name], prints[c.name]) not in SCORED_U]
    fresh = sample_u(model, todo, df, db, uid)
    for name, u in fresh.items():
        SCORED_U[keys[name], prints[name]] = u
        on_disk.pop(stable(name), None)
        on_disk[stable(name)] = u  # the newest last
    if kept and fresh:
        with contextlib.suppress(OSError):  # a folder people can only read: sampled again next time
            tmp = kept.with_name(f".{kept.name}.{os.getpid()}")
            tmp.write_text(json.dumps(dict(list(on_disk.items())[-U_KEPT:])), encoding="utf-8")
            os.replace(tmp, kept)
    return {c.name: SCORED_U[keys[c.name], prints[c.name]] for c in wanted}


def assemble_u(model: FSModel, model_json: dict, sampled: U, exact: U, df: Records, db: DuckDBAPI) -> dict:
    """model_json with each level's u: counted exactly (when the model counts them), else sampled, else, for a level no
    sampled pair reached, the bound on these records. A level never seen in training gets m = u, 0 bits. m and λ stay as
    fitted (score_fs rescales λ)."""
    exact = exact if model.u_exact_by_counts else {}
    by_name, filled_m = {c.name: c for c in model.comparisons}, {tuple(x) for x in model_json["er"]["filled"]["m"]}
    out = copy.deepcopy(model_json)
    for c in out["comparisons"]:
        name = c["output_column_name"]
        for lv in (lv for lv in c["comparison_levels"] if not lv.get("is_null_level")):
            label = lv["label_for_charts"]
            lv["u_probability"] = exact.get(name, {}).get(label) or sampled.get(name, {}).get(label) or u_bound(model, by_name[name], df, db)
            if (name, label) in filled_m:
                lv["m_probability"] = lv["u_probability"]
    return out


def scored_u(model: FSModel, model_json: dict, df: Records, db: DuckDBAPI, uid: str, kept: Path | None = None) -> tuple[dict, U, U]:
    """model_json with u measured on the records to be scored, and the u sampled and counted for it (u_basis reads them).
    In a bigger file, a field whose value set grows with it (address, CIF ID) agrees by chance less often, so u fixed
    from the fitting set under-credits it. Needs no labels; O(N) counts and u_max_pairs sampled, whatever the file's size."""
    exact = exact_u(model, df, db)
    skip = counted(model, exact)
    sampled = scored_sample(model, df, db, uid, [c for c in model.comparisons if c.name not in skip], kept)
    return assemble_u(model, model_json, sampled, exact, df, db), sampled, exact


def u_basis(model: FSModel, sampled: U, exact: U, df: Records, db: DuckDBAPI, names: Iterable[str] | None = None) -> dict:
    """What a later increment needs to tell whether these sampled u have gone stale, per comparison: the sampled u, the
    exact-level u counted alongside, the record count, and how many sampled pairs had the comparison filled."""
    n = rows(df, db)
    sampled_pairs = min(model.u_max_pairs, n * (n - 1) / 2)
    return {c.name: dict(sampled=sampled.get(c.name, {}), exact=exact.get(c.name, {}), n=n,
                         pairs=sampled_pairs * max(fill_share(df, col, db) for col in c.null_if_missing) ** 2)
            for c in model.comparisons if names is None or c.name in names}


def stale_u(model: FSModel, basis: dict, exact_now: U, n: int) -> dict[str, dict[str, float]]:
    """Per comparison, d: how far its sampled u have likely drifted since they were sampled, in bits. That is the drift
    of its leading exact level, counted exactly, or log2(N / N then) without one (an equality level can't fall faster).
    And se: the sampling error of its most precise sampled agreement level, 1/(ln 2·√hits). Once d > se, staleness
    outweighs the sample's own noise, so a new sample is closer to the truth; below that, it would only redraw the
    noise. A comparison never sampled has d = ∞."""
    out = {}
    for c in model.comparisons:
        b = basis.get(c.name)
        if b is None:
            out[c.name] = dict(drift_bits=math.inf, se_bits=0.0)
            continue
        lead = next(iter(b["exact"]), None)
        now = exact_now.get(c.name, {}).get(lead) if lead else None
        d = abs(math.log2(now / b["exact"][lead])) if now else math.log2(max(n, 2) / max(b["n"], 2))
        hits = [u * b["pairs"] for label, u in b["sampled"].items() if label != ELSE and label not in b["exact"]]
        out[c.name] = dict(drift_bits=d, se_bits=min((1 / (math.log(2) * math.sqrt(h)) for h in hits if h >= 1), default=math.inf))
    return out


def refreshed_u(model: FSModel, model_json: dict, basis: dict, df: Records, db: DuckDBAPI, uid: str) -> tuple[dict, dict, list[str]]:
    """For an increment: the exact levels counted again on all records (O(N), a group-by per level), and only the
    comparisons stale_u finds stale sampled again (u_max_pairs each); the rest keep their stored sample. Returns the
    scoring model, the updated basis (each comparison with its last check) and the comparisons sampled again."""
    exact, n = exact_u(model, df, db), rows(df, db)
    check = stale_u(model, basis, exact, n)
    todo = [c for c in model.comparisons if check[c.name]["drift_bits"] > check[c.name]["se_bits"] and c.name not in counted(model, exact)]
    basis = {**basis, **u_basis(model, sample_u(model, todo, df, db, uid), exact, df, db, {c.name for c in todo})}
    for name, x in check.items():
        basis[name]["last_check"] = {k: v if math.isfinite(v) else None for k, v in x.items()}
    sampled = {name: b["sampled"] for name, b in basis.items()}
    return assemble_u(model, model_json, sampled, exact, df, db), basis, [c.name for c in todo]


def rule_pairs(df: pd.DataFrame, rule: tuple[Key, ...]) -> int:  # the pairs a blocking rule makes in these records
    cols = [k.name for k in rule]
    sizes = df.dropna(subset=cols).groupby(cols).size()
    return int((sizes * (sizes - 1) // 2).sum())


def train_fs(model: FSModel, df: pd.DataFrame, db: DuckDBAPI, uid: str, labels: pd.Series | None = None, kept: Path | None = None) -> dict:
    """Train on df; `labels` (entity per uid) is required for m_method="labels". Returns the Splink model JSON plus
    "er": what scoring needs (fitting-set size, term frequencies) and which levels had no estimate.
    u-sampling is ~97% of training time and depends only on each comparison and the records (FSModel.u_keys), not on
    the m method or term-frequency adjustment, so it goes through scored_sample's cache.
    A level without an estimate never falls back to Splink's defaults: no sampled pair → u at its upper bound (the
    weight is a lower bound on the evidence); never seen in training → m = u (0 bits). A prior or EM rule that finds no
    pair in df (its fields nearly empty there) is skipped, and listed in "er"; none left of either stops the fit."""
    t = df.copy()
    if model.fit_u_max_pairs:  # the fit's own sample size: its own entries in the cache, and its own bounds
        model = replace(model, u_max_pairs=model.fit_u_max_pairs)
    if model.m_method == "labels":
        assert labels is not None, "m_method='labels' needs truth labels"
        t["__label__"] = t[uid].map(labels)
    exact = exact_u(model, t, db) if model.u_exact_by_counts else {}  # the leading exact levels, exactly
    skip = counted(model, exact)
    u = {**{c: {} for c in skip}, **scored_sample(model, t, db, uid, [c for c in model.comparisons if c.name not in skip], kept)}
    u = {c: {**levels, **exact.get(c, {})} for c, levels in u.items()}
    labels_of = {c.name: [*(lv.label for lv in c.levels), ELSE] for c in model.comparisons}
    filled_u = [[c.name, lv] for c in model.comparisons for lv in labels_of[c.name] if lv not in u[c.name]]
    u = {c.name: {lv: u[c.name].get(lv) or u_bound(model, c, t, db) for lv in labels_of[c.name]} for c in model.comparisons}
    fields = lambda rule: " + ".join(k.column for k in rule)
    prior = [r for r in model.prior_rules if rule_pairs(t, r)]
    em = [r for r in model.em_rules if rule_pairs(t, r)] if model.m_method == "em" else []
    if not prior:
        raise InputError(f"no two records of the {len(t):,} the fit samples agree on any near-certain rule "
                         f"({'; '.join(map(fields, model.prior_rules))}), so the chance that two records match can't be estimated",
                         fix="map the fields those rules read, or give a model fitted before with --model")
    if model.m_method == "em" and not em:
        raise InputError(f"no two records of the {len(t):,} the fit samples share {' or '.join(map(fields, model.em_rules))}, "
                         "the pairs it learns from", fix="map those fields to filled columns, or give a model fitted before with --model")
    settings = fs_settings(model, uid, u)  # unestimated levels: handled here
    with narrowed(t, db, read_by(settings, *(keys_sql(r) for r in prior)) | {uid, "__label__"}) as records:
        linker = Linker(records, settings, log_level=logging.ERROR)
        linker.training.estimate_probability_two_random_records_match([keys_sql(r) for r in prior], recall=model.prior_recall)
        for rule in em:
            linker.training.estimate_parameters_using_expectation_maximisation(keys_sql(rule))
        if model.m_method == "labels":
            linker.training.estimate_m_from_label_column("__label__")
        model_json = linker.misc.save_model_to_json()
        linker.table_management.invalidate_cache()
    filled_m = []
    for c in model_json["comparisons"]:
        for lv in c["comparison_levels"]:
            if not lv.get("is_null_level") and "m_probability" not in lv:
                lv["m_probability"] = lv["u_probability"]
                filled_m.append([c["output_column_name"], lv["label_for_charts"]])
    tf = {c.tf.name: (t[c.tf.name].value_counts() / t[c.tf.name].notna().sum()).to_dict()  # Splink's own formula
          for c in model.comparisons if c.tf and any(lv.tf for lv in c.levels)}
    skipped = [fields(r) for r in (*model.prior_rules, *(model.em_rules if model.m_method == "em" else ())) if r not in (*prior, *em)]
    return {**model_json, "er": dict(fit_rows=len(t), tf=tf, filled=dict(u=filled_u, m=filled_m), skipped=skipped)}


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
    with narrowed(df, db, read_by(settings) | {uid}) as records:
        linker = Linker(records, settings, log_level=logging.WARNING)
        linker.table_management.invalidate_cache()  # the cache lives on the shared db, keyed by table name only
        con, held = db.duckdb_con, []  # what it registers, released once scored: a run calls it once a slice
        try:
            for col, tf in fit["tf"].items():
                held.append(db.register(pd.DataFrame({col: list(tf), f"tf_{col}": list(tf.values())})))
                linker.table_management.register_term_frequency_lookup(held[-1], col)
            return _predict(linker, held, db, pairs, l, r, into)
        finally:  # the db's cache first: it names the lookups, and a linker made later on this db would read them
            linker.table_management.invalidate_cache()
            for x in held:
                con.unregister(x.physical_name)


def _predict(linker: Linker, held: list, db: DuckDBAPI, pairs: pd.DataFrame | str, l: str, r: str, into: str | None) -> pd.DataFrame | str:
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
    held.append(blocked)
    linker.table_management.register_blocked_pairs_for_predict(blocked)
    predictions = linker.inference.predict()
    rel = predictions.as_duckdbpyrelation()
    keep = [l, r, "match_weight", "match_probability", *(c for c in rel.columns if c.startswith("gamma_"))]
    projected = rel.project(", ".join(q(c) for c in keep))  # memory: the matching columns never reach pandas
    if into is not None:
        con.execute(f'DROP TABLE IF EXISTS "{into}"')
        projected.to_table(into)
        predictions.drop_table_from_database_and_remove_from_cache()
        return into
    out = projected.df()
    predictions.drop_table_from_database_and_remove_from_cache()  # else every call keeps its predictions in the shared db
    return out.astype({l: "string", r: "string"})


def levels(model_json: dict) -> dict[str, dict[int, tuple[str, float]]]:
    """Per comparison: each gamma, as score_fs returns it, → its level's label and bits log2(m/u). Gamma counts up from
    the else level (0); -1 is a missing side, worth 0 bits."""
    out = {}
    for c in model_json["comparisons"]:
        ordered = [lv for lv in c["comparison_levels"] if not lv.get("is_null_level")][::-1]
        out[c["output_column_name"]] = {-1: ("missing", 0.0), **{g: (lv["label_for_charts"], math.log2(lv["m_probability"] / lv["u_probability"]))
                                                                for g, lv in enumerate(ordered)}}
    return out


def waterfall(model_json: dict, gammas: dict[str, int], n_records: int) -> pd.DataFrame:
    """One scored pair's match weight as evidence: the prior, then per comparison the bits of the level the pair landed
    in. The bits sum to Splink's match_weight."""
    assert not model_json["er"]["tf"], "term-frequency adjustments are per value and not shown here"
    lam = scaled_prior(model_json, n_records)
    rows = [dict(evidence="prior", level="two random records match", bits=math.log2(lam / (1 - lam)))]
    for name, by_gamma in levels(model_json).items():
        label, bits = by_gamma[int(gammas[name])]
        rows.append(dict(evidence=name, level=label, bits=bits))
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


def pattern_coverage(spec: FSSpec, model_json: dict, n_records: int) -> pd.DataFrame:
    """The label-free form of window_only: every agreement pattern (one level per comparison, or missing) whose bits
    reach min_match_weight at n_records, that no equality key is guaranteed to pair, with its share of true matches
    (Π m, the model's own estimate). A level guarantees what its comparators imply: an exact comparator, equality of
    that normalized field and of any longer normalization of it; a distance ≤ 1, a shared one-deletion key. A fuzzy
    similarity (Jaro–Winkler) implies no key, so for its patterns the share is an upper bound on what is at risk.
    O(Π levels) patterns, a few thousand."""
    by_name = {c.name: c for c in spec.model.comparisons}
    lam = scaled_prior(model_json, n_records)
    prior = math.log2(lam / (1 - lam))

    def implied(col: str, comp) -> set[tuple[str, tuple[str, ...], str]]:  # (field, normalization, "eq" | "near")
        if comp.function == "exact":
            return {(col, comp.normalize, "eq")}
        if comp.function in ("levenshtein", "damerau_levenshtein", "hamming") and comp.threshold is not None and comp.threshold <= 1:
            return {(col, comp.normalize, "near")}
        return set()

    def holds(facts: set, key, near_ok: bool = False) -> bool:  # does a fact imply equality (or nearness) of this key?
        return any(f == key.column and key.normalize[:len(n)] == n and (kind == "eq" or (near_ok and n == key.normalize))
                   for f, n, kind in facts)

    def covered(branches: list[set]) -> bool:  # every way the pattern can hold must imply some generator's keys
        def one(facts: set) -> bool:
            for b in spec.blockers:
                if isinstance(b, KeyBlocker) and all(holds(facts, k) for k in b.keys):
                    return True
                if isinstance(b, DeletionKeys) and holds(facts, b.key, near_ok=True) and all(holds(facts, k) for k in b.within):
                    return True
            return False
        return all(one(f) for f in branches)

    options = []
    for c in model_json["comparisons"]:
        comp = by_name[c["output_column_name"]]
        levels = {lv.label: lv for lv in comp.levels}
        opts = [("missing", 0.0, 1.0, [set()])]
        for lv in (x for x in c["comparison_levels"] if not x.get("is_null_level")):
            label = lv["label_for_charts"]
            branches = [implied(col, cmp) for col, cmp in levels[label].any_of] if label in levels else [set()]
            opts.append((label, math.log2(lv["m_probability"] / lv["u_probability"]), lv["m_probability"], branches))
        options.append((c["output_column_name"], opts))
    rows = []
    for combo in product(*(opts for _, opts in options)):
        weight = prior + sum(o[1] for o in combo)
        if weight < spec.min_match_weight:
            continue
        branches = [set()]
        for o in combo:  # the pattern's facts: one branch per OR'd condition of each level
            branches = [b | f for b in branches for f in o[3]]
        if not covered(branches):
            rows.append({**{name: o[0] for (name, _), o in zip(options, combo)}, "bits": round(weight, 2),
                         "share_of_matches": math.prod(o[2] for o in combo if o[0] != "missing")})
    out = pd.DataFrame(rows, columns=[*(n for n, _ in options), "bits", "share_of_matches"])
    return out.sort_values("share_of_matches", ascending=False, ignore_index=True)


def named_sql(fs: FSSpec, s: str = "s") -> str:  # the name check (FSSpec.needs) on scores aliased `s`: a merge without people compares a name
    return "(" + (" OR ".join(f"{s}.{q('gamma_' + c)} >= 0" for c in fs.needs) or "TRUE") + ")"


def review_floor(p: Pipeline) -> float:
    """The lowest weight people are asked to decide: the threshold rule's safety margin below min_match_weight, i.e. the
    [threshold] grid point margin_steps below it. Pairs there were clean on cross-validated train, but held back."""
    below = sorted(g for g in p.threshold.grid if g < p.fs.min_match_weight)
    if not p.threshold.margin_steps or not below:
        return p.fs.min_match_weight
    return below[-min(p.threshold.margin_steps, len(below))]
