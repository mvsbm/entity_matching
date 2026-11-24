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
    fingerprint()                   what an increment needs unchanged since the full run: the SQL, the values, the mapping
                                    and the name model
"""
import hashlib
import json
import math
import os
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
METHOD = "CREATE OR REPLACE TABLE method AS SELECT @fingerprint AS fingerprint"  # a build's: the SQL, the values and the mapping it ran
CHANGED = "the method, its values or the mapping changed since the run was built: a batch or a lookup would be scored otherwise"
UNCHANGED = f"SELECT IF((SELECT fingerprint FROM method) <> @fingerprint, ERROR('{CHANGED}; build the run again'), 0)"  # an update's first, on BigQuery
QUERY = "\uffffasked"  # the ID of a record looked up by its values: no record's, and after every one in order
SHOWN = ("full_name", "person_name", "company_name", "address", "postal_code", "phone", "birth_date", "customer_id")  # a record, as a person reads it
BLANK = "".join(ch for ch in map(chr, range(0x3001)) if ch.isspace())  # what a blank value people give is made of: Python's whitespace
COMPARISONS = ("name", "company", "address", "phone", "cif", "birth")  # the model's, in its order
FIELDS = ("full_name", "person_name", "given_name", "company_name", "any_name", "address", "address_code", "postal_code", "prefecture",
          "town_code", "city", "phone", "customer_id", "birth_date")  # a record's fields, as report.txt lists them

# a statement, read from its text (run_file, scratched, the deploy's procedures)
PARAMETER = re.compile(r"@(\w+)")  # a value a statement reads, by name (run_file gives it, the deploy declares it)
NOT_CODE = re.compile(r"--[^\n]*|'(?:[^'\\]|\\.)*'")  # a comment or a string: what isn't code
WHEN = re.compile(r"^\s*--\s*when:(.*)$", re.M | re.I)
LEAD = r"(?:\s*--[^\n]*\n|\s*/\*.*?\*/)*\s*"  # a statement's leading comments
WRITE = re.compile(rf"^({LEAD})(CREATE\s+OR\s+REPLACE\s+TEMP(?:ORARY)?\s+TABLE|CREATE\s+OR\s+REPLACE\s+TABLE|"
                   r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS|CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW|CREATE\s+TABLE|"
                   r"INSERT(?:\s+INTO)?|DELETE(?:\s+FROM)?|UPDATE|MERGE(?:\s+INTO)?|TRUNCATE\s+TABLE)\s+`?(\w+)`?", re.I | re.S)
READ = re.compile(rf"^{LEAD}(SELECT|WITH|CREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+(?:FUNCTION|TABLE))\b", re.I | re.S)
TEMP_FUNCTION = re.compile(rf"^({LEAD})CREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+FUNCTION\s+(\w+)", re.I | re.S)  # (its comments, its name)


class InputError(ValueError):  # a refusal the person running the job can act on: what is wrong, and how to fix it
    def __init__(self, message: str, fix: str = "") -> None:
        super().__init__(message)
        self.fix = fix


def config() -> dict:  # config.toml, or the file NAYOSE_CONFIG names (a variant at design time)
    return tomllib.loads(Path(os.environ.get("NAYOSE_CONFIG") or HERE / "config.toml").read_text(encoding="utf-8"))


def mapping() -> Path:  # mapping.sql, or the file NAYOSE_MAPPING names (another file's columns)
    return Path(os.environ.get("NAYOSE_MAPPING") or HERE / "mapping.sql")


def legal_pattern(c: dict) -> str:
    """A legal form anywhere (also with its small kana written large), or a bank abbreviation where it may stand: first,
    カ)〇〇, or last, 〇〇(カ. Longest first, so 医療法人社団 isn't cut to 医療法人. On NFKC text."""
    forms = sorted({f for x in c["legal_forms"] for f in (x, x.translate(SMALL_KANA))}, key=lambda f: (-len(f), f))  # one order, every run
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


def records(engine, files: list | None, lookup: bool = False, scratch: set | None = None) -> None:
    """Stage 1 on `engine`: the input files as the table input (every column mapping.sql reads that a file lacks,
    missing; None: the table input as it is), the name model's weights as name_weights; then mapping.sql, then
    records.sql. O(Δ·L) + O(N) for the placeholders. `lookup`: the input is records asked about (lookup), in
    `scratch`'s temporary tables (run_file), the run's name model as it is."""
    c = config()
    if bad := [x for x in c["input"]["columns"] if not NAME.match(x)]:
        raise ValueError(f"config.toml [input] columns: {bad} are no plain column names")
    if files is not None:
        engine.read_parquet("input", files, c["input"]["columns"])
    if scratch is None:
        engine.put("name_weights", name_weights())
    stage(engine, "functions", scratch=scratch)
    run_file(engine, mapping(), scratch=scratch, **values_of("mapping"))
    stage(engine, "records", scratch=scratch, **values_of("records", lookup=lookup))
    if files is not None and engine.name == "duckdb":  # a temporary table, held whole: kept to what the report reads
        engine.run("CREATE OR REPLACE TEMP TABLE input AS SELECT * FROM input LIMIT 10000")  # (unmapped's sample)


def name_weights() -> pd.DataFrame:  # the name model (config/kind_names.npz): each character n-gram's weight
    model = np.load(NAME_MODEL)
    return pd.DataFrame({"term": model["terms"].tolist(), "w": model["coef"]})


def values_of(name: str, refit: bool = True, lookup: bool = False) -> dict:
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
                    search_floor=float(s["search_floor"]), oversized=int(s["oversized"]), lookup=lookup, outside=0)
    if name == "decide":
        return dict(blank=BLANK)
    if name == "report":
        lo, line = float(c["lookup"]["at_least"]), float(c["lookup"]["likely_from"])
        return dict(patterns=json.dumps({**c["report"]["patterns"], "company_name": legal_pattern(r)}, ensure_ascii=False),
                    edges=sorted({-20.0, -10.0, 0.0, lo, line, line + 2, line + 4, line + 8, line + 12}), floor=lo, oversized=int(s["oversized"]))
    return {}


