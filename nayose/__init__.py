"""nayose: entity resolution for Japanese customer records, written as BigQuery SQL and run by a little Python.

The method is SQL in BigQuery's dialect, one file per stage (nayose/sql/<stage>.sql), each read top to bottom.
BigQuery runs the SQL as written. DuckDB, on a laptop or in CI, runs it after sqlglot translates it
(nayose/engines.py). A run is a set of tables: a BigQuery dataset, or a DuckDB database file.

The jobs:
    build(engine, files)            make a run from its first batch: records, fit, score, decide
    update(engine, files)           add a batch: its records, u measured again, the pairs touching it scored, decide
    decide(engine, files)           store people's decisions and make the entities from them (decide.sql)
    match(engine, threshold)        list the pairs at a threshold for people, less those they said differ (match.sql)
    lookup(engine, record|values)   find the entities a record would join, as an update of it alone, writing nothing

The stages the jobs run:
    records(engine, files)          stage 1: read the input files, map them (mapping.sql), make records (records.sql)
    fit(engine)                     stage 2: learn the model on a sample, then u on the file (fit.sql, nayose/em.py)
    score(engine)                   stage 3: the rules' pairs, the keys' candidates and their scores (score.sql)

Running SQL:
    stage(engine, name, **values)   run a stage file's statements in order, each given the values it names (@name)
    statements(text)                split a stage file into statements: each ends with a line that ends in ';'
    fingerprint()                   hash what an update needs unchanged since its build: the SQL, the values, the
                                    mapping and the name model
"""
import functools
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
import sqlglot
from sqlglot import exp

HERE = Path(__file__).parent
SQL = HERE / "sql"
NAME_MODEL = HERE.parent / "config" / "kind_names.npz"  # the name model's terms, weights and intercept
SMALL_KANA = str.maketrans("ァィゥェォッャュョヮ", "アイウエオツヤユヨワ")  # banks write none: legal forms match both
HIRAGANA = "".join(chr(c) for c in range(0x3041, 0x3097))
KATAKANA = "".join(chr(c + 0x60) for c in range(0x3041, 0x3097))  # the katakana each hiragana is read as
KATAKANA_BLOCK = "".join(map(chr, range(0x30A0, 0x3100)))
ONE_BYTE = "".join(map(chr, range(1, 0x61)))  # one byte for each character of the katakana block: 0x01–0x60
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # a column name config.toml may give
METHOD = "CREATE OR REPLACE TABLE method AS SELECT @fingerprint AS fingerprint"  # a build's last statement
CHANGED = ("the method, its values or the mapping changed since the run was built: "
           "a batch or a lookup would be scored otherwise")
UNCHANGED = f"SELECT IF((SELECT fingerprint FROM method) <> @fingerprint, ERROR('{CHANGED}; build the run again'), 0)"
QUERY = "￿asked"  # the ID of a record looked up by its values: no record has it, and it sorts after every ID
SHOWN = ("full_name", "person_name", "company_name", "address", "postal_code", "phone", "birth_date", "customer_id")
BLANK = "".join(ch for ch in map(chr, range(0x3001)) if ch.isspace())  # a blank value's characters: Python's whitespace
COMPARISONS = ("name", "company", "address", "phone", "cif", "birth")  # the model's, in its order
FIELDS = (  # a record's fields, as report.txt lists them
    "full_name", "person_name", "given_name", "company_name", "any_name", "address", "address_code", "postal_code",
    "prefecture", "town_code", "city", "phone", "customer_id", "birth_date")

# Reading a statement from its text: run_file, for_lookup and the deploy's procedures do.
PARAMETER = re.compile(r"@(\w+)")  # a value a statement reads, by name: run_file passes it, the deploy declares it
NOT_CODE = re.compile(r"--[^\n]*|'(?:[^'\\]|\\.)*'")  # a -- comment or a '…' string: the parts that aren't code
QUOTED = re.compile(  # a -- comment, or any of BigQuery's strings and quoted names
    r"""--[^\n]*|'''.*?'''|\"\"\".*?\"\"\"|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`[^`]*`""", re.S)
WHEN = re.compile(r"^\s*--\s*when:(.*)$", re.M | re.I)  # a `-- when: <condition>` line: see when()
LEAD = r"(?P<lead>(?:\s*--[^\n]*\n|\s*/\*.*?\*/)*\s*)"  # a statement's leading comments
WRITE = re.compile(  # a statement that writes a table: its leading comments, its verb, and the table it writes
    rf"^{LEAD}(?P<verb>"
    r"CREATE\s+OR\s+REPLACE\s+TEMP(?:ORARY)?\s+TABLE|CREATE\s+OR\s+REPLACE\s+TABLE|CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS|"
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW|CREATE\s+TABLE|"
    r"INSERT(?:\s+INTO)?|DELETE(?:\s+FROM)?|UPDATE|MERGE(?:\s+INTO)?|TRUNCATE\s+TABLE"
    r")\s+`?(?P<table>\w+)`?", re.I | re.S)
READ_OR_TEMP = re.compile(  # a statement that only reads, or makes a temporary table or function
    rf"^{LEAD}(SELECT|WITH|CREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+(?:FUNCTION|TABLE))\b", re.I | re.S)
TEMP_FUNCTION = re.compile(  # a statement that makes a temporary function: its leading comments and the function's name
    rf"^{LEAD}CREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+FUNCTION\s+(?P<name>\w+)", re.I | re.S)


class InputError(ValueError):
    """A refusal the person running the job can act on: what is wrong (the message), and how to fix it (`fix`)."""

    def __init__(self, message: str, fix: str = "") -> None:
        super().__init__(message)
        self.fix = fix


def config() -> dict:
    """Return config.toml, or the file NAYOSE_CONFIG names (a variant, at design time)."""
    return tomllib.loads(Path(os.environ.get("NAYOSE_CONFIG") or HERE / "config.toml").read_text(encoding="utf-8"))


def mapping() -> Path:
    """Return the path of mapping.sql, or of the file NAYOSE_MAPPING names (another input's columns)."""
    return Path(os.environ.get("NAYOSE_MAPPING") or HERE / "mapping.sql")


MAPPED = ("input_rows", "mapped")  # the tables a mapping makes, for records.sql


@functools.cache
def method_tables() -> frozenset[str]:
    """Return, in lower case, every table the method's SQL names (a WITH's names aside) and every table Python makes."""
    names = {"input", "name_weights", "method"}
    for f in SQL.glob("*.sql"):
        for sql in statements(f.read_text(encoding="utf-8")):
            tree = sqlglot.parse_one(sql, read="bigquery")
            ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
            names |= {t.name for t in tree.find_all(exp.Table) if t.name not in ctes}
    return frozenset(n.lower() for n in names) - set(MAPPED)


