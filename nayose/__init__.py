"""nayose: entity resolution for Japanese customer records, as BigQuery SQL run by a few lines of Python.

The method is SQL, in BigQuery's dialect, one file per stage (nayose/sql/<stage>.sql), read top to bottom. BigQuery
runs it as written; DuckDB, on a laptop or in CI, runs it after sqlglot translates it (nayose/engines.py). A run is
a set of tables: a BigQuery dataset, or a DuckDB database file.

    build(engine, files)            a run's first batch: records, fit, score, decide
    update(engine, files)           a batch added: records, u measured again, the pairs touching it scored, decide
    records(engine, files)          stage 1: the input files read and mapped (mapping.sql), made records (records.sql)
    fit(engine)                     stage 2: the model learned on a sample, u on the file (fit.sql; EM in nayose/em.py)
    score(engine)                   stage 3: the rules' pairs, the keys' candidates and their scores (score.sql)
    decide(engine, files)           people's decisions stored, the entities made from them (decide.sql; a build: none given)
    match(engine, threshold)        the pairs at a threshold people set, less those they said differ, for them (match.sql)
    lookup(engine, record|values)   the entities a record would join, as an update of it alone, nothing written (lookup.sql)
    stage(engine, name, **values)   a stage's statements in order, each given the values it names (@name)
    statements(text)                a stage file's statements: each ends with a line that ends in ;
    fingerprint()                   what an increment needs unchanged since the full run: the SQL and the values
"""
import hashlib
import json
import math
import platform
import re
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
SQL = HERE / "sql"
NAME_MODEL = HERE.parent / "config" / "kind_names.npz"  # the name model: its terms, weights and intercept (scripts/train_name_model.py)
SMALL_KANA = str.maketrans("ァィゥェォッャュョヮ", "アイウエオツヤユヨワ")  # banks write no small kana: a legal form is also matched so
HIRAGANA = "".join(chr(c) for c in range(0x3041, 0x3097))  # hiragana, and the katakana each is read as
KATAKANA = "".join(chr(c + 0x60) for c in range(0x3041, 0x3097))
KATAKANA_BLOCK, ONE_BYTE = "".join(map(chr, range(0x30A0, 0x3100))), "".join(map(chr, range(1, 0x61)))  # the block, each a byte: 0x01–0x60
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # a column name config.toml gives
QUERY = "\uffffasked"  # the ID of a record looked up by its values: no record's, and after every one in order
SHOWN = ("full_name", "person_name", "company_name", "address", "postal_code", "phone", "birth_date", "customer_id")  # a record, as a person reads it
BLANK = "".join(ch for ch in map(chr, range(0x3001)) if ch.isspace())  # what a blank value people give is made of: Python's whitespace


class InputError(ValueError):  # a refusal the person running the job can act on: what is wrong, and how to fix it
    def __init__(self, message: str, fix: str = "") -> None:
        super().__init__(message)
        self.fix = fix


def config(path: Path = HERE / "config.toml") -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def legal_pattern(c: dict) -> str:
    """A legal form anywhere (also with its small kana written large), or a bank abbreviation where it may stand: first,
    カ)〇〇, or last, 〇〇(カ. Longest first, so 医療法人社団 isn't cut to 医療法人. On NFKC text."""
    forms = sorted({f for x in c["legal_forms"] for f in (x, x.translate(SMALL_KANA))}, key=len, reverse=True)
    parts = [re.escape(f) for f in forms]
    if c["legal_front"]:
        parts.append(f"^(?:{'|'.join(map(re.escape, sorted(c['legal_front'], key=len, reverse=True)))})\\)")
    if c["legal_end"]:
        parts.append(f"\\((?:{'|'.join(map(re.escape, sorted(c['legal_end'], key=len, reverse=True)))})$")
    return "|".join(parts)