def fit(engine, refit: bool = True) -> None:
    """Stage 2 on `engine`, after records: fit.sql, with config.toml [fit]. O(n + S·K) on the sample of n records, S
    sampled pairs and K comparisons; O(N + S·K) on the
    file. refit False (an update): the build's model kept, its u measured again on the run's records."""
    stage(engine, "functions")
    stage(engine, "fit", **values_of("fit", refit=refit))


def score(engine, lookup: bool = False, scratch: set | None = None, until: str | None = None, outside: int = 0) -> None:
    """Stage 3 on `engine`, after fit: score.sql, with config.toml [score]. O(Δ·b + C·K·L²) + O(N·L) for the keys.
    `lookup`: every candidate scored, whatever its points (lookup), in `scratch`'s temporary tables, up to the table
    `until` makes; `outside`: the run's records its records table doesn't hold (a lookup's holds its blocks' alone)."""
    stage(engine, "functions", scratch=scratch)
    stage(engine, "score", scratch=scratch, until=until, **(values_of("score", lookup=lookup) | {"outside": outside}))


def lookup(engine, record: str | None = None, values: dict | None = None, at_least: float | None = None, most: int | None = None) -> dict:
    """The entities a record would be compared with, as an update of it alone compares it, best first: `record`, a
    stored record's ID, looked up as if it were new (itself left out), or `values` by the input's column names. Each
    entity at `at_least` points or more ([lookup] at_least: the review floor), or joined by a rule, with its best
    record, its points, each comparison's level, the rule that would join it and the keys that listed it; at most
    `most`. With none, the closest record. Also the record as compared, and each key looked up. Writes nothing, and
    reads what it touches: the record's keys made from it alone, the run's key index (every_key, rule_keys) read by
    them, then the record scored against those keys' records alone, all in temporary tables that end with each step
    (engine.scratch). O(G) for its keys + O(G·b + C·K·L²)."""
    c = config()
    at_least = float(c["lookup"]["at_least"] if at_least is None else at_least)
    most = int(c["lookup"]["most"] if most is None else most)
    if (record is None) == (values is None):
        raise InputError("give one of: a stored record's ID, or a record's values", fix="for example --record 1234")
    if values is not None and (unknown := sorted(set(values) - set(c["input"]["columns"]))):
        raise InputError(f"{', '.join(unknown)}: no field reads that column", fix=f"the columns a field reads: {', '.join(c['input']['columns'])}")
    me = record if record is not None else QUERY
    unchanged(engine, "build the run again with them, or look up with the code the build ran")  # its index and scores are the method's
    if record is not None and not engine.value("SELECT COUNT(*) FROM records WHERE id = @me", {"me": me}):
        raise InputError(f"{record}: no record of the run has that ID", fix="give a record ID the run holds, or the record's values")
    held = engine.value("SELECT COUNT(*) FROM records")
    keys = its_keys(engine, record, values, me)
    ids, blocks = index_records(engine, keys, record, me, int(c["score"]["oversized"]))
    view, cands, found, checked = scored_against(engine, record, values, me, ids, blocks, held, at_least)
    return answer(record, view, cands, found, checked, at_least, most)