def mapping_statements(path: Path) -> list[str]:
    """Return a mapping's statements, or raise InputError unless every one keeps to a mapping's form.

    A mapping turns the input's columns into fields and keeps nothing. So each statement, as BigQuery parses it, must
    be one query, or make one temporary table with a name the method doesn't use (in any case), and its comments must
    start with --. The reasons:
    - a table of its own would be dropped by the next build, which makes again every table it writes;
    - a temporary table named like one of the method's would hide it, as a statement reads a temporary table first;
    - a function of its own would replace one of the method's on BigQuery, but not on DuckDB;
    - nayose finds a statement's end, and the @values it reads, past -- comments alone (statements, run_file).
    """
    try:
        out = statements(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise InputError(f"{path.name}: {e}",
                         fix="end each statement with a line ending in ';', and start a comment with --") from e
    for sql in out:
        said = " ".join(sql.split())[-100:]
        if "#" in QUOTED.sub("", sql):
            raise InputError(f"{path.name}: a comment starts with --, as in the method's files: {said}",
                             fix="write each # comment as --")
        try:
            parsed = sqlglot.parse(sql, read="bigquery")
            trees = [t for t in parsed if t is not None and not isinstance(t, exp.Semicolon)]  # a comment after ';' too
        except sqlglot.errors.ParseError as e:
            raise InputError(f"{path.name}: a statement doesn't parse as BigQuery's: {said}",
                             fix=str(e).split("\n")[0]) from e
        tree = trees[0] if len(trees) == 1 else None
        is_temp_table = isinstance(tree, exp.Create) and tree.kind == "TABLE" and tree.find(exp.TemporaryProperty)
        created = tree if is_temp_table else None
        name = created and (created.this.this if isinstance(created.this, exp.Schema) else created.this).name
        if isinstance(tree, exp.Create) and tree.kind == "FUNCTION":
            raise InputError(f"{path.name}: a mapping makes no function of its own: {said}",
                             fix="write it in place, or call one of functions.sql's")
        if created is not None and name.lower() in method_tables():
            raise InputError(f"{path.name}: the temporary table {name} has the name of one of the method's tables, "
                             "which it would hide", fix="give it a name of its own")
        if created is None and not isinstance(tree, exp.Query):
            raise InputError(f"{path.name}: a mapping reads, and makes temporary tables alone, "
                             f"one statement to a line ending in ';': {said}",
                             fix="make it CREATE OR REPLACE TEMP TABLE <a name of its own> AS SELECT …")
    return out


def legal_pattern(section: dict) -> str:
    """Return the pattern of a legal form, from config.toml's [records] `section`, matched on NFKC text.

    It matches a legal form anywhere, also with its small kana written large, or a bank's abbreviation where one
    may stand: first, as in カ)〇〇, or last, as in 〇〇(カ. Longer forms come first, so 医療法人社団 isn't
    cut to 医療法人.
    """
    spellings = {f for x in section["legal_forms"] for f in (x, x.translate(SMALL_KANA))}
    forms = sorted(spellings, key=lambda f: (-len(f), f))  # one order, so every run builds the same pattern
    parts = [re.escape(f) for f in forms]
    if section["legal_front"]:
        parts.append(f"^(?:{'|'.join(map(re.escape, sorted(section['legal_front'], key=len, reverse=True)))})\\)")
    if section["legal_end"]:
        parts.append(f"\\((?:{'|'.join(map(re.escape, sorted(section['legal_end'], key=len, reverse=True)))})$")
    return "|".join(parts)


def nulls_pattern(nulls: list[str]) -> str:
    """Return the RE2 pattern of a value read_value reads as missing.

    That is one of `nulls`, with spaces or U+3000 around it or not, or a value of spaces alone (Python's whitespace,
    as str.strip removes it).
    """
    return (r"^[ \x{3000}]*(?:" + "|".join(map(re.escape, nulls)) + r")[ \x{3000}]*$"
            r"|^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$")


def records(engine, files: list | None, lookup: bool = False, scratch: set | None = None) -> None:
    """Run stage 1 on `engine`: load the input files, then run mapping.sql and records.sql.

    The files become the table input, with every column mapping.sql reads that a file lacks, as missing; with
    `files` None, the table input is used as it is. The name model's weights become the table name_weights. With
    `lookup`, the input is a record asked about, and the stage writes `scratch`'s temporary tables alone (run_file),
    reading the run's name model as it is. O(Δ·L), plus O(N) for the placeholders.
    """
    c = config()
    if bad := [x for x in c["input"]["columns"] if not NAME.match(x)]:
        raise ValueError(f"config.toml [input] columns: {bad} are no plain column names")
    mapping_statements(mapping())  # refused before the job writes anything
    if files is not None:
        engine.read_parquet("input", files, c["input"]["columns"])
    if scratch is None:
        engine.put("name_weights", name_weights())
    stage(engine, "functions", scratch=scratch)
    run_file(engine, mapping(), scratch=scratch, **values_of("mapping"))
    stage(engine, "records", scratch=scratch, **values_of("records", lookup=lookup))
    if files is not None and engine.name == "duckdb":
        # DuckDB holds a temporary table whole, so it keeps only the rows the report samples (unmapped)
        engine.run("CREATE OR REPLACE TEMP TABLE input AS SELECT * FROM input LIMIT 10000")


def name_weights() -> pd.DataFrame:
    """Return the name model (config/kind_names.npz) as a table: each character n-gram and its weight."""
    model = np.load(NAME_MODEL)
    return pd.DataFrame({"term": model["terms"].tolist(), "w": model["coef"]})


def values_of(name: str, refit: bool = True, lookup: bool = False) -> dict:
    """Return the values stage `name` reads as @name, from config.toml.

    A run here passes them as query parameters; a BigQuery procedure declares them (engines.procedures). `refit` is
    True for a build, False for an update, which keeps the model. With `lookup`, the batch is a record asked about.
    match's @threshold, and the values of lookup.sql and report.sql, come from their jobs.
    """
    c = config()
    if name == "mapping":
        return dict(nulls=nulls_pattern(c["input"]["nulls"]))
    if name == "records":
        r = c["records"]
        return dict(hiragana=HIRAGANA, katakana=KATAKANA, katakana_block=KATAKANA_BLOCK, one_byte=ONE_BYTE,
                    kana_fold_from=r["kana_fold_from"], kana_fold_to=r["kana_fold_to"], legal_pattern=legal_pattern(r),
                    prefecture_pattern=f"^(?:{'|'.join(map(re.escape, r['prefectures']))})",
                    flag_company=list(r["flag_company"]), name_line=float(r["name_line"]),
                    trust_flag=bool(r["trust_flag"]), shared_name_column=bool(r["shared_name_column"]),
                    ngram=int(r["ngram"]),
                    intercept=float(np.load(NAME_MODEL)["intercept"]), min_block=int(r["min_block"]),
                    spread=int(r["spread"]), crowd=int(r["crowd"]), lookup=lookup)
    if name == "fit":
        f = c["fit"]
        return dict(fit_rows=int(f["fit_rows"]), seed=str(f["seed"]), fit_u_max_pairs=float(f["fit_u_max_pairs"]),
                    u_max_pairs=float(f["u_max_pairs"]), settings=json.dumps(f), refit=refit)
    if name == "score":
        s = c["score"]
        return dict(keys=list(s["keys"]), rules=list(s["rules"]),
                    keep_from=-math.inf if lookup else float(s["keep_from"]), search_floor=float(s["search_floor"]),
                    oversized=int(s["oversized"]), lookup=lookup, outside=0)
    if name == "decide":
        return dict(blank=BLANK)
    if name == "report":
        floor, likely = float(c["lookup"]["at_least"]), float(c["lookup"]["likely_from"])
        patterns = {**c["report"]["patterns"], "company_name": legal_pattern(c["records"])}
        return dict(patterns=json.dumps(patterns, ensure_ascii=False),
                    edges=sorted({-20.0, -10.0, 0.0, floor, likely, likely + 2, likely + 4, likely + 8, likely + 12}),
                    floor=floor, oversized=int(c["score"]["oversized"]))
    return {}


def fit(engine, refit: bool = True) -> None:
    """Run stage 2 on `engine`, after records: fit.sql, with config.toml's [fit].

    With `refit` False (an update), the build's model is kept and its u measured again on the run's records.
    O(n + S·K) on the sample of n records, S sampled pairs and K comparisons, and O(N + S·K) on the file.
    """
    stage(engine, "functions")
    stage(engine, "fit", **values_of("fit", refit=refit))


def score(engine, lookup: bool = False, scratch: set | None = None, until: str | None = None, outside: int = 0) -> None:
    """Run stage 3 on `engine`, after fit: score.sql, with config.toml's [score].

    With `lookup`, every candidate is scored, whatever its points, in `scratch`'s temporary tables, up to the table
    `until` makes; `outside` is how many of the run's records the records table doesn't hold (a lookup's holds its
    blocks' records alone). O(Δ·b + C·K·L²), plus O(Δ·L) for the keys and a scan of the key index.
    """
    stage(engine, "functions", scratch=scratch)
    stage(engine, "score", scratch=scratch, until=until, **(values_of("score", lookup=lookup) | {"outside": outside}))


# ---------- lookup ----------

def lookup(engine, record: str | None = None, values: dict | None = None, at_least: float | None = None,
           most: int | None = None) -> dict:
    """Return the entities a record would be compared with, as an update of it alone compares it, best first.

    Give `record`, a stored record's ID, to look it up as if it were new (itself left out), or `values`, by the
    input's column names. The answer lists each entity at `at_least` points or more ([lookup] at_least, the review
    floor), or joined by a rule, with its best record, its points, each comparison's level, the rule that would join
    it and the keys that listed it: at most `most` of them, else the closest record. It also gives the record as
    compared, and each key looked up.

    A lookup writes nothing to the run, and reads only what it touches, in three steps: the record's own keys
    (asked_keys), the run's key index read by those keys (read_index), and the record scored against those records
    alone (score_asked). Each step works in temporary tables that end with it (engine.scratch), and every statement
    it runs goes through for_lookup, which refuses any write to a run's table. O(G) for its keys + O(G·b + C·K·L²).
    """
    c = config()
    at_least = float(c["lookup"]["at_least"] if at_least is None else at_least)
    most = int(c["lookup"]["most"] if most is None else most)
    if (record is None) == (values is None):
        raise InputError("give one of: a stored record's ID, or a record's values", fix="for example --record 1234")
    if values is not None and (unknown := sorted(set(values) - set(c["input"]["columns"]))):
        raise InputError(f"{', '.join(unknown)}: no field reads that column",
                         fix=f"the columns a field reads: {', '.join(c['input']['columns'])}")
    asked_id = record if record is not None else QUERY
    # the key index and the scores are the build's method's
    unchanged(engine, "build the run again with them, or look up with the code the build ran")
    if record is not None and not engine.value("SELECT COUNT(*) FROM records WHERE id = @id", {"id": asked_id}):
        raise InputError(f"{record}: no record of the run has that ID",
                         fix="give a record ID the run holds, or the record's values")
    run_size = engine.value("SELECT COUNT(*) FROM records")
    keys = asked_keys(engine, record, values, asked_id)
    ids, blocks = read_index(engine, keys, record, asked_id, int(c["score"]["oversized"]))
    view, candidates, found, checked = score_asked(engine, record, values, asked_id, ids, blocks, run_size, at_least)
    return lookup_answer(record, view, candidates, found, checked, at_least, most)


def asked_keys(engine, record: str | None, values: dict | None, asked_id: str) -> dict[str, set]:
    """Return the keys of the record asked about, made from it alone: its every_key and rule_keys rows (step 1)."""
    with engine.scratch():
        score_in_scratch(engine, record, values, [asked_id] if record is not None else [], until="made_keys")
        return {"every_key": set(engine.rows("SELECT g, k FROM made_keys WHERE id = @id", {"id": asked_id})),
                "rule_keys": set(engine.rows("SELECT i, k FROM made_rule_keys WHERE id = @id", {"id": asked_id}))}


def read_index(engine, keys: dict[str, set], record: str | None, asked_id: str, big: int) -> tuple[set, dict]:
    """Return the records the run's key index holds under the record's keys (step 2).

    That is every record of each rule key and of each block, but of an oversized block (`big` records or more) only
    its first records by hash: the gate's sample (score.sql), and one more, so the record asked about may rank
    anywhere. Returns the IDs, and each block's (g, k) with [its size, the IDs read].
    """
    ids = {asked_id} if record is not None else set()
    if keys["rule_keys"]:
        rows = engine.rows("SELECT i, k, id FROM rule_keys WHERE k IN UNNEST(@ks)",
                           {"ks": sorted({k for _, k in keys["rule_keys"]})})
        ids |= {i for g, k, i in rows if (g, k) in keys["rule_keys"]}
    blocks = {}
    if keys["every_key"]:
        rows = engine.rows("SELECT g, k, id, COUNT(*) OVER (PARTITION BY g, k) AS n FROM every_key "
                           "WHERE k IN UNNEST(@ks) QUALIFY COUNT(*) OVER (PARTITION BY g, k) < @big "
                           "OR ROW_NUMBER() OVER (PARTITION BY g, k ORDER BY er_hash(id)) <= @big + 1",
                           {"ks": sorted({k for _, k in keys["every_key"]}), "big": big})
        for g, k, i, n in rows:
            if (g, k) in keys["every_key"]:
                blocks.setdefault((g, k), [n, set()])[1].add(i)
    return ids | {i for _, read in blocks.values() for i in read}, blocks


def score_asked(engine, record: str | None, values: dict | None, asked_id: str, ids: set, blocks: dict, run_size: int,
                at_least: float) -> tuple:
    """Score the record against the records read, and return the record as compared and lookup.sql's tables (step 3).

    A block read in part is scored at its whole size. A big block that the gate keeps makes every pair of it a
    candidate, so that block is then read whole, from the run's index, and the record scored again: each pass reads
    more, and the loop ends once no block read in part is kept. The index is read outside the scratch, whose
    every_key is the lookup's own. Returns (the record as compared, candidates, entities, checked).
    """
    c = config()
    big = int(c["score"]["oversized"])
    while True:
        with engine.scratch():
            typed = 0 if record is not None else 1  # a typed record isn't in the index: its blocks hold one record more
            sized = [(g, k, n + typed) for (g, k), (n, read) in blocks.items() if n > len(read)]
            temp = score_in_scratch(engine, record, values, sorted(ids), outside=run_size - len(ids), sized=sized)
            gate_kept = {(g, k) for g, k in engine.rows("SELECT g, value FROM gated WHERE decision = 'kept'")}
            kept = gate_kept & {(g, k) for g, k, _ in sized}
            if not kept:
                stage(engine, "lookup", scratch=temp, at_least=at_least, likely_from=float(c["lookup"]["likely_from"]),
                      oversized=big, stored=record is not None)
                shown = ", ".join(SHOWN) + ("" if record is not None else ", kind")
                return (engine.frame(f"SELECT {shown} FROM records WHERE id = @id", {"id": asked_id}).iloc[0],
                        engine.frame("SELECT * FROM candidates ORDER BY points DESC, id"),
                        engine.frame("SELECT * FROM entities "
                                     "ORDER BY rule IS NULL, ROUND(points, 2) DESC, points DESC, id"),
                        engine.frame("SELECT * FROM checked ORDER BY position"))
        index = engine.rows("SELECT g, k, id FROM every_key WHERE k IN UNNEST(@ks)",
                            {"ks": sorted({k for _, k in kept})})
        for g, k, i in index:
            if (g, k) in kept:
                blocks[g, k][1].add(i)
                ids.add(i)


def score_in_scratch(engine, record: str | None, values: dict | None, ids: list, until: str | None = None,
                     outside: int = 0, sized: list = ()) -> set:
    """Score the record asked about in temporary tables of the run's names, and return those tables' names.

    The temporary tables hold the run as the lookup sees it (copy_for_lookup), with the record asked about as a batch
    of its own (add_asked_record). score.sql then runs on them, up to the table `until` makes. `outside` is how many
    of the run's records the temporary records table doesn't hold; `sized` gives each block it holds in part with its
    whole size, as (g, k, n).
    """
    temp = copy_for_lookup(engine, ids, sized)
    add_asked_record(engine, record, values, temp)
    engine.run(for_lookup(statement_making("fit", "compared"), temp))  # the columns score compares: fit.sql's view
    score(engine, lookup=True, scratch=temp, until=until, outside=outside)
    return temp


def copy_for_lookup(engine, ids: list, sized: list) -> set:
    """Copy the run's tables a lookup reads into temporary tables of the same names, and return their names.

    records and gold hold `ids` alone, each read by ID (on BigQuery, from its clustering's blocks); placeholders is
    copied whole. block_size holds `sized`. A statement reads a temporary table before the run's of the same name.
    """
    if sized:  # three arrays, as a parameter is an array of values on both engines
        engine.run("CREATE OR REPLACE TEMP TABLE block_size AS SELECT g, @k[OFFSET(i)] AS k, @n[OFFSET(i)] AS n "
                   "FROM UNNEST(@g) AS g WITH OFFSET AS i",
                   {"g": [g for g, _, _ in sized], "k": [k for _, k, _ in sized], "n": [n for _, _, n in sized]})
    else:
        engine.run("CREATE OR REPLACE TEMP TABLE block_size (g INT64, k STRING, n INT64)")
    temp = {"block_size"}
    for table in ("records", "gold"):
        engine.run(f"CREATE TEMP TABLE {table} AS SELECT * FROM {table} WHERE id IN UNNEST(@ids)", {"ids": ids})
        temp.add(table)
    engine.run("CREATE TEMP TABLE placeholders AS SELECT * FROM placeholders")
    temp.add("placeholders")
    return temp


def add_asked_record(engine, record: str | None, values: dict | None, temp: set) -> None:
    """Make the record asked about a batch of its own in the temporary tables.

    A stored record (`record`) gets the next batch number. A typed one (`values`) is made a record by records.sql,
    as a file's would be; InputError is raised when every value it gives reads as missing.
    """
    if record is not None:
        temp.add("this_batch")
        engine.run("CREATE OR REPLACE TEMP TABLE this_batch AS SELECT MAX(batch) + 1 AS batch FROM records")
        engine.run("UPDATE records SET batch = (SELECT batch FROM this_batch) WHERE id = @id", {"id": record})
        return
    columns = config()["input"]
    given = list(({x: values.get(x) for x in columns["columns"]} | {columns["id"]: QUERY}).items())
    temp.add("input")
    cells = ", ".join(f"CAST({'NULL' if v is None else f'@v{i}'} AS STRING) AS `{x}`" for i, (x, v) in enumerate(given))
    engine.run(f"CREATE OR REPLACE TEMP TABLE input AS SELECT {cells}",
               {f"v{i}": str(v) for i, (_, v) in enumerate(given) if v is not None})
    records(engine, None, lookup=True, scratch=temp)
    filled = f"SELECT COUNT(*) FROM records WHERE id = @id AND COALESCE({', '.join(SHOWN)}) IS NOT NULL"
    if not engine.value(filled, {"id": QUERY}):
        shown = [f"{k}={v}" for k, v in values.items() if v not in (None, "")]
        raise InputError(f"{', '.join(shown)}: read as missing, as a file's would be" if shown else "no value given",
                         fix="give a value a record holds: a name, a phone, a postal code")


def lookup_answer(record: str | None, view, candidates: pd.DataFrame, found: pd.DataFrame, checked: pd.DataFrame,
                  at_least: float, most: int) -> dict:
    """Return what a lookup gives back (docs/data.md, "A lookup's answer"), from lookup.sql's tables."""
    def text(v) -> str | None:
        return None if pd.isna(v) else str(v)

    def shown(x) -> dict:
        return {f: text(x[f]) for f in SHOWN}

    entities = [dict(entity=x["entity"], record=x["id"], points=round(float(x["points"]), 2), likely=bool(x["likely"]),
                     rule=text(x["rule"]), keys=sorted(x["sources"].split("+")) if text(x["sources"]) else [],
                     compared={k: x[f"level_{k}"] for k in COMPARISONS}, records=int(x["records"]), shown=shown(x))
                for _, x in found.iterrows()]
    keys = []
    for _, x in checked.iterrows():
        key = dict(key=x["key"], found=int(x["found"]))
        if x["lacks"]:
            key["why"] = "the record has no value for it"
        if not pd.isna(x["untrusted"]):
            key["why"] = f"its value is on {int(x['untrusted']):,} records: the rule doesn't trust it"
        if isinstance(x["big"], (list, np.ndarray)) and len(x["big"]):
            key["big"] = [dict(records=int(b["records"]), sampled=int(b["sampled"]),
                               best=None if b["best"] is None else round(float(b["best"]), 2), decision=b["decision"])
                          for b in x["big"]]
        keys.append(key)
    near = candidates.iloc[0] if len(candidates) and not entities else None
    closest = None if near is None else dict(record=near["id"], entity=near["entity"],
                                             points=round(float(near["points"]), 2), shown=shown(near))
    return dict(record={"id": record, **{k: text(view[k]) for k in view.index}}, entities=entities[:most],
                found=len(entities), at_least=at_least, candidates=len(candidates),
                likely=sum(e["likely"] for e in entities), closest=closest, checked=keys)


# ---------- the jobs ----------

def unchanged(engine, fix: str) -> None:
    """Raise InputError (CHANGED, then `fix`) unless the run was built by this method: its fingerprint."""
    try:
        stored = engine.value("SELECT fingerprint FROM method")
    except duckdb.CatalogException:  # no method table: a run this build didn't make
        stored = None
    if stored != fingerprint():
        raise InputError(CHANGED, fix=fix)


def run_stage(name: str, do, *args) -> None:
    """Run a stage of build as it is: build's default `timed`. The CLI passes one that times each stage."""
    do(*args)


def build(engine, files: list, model: str | None = None, timed=run_stage) -> None:
    """Make a run from its first batch on `engine`, an empty run: its records, its model, its scores and its entities.

    With `model`, a model fitted elsewhere (what fit returned), the model is kept and only its u measured on these
    records. The entities are those people's decisions make: none yet, or those the run kept from before. Each stage
    is run by `timed(name, stage, *arguments)`. O(N·L + n + S·K + ΣP + C·K·L²): P a block's pairs, C the
    candidates, L a value's length.
    """
    timed("records", records, engine, files)
    if model is not None:
        engine.run("CREATE OR REPLACE TABLE fit AS SELECT CAST(NULL AS FLOAT64) AS probability, "
                   "CAST(NULL AS INT64) AS fit_rows, CAST(NULL AS INT64) AS records, "
                   "CAST(NULL AS FLOAT64) AS prior_bits, "
                   "CAST(NULL AS STRING) AS notes, @fitted AS fitted",
                   {"fitted": json.dumps({**json.loads(model), "basis": None})})
    timed("fit", fit, engine, model is None)
    timed("score", score, engine)
    timed("decide", decide, engine, [])
    engine.run(METHOD, {"fingerprint": fingerprint()})


def update(engine, files: list) -> None:
    """Add a batch to the run on `engine`.

    The batch's records are made (one already in the run is set aside), the build's model has its u measured again on
    every record, the pairs touching the batch are scored, and the entities are made again.
    O(Δ·(L + b) + C_Δ·K·L²), plus O(N) scans of the run's records and keys.
    """
    unchanged(engine, "build the run again with them (python -m nayose build FILE --out RUN --overwrite), "
                      "or update with the code the build ran")
    records(engine, files)
    fit(engine, refit=False)
    score(engine)
    decide(engine, [])


def decide(engine, files: list) -> None:
    """Run the decide job on `engine`, after score: store people's decisions, then make the entities (decide.sql).

    `files` are Parquet: a match table filled in, or any file with id_l, id_r and decision (and why, kept where given).
    They become the table given. With no files (a build's last step), the entities come from the decisions the run
    holds. O(D + N).
    """
    if files:
        engine.read_parquet("given", files, ["why"])
        if lack := sorted({"id_l", "id_r", "decision"} - {n.casefold() for n, _ in engine.columns("given")}):
            raise InputError(f"the decisions lack the columns {lack}", fix="give back a match table with decision "
                             "filled in, or a file with id_l, id_r and decision")
    else:  # an empty table, as a file's would be
        engine.run("CREATE OR REPLACE TEMP TABLE given (id_l STRING, id_r STRING, decision STRING, why STRING)")
    stage(engine, "functions")
    stage(engine, "decide", **values_of("decide"))


def check_threshold(threshold: float) -> None:
    """Raise InputError for a threshold below [score] keep_from: the run keeps no pair below it."""
    floor = float(config()["score"]["keep_from"])
    if threshold < floor:
        raise InputError(f"threshold {threshold:g}: the run keeps the pairs from {floor:g} points up only",
                         fix=f"give a threshold of {floor:g} or more, "
                             "or lower [score] keep_from in config.toml and build the run again")


def match(engine, threshold: float) -> None:
    """Run the match job on `engine`, after decide: match.sql at `threshold` points (check_threshold). O(C + P·F)."""
    check_threshold(threshold)
    stage(engine, "functions")
    stage(engine, "match", threshold=float(threshold))


# ---------- report.txt ----------

def report(engine, steps: dict[str, float], job: str) -> str:
    """Run report.sql on `engine`, after a build or an update, and return report.txt (report_text)."""
    stage(engine, "report", **values_of("report"))
    return report_text(engine, steps, job)


def report_text(engine, steps: dict[str, float], job: str) -> str:
    """Return report.txt from report.sql's tables: the run on a page, with no record's value in it.

    `steps` holds each stage's seconds. The page has a section each: what ran, the summary, each field's fill and look,
    the input's columns no field reads, the batch's candidates by bits and each band's commonest patterns, the
    entities' sizes, each stage, each key's pairs, the model and the largest blocks. O(F + C) over the report's tables.
    """
    c, values = config(), values_of("report")
    counts = engine.frame("SELECT * FROM report_counts").iloc[0]
    added = None if job == "build" else int(counts["added"])
    fill = {f: counts[f] / max(counts["records"], 1) for f in FIELDS}
    keys = engine.frame("SELECT * FROM report_keys ORDER BY pairs DESC, g")
    notes = json.loads(engine.value("SELECT notes FROM fit"))
    sections = [report_header(engine, steps, added), report_summary(engine, c, counts, added, fill),
                report_fields(engine, fill), report_unmapped(engine, c, json.loads(values["patterns"])),
                report_scores(engine, values["edges"]), report_patterns(engine, values["floor"]),
                report_clusters(engine), report_steps(counts, notes, steps, job), report_keys(keys),
                report_model(engine, notes), report_blocks(keys, counts)]
    return "\n".join(line for section in sections for line in section) + "\n"


def number(x) -> str:
    """Return a count as people read it, with thousands separated: 12,345."""
    return f"{int(x):,}"


def percent(x) -> str:
    """Return a share as report.txt prints it, or a dash where there is none."""
    return "—" if x is None or pd.isna(x) else f"{x:.1%}"


def text_table(df: pd.DataFrame) -> list[str]:
    """Return `df` as the lines of a plain-text table: numbers right-aligned, text left, so the page stays narrow."""
    if not len(df):
        return ["  none"]
    rows = [list(map(str, df.columns)), *([str(v) for v in r] for r in df.itertuples(index=False))]
    columns = range(len(df.columns))
    width = [max(len(r[i]) for r in rows) for i in columns]
    numeric = [all(re.fullmatch(r"[-+]?[\d,.]+(%|e[-+]\d+)?|—", r[i]) for r in rows[1:]) for i in columns]
    return ["  " + "  ".join(v.rjust(w) if right else v.ljust(w) for v, w, right in zip(r, width, numeric)).rstrip()
            for r in rows]


def report_header(engine, steps: dict[str, float], added: int | None) -> list[str]:
    """Return the report's first lines: when, what ran, the code, the machine and the time taken."""
    if engine.name == "duckdb":
        threads, memory = engine.rows("SELECT current_setting('threads'), current_setting('memory_limit')")[0]
    else:
        threads, memory = "—", "—"
    run = "full run" if added is None else f"increment of {added:,} new records"
    machine = f"{platform.system()} {platform.machine()}"
    return [f"RUN REPORT · {datetime.now():%Y-%m-%d %H:%M} · {run} · no record's value in it",
            f"code {code_version()} · method {fingerprint()[:12]}",
            f"python {platform.python_version()} · duckdb {duckdb.__version__} · {machine}",
            f"{threads} threads · memory limit {memory} · took {sum(steps.values()):,.1f} s", ""]


def report_summary(engine, c: dict, counts, added: int | None, fill: dict) -> list[str]:
    """Return the SUMMARY section: records, candidates, entities, kinds, and notes on placeholders and empty fields."""
    def n(column: str) -> str:
        return number(counts[column])

    placeholders = engine.rows("SELECT p.field, COUNT(*) FROM placeholders AS p GROUP BY p.field ORDER BY p.field")
    without = {f: int(counts["records"] - counts[f]) for f, _ in placeholders if f in counts}
    records_line = n("records") + (f", {added:,} of them new" if added is not None else "")
    if counts["set_aside"]:
        records_line += f"; {n('set_aside')} set aside (set_aside)"
    in_batch = " in this batch" if added is not None else ""
    section = c["records"]
    summary = [
        ("records", records_line),
        ("candidates", f"{n('scored')} pairs scored{in_batch}, {n('ruled')} of them a rule's too: "
                       "scored, which a match run reads at its threshold (python -m nayose match)"),
        ("entities", f"{n('entities')}; {n('by_people')} records joined by people's decisions; "
                     f"the largest holds {n('largest')} record{'s' * bool(counts['largest'] != 1)}"),
        ("kinds", f"{n('companies')} × 2 company · {n('persons')} × 1 person · "
                  f"{n('unsure')} × 0 not sure (records)"),
        ("kinds", f"{n('company_customers')} × 2 company · {n('person_customers')} × 1 person · "
                  f"{n('unsure_customers')} × 0 not sure (customers)"),
    ]
    if counts["flagged"]:
        summary.append(("flagged", f"{n('flagged')} records the engine is sure of against the flag: "
                                   "matched as the engine says (gold: kind_flagged)"))
    summary.append(("kinds from", "the file's flag, as it is (trust_flag)" if section["trust_flag"]
                    else f"a written legal form, or a name {section['name_line']:.0%} sure; else the flag"))
    for f, k in placeholders:
        if f in without:
            owner = "one entity" if f == "customer_id" else "evidence"
            summary.append(("note", f"{f}: {k:,} value{'s' * bool(k != 1)} held by {section['min_block']}+ records "
                                    f"read as missing, a placeholder and not {owner}'s "
                                    f"({without[f]:,} records without one)"))
    summary += [("note", f"{f} only {x:.1%} filled: check its mapping") for f, x in fill.items() if x < 0.05]
    return ["SUMMARY", *(f"  {what:<12} {value}" for what, value in summary), ""]


def report_fields(engine, fill: dict) -> list[str]:
    """Return the FIELDS section: each field's fill, and how its values look on a sample."""
    shape = engine.frame("SELECT * FROM report_fields").set_index("field")
    rows = []
    for f in FIELDS:
        length, longest = shape.at[f, "length"], shape.at[f, "longest"]
        rows.append(dict(field=f, filled=percent(fill[f]), looks_right=percent(shape.at[f, "looks_right"]),
                         top_value=percent(shape.at[f, "top_value"]), no_letters=percent(shape.at[f, "no_letters"]),
                         length="" if pd.isna(length) else f"{length:.0f}",
                         longest="" if pd.isna(longest) else number(longest)))
    return ["FIELDS  (looks right, top value, no letters, length: on a sample of 10,000 records)",
            *text_table(pd.DataFrame(rows)), ""]


def report_unmapped(engine, c: dict, patterns: dict[str, str]) -> list[str]:
    """Return the COLUMNS NOT MAPPED section, on DuckDB only, where the input's own columns can be read by name."""
    columns = unmapped(engine, c, patterns) if engine.name == "duckdb" else None
    if columns is None or not len(columns):
        return []
    shown = columns.head(30)
    share = [percent(x) if f else "" for f, x in zip(shown["looks_like"], shown["share"])]
    table = pd.DataFrame(dict(column=shown["column"], filled=shown["filled"].map(percent),
                              distinct=shown["distinct"].map(percent), looks_like=shown["looks_like"], share=share))
    more = [f"  and {len(columns) - len(shown):,} more"] if len(columns) > len(shown) else []
    return ["COLUMNS NOT MAPPED  (no field reads them; filled, distinct and the field their values look most like: "
            "on the first 10,000 records)", *text_table(table), *more, ""]


def report_scores(engine, edges: list[float]) -> list[str]:
    """Return the SCORES section: the candidates scored, by bands of bits between `edges`."""
    scored = dict(engine.rows("SELECT band, pairs FROM report_scores"))

    def label(i: int) -> str:
        if i == -1:
            return "below 0"
        if i == 0:
            return f"below {edges[0]:g}"
        if i == len(edges):
            return f"{edges[-1]:g} and up"
        return f"{edges[i - 1]:g} to {edges[i]:g}"

    rows = [dict(bits=label(i), candidates=f"{scored[i]:,}") for i in sorted(scored) if scored[i]]
    return ["SCORES  (the candidates scored, by bits)", *text_table(pd.DataFrame(rows)), ""]


def report_patterns(engine, floor: float) -> list[str]:
    """Return the PATTERNS BY SCORE section: each band's 12 commonest patterns of levels, below and from `floor`."""
    label_of = {(x, g): label for x, g, label in engine.rows("SELECT comparison, gamma, label FROM model")}
    patterns = engine.frame("SELECT * FROM report_patterns ORDER BY up DESC, k")

    def band(up: bool) -> str:
        return f"{floor:g} and up" if up else f"0 to {floor:g}"

    def level(x, k: str) -> str:
        g = x[f"gamma_{k}"]
        return "missing" if pd.isna(g) or g < 0 else label_of[k, int(g)]

    rows = [dict(band=band(x["up"]), pairs=number(x["n"]), bits=f"{x['w']:.1f}",
                 **{k: level(x, k) for k in COMPARISONS}) for _, x in patterns.iterrows()]
    more = []  # a band with more than the 12 patterns shown: how many more, and their pairs
    for up, g in patterns.groupby("up", sort=False):
        if g["kinds"].iloc[0] > 12:
            pairs = int(g["total"].iloc[0]) - int(g["n"].sum())
            more.append(f"  {band(up)}: {int(g['kinds'].iloc[0]) - 12:,} patterns more, {pairs:,} pairs")
    return ["PATTERNS BY SCORE  (the keys' pairs at 0 bits and up, below and from the review floor: "
            "each band's 12 most common levels)", *text_table(pd.DataFrame(rows)), *more, ""]


def report_clusters(engine) -> list[str]:
    """Return the CLUSTERS section: how many entities hold each number of records."""
    sizes = dict(engine.rows("SELECT size, entities FROM report_clusters"))
    bins = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5–9", 5, 9), ("10–49", 10, 49),
            ("50+", 50, math.inf)]
    counted = []
    for name, low, high in bins:
        if total := sum(v for k, v in sizes.items() if low <= k <= high):
            counted.append(f"{name}: {total:,}")
    return ["CLUSTERS  (size: how many)", "  " + " · ".join(counted), ""]