def nulls_pattern(nulls: list[str]) -> str:
    """A value read_value reads as missing: one of nulls but for spaces and U+3000 around it, or spaces alone (Python's
    whitespace, str.strip's). An RE2 pattern."""
    return r"^[ \x{3000}]*(?:" + "|".join(map(re.escape, nulls)) + r")[ \x{3000}]*$|^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$"


def records(engine, files: list | None, lookup: bool = False) -> None:
    """Stage 1 on `engine`: the input files as the table input (every column mapping.sql reads that a file lacks,
    missing; None: the table input as it is), the name model's weights as name_weights; then mapping.sql, then
    records.sql. O(Δ·L) + O(N) for the placeholders. `lookup`: the input is records asked about (lookup)."""
    c = config()
    if bad := [x for x in c["input"]["columns"] if not NAME.match(x)]:
        raise ValueError(f"config.toml [input] columns: {bad} are no plain column names")
    if files is not None:
        engine.read_parquet("input", files, c["input"]["columns"])
    engine.put("name_weights", name_weights())
    stage(engine, "functions")
    run_file(engine, HERE / "mapping.sql", **values("mapping"))
    stage(engine, "records", **values("records", lookup=lookup))


def name_weights() -> pd.DataFrame:  # the name model (config/kind_names.npz): each character n-gram's weight
    model = np.load(NAME_MODEL)
    return pd.DataFrame({"term": model["terms"].tolist(), "w": model["coef"]})


def values(name: str, refit: bool = True, lookup: bool = False) -> dict:
    """The values stage `name` reads as @name, from config.toml: what a run here passes as query parameters, and what
    a BigQuery procedure declares (engines.procedures). `refit`: a build (an update keeps the model); `lookup`: the
    batch is a record asked about. match's @threshold, lookup's and report's own are their jobs'."""
    c = config()
    r, f, s = c["records"], c["fit"], c["score"]
    if name == "mapping":
        return dict(nulls=nulls_pattern(c["input"]["nulls"]))
    if name == "records":
        return dict(hiragana=HIRAGANA, katakana=KATAKANA, katakana_block=KATAKANA_BLOCK, one_byte=ONE_BYTE, kana_fold_from=r["kana_fold_from"],
                    kana_fold_to=r["kana_fold_to"], legal_pattern=legal_pattern(r), prefecture_pattern=f"^(?:{'|'.join(map(re.escape, r['prefectures']))})",
                    flag_company=list(r["flag_company"]), name_line=float(r["name_line"]), trust_flag=bool(r["trust_flag"]),
                    shared_name_column=bool(r["shared_name_column"]), ngram=int(r["ngram"]), intercept=float(np.load(NAME_MODEL)["intercept"]),
                    min_block=int(r["min_block"]), spread=int(r["spread"]), crowd=int(r["crowd"]), lookup=lookup)
    if name == "fit":
        return dict(fit_rows=int(f["fit_rows"]), seed=str(f["seed"]), fit_u_max_pairs=float(f["fit_u_max_pairs"]),
                    u_max_pairs=float(f["u_max_pairs"]), settings=json.dumps(f), refit=refit)
    if name == "score":
        return dict(keys=list(s["keys"]), rules=list(s["rules"]), keep_from=-math.inf if lookup else float(s["keep_from"]),
                    search_floor=float(s["search_floor"]), oversized=int(s["oversized"]))
    if name == "decide":
        return dict(blank=BLANK)
    if name == "report":
        lo, line = float(c["lookup"]["at_least"]), float(c["lookup"]["likely_from"])
        return dict(patterns=json.dumps({**c["report"]["patterns"], "company_name": legal_pattern(r)}, ensure_ascii=False),
                    edges=sorted({-20.0, -10.0, 0.0, lo, line, line + 2, line + 4, line + 8, line + 12}), floor=lo, oversized=int(s["oversized"]))
    return {}