def its_keys(engine, record: str | None, values: dict | None, me: str) -> dict[str, set]:
    """A lookup's step 1: the keys of the record asked about, made from it alone (every_key's and rule_keys')."""
    with engine.scratch():
        asked(engine, record, values, [me] if record is not None else [], until="every_key")
        return {"every_key": set(engine.rows("SELECT g, k FROM every_key WHERE id = @me", {"me": me})),
                "rule_keys": set(engine.rows("SELECT i, k FROM rule_keys WHERE id = @me", {"me": me}))}


def index_records(engine, keys: dict[str, set], record: str | None, me: str, big: int) -> tuple[set, dict]:
    """A lookup's step 2: the run's index read by those keys. Every record of each rule key, and of each block, but of
    an oversized one (`big` records or more) its first records by hash alone: the gate's sample (score.sql), and one
    more, so the record asked about may rank anywhere. The IDs, and each block's (g, k): [its size, the IDs read]."""
    ids = {me} if record is not None else set()
    if keys["rule_keys"]:
        rows = engine.rows("SELECT i, k, id FROM rule_keys WHERE k IN UNNEST(@ks)", {"ks": sorted({k for _, k in keys["rule_keys"]})})
        ids |= {i for g, k, i in rows if (g, k) in keys["rule_keys"]}
    blocks = {}
    if keys["every_key"]:
        rows = engine.rows("SELECT g, k, id, COUNT(*) OVER (PARTITION BY g, k) AS n FROM every_key WHERE k IN UNNEST(@ks) "
                           "QUALIFY COUNT(*) OVER (PARTITION BY g, k) < @big OR ROW_NUMBER() OVER (PARTITION BY g, k ORDER BY er_hash(id)) <= @big + 1",
                           {"ks": sorted({k for _, k in keys["every_key"]}), "big": big})
        for g, k, i, n in rows:
            if (g, k) in keys["every_key"]:
                blocks.setdefault((g, k), [n, set()])[1].add(i)
    return ids | {i for _, read in blocks.values() for i in read}, blocks


def scored_against(engine, record: str | None, values: dict | None, me: str, ids: set, blocks: dict, held: int, at_least: float) -> tuple:
    """A lookup's step 3: the record scored against those records alone, a block read in part at its size whole. A big
    block the gate keeps makes every pair of it a candidate, so it is read whole, from the run's index (outside the
    scratch, whose every_key is the lookup's own), and scored again. The record as compared and lookup.sql's tables."""
    c = config()
    big = int(c["score"]["oversized"])
    while True:
        with engine.scratch():
            typed = 0 if record is not None else 1  # a typed record isn't in the index: its blocks hold one more
            sized = [(g, k, n + typed) for (g, k), (n, read) in blocks.items() if n > len(read)]
            temp = asked(engine, record, values, sorted(ids), outside=held - len(ids), sized=sized)
            kept = {(g, k) for g, k in engine.rows("SELECT g, value FROM gated WHERE decision = 'kept'")} & {(g, k) for g, k, _ in sized}
            if not kept:
                stage(engine, "lookup", scratch=temp, at_least=at_least, likely_from=float(c["lookup"]["likely_from"]),
                      oversized=big, stored=record is not None)
                return (engine.frame(f"SELECT {', '.join(SHOWN)}{'' if record is not None else ', kind'} FROM records WHERE id = @me", {"me": me}).iloc[0],
                        engine.frame("SELECT * FROM candidates ORDER BY points DESC, id"),
                        engine.frame("SELECT * FROM entities ORDER BY rule IS NULL, ROUND(points, 2) DESC, points DESC, id"),
                        engine.frame("SELECT * FROM checked ORDER BY position"))
        for g, k, i in engine.rows("SELECT g, k, id FROM every_key WHERE k IN UNNEST(@ks)", {"ks": sorted({k for _, k in kept})}):
            if (g, k) in kept:
                blocks[g, k][1].add(i)
                ids.add(i)