def report_steps(counts, notes: dict, steps: dict[str, float], job: str) -> list[str]:
    """Return the STEPS section: each stage's seconds, with what it made."""
    def n(column: str) -> str:
        return number(counts[column])

    kept = " · the build's model" if job != "build" else ""
    facts = dict(
        records=f"records {n('added')} · set_aside {n('set_aside')} · companies {n('companies')} · "
                f"persons {n('persons')} · not sure {n('unsure')}",
        fit=f"fit_rows {notes['fit_rows']:,}{kept} · sampled_again {len(notes.get('sampled_again', [])):,}",
        score=f"candidates {n('candidates')} · stored {n('scored')} · rule pairs {n('ruled')} · "
              f"oversized_kept {n('oversized_kept')} · oversized_skipped {n('oversized_skipped')}",
        decide=f"decided {n('decided')} · entities {n('entities')}")
    rows = [dict(step=s, seconds=f"{x:.2f}", facts=facts.get(s, "")) for s, x in steps.items()]
    return ["STEPS", *text_table(pd.DataFrame(rows)), ""]


def report_keys(keys: pd.DataFrame) -> list[str]:
    """Return the KEYS section: the pairs each key lists, most first."""
    table = pd.DataFrame(dict(key=keys["name"], pairs=keys["pairs"].map(number)))
    return ["KEYS  (pairs each lists, most first)", *text_table(table), ""]