def fit(engine, refit: bool = True) -> None:
    """Stage 2 on `engine`, after records: fit.sql, with config.toml [fit]. O(n + S·K) on the sample, O(N + S·K) on the
    file. refit False (an update): the build's model kept, its u measured again on the run's records."""
    stage(engine, "functions")
    stage(engine, "fit", **values("fit", refit=refit))


def score(engine, lookup: bool = False) -> None:
    """Stage 3 on `engine`, after fit: score.sql, with config.toml [score]. O(Δ·b + C·K·L²) + O(N·L) for the keys.
    `lookup`: every candidate scored, whatever its points (lookup)."""
    stage(engine, "functions")
    stage(engine, "score", **values("score", lookup=lookup))


def lookup(engine, record: str | None = None, values: dict | None = None, at_least: float | None = None, most: int | None = None) -> dict:
    """The entities a record would be compared with, as an update of it alone compares it, best first: `record`, a
    stored record's ID, looked up as if it were new (itself left out), or `values` by the input's column names. Each
    entity at `at_least` points or more ([lookup] at_least: the review floor), or joined by a rule, with its best
    record, its points, each comparison's level, the rule that would join it and the keys that listed it; at most
    `most`. With none, the closest record. Also the record as compared, and each key looked up. Writes nothing: the
    run is rolled back after. O(N·G) for the run's keys + O(G·b + C·K·L²)."""
    c = config()
    at_least = float(c["lookup"]["at_least"] if at_least is None else at_least)
    most = int(c["lookup"]["most"] if most is None else most)
    if (record is None) == (values is None):
        raise InputError("give one of: a stored record's ID, or a record's values", fix="for example --record 1234")
    if values is not None and (unknown := sorted(set(values) - set(c["input"]["columns"]))):
        raise InputError(f"{', '.join(unknown)}: no field reads that column", fix=f"the columns a field reads: {', '.join(c['input']['columns'])}")
    me = record if record is not None else QUERY
    engine.run("BEGIN TRANSACTION")
    try:
        if record is not None:
            if not engine.value("SELECT COUNT(*) FROM records WHERE id = @me", {"me": me}):
                raise InputError(f"{record}: no record of the run has that ID", fix="give a record ID the run holds, or the record's values")
            engine.run("CREATE OR REPLACE TABLE this_batch AS SELECT MAX(batch) + 1 AS batch FROM records")
            engine.run("UPDATE records SET batch = (SELECT batch FROM this_batch) WHERE id = @me", {"me": me})
        else:
            engine.put("input", pd.DataFrame({x: [values.get(x)] for x in c["input"]["columns"]} | {c["input"]["id"]: [QUERY]}, dtype="string"))
            records(engine, None, lookup=True)
            if not engine.value(f"SELECT COUNT(*) FROM records WHERE id = @me AND COALESCE({', '.join(SHOWN)}) IS NOT NULL", {"me": me}):
                given = [f"{k}={v}" for k, v in values.items() if v not in (None, "")]
                raise InputError(f"{', '.join(given)}: read as missing, as a file's would be" if given else "no value given",
                                 fix="give a value a record holds: a name, a phone, a postal code")
        score(engine, lookup=True)
        stage(engine, "lookup", at_least=at_least, likely_from=float(c["lookup"]["likely_from"]), oversized=int(c["score"]["oversized"]),
              stored=record is not None)
        view = engine.frame(f"SELECT {', '.join(SHOWN)}{'' if record is not None else ', kind'} FROM records WHERE id = @me", {"me": me}).iloc[0]
        cands = engine.frame("SELECT * FROM candidates ORDER BY points DESC, id")
        found = engine.frame("SELECT * FROM entities ORDER BY rule IS NULL, ROUND(points, 2) DESC, points DESC, id")
        checked = engine.frame("SELECT * FROM checked ORDER BY position")
    finally:
        engine.run("ROLLBACK")
    text = lambda v: None if pd.isna(v) else str(v)
    shown = lambda x: {f: text(x[f]) for f in SHOWN}
    compared = lambda x: {k: x[f"level_{k}"] for k in ("name", "company", "address", "phone", "cif", "birth")}
    entities = [dict(entity=x["entity"], record=x["id"], points=round(float(x["points"]), 2), likely=bool(x["likely"]), rule=text(x["rule"]),
                     keys=sorted(x["sources"].split("+")) if text(x["sources"]) else [], compared=compared(x), records=int(x["records"]), shown=shown(x))
                for _, x in found.iterrows()]
    near = cands.iloc[0] if len(cands) and not entities else None
    return dict(record={"id": None if record is None else record, **{k: text(view[k]) for k in view.index}}, entities=entities[:most],
                found=len(entities), at_least=at_least, candidates=len(cands), likely=sum(e["likely"] for e in entities),
                closest=None if near is None else dict(record=near["id"], entity=near["entity"], points=round(float(near["points"]), 2), shown=shown(near)),
                checked=[dict(key=x["key"], found=int(x["found"]),
                              **({"why": "the record has no value for it"} if x["lacks"] else {}),
                              **({"why": f"its value is on {int(x['untrusted']):,} records: the rule doesn't trust it"} if not pd.isna(x["untrusted"]) else {}),
                              **({"big": [dict(records=int(b["records"]), sampled=int(b["sampled"]), best=None if b["best"] is None else round(float(b["best"]), 2),
                                               decision=b["decision"]) for b in x["big"]]} if isinstance(x["big"], (list, np.ndarray)) and len(x["big"]) else {}))
                         for _, x in checked.iterrows()])