def answer(record: str | None, view, cands: pd.DataFrame, found: pd.DataFrame, checked: pd.DataFrame, at_least: float, most: int) -> dict:
    """What a lookup gives back (docs/data.md, "A lookup's answer"), from lookup.sql's tables."""
    text = lambda v: None if pd.isna(v) else str(v)
    shown = lambda x: {f: text(x[f]) for f in SHOWN}
    entities = [dict(entity=x["entity"], record=x["id"], points=round(float(x["points"]), 2), likely=bool(x["likely"]), rule=text(x["rule"]),
                     keys=sorted(x["sources"].split("+")) if text(x["sources"]) else [], compared={k: x[f"level_{k}"] for k in COMPARISONS},
                     records=int(x["records"]), shown=shown(x))
                for _, x in found.iterrows()]
    near = cands.iloc[0] if len(cands) and not entities else None
    keys = []
    for _, x in checked.iterrows():
        key = dict(key=x["key"], found=int(x["found"]))
        if x["lacks"]:
            key["why"] = "the record has no value for it"
        if not pd.isna(x["untrusted"]):
            key["why"] = f"its value is on {int(x['untrusted']):,} records: the rule doesn't trust it"
        if isinstance(x["big"], (list, np.ndarray)) and len(x["big"]):
            key["big"] = [dict(records=int(b["records"]), sampled=int(b["sampled"]), best=None if b["best"] is None else round(float(b["best"]), 2),
                               decision=b["decision"]) for b in x["big"]]
        keys.append(key)
    return dict(record={"id": record, **{k: text(view[k]) for k in view.index}}, entities=entities[:most],
                found=len(entities), at_least=at_least, candidates=len(cands), likely=sum(e["likely"] for e in entities),
                closest=None if near is None else dict(record=near["id"], entity=near["entity"], points=round(float(near["points"]), 2), shown=shown(near)),
                checked=keys)


def unchanged(engine, fix: str) -> None:
    """Refused (CHANGED, then `fix`) unless the run was built by this method: its SQL, values and mapping (fingerprint)."""
    try:
        made = engine.value("SELECT fingerprint FROM method")
    except duckdb.CatalogException:  # no method table: a run not made by this build, so by another method
        made = None
    if made != fingerprint():
        raise InputError(CHANGED, fix=fix)


def asked(engine, record: str | None, values: dict | None, ids: list, until: str | None = None, outside: int = 0, sized: list = ()) -> set:
    """The run as a lookup sees it, in temporary tables of the run's names (run_file's scratch): records and gold, of
    `ids` alone (each read by ID: on BigQuery, its clustering's blocks), placeholders whole; the record asked about,
    a batch of its own (a stored one's batch raised, or `values` made a record by records.sql); then score.sql, up to
    `until`, `outside` the run's records the temporary records don't hold, `sized` each block they hold in part, at its
    whole size (g, k, n). The temporary tables' names."""
    temp = {"block_size"}
    if sized:  # three arrays: a parameter is an array of values on both engines
        engine.run("CREATE OR REPLACE TEMP TABLE block_size AS SELECT g, @k[OFFSET(i)] AS k, @n[OFFSET(i)] AS n FROM UNNEST(@g) AS g WITH OFFSET AS i",
                   {"g": [g for g, _, _ in sized], "k": [k for _, k, _ in sized], "n": [n for _, _, n in sized]})
    else:
        engine.run("CREATE OR REPLACE TEMP TABLE block_size (g INT64, k STRING, n INT64)")
    for table, which in (("records", "WHERE id IN UNNEST(@ids)"), ("gold", "WHERE id IN UNNEST(@ids)"), ("placeholders", "")):
        engine.run(f"CREATE TEMP TABLE {table} AS SELECT * FROM {table} {which}", {"ids": ids} if which else None)
        temp.add(table)
    if record is not None:
        temp.add("this_batch")
        engine.run("CREATE TEMP TABLE this_batch AS SELECT MAX(batch) + 1 AS batch FROM records")
        engine.run("UPDATE records SET batch = (SELECT batch FROM this_batch) WHERE id = @me", {"me": record})
    else:
        columns = config()["input"]
        given = list(({x: values.get(x) for x in columns["columns"]} | {columns["id"]: QUERY}).items())
        temp.add("input")
        engine.run("CREATE OR REPLACE TEMP TABLE input AS SELECT " + ", ".join(f"CAST({'NULL' if v is None else f'@v{i}'} AS STRING) AS `{x}`"
                                                                     for i, (x, v) in enumerate(given)),
                   {f"v{i}": str(v) for i, (_, v) in enumerate(given) if v is not None})
        records(engine, None, lookup=True, scratch=temp)
        if not engine.value(f"SELECT COUNT(*) FROM records WHERE id = @me AND COALESCE({', '.join(SHOWN)}) IS NOT NULL", {"me": QUERY}):
            shown = [f"{k}={v}" for k, v in values.items() if v not in (None, "")]
            raise InputError(f"{', '.join(shown)}: read as missing, as a file's would be" if shown else "no value given",
                             fix="give a value a record holds: a name, a phone, a postal code")
    engine.run(scratched(making("fit", "compared"), temp))  # the columns score compares, of these records: fit.sql's view, as a temporary table
    score(engine, lookup=True, scratch=temp, until=until, outside=outside)
    return temp