def report_model(engine, notes: dict) -> list[str]:
    """Return the MODEL section: the prior, what EM learned from, and each level's m, u and bits."""
    fit_row = engine.frame("SELECT * FROM fit").iloc[0]
    levels = engine.frame("SELECT comparison, label, file_m, file_u, bits FROM model ORDER BY position, gamma DESC")
    prior = json.loads(fit_row["fitted"])["prior_bits"]
    skipped = f"; learned nothing about {', '.join(notes['skipped'])}" if notes.get("skipped") else ""
    head = (f"MODEL  (prior {prior:.2f} bits at {number(fit_row['records'])} records; "
            f"fitted on {number(fit_row['fit_rows'])} records{skipped})")
    em = []
    if notes.get("em_pairs"):
        em.append("  EM learned from: " + " · ".join(f"{k} {v:,} pairs" for k, v in notes["em_pairs"].items()))
    table = pd.DataFrame(dict(comparison=levels["comparison"], level=levels["label"],
                              m=levels["file_m"].map(lambda x: f"{x:.4f}" if x >= 1e-3 else f"{x:.2e}"),
                              u=levels["file_u"].map(lambda x: f"{x:.2e}"),
                              bits=levels["bits"].map(lambda x: f"{x:.2f}")))
    adjusted = [f"  {k} {lv}: {why} (EM said {was:+.2f} bits)" for k, lv, why, was in notes.get("file_adjusted", [])]
    return [head, *em, *text_table(table), *adjusted, ""]