def build(engine, files: list) -> None:
    """A run's first batch on `engine`, an empty run: its records, the model fitted, every pair scored, the entities
    people's decisions make (none yet, or those the run kept). O(N·L + n + S·K + ΣP + C·K·L²)."""
    records(engine, files)
    fit(engine)
    score(engine)
    decide(engine, [])


def update(engine, files: list) -> None:
    """A batch added to the run on `engine`: its records (one already in the run set aside), the build's model with u
    measured again on every record, the pairs touching the batch scored, the entities made again.
    O(Δ·(L + b) + C_Δ·K·L²), plus O(N) scans of the run's records and keys."""
    records(engine, files)
    fit(engine, refit=False)
    score(engine)
    decide(engine, [])


def decide(engine, files: list) -> None:
    """The decide job on `engine`, after score: people's decisions (Parquet files: a match table filled in, or any with
    id_l, id_r and decision; why kept where given) as the table given, then decide.sql. With no files (a build's last
    step), the entities from the decisions the run holds. O(D + N)."""
    if files:
        engine.read_parquet("given", files, ["why"])
        if lack := sorted({"id_l", "id_r", "decision"} - {n.casefold() for n, _ in engine.columns("given")}):
            raise InputError(f"the decisions lack the columns {lack}", fix="give back a match table with decision filled in, or a file with id_l, id_r and decision")
    else:
        engine.run("CREATE OR REPLACE TABLE given (id_l STRING, id_r STRING, decision STRING, why STRING)")
    stage(engine, "functions")
    stage(engine, "decide", **values("decide"))


def match(engine, threshold: float) -> None:
    """The match job on `engine`, after decide: match.sql at `threshold` points. A threshold below [score] keep_from is
    refused: the run keeps no pair below it. O(C + P·F)."""
    floor = float(config()["score"]["keep_from"])
    if threshold < floor:
        raise InputError(f"threshold {threshold:g}: the run keeps the pairs from {floor:g} points up only",
                         fix=f"give a threshold of {floor:g} or more, or lower [score] keep_from in config.toml and build the run again")
    stage(engine, "functions")
    stage(engine, "match", threshold=float(threshold))


FIELDS = ("full_name", "person_name", "given_name", "company_name", "any_name", "address", "address_code", "postal_code", "prefecture",
          "town_code", "city", "phone", "customer_id", "birth_date")  # a record's fields, as report.txt lists them