def run_stage(name: str, do, *args) -> None:  # a stage of build or update, run as it is (the CLI's times each)
    do(*args)


def build(engine, files: list, model: str | None = None, timed=run_stage) -> None:
    """A run's first batch on `engine`, an empty run: its records, the model fitted (`model`: one fitted elsewhere, as
    fit gave it back, kept: its u measured on these records), every pair scored, the entities people's decisions make
    (none yet, or those the run kept). Each stage run by `timed` (name, the stage, its arguments). O(N·L + n + S·K +
    ΣP + C·K·L²): P a block's pairs, C the candidates, L a value's length."""
    timed("records", records, engine, files)
    if model is not None:
        engine.run("CREATE OR REPLACE TABLE fit AS SELECT CAST(NULL AS FLOAT64) AS probability, CAST(NULL AS INT64) AS fit_rows, "
                   "CAST(NULL AS INT64) AS records, CAST(NULL AS FLOAT64) AS prior_bits, CAST(NULL AS STRING) AS notes, @fitted AS fitted",
                   {"fitted": json.dumps({**json.loads(model), "basis": None})})
    timed("fit", fit, engine, model is None)
    timed("score", score, engine)
    timed("decide", decide, engine, [])
    engine.run(METHOD, {"fingerprint": fingerprint()})


def update(engine, files: list, timed=run_stage, out: object = "RUN") -> int:
    """A batch added to the run on `engine`: its records (one already in the run set aside), the build's model with u
    measured again on every record, the pairs touching the batch scored, the entities made again; each stage run by
    `timed`, as build's. The records added; none, and nothing past the records is done (the CLI keeps the run as it
    was). `out`: the run's folder, as a refusal names it. O(Δ·(L + b) + C_Δ·K·L²), plus O(N) scans of the run's
    records and keys."""
    unchanged(engine, f"build the run again with them (python -m nayose build FILE --out {out} --overwrite), or update with the code the build ran")
    before = engine.value("SELECT COUNT(*) FROM records")
    timed("records", records, engine, files)
    if not (added := engine.value("SELECT COUNT(*) FROM records") - before):
        return 0
    timed("fit", fit, engine, False)
    timed("score", score, engine)
    timed("decide", decide, engine, [])
    return added


def decide(engine, files: list) -> None:
    """The decide job on `engine`, after score: people's decisions (Parquet files: a match table filled in, or any with
    id_l, id_r and decision; why kept where given) as the table given, then decide.sql. With no files (a build's last
    step), the entities from the decisions the run holds. O(D + N)."""
    if files:
        engine.read_parquet("given", files, ["why"])
        if lack := sorted({"id_l", "id_r", "decision"} - {n.casefold() for n, _ in engine.columns("given")}):
            raise InputError(f"the decisions lack the columns {lack}", fix="give back a match table with decision filled in, or a file with id_l, id_r and decision")
    else:
        engine.run("CREATE OR REPLACE TEMP TABLE given (id_l STRING, id_r STRING, decision STRING, why STRING)")  # as a file's
    stage(engine, "functions")
    stage(engine, "decide", **values_of("decide"))


def check_threshold(threshold: float) -> None:  # refused below [score] keep_from: the run keeps no pair below it
    floor = float(config()["score"]["keep_from"])
    if threshold < floor:
        raise InputError(f"threshold {threshold:g}: the run keeps the pairs from {floor:g} points up only",
                         fix=f"give a threshold of {floor:g} or more, or lower [score] keep_from in config.toml and build the run again")


def match(engine, threshold: float) -> None:
    """The match job on `engine`, after decide: match.sql at `threshold` points. A threshold below [score] keep_from is
    refused: the run keeps no pair below it. O(C + P·F)."""
    check_threshold(threshold)
    stage(engine, "functions")
    stage(engine, "match", threshold=float(threshold))