def report_blocks(keys: pd.DataFrame, counts) -> list[str]:
    """Return the BLOCKS section: the keys with oversized blocks, and the six that list the most pairs a record."""
    blocks = keys.assign(per_record=keys["pairs"] / max(int(counts["records"]), 1))
    busiest = blocks.nlargest(6, "per_record")["name"]
    shown = blocks[(blocks["oversized"] > 0) | blocks["name"].isin(busiest)]
    shown = shown.sort_values("per_record", ascending=False, kind="stable")
    table = pd.DataFrame(dict(kind="generator", name=shown["name"],
                              per_record=shown["per_record"].map(lambda x: f"{x:.2f}"),
                              largest=shown["largest"].map(number), oversized=shown["oversized"].map(number)))
    return [f"BLOCKS  ({number(keys['pairs'].sum())} pairs the keys list, before dedupe)", *text_table(table)]


def unmapped(engine, c: dict, patterns: dict[str, str]) -> pd.DataFrame | None:
    """Return the input's columns that no field reads (config.toml's [input] columns), on its first 10,000 rows.

    For each column: the share filled, the share of filled values held once, and the field whose look ([report]
    patterns) its values have most, with that share; best fit first. DuckDB only: it reads the file's own columns by
    their names. O(sample · columns · fields).
    """
    read = {x.casefold() for x in c["input"]["columns"]}
    columns = [x for x, _ in engine.columns("input") if x.casefold() not in read]
    if not columns:
        return None

    def quote(x: str) -> str:
        return '"' + x.replace('"', '""') + '"'

    con = engine.con
    cast = ", ".join(f"CAST({quote(x)} AS VARCHAR) AS {quote(x)}" for x in columns)
    con.execute(f"CREATE OR REPLACE TEMP TABLE nayose_sample AS SELECT {cast} FROM input LIMIT 10000")
    n = max(1, con.execute("SELECT COUNT(*) FROM nayose_sample").fetchall()[0][0])
    filled = "SELECT * FROM (UNPIVOT nayose_sample ON COLUMNS(*) INTO NAME c VALUE v) WHERE trim(v, ?) <> ''"
    counted = con.execute(f"SELECT c, COUNT(*), COUNT(DISTINCT v) FROM ({filled}) GROUP BY c", [BLANK]).fetchall()
    shape = {x: (k / n, d / max(1, k)) for x, k, d in counted}
    fits = {x: {} for x in columns}
    for field, pattern in patterns.items():
        matched = con.execute(f"SELECT c, AVG(regexp_matches(v, ?)::INT) FROM ({filled}) GROUP BY c", [pattern, BLANK])
        for x, share in matched.fetchall():
            fits[x][field] = share
    best = {x: max(fits[x].items(), key=lambda kv: kv[1], default=("", 0.0)) for x in columns}
    rows = [dict(column=x, filled=shape.get(x, (0.0, 0.0))[0], distinct=shape.get(x, (0.0, 0.0))[1],
                 looks_like=best[x][0] if best[x][1] > 0 else "", share=best[x][1]) for x in columns]
    return pd.DataFrame(rows).sort_values(["share", "filled"], ascending=False, kind="stable", ignore_index=True)