def report(engine, steps: dict[str, float], job: str) -> str:
    """report.txt, after a build or an update on `engine`: report.sql, then report_text."""
    stage(engine, "report", **values("report"))
    return report_text(engine, steps, job)


def report_text(engine, steps: dict[str, float], job: str) -> str:
    """report.txt from report.sql's tables (`steps`: each stage's seconds): the run on a page with no record's value in
    it: what ran, the summary, each field's fill and look, the input's columns no field reads (here, from the input
    table's own columns), the batch's candidates by bits and each band's commonest patterns, the entities' sizes, each
    stage, each key's pairs, the model and the largest blocks. O(F + C) over the report's tables."""
    c, v = config(), values("report")
    lo, edges, patterns = v["floor"], v["edges"], json.loads(v["patterns"])
    n = engine.frame("SELECT * FROM report_counts").iloc[0]
    pct = lambda x: "—" if x is None or pd.isna(x) else f"{x:.1%}"

    def table(df: pd.DataFrame) -> list[str]:  # numbers right-aligned, text left, so the page stays narrow
        if not len(df):
            return ["  none"]
        rows = [list(map(str, df.columns)), *([str(v) for v in r] for r in df.itertuples(index=False))]
        width = [max(len(r[i]) for r in rows) for i in range(len(df.columns))]
        number = [all(re.fullmatch(r"[-+]?[\d,.]+(%|e[-+]\d+)?|—", r[i]) for r in rows[1:]) for i in range(len(df.columns))]
        return ["  " + "  ".join(v.rjust(w) if k else v.ljust(w) for v, w, k in zip(r, width, number)).rstrip() for r in rows]

    added = None if job == "build" else int(n["added"])
    threads, memory = engine.rows("SELECT current_setting('threads'), current_setting('memory_limit')")[0] if engine.name == "duckdb" else ("—", "—")
    out = [f"RUN REPORT · {datetime.now():%Y-%m-%d %H:%M} · {'full run' if added is None else f'increment of {added:,} new records'} · no record's value in it",
           f"code {code_version()} · method {fingerprint()[:12]}",
           f"python {platform.python_version()} · duckdb {duckdb.__version__} · {platform.system()} {platform.machine()}",
           f"{threads} threads · memory limit {memory} · took {sum(steps.values()):,.1f} s", ""]

    ph = engine.rows("SELECT p.field, COUNT(*) FROM placeholders AS p GROUP BY p.field ORDER BY p.field")
    empty = {f: int(n["records"] - n[f]) for f, _ in ph if f in n}
    fill = {f: n[f] / max(n["records"], 1) for f in FIELDS}
    summary = [("records", f"{int(n['records']):,}" + (f", {added:,} of them new" if added is not None else "") + (f"; {int(n['set_aside']):,} set aside (set_aside)" if n["set_aside"] else "")),
               ("candidates", f"{int(n['scored']):,} pairs scored{' in this batch' if added is not None else ''}, {int(n['ruled']):,} of them a rule's too: "
                              "scored, which a match run reads at its threshold (python -m nayose match)"),
               ("entities", f"{int(n['entities']):,}; {int(n['by_people']):,} records joined by people's decisions; the largest holds {int(n['largest']):,} record{'s' * bool(n['largest'] != 1)}"),
               ("kinds", f"{int(n['companies']):,} × 2 company · {int(n['persons']):,} × 1 person · {int(n['unsure']):,} × 0 not sure (records)"),
               ("kinds", f"{int(n['company_customers']):,} × 2 company · {int(n['person_customers']):,} × 1 person · {int(n['unsure_customers']):,} × 0 not sure (customers)"),
               *([("flagged", f"{int(n['flagged']):,} records the engine is sure of against the flag: matched as the engine says (gold: kind_flagged)")] if n["flagged"] else []),
               ("kinds from", "the file's flag, as it is (trust_flag)" if c["records"]["trust_flag"] else f"a written legal form, or a name {c['records']['name_line']:.0%} sure; else the flag"),
               *(("note", f"{f}: {k:,} value{'s' * bool(k != 1)} held by {c['records']['min_block']}+ records read as missing, a placeholder and not "
                          f"{'one entity' if f == 'customer_id' else 'evidence'}'s ({empty[f]:,} records without one)") for f, k in ph if f in empty),
               *(("note", f"{f} only {x:.1%} filled: check its mapping") for f, x in fill.items() if x < 0.05)]
    out += ["SUMMARY", *(f"  {what:<12} {value}" for what, value in summary), ""]

    shape = engine.frame("SELECT * FROM report_fields").set_index("field")
    out += ["FIELDS  (looks right, top value, no letters, length: on a sample of 10,000 records)", *table(pd.DataFrame([dict(
        field=f, filled=pct(fill[f]), looks_right=pct(shape.at[f, "looks_right"]), top_value=pct(shape.at[f, "top_value"]),
        no_letters=pct(shape.at[f, "no_letters"]), length="" if pd.isna(shape.at[f, "length"]) else f"{shape.at[f, 'length']:.0f}",
        longest="" if pd.isna(shape.at[f, "longest"]) else f"{int(shape.at[f, 'longest']):,}") for f in FIELDS])), ""]
    if engine.name == "duckdb" and (cols := unmapped(engine, c, patterns)) is not None and len(cols):
        shown = cols.head(30)
        out += ["COLUMNS NOT MAPPED  (no field reads them; filled, distinct and the field their values look most like: on the first 10,000 records)",
                *table(pd.DataFrame(dict(column=shown["column"], filled=shown["filled"].map(pct), distinct=shown["distinct"].map(pct),
                                         looks_like=shown["looks_like"], share=[pct(x) if f else "" for f, x in zip(shown["looks_like"], shown["share"])]))),
                *([f"  and {len(cols) - len(shown):,} more"] if len(cols) > len(shown) else []), ""]

    scored = dict(engine.rows("SELECT band, pairs FROM report_scores"))
    label = lambda i: "below 0" if i == -1 else f"below {edges[0]:g}" if i == 0 else f"{edges[-1]:g} and up" if i == len(edges) else f"{edges[i - 1]:g} to {edges[i]:g}"
    if scored.get(-1):  # pairs the bound put below the floor, never weighed: one row below 0, with those weighed below it
        scored[-1] += sum(scored.pop(i) for i in [i for i in scored if 0 <= i < len(edges) and edges[i] <= 0])
    out += ["SCORES  (the candidates scored, by bits)", *table(pd.DataFrame([dict(bits=label(i), candidates=f"{scored[i]:,}") for i in sorted(scored) if scored[i]])), ""]

    named = {(x, g): lab for x, g, lab in engine.rows("SELECT comparison, gamma, label FROM model")}
    comps = ("name", "company", "address", "phone", "cif", "birth")
    got = engine.frame("SELECT * FROM report_patterns ORDER BY up DESC, k")
    band = lambda up: f"{lo:g} and up" if up else f"0 to {lo:g}"
    out += ["PATTERNS BY SCORE  (the keys' pairs at 0 bits and up, below and from the review floor: each band's 12 most common levels)",
            *table(pd.DataFrame([dict(band=band(x["up"]), pairs=f"{int(x['n']):,}", bits=f"{x['w']:.1f}",
                                      **{k: "missing" if pd.isna(x[f"gamma_{k}"]) or x[f"gamma_{k}"] < 0 else named[k, int(x[f"gamma_{k}"])] for k in comps})
                                 for _, x in got.iterrows()])),
            *(f"  {band(up)}: {int(g['kinds'].iloc[0]) - 12:,} patterns more, {int(g['total'].iloc[0]) - int(g['n'].sum()):,} pairs"
              for up, g in got.groupby("up", sort=False) if g["kinds"].iloc[0] > 12), ""]

    sizes = dict(engine.rows("SELECT size, entities FROM report_clusters"))
    bins = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5–9", 5, 9), ("10–49", 10, 49), ("50+", 50, math.inf)]
    out += ["CLUSTERS  (size: how many)", "  " + " · ".join(f"{name}: {total:,}" for name, a, b in bins if (total := sum(v for k, v in sizes.items() if a <= k <= b))), ""]

    fitted = json.loads(engine.value("SELECT notes FROM fit"))
    facts = dict(records=f"records {int(n['added']):,} · set_aside {int(n['set_aside']):,} · companies {int(n['companies']):,} · persons {int(n['persons']):,} · not sure {int(n['unsure']):,}",
                 fit=f"fit_rows {fitted['fit_rows']:,}" + (" · the build's model" if job != "build" else "") + f" · sampled_again {len(fitted.get('sampled_again', [])):,}",
                 score=f"candidates {int(n['candidates']):,} · stored {int(n['scored']):,} · rule pairs {int(n['ruled']):,} · oversized_kept {int(n['oversized_kept']):,} · "
                       f"oversized_skipped {int(n['oversized_skipped']):,} · unscored {int(n['unscored']):,}",
                 decide=f"decided {int(n['decided']):,} · entities {int(n['entities']):,}")
    out += ["STEPS", *table(pd.DataFrame([dict(step=s, seconds=f"{x:.2f}", facts=facts.get(s, "")) for s, x in steps.items()])), ""]

    keys = engine.frame("SELECT * FROM report_keys ORDER BY pairs DESC, g")
    out += ["KEYS  (pairs each lists, most first)", *table(pd.DataFrame(dict(key=keys["name"], pairs=keys["pairs"].map(lambda x: f"{int(x):,}")))), ""]

    f = engine.frame("SELECT * FROM fit").iloc[0]
    levels = engine.frame("SELECT comparison, label, file_m, file_u, bits FROM model ORDER BY position, gamma DESC")
    prior = json.loads(f["fitted"])["prior_bits"]
    out += [f"MODEL  (prior {prior:.2f} bits at {int(f['records']):,} records; fitted on {int(f['fit_rows']):,} records"
            + (f"; learned nothing about {', '.join(fitted['skipped'])}" if fitted.get("skipped") else "") + ")",
            *(["  EM learned from: " + " · ".join(f"{k} {v:,} pairs" for k, v in fitted["em_pairs"].items())] if fitted.get("em_pairs") else []),
            *table(pd.DataFrame(dict(comparison=levels["comparison"], level=levels["label"], m=levels["file_m"].map(lambda x: f"{x:.4f}" if x >= 1e-3 else f"{x:.2e}"),
                                     u=levels["file_u"].map(lambda x: f"{x:.2e}"), bits=levels["bits"].map(lambda x: f"{x:.2f}")))),
            *(f"  {k} {lv}: {why} (EM said {was:+.2f} bits)" for k, lv, why, was in fitted.get("file_adjusted", [])), ""]

    shown = keys.assign(per_record=keys["pairs"] / max(int(n["records"]), 1))
    shown = shown[(shown["oversized"] > 0) | shown["name"].isin(shown.nlargest(6, "per_record")["name"])].sort_values("per_record", ascending=False, kind="stable")
    out += [f"BLOCKS  ({int(keys['pairs'].sum()):,} pairs the keys list, before dedupe)", *table(pd.DataFrame(dict(
        kind="generator", name=shown["name"], per_record=shown["per_record"].map(lambda x: f"{x:.2f}"),
        largest=shown["largest"].map(lambda x: f"{int(x):,}"), oversized=shown["oversized"].map(lambda x: f"{int(x):,}"))))]
    return "\n".join(out) + "\n"