def report(engine, steps: dict[str, float], job: str) -> str:
    """report.txt, after a build or an update on `engine`: report.sql, then report_text."""
    stage(engine, "report", **values_of("report"))
    return report_text(engine, steps, job)


def report_text(engine, steps: dict[str, float], job: str) -> str:
    """report.txt from report.sql's tables (`steps`: each stage's seconds): the run on a page with no record's value in
    it: what ran, the summary, each field's fill and look, the input's columns no field reads (here, from the input
    table's own columns), the batch's candidates by bits and each band's commonest patterns, the entities' sizes, each
    stage, each key's pairs, the model and the largest blocks. O(F + C) over the report's tables."""
    c, v = config(), values_of("report")
    lo, edges, patterns = v["floor"], v["edges"], json.loads(v["patterns"])
    counts = engine.frame("SELECT * FROM report_counts").iloc[0]
    pct = lambda x: "—" if x is None or pd.isna(x) else f"{x:.1%}"

    def table(df: pd.DataFrame) -> list[str]:  # numbers right-aligned, text left, so the page stays narrow
        if not len(df):
            return ["  none"]
        rows = [list(map(str, df.columns)), *([str(v) for v in r] for r in df.itertuples(index=False))]
        width = [max(len(r[i]) for r in rows) for i in range(len(df.columns))]
        number = [all(re.fullmatch(r"[-+]?[\d,.]+(%|e[-+]\d+)?|—", r[i]) for r in rows[1:]) for i in range(len(df.columns))]
        return ["  " + "  ".join(v.rjust(w) if k else v.ljust(w) for v, w, k in zip(r, width, number)).rstrip() for r in rows]

    added = None if job == "build" else int(counts["added"])
    threads, memory = engine.rows("SELECT current_setting('threads'), current_setting('memory_limit')")[0] if engine.name == "duckdb" else ("—", "—")
    out = [f"RUN REPORT · {datetime.now():%Y-%m-%d %H:%M} · {'full run' if added is None else f'increment of {added:,} new records'} · no record's value in it",
           f"code {code_version()} · method {fingerprint()[:12]}",
           f"python {platform.python_version()} · duckdb {duckdb.__version__} · {platform.system()} {platform.machine()}",
           f"{threads} threads · memory limit {memory} · took {sum(steps.values()):,.1f} s", ""]

    ph = engine.rows("SELECT p.field, COUNT(*) FROM placeholders AS p GROUP BY p.field ORDER BY p.field")
    empty = {f: int(counts["records"] - counts[f]) for f, _ in ph if f in counts}
    fill = {f: counts[f] / max(counts["records"], 1) for f in FIELDS}
    summary = [("records", f"{int(counts['records']):,}" + (f", {added:,} of them new" if added is not None else "") + (f"; {int(counts['set_aside']):,} set aside (set_aside)" if counts["set_aside"] else "")),
               ("candidates", f"{int(counts['scored']):,} pairs scored{' in this batch' if added is not None else ''}, {int(counts['ruled']):,} of them a rule's too: "
                              "scored, which a match run reads at its threshold (python -m nayose match)"),
               ("entities", f"{int(counts['entities']):,}; {int(counts['by_people']):,} records joined by people's decisions; the largest holds {int(counts['largest']):,} record{'s' * bool(counts['largest'] != 1)}"),
               ("kinds", f"{int(counts['companies']):,} × 2 company · {int(counts['persons']):,} × 1 person · {int(counts['unsure']):,} × 0 not sure (records)"),
               ("kinds", f"{int(counts['company_customers']):,} × 2 company · {int(counts['person_customers']):,} × 1 person · {int(counts['unsure_customers']):,} × 0 not sure (customers)"),
               *([("flagged", f"{int(counts['flagged']):,} records the engine is sure of against the flag: matched as the engine says (gold: kind_flagged)")] if counts["flagged"] else []),
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
    out += ["SCORES  (the candidates scored, by bits)", *table(pd.DataFrame([dict(bits=label(i), candidates=f"{scored[i]:,}") for i in sorted(scored) if scored[i]])), ""]

    named = {(x, g): lab for x, g, lab in engine.rows("SELECT comparison, gamma, label FROM model")}
    got = engine.frame("SELECT * FROM report_patterns ORDER BY up DESC, k")
    band = lambda up: f"{lo:g} and up" if up else f"0 to {lo:g}"
    out += ["PATTERNS BY SCORE  (the keys' pairs at 0 bits and up, below and from the review floor: each band's 12 most common levels)",
            *table(pd.DataFrame([dict(band=band(x["up"]), pairs=f"{int(x['n']):,}", bits=f"{x['w']:.1f}",
                                      **{k: "missing" if pd.isna(x[f"gamma_{k}"]) or x[f"gamma_{k}"] < 0 else named[k, int(x[f"gamma_{k}"])] for k in COMPARISONS})
                                 for _, x in got.iterrows()])),
            *(f"  {band(up)}: {int(g['kinds'].iloc[0]) - 12:,} patterns more, {int(g['total'].iloc[0]) - int(g['n'].sum()):,} pairs"
              for up, g in got.groupby("up", sort=False) if g["kinds"].iloc[0] > 12), ""]

    sizes = dict(engine.rows("SELECT size, entities FROM report_clusters"))
    bins = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5–9", 5, 9), ("10–49", 10, 49), ("50+", 50, math.inf)]
    out += ["CLUSTERS  (size: how many)", "  " + " · ".join(f"{name}: {total:,}" for name, a, b in bins if (total := sum(v for k, v in sizes.items() if a <= k <= b))), ""]

    notes = json.loads(engine.value("SELECT notes FROM fit"))
    facts = dict(records=f"records {int(counts['added']):,} · set_aside {int(counts['set_aside']):,} · companies {int(counts['companies']):,} · persons {int(counts['persons']):,} · not sure {int(counts['unsure']):,}",
                 fit=f"fit_rows {notes['fit_rows']:,}" + (" · the build's model" if job != "build" else "") + f" · sampled_again {len(notes.get('sampled_again', [])):,}",
                 score=f"candidates {int(counts['candidates']):,} · stored {int(counts['scored']):,} · rule pairs {int(counts['ruled']):,} · oversized_kept {int(counts['oversized_kept']):,} · "
                       f"oversized_skipped {int(counts['oversized_skipped']):,}",
                 decide=f"decided {int(counts['decided']):,} · entities {int(counts['entities']):,}")
    out += ["STEPS", *table(pd.DataFrame([dict(step=s, seconds=f"{x:.2f}", facts=facts.get(s, "")) for s, x in steps.items()])), ""]

    keys = engine.frame("SELECT * FROM report_keys ORDER BY pairs DESC, g")
    out += ["KEYS  (pairs each lists, most first)", *table(pd.DataFrame(dict(key=keys["name"], pairs=keys["pairs"].map(lambda x: f"{int(x):,}")))), ""]

    fit_row = engine.frame("SELECT * FROM fit").iloc[0]
    levels = engine.frame("SELECT comparison, label, file_m, file_u, bits FROM model ORDER BY position, gamma DESC")
    prior = json.loads(fit_row["fitted"])["prior_bits"]
    out += [f"MODEL  (prior {prior:.2f} bits at {int(fit_row['records']):,} records; fitted on {int(fit_row['fit_rows']):,} records"
            + (f"; learned nothing about {', '.join(notes['skipped'])}" if notes.get("skipped") else "") + ")",
            *(["  EM learned from: " + " · ".join(f"{k} {v:,} pairs" for k, v in notes["em_pairs"].items())] if notes.get("em_pairs") else []),
            *table(pd.DataFrame(dict(comparison=levels["comparison"], level=levels["label"], m=levels["file_m"].map(lambda x: f"{x:.4f}" if x >= 1e-3 else f"{x:.2e}"),
                                     u=levels["file_u"].map(lambda x: f"{x:.2e}"), bits=levels["bits"].map(lambda x: f"{x:.2f}")))),
            *(f"  {k} {lv}: {why} (EM said {was:+.2f} bits)" for k, lv, why, was in notes.get("file_adjusted", [])), ""]

    blocks = keys.assign(per_record=keys["pairs"] / max(int(counts["records"]), 1))
    blocks = blocks[(blocks["oversized"] > 0) | blocks["name"].isin(blocks.nlargest(6, "per_record")["name"])].sort_values("per_record", ascending=False, kind="stable")
    out += [f"BLOCKS  ({int(keys['pairs'].sum()):,} pairs the keys list, before dedupe)", *table(pd.DataFrame(dict(
        kind="generator", name=blocks["name"], per_record=blocks["per_record"].map(lambda x: f"{x:.2f}"),
        largest=blocks["largest"].map(lambda x: f"{int(x):,}"), oversized=blocks["oversized"].map(lambda x: f"{int(x):,}"))))]
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


def making(name: str, table: str) -> str:  # the statement of stage `name` that makes `table`
    return next(s for s in statements((SQL / f"{name}.sql").read_text(encoding="utf-8")) if (m := WRITE.match(s)) and m[3] == table)


def stage(engine, name: str, scratch: set | None = None, until: str | None = None, **values: object) -> None:
    """The stage nayose/sql/<name>.sql on `engine`, its statements in order (run_file)."""
    run_file(engine, SQL / f"{name}.sql", scratch=scratch, until=until, **values)


def run_file(engine, path: Path, scratch: set | None = None, until: str | None = None, **values: object) -> None:
    """The SQL file at `path` on `engine`, its statements in order. Each is given the values it names as @name, and only
    those: BigQuery refuses a parameter a statement doesn't read. A statement whose comments say `-- when: <condition>`
    runs only where the condition holds (on BigQuery, the procedure's IF: engines.procedures). `scratch`: as a lookup
    runs it, writing the temporary tables it names alone (scratched); `until`: up to the statement that makes that table."""
    for sql in statements(path.read_text(encoding="utf-8")):
        named = set(PARAMETER.findall(NOT_CODE.sub("", sql)))
        guard = when(sql)
        told = set(PARAMETER.findall(guard)) if guard else set()
        if missing := (named | told) - set(values):
            raise ValueError(f"{path.name} names @{', @'.join(sorted(missing))}, which no value gives")
        last = until is not None and (made := WRITE.match(sql)) is not None and made.group(3) == until
        runs = not guard or engine.value(f"SELECT {guard}", {k: values[k] for k in told})
        if runs and scratch is not None:
            sql = scratched(sql, scratch)
        if runs and sql is not None:
            engine.run(sql, {k: values[k] for k in named})
        if last:
            return


def when(sql: str) -> str | None:
    """A statement's condition: its leading comments' `-- when: <condition>`, a comment after it aside; None without.
    Refused where there are two, or one on a function (the deploy makes those apart), or one past the statement's start."""
    body = re.match(r"\A(?:\s*--[^\n]*\n)*", sql)[0]
    lines = WHEN.findall(body)
    if len(lines) > 1 or (lines and TEMP_FUNCTION.match(sql)) or len(WHEN.findall(sql)) > len(lines):
        raise ValueError(f"a statement holds one condition, in its leading comments, and a function none: {sql.strip()[:80]}")
    return lines[0].split("--")[0].strip() or None if lines else None


def scratched(sql: str, temp: set) -> str | None:
    """`sql` as a lookup runs it, so that it never writes the run: a table or a view it makes, a temporary table (added
    to `temp`: BigQuery's views read the run's tables, never a session's), unclustered;
    one it would make if missing, skipped where `temp` holds it already (a run's table copied first: lookup's
    asked); a table it changes, refused unless `temp` holds it; any other statement but a read or a temporary
    function, refused. A statement reads a temporary table before the run's of the same name, on both engines."""
    m = WRITE.match(sql)
    if not m:
        if READ.match(sql):
            return sql
        raise ValueError(f"a lookup can't tell what this statement writes, so it isn't run: {sql.strip()[:80]}")
    lead, verb, name, rest = m.group(1), " ".join(m.group(2).upper().split()), m.group(3), sql[m.end():]
    if verb == "CREATE TABLE IF NOT EXISTS" and name in temp:
        return None
    if verb.startswith("CREATE"):
        temp.add(name)
        return f"{lead}CREATE OR REPLACE TEMP TABLE {name}{re.sub(r'^\s*CLUSTER\s+BY\s+\w+(?:\s*,\s*\w+)*', '', rest, flags=re.I)}"
    if name not in temp:
        raise ValueError(f"a lookup would write the run's {name} ({verb}): it holds no temporary table of that name")
    return sql


def fingerprint(root: Path = HERE, mapping_file: Path | None = None) -> str:
    """What an update needs to be what the build was: a hash of every stage file, the values (config.toml), the
    input's mapping and the name model, by name and content. A build stores it (the table method); an update refuses another."""
    h = hashlib.sha256()
    the_mapping = mapping_file or (mapping() if root == HERE else root / "mapping.sql")
    config_file = Path(os.environ.get("NAYOSE_CONFIG") or root / "config.toml") if root == HERE else root / "config.toml"
    name_model = NAME_MODEL if root == HERE else root.parent / "config" / NAME_MODEL.name  # it says each record's kind
    for f in sorted([*(root / "sql").glob("*.sql"), *(p for p in (config_file, the_mapping, name_model) if p.exists())], key=lambda p: p.name):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()