def code_version() -> str:
    """Return the commit the code is at, with a + when this copy's tracked files differ from it."""
    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, text=True, timeout=10)
        return done.stdout.strip()

    try:
        head, dirty = git("rev-parse", "--short", "HEAD"), git("status", "--porcelain", "--untracked-files=no")
        return (head or "unknown") + ("+" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# ---------- running SQL ----------

def statements(text: str) -> list[str]:
    """Split a stage file into its statements, in order.

    Each statement ends with a line ending in ';', outside a -- comment. Comments stay with the statement they
    precede. Raises ValueError for text left without its closing ';'.
    """
    out, lines = [], []
    for line in text.splitlines():
        lines.append(line)
        if line.split("--")[0].rstrip().endswith(";"):
            out.append("\n".join(lines).rstrip().rstrip(";"))
            lines = []
    if rest := [line for line in lines if line.strip() and not line.strip().startswith("--")]:
        raise ValueError(f"a statement without its closing ';': {' '.join(rest).strip()[:120]}")
    return out


def statement_making(stage_name: str, table: str) -> str:
    """Return the statement of nayose/sql/<stage_name>.sql that makes `table`."""
    return next(s for s in statements((SQL / f"{stage_name}.sql").read_text(encoding="utf-8"))
                if (head := WRITE.match(s)) and head["table"] == table)


def stage(engine, name: str, scratch: set | None = None, until: str | None = None, **values: object) -> None:
    """Run the stage nayose/sql/<name>.sql on `engine`, its statements in order (run_file)."""
    run_file(engine, SQL / f"{name}.sql", scratch=scratch, until=until, **values)


def run_file(engine, path: Path, scratch: set | None = None, until: str | None = None, **values: object) -> None:
    """Run the SQL file at `path` on `engine`, its statements in order.

    Each statement is given the values it names as @name, and only those: BigQuery refuses a parameter a statement
    doesn't read. A statement whose leading comments say `-- when: <condition>` runs only where the condition holds;
    in a deployed procedure, the condition becomes an IF (engines.procedures). With `scratch` (a lookup), each
    statement first goes through for_lookup, so that it writes temporary tables alone. With `until`, the file stops
    after the statement that makes that table, whether or not it ran.
    """
    for sql in statements(path.read_text(encoding="utf-8")):
        named = set(PARAMETER.findall(NOT_CODE.sub("", sql)))
        guard = when(sql)
        guard_values = set(PARAMETER.findall(guard)) if guard else set()
        if missing := (named | guard_values) - set(values):
            raise ValueError(f"{path.name} names @{', @'.join(sorted(missing))}, which no value gives")
        if not guard or engine.value(f"SELECT {guard}", {k: values[k] for k in guard_values}):
            runnable = for_lookup(sql, scratch) if scratch is not None else sql
            if runnable is not None:
                engine.run(runnable, {k: values[k] for k in named})
        if until is not None and (head := WRITE.match(sql)) and head["table"] == until:
            return


def when(sql: str) -> str | None:
    """Return a statement's condition, from a `-- when: <condition>` line among its leading comments, or None.

    A comment after the condition is left out. Raises ValueError where a statement holds two conditions, where a
    function holds one (the deploy makes functions apart from the procedures), or where one stands past the
    statement's leading comments.
    """
    leading = re.match(r"\A(?:\s*--[^\n]*\n)*", sql)[0]
    conditions = WHEN.findall(leading)
    if len(conditions) > 1 or (conditions and TEMP_FUNCTION.match(sql)) or len(WHEN.findall(sql)) > len(conditions):
        raise ValueError("a statement holds one condition, in its leading comments, and a function none: "
                         f"{sql.strip()[:80]}")
    if not conditions:
        return None
    return conditions[0].split("--")[0].strip() or None


def for_lookup(sql: str, temp: set) -> str | None:
    """Return `sql` as a lookup runs it, so that it never writes the run's tables; None to skip it.

    - A table or view it makes becomes a temporary table, unclustered, and its name is added to `temp`. A view
      can't stay one: BigQuery's views read the run's tables, never a session's.
    - A table it makes only if missing is skipped where `temp` already holds it (copy_for_lookup copied it first).
    - A table it changes must be one of `temp`'s; any other is refused.
    - Any other statement must only read, or make a temporary table or function; any other is refused.
    A statement reads a temporary table before the run's table of the same name, on both engines.
    """
    head = WRITE.match(sql)
    if not head:
        if READ_OR_TEMP.match(sql):
            return sql
        raise ValueError(f"a lookup can't tell what this statement writes, so it isn't run: {sql.strip()[:80]}")
    verb, table = " ".join(head["verb"].upper().split()), head["table"]
    if verb == "CREATE TABLE IF NOT EXISTS" and table in temp:
        return None
    if verb.startswith("CREATE"):
        temp.add(table)
        # a temporary table can't be clustered
        rest = re.sub(r"^\s*CLUSTER\s+BY\s+\w+(?:\s*,\s*\w+)*", "", sql[head.end():], flags=re.I)
        return f"{head['lead']}CREATE OR REPLACE TEMP TABLE {table}{rest}"
    if table not in temp:
        raise ValueError(f"a lookup would write the run's {table} ({verb}): it holds no temporary table of that name")
    return sql


def fingerprint(root: Path = HERE, mapping_file: Path | None = None) -> str:
    """Return the hash of what an update needs unchanged since its build.

    It covers every stage file, the values (config.toml), the input's mapping and the name model, each by name and
    content, and every function the deploy makes outside the SQL files (engines.functions: the comparisons, the hash,
    nfkc and the Python UDFs, em.py's and entities.py's whole source). Any byte counts, a comment's too: a run built
    before an edit is built again. DuckDB's twins of the comparisons are held to them by tests/test_functions.py. A
    build stores the hash in the table method; an update or a lookup refuses a run whose hash differs. `root` is the
    nayose folder to hash; `mapping_file` is the deployment's mapping, where the deploy has one.
    """
    if root == HERE:
        config_file = Path(os.environ.get("NAYOSE_CONFIG") or HERE / "config.toml")
        the_mapping = mapping_file or mapping()
        name_model = NAME_MODEL
    else:
        config_file, the_mapping = root / "config.toml", mapping_file or root / "mapping.sql"
        name_model = root.parent / "config" / NAME_MODEL.name
    inputs = (config_file, the_mapping, name_model)
    hashed = [*(root / "sql").glob("*.sql"), *(p for p in inputs if p.exists())]
    digest = hashlib.sha256()
    for f in sorted(hashed, key=lambda p: p.name):
        digest.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    from nayose.engines import functions  # engines imports this module, so not at its top
    digest.update("\0".join(functions("dataset.d")).encode() + b"\0")  # as the deploy makes them, any dataset alike
    return digest.hexdigest()