def unmapped(engine, c: dict, patterns: dict[str, str]) -> pd.DataFrame | None:
    """The input's columns no field reads (config.toml [input] columns), on its first 10,000 rows: the share filled, the
    share of filled values held once, and the field whose look ([report] patterns) its values have most, with that
    share; best fit first. DuckDB's: the file's own columns, read by their names. O(sample · columns · fields)."""
    read = {x.casefold() for x in c["input"]["columns"]}
    cols = [x for x, _ in engine.columns("input") if x.casefold() not in read]
    if not cols:
        return None
    quote = lambda x: '"' + x.replace('"', '""') + '"'
    con = engine.con
    con.execute("CREATE OR REPLACE TEMP TABLE nayose_sample AS SELECT " + ", ".join(f"CAST({quote(x)} AS VARCHAR) AS {quote(x)}" for x in cols) + " FROM input LIMIT 10000")
    n = max(1, con.execute("SELECT COUNT(*) FROM nayose_sample").fetchall()[0][0])
    long = "SELECT * FROM (UNPIVOT nayose_sample ON COLUMNS(*) INTO NAME c VALUE v) WHERE trim(v, ?) <> ''"
    shape = {x: (k / n, d / max(1, k)) for x, k, d in con.execute(f"SELECT c, COUNT(*), COUNT(DISTINCT v) FROM ({long}) GROUP BY c", [BLANK]).fetchall()}
    fits = {x: {} for x in cols}
    for field, pattern in patterns.items():
        for x, share in con.execute(f"SELECT c, AVG(regexp_matches(v, ?)::INT) FROM ({long}) GROUP BY c", [pattern, BLANK]).fetchall():
            fits[x][field] = share
    best = {x: max(fits[x].items(), key=lambda kv: kv[1], default=("", 0.0)) for x in cols}
    return pd.DataFrame([dict(column=x, filled=shape.get(x, (0.0, 0.0))[0], distinct=shape.get(x, (0.0, 0.0))[1],
                              looks_like=best[x][0] if best[x][1] > 0 else "", share=best[x][1]) for x in cols]
                        ).sort_values(["share", "filled"], ascending=False, kind="stable", ignore_index=True)


def code_version() -> str:  # the commit the code is at, and + when this copy's tracked files differ from it
    try:
        head = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10).stdout.strip()
        return (head or "unknown") + ("+" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def statements(text: str) -> list[str]:
    """The statements of a stage file, in order: each ends with a line ending in ';' (outside a comment). The
    comments stay with the statement they precede."""
    out, lines = [], []
    for line in text.splitlines():
        lines.append(line)
        if line.split("--")[0].rstrip().endswith(";"):
            out.append("\n".join(lines).rstrip().rstrip(";"))
            lines = []
    if rest := [line for line in lines if line.strip() and not line.strip().startswith("--")]:
        raise ValueError(f"a statement without its closing ';': {' '.join(rest).strip()[:120]}")
    return out


def stage(engine, name: str, **values: object) -> None:
    """The stage nayose/sql/<name>.sql on `engine`, its statements in order (run_file)."""
    run_file(engine, SQL / f"{name}.sql", **values)


def run_file(engine, path: Path, **values: object) -> None:
    """The SQL file at `path` on `engine`, its statements in order. Each is given the values it names as @name, and only
    those: BigQuery refuses a parameter a statement doesn't read."""
    for sql in statements(path.read_text(encoding="utf-8")):
        named = set(re.findall(r"@(\w+)", re.sub(r"--[^\n]*|'(?:[^'\\]|\\.)*'", "", sql)))
        if missing := named - set(values):
            raise ValueError(f"{path.name} names @{', @'.join(sorted(missing))}, which no value gives")
        engine.run(sql, {k: values[k] for k in named})


def fingerprint(root: Path = HERE) -> str:
    """What an increment needs to be what the full run was: a hash of every stage file, the values (config.toml) and
    the input's mapping (mapping.sql), by name and content. A change to any refuses increments until a full run."""
    h = hashlib.sha256()
    for f in sorted([*(root / "sql").glob("*.sql"), *(p for p in (root / "config.toml", root / "mapping.sql") if p.exists())]):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()
