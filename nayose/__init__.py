"""nayose: entity resolution for Japanese customer records, written as BigQuery SQL and run by a little Python.

The method is SQL in BigQuery's dialect, one file per stage (nayose/sql/<stage>.sql), each read top to bottom.
BigQuery runs the SQL as written. DuckDB, on a laptop or in CI, runs it after sqlglot translates it
(nayose/engines.py). A run is a set of tables: a BigQuery dataset, or a DuckDB database file.

The jobs:
    build(engine, files)            make a run from its first batch: records, fit, score, decide
    update(engine, files)           add a batch: its records, its pairs scored with the build's model, decide
    decide(engine, files)           store people's decisions and make the entities from them (decide.sql)
    match(engine, threshold)        list the pairs at a threshold for people, less those they said differ (match.sql)
    lookup(engine, record|values)   find the entities a record would join, as an update of it alone, writing nothing

The stages the jobs run:
    records(engine, files)          stage 1: read the input files, map them (mapping.sql), make records (records.sql)
    fit(engine)                     stage 2: learn the model on a sample, then u on the file (fit.sql, nayose/em.py)
    score(engine)                   stage 3: the rules' pairs, the generators' candidates and their scores (score.sql)
    report(engine, steps, job)      after a build or an update: report.sql, then report.txt (nayose/reporting.py)

Running SQL:
    stage(engine, name, **values)   run a stage file's statements in order, each given the values it names (@name)
    statements(text)                split a stage file into statements: each ends with a line that ends in ';'
    fingerprint()                   hash what every job after a build needs unchanged: the SQL, the values, the
                                    mapping and the name model
"""
import contextlib
import functools
import hashlib
import json
import math
import os
import re
import tomllib
import typing
from pathlib import Path

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
MAPPED = ("input_rows", "mapped")  # the tables a mapping makes, for records.sql
METHOD = "CREATE OR REPLACE TABLE method AS SELECT @fingerprint AS fingerprint"  # a build's last statement
CHANGED = ("the method, its values or the mapping changed since the run was built: "
           "this code would read its tables, and score its batches, otherwise")
UNCHANGED = (f"SELECT IF((SELECT fingerprint FROM method) IS DISTINCT FROM @fingerprint, "  # a NULL one differs too
             f"ERROR('{CHANGED}; build the run again'), 0)")
QUERY = "￿asked"  # the ID of a record looked up by its values: no record has it, and it sorts after every ID
SHOWN = ("full_name", "person_name", "company_name", "address", "postal_code", "phone", "birth_date", "customer_id")
BLANK = "".join(ch for ch in map(chr, range(0x3001)) if ch.isspace())  # a blank value's characters: Python's whitespace
COMPARISONS = ("name", "company", "address", "phone", "cif", "birth")  # the model's, in its order
FIELDS = (  # a record's fields, as report.txt lists them
    "full_name", "person_name", "given_name", "company_name", "any_name", "address", "address_code", "postal_code",
    "prefecture", "town_code", "city", "phone", "customer_id", "birth_date")

# Reading a statement from its text: run_file, for_lookup and the deploy's procedures do.
PARAMETER = re.compile(r"@(\w+)")  # a value a statement reads, by name: run_file passes it, the deploy declares it
NOT_CODE = re.compile(  # a comment (-- or /* */), or any of BigQuery's strings and quoted names: not code
    r"""--[^\n]*|/\*.*?\*/|'''.*?'''|\"\"\".*?\"\"\"|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`[^`]*`""", re.S)
WHEN = re.compile(r"^\s*--\s*when:(.*)$", re.M | re.I)  # a `-- when: <condition>` line: see when()
LEAD = r"(?P<lead>(?:\s*--[^\n]*\n|\s*/\*.*?\*/)*\s*)"  # a statement's leading comments
# A statement that writes a table: its leading comments, its verb, and the table it writes. The verbs are tried in
# order and the first that fits wins, so a verb comes before any shorter one it starts with: CREATE TABLE IF NOT
# EXISTS x before CREATE TABLE, which would read the table as IF.
WRITE = re.compile(rf"^{LEAD}(?P<verb>" r"""
      CREATE\s+OR\s+REPLACE\s+TEMP(?:ORARY)?\s+TABLE
    | CREATE\s+OR\s+REPLACE\s+TABLE
    | CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS
    | CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW
    | CREATE\s+TABLE
    | INSERT(?:\s+INTO)?
    | DELETE(?:\s+FROM)?
    | UPDATE
    | MERGE(?:\s+INTO)?
    | TRUNCATE\s+TABLE
    )\s+`?(?P<table>\w+)`?""", re.I | re.S | re.X)
# A statement that only reads, or makes a temporary function, or makes a temporary table in a form WRITE doesn't
# read: score.sql's CREATE TEMP TABLE IF NOT EXISTS block_size, which a lookup has made already (copy_for_lookup)
READ_OR_TEMP = re.compile(
    rf"^{LEAD}(SELECT|WITH|CREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+(?:FUNCTION|TABLE))\b", re.I | re.S)
TEMP_FUNCTION = re.compile(  # a statement that makes a temporary function: its leading comments and the function's name
    rf"^{LEAD}CREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+FUNCTION\s+(?P<name>\w+)", re.I | re.S)


class Engine(typing.Protocol):
    """What the jobs run SQL on, BigQuery's dialect: engines.DuckDB or engines.BigQuery, which answer alike."""

    name: str  # "duckdb" or "bigquery"
    MISSING: tuple[type[Exception], ...]  # what a query of a table the run lacks raises

    def run(self, sql: str, values: dict | None = None) -> None: ...  # a statement, given its @values
    def rows(self, sql: str, values: dict | None = None) -> list[tuple]: ...
    def value(self, sql: str, values: dict | None = None) -> object: ...  # the first row's first value
    def frame(self, sql: str, values: dict | None = None) -> pd.DataFrame: ...  # a small result only
    def columns(self, table: str) -> list[tuple[str, str]]: ...  # a table's columns, as (name, type)
    def put(self, table: str, frame: pd.DataFrame) -> None: ...  # a small frame made a table
    def read_parquet(self, table: str, files: list, columns: list[str] = ()) -> None: ...  # input files as a table
    def scratch(self) -> contextlib.AbstractContextManager: ...  # temporary tables that end with it
    def close(self) -> None: ...


class InputError(ValueError):
    """A refusal the person running the job can act on: what is wrong (the message), and how to fix it (`fix`)."""

    def __init__(self, message: str, fix: str = "") -> None:
        super().__init__(message)
        self.fix = fix


# What an older config.toml names otherwise: (section, key) → as it was written, as it is written now
RENAMED = {
    ("score", "keys"): ("[score] keys", "[score] generators"),
    ("records", "min_block"): ("[records] min_block", "[records] placeholder_min"),
    ("fit", "fit_rows"): ("[fit] fit_rows", "[fit] fit_records"),
    ("fit", "sessions"): ("[fit] sessions", "[fit] em_sessions"),
    ("report", "patterns"): ("[report.patterns]", "[report.looks]"),
}
ADDED = (("report", "sample_records"), ("report", "patterns_shown"))  # what an older config.toml lacks


def config() -> dict:
    """Return config.toml, or the file NAYOSE_CONFIG names (a variant, at design time).

    Raises InputError for a key an older config.toml names otherwise (RENAMED, and an EM session's key, now its field),
    or one it lacks (ADDED).
    """
    path = Path(os.environ.get("NAYOSE_CONFIG") or HERE / "config.toml")
    c = tomllib.loads(path.read_text(encoding="utf-8"))
    for (section, key), (was, now) in RENAMED.items():
        if key in c.get(section, {}):
            raise InputError(f"{path.name}: {was} is named {now} now", fix=f"rename {was} {now}")
    if any("key" in session for session in c.get("fit", {}).get("em_sessions", [])):
        raise InputError(f"{path.name}: [fit] em_sessions' key is named field now",
                         fix="rename each session's key field")
    for section, key in ADDED:
        if key not in c.get(section, {}):
            raise InputError(f"{path.name}: [{section}] lacks {key}",
                             fix=f"add [{section}] {key}, as nayose/config.toml has it")
    return c


def mapping() -> Path:
    """Return the path of mapping.sql, or of the file NAYOSE_MAPPING names (another input's columns)."""
    return Path(os.environ.get("NAYOSE_MAPPING") or HERE / "mapping.sql")


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
    be one query, or make one temporary table with a name the method doesn't use (in any case), and its comments
    should start with --. A # comment is refused. A /* */ one is not, unless a line in it ends in ';' (the last
    reason). The reasons:
    - a table of its own would be dropped by the next build, which makes again every table it writes;
    - a temporary table named like one of the method's would hide it, as a statement reads a temporary table first;
    - a function of its own would replace one of the method's on BigQuery, but not on DuckDB;
    - nayose finds a statement's end past -- comments alone (statements): in a /* */ comment, a line ending in ';'
      ends the statement.
    """
    try:
        out = statements(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise InputError(f"{path.name}: {e}",
                         fix="end each statement with a line ending in ';', and start a comment with --") from e
    for sql in out:
        check_mapping_statement(path.name, sql)
    return out


def check_mapping_statement(file: str, sql: str) -> None:
    """Raise InputError unless one statement of the mapping `file` keeps to a mapping's form (mapping_statements)."""
    tail = " ".join(sql.split())[-100:]
    if "#" in NOT_CODE.sub("", sql):
        raise InputError(f"{file}: a comment starts with --, as in the method's files: {tail}",
                         fix="write each # comment as --")
    try:
        parsed = sqlglot.parse(sql, read="bigquery")
    except sqlglot.errors.SqlglotError as e:  # ParseError; TokenError where a line ending in ';' cut a /* */ comment
        raise InputError(f"{file}: a statement doesn't parse as BigQuery's: {tail}",
                         fix=f"{str(e).splitlines()[0]}; start each comment with --, as a line ending in ';' ends a "
                             "statement even in a /* */ comment") from e
    trees = [t for t in parsed if t is not None and not isinstance(t, exp.Semicolon)]  # a comment after ';' too
    tree = trees[0] if len(trees) == 1 else None
    name = temp_table_name(tree)
    if isinstance(tree, exp.Create) and tree.kind == "FUNCTION":
        raise InputError(f"{file}: a mapping makes no function of its own: {tail}",
                         fix="write it in place, or call one of functions.sql's")
    if name is not None and name.lower() in method_tables():
        raise InputError(f"{file}: the temporary table {name} has the name of one of the method's tables, "
                         "which it would hide", fix="give it a name of its own")
    if name is None and not isinstance(tree, exp.Query):
        raise InputError(f"{file}: a mapping reads, and makes temporary tables alone, "
                         f"one statement to a line ending in ';': {tail}",
                         fix="make it CREATE OR REPLACE TEMP TABLE <a name of its own> AS SELECT …")


def temp_table_name(tree: exp.Expression | None) -> str | None:
    """Return the name of the temporary table a parsed statement makes, or None where it makes none."""
    if not (isinstance(tree, exp.Create) and tree.kind == "TABLE" and tree.find(exp.TemporaryProperty)):
        return None
    made = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this  # a column list wraps the name
    return made.name


def legal_regex(section: dict) -> str:
    """Return the regex of a legal form, from config.toml's [records] `section`, matched on NFKC text.

    It matches a legal form anywhere, also with its small kana written large, or a bank's abbreviation where one
    may stand: first, as in カ)〇〇, or last, as in 〇〇(カ. Longer forms come first, so 医療法人社団 isn't
    cut to 医療法人.
    """
    spellings = {f for x in section["legal_forms"] for f in (x, x.translate(SMALL_KANA))}
    forms = sorted(spellings, key=lambda f: (-len(f), f))  # one order, so every run builds the same regex
    parts = [re.escape(f) for f in forms]
    if section["legal_front"]:
        parts.append(f"^(?:{'|'.join(map(re.escape, sorted(section['legal_front'], key=len, reverse=True)))})\\)")
    if section["legal_end"]:
        parts.append(f"\\((?:{'|'.join(map(re.escape, sorted(section['legal_end'], key=len, reverse=True)))})$")
    return "|".join(parts)


def null_regex(nulls: list[str]) -> str:
    """Return the RE2 regex of a value read_value reads as missing.

    That is one of `nulls`, with spaces or U+3000 around it or not, or a value of spaces alone (Python's whitespace,
    as str.strip removes it).
    """
    return (r"^[ \x{3000}]*(?:" + "|".join(map(re.escape, nulls)) + r")[ \x{3000}]*$"
            r"|^[\t-\r\x{1c}-\x{20}\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]*$")


def records(engine: Engine, files: list | None, temp: set | None = None) -> None:
    """Run stage 1 on `engine`: load the input files, then run mapping.sql and records.sql.

    The files become the table input, with every column mapping.sql reads that a file lacks, as missing; with
    `files` None, the table input is used as it is. The name model's weights become the table name_weights. With
    `temp`, a lookup's temporary tables, the input is a record asked about, and the stage writes temporary tables
    alone (run_file), reading the run's name model as it is. O(Δ·L), plus O(N) for the placeholders.
    """
    lookup = temp is not None
    c = config()
    if bad := [x for x in c["input"]["columns"] if not NAME.match(x)]:
        raise ValueError(f"config.toml [input] columns: {bad} are no plain column names")
    mapping_statements(mapping())  # refused before the job writes anything
    if files is not None:
        engine.read_parquet("input", files, c["input"]["columns"])
    if not lookup:
        engine.put("name_weights", name_weights())
    stage(engine, "functions", temp=temp)
    run_file(engine, mapping(), temp=temp, **values_of("mapping"))
    stage(engine, "records", temp=temp, **values_of("records", lookup=lookup))
    if files is not None and engine.name == "duckdb":
        # DuckDB holds a temporary table whole, so it keeps only the rows the report samples (unmapped)
        sample = int(c["report"]["sample_records"])
        engine.run(f"CREATE OR REPLACE TEMP TABLE input AS SELECT * FROM input LIMIT {sample}")


def name_weights() -> pd.DataFrame:
    """Return the name model (config/kind_names.npz) as a table: each character n-gram and its coefficient."""
    model = np.load(NAME_MODEL)
    return pd.DataFrame({"term": model["terms"].tolist(), "coef": model["coef"]})


def values_of(name: str, refit: bool = True, lookup: bool = False) -> dict:
    """Return the values stage `name` reads as @name, from config.toml.

    A run here passes them as query parameters; a BigQuery procedure declares them (engines.procedures). `refit` is
    True for a build, False for a build given a model, which keeps it. With `lookup`, the batch is a record asked about.
    match's @threshold and lookup.sql's values come from their jobs.
    """
    c = config()
    if name == "mapping":
        return dict(nulls=null_regex(c["input"]["nulls"]))
    if name == "records":
        r = c["records"]
        return dict(hiragana=HIRAGANA, katakana=KATAKANA, katakana_block=KATAKANA_BLOCK, one_byte=ONE_BYTE,
                    kana_fold_from=r["kana_fold_from"], kana_fold_to=r["kana_fold_to"], legal_regex=legal_regex(r),
                    prefecture_regex=f"^(?:{'|'.join(map(re.escape, r['prefectures']))})",
                    flag_company=list(r["flag_company"]), name_line=float(r["name_line"]),
                    trust_flag=bool(r["trust_flag"]), shared_name_column=bool(r["shared_name_column"]),
                    ngram=int(r["ngram"]),
                    intercept=float(np.load(NAME_MODEL)["intercept"]), placeholder_min=int(r["placeholder_min"]),
                    spread=int(r["spread"]), crowd=int(r["crowd"]), lookup=lookup)
    if name == "fit":
        f = c["fit"]
        return dict(fit_records=int(f["fit_records"]), seed=str(f["seed"]), fit_u_max_pairs=float(f["fit_u_max_pairs"]),
                    u_max_pairs=float(f["u_max_pairs"]), settings=json.dumps(f), refit=refit)
    if name == "score":
        s = c["score"]
        return dict(generators=list(s["generators"]), rules=list(s["rules"]),
                    keep_from=-math.inf if lookup else float(s["keep_from"]), search_floor=float(s["search_floor"]),
                    oversized=int(s["oversized"]), lookup=lookup, outside=0)
    if name == "report":
        floor, likely = float(c["lookup"]["at_least"]), float(c["lookup"]["likely_from"])
        looks = {**c["report"]["looks"], "company_name": legal_regex(c["records"])}
        return dict(looks=json.dumps(looks, ensure_ascii=False),
                    edges=sorted({-20.0, -10.0, 0.0, floor, likely, likely + 2, likely + 4, likely + 8, likely + 12}),
                    floor=floor, oversized=int(c["score"]["oversized"]),
                    sample_records=int(c["report"]["sample_records"]),
                    patterns_shown=int(c["report"]["patterns_shown"]))
    return {}


def fit(engine: Engine, model: str | None = None) -> None:
    """Run stage 2 on `engine`, after records: fit.sql, with config.toml's [fit].

    With `model`, a model fitted elsewhere (what a fit returned), the table fit is made to hold it, and fit.sql keeps
    it and measures only its u on the records. O(n + S·K) on the sample of n records, S sampled pairs and K
    comparisons, and O(N + S·K) on the file.
    """
    if model is not None:
        engine.run("CREATE OR REPLACE TABLE fit AS SELECT CAST(NULL AS FLOAT64) AS probability, "
                   "CAST(NULL AS INT64) AS fit_records, CAST(NULL AS INT64) AS records, "
                   "CAST(NULL AS FLOAT64) AS prior_bits, "
                   "CAST(NULL AS STRING) AS notes, @fitted AS fitted",
                   {"fitted": model})
    stage(engine, "functions")
    stage(engine, "fit", **values_of("fit", refit=model is None))


def score(engine: Engine, temp: set | None = None, until: str | None = None, outside: int = 0) -> None:
    """Run stage 3 on `engine`, after fit: score.sql, with config.toml's [score].

    With `temp`, a lookup's temporary tables, every candidate is scored, whatever its points, in temporary tables, up
    to the table `until` makes; `outside` is how many of the run's records the records table doesn't hold (a lookup's
    holds its blocks' records alone). O(Δ·b + C·K·L²), plus O(Δ·L) for the keys and a scan of the key index.
    """
    lookup = temp is not None
    stage(engine, "functions", temp=temp)
    stage(engine, "score", temp=temp, until=until, **(values_of("score", lookup=lookup) | {"outside": outside}))


# ---------- lookup ----------

def lookup(engine: Engine, record: str | None = None, values: dict | None = None, at_least: float | None = None,
           most: int | None = None) -> dict:
    """Return the entities a record would be compared with, as an update of it alone compares it, best first.

    Give `record`, a stored record's ID, to look it up as if it were new (itself left out), or `values`, by the
    input's column names. The answer lists each entity at `at_least` points or more ([lookup] at_least, the review
    floor), or joined by a rule, with its best record, its points, each comparison's level, the rule that would join
    it and the generators whose keys listed it: at most `most` of them, else the closest record. It also gives the
    record as compared, and what each generator looked up.

    A lookup writes nothing to the run, and reads only what it touches, in three steps: the record's own keys
    (asked_keys), the run's key index read by those keys (read_index), and the record scored against those records
    alone (score_asked). Each step works in temporary tables that end with it (engine.scratch). Each statement of a
    SQL file goes through for_lookup, which refuses any write to a run's table. The lookup's own statements write
    temporary tables alone: copy_for_lookup's make them, and add_asked_record's three, run directly, make this_batch and
    give a stored record asked about its batch in the copy of records, or make a typed record's input. O(G) for its
    G keys + O(b + C·K·L²): b the pairs its keys list, C its candidates, K the comparisons, L a value's length.
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
    unchanged(engine, build_again("look up"))  # the key index and the scores are the build's method's
    if record is not None and not engine.value("SELECT COUNT(*) FROM records WHERE id = @id", {"id": asked_id}):
        raise InputError(f"{record}: no record of the run has that ID",
                         fix="give a record ID the run holds, or the record's values")
    run_size = engine.value("SELECT COUNT(*) FROM records")
    keys = asked_keys(engine, record, values, asked_id)
    ids, blocks = read_index(engine, keys, record, asked_id, int(c["score"]["oversized"]))
    asked_record, candidates, entities, checked = score_asked(engine, record, values, asked_id, ids, blocks, run_size,
                                                              at_least)
    return lookup_answer(record, asked_record, candidates, entities, checked, at_least, most)


def asked_keys(engine: Engine, record: str | None, values: dict | None, asked_id: str) -> dict[str, set]:
    """Return the keys of the record asked about, made from it alone: its every_key and rule_keys rows (step 1)."""
    with engine.scratch():
        score_in_scratch(engine, record, values, [asked_id] if record is not None else [], until="made_keys")
        return {"every_key": set(engine.rows("SELECT g, key FROM made_keys WHERE id = @id", {"id": asked_id})),
                "rule_keys": set(engine.rows("SELECT i, key FROM made_rule_keys WHERE id = @id", {"id": asked_id}))}


def read_index(engine: Engine, keys: dict[str, set], record: str | None, asked_id: str,
               oversized: int) -> tuple[set, dict]:
    """Return the records the run's key index holds under the record's keys (step 2).

    That is every record of each rule key and of each block, but of an oversized block (`oversized` records or more)
    only its first records by hash: the gate's sample (score.sql), and one more, so the record asked about may rank
    anywhere. Returns the IDs, and each block's (g, key) with [its size, the IDs read].
    """
    ids = {asked_id} if record is not None else set()
    if keys["rule_keys"]:
        rows = engine.rows("SELECT i, key, id FROM rule_keys WHERE key IN UNNEST(@keys)",
                           {"keys": sorted({key for _, key in keys["rule_keys"]})})
        ids |= {record_id for rule_rank, key, record_id in rows if (rule_rank, key) in keys["rule_keys"]}
    blocks = {}
    if keys["every_key"]:
        rows = engine.rows("SELECT g, key, id, COUNT(*) OVER (PARTITION BY g, key) AS n FROM every_key "
                           "WHERE key IN UNNEST(@keys) QUALIFY COUNT(*) OVER (PARTITION BY g, key) < @oversized "
                           "OR ROW_NUMBER() OVER (PARTITION BY g, key ORDER BY er_hash(id)) <= @oversized + 1",
                           {"keys": sorted({key for _, key in keys["every_key"]}), "oversized": oversized})
        for g, key, record_id, n in rows:
            if (g, key) in keys["every_key"]:
                blocks.setdefault((g, key), [n, set()])[1].add(record_id)
    return ids | {record_id for _, read in blocks.values() for record_id in read}, blocks


def score_asked(engine: Engine, record: str | None, values: dict | None, asked_id: str, ids: set, blocks: dict,
                run_size: int, at_least: float) -> tuple:
    """Score the record against the records read, and return the record as compared and lookup.sql's tables (step 3).

    A block read in part is scored at its whole size. An oversized block that the gate lists makes every pair of it a
    candidate, so that block is then read whole, from the run's index, and the record scored again: each pass reads
    more, and the loop ends once no block read in part is listed. The index is read outside the scratch, whose
    every_key is the lookup's own. Returns (the record as compared, candidates, entities, checked).
    """
    extra = 0 if record is not None else 1  # a typed record isn't in the index: its blocks hold one record more
    while True:
        with engine.scratch():
            in_part = [(g, key, n + extra) for (g, key), (n, read) in blocks.items() if n > len(read)]
            temp = score_in_scratch(engine, record, values, sorted(ids), outside=run_size - len(ids), sized=in_part)
            gate_listed = set(engine.rows("SELECT g, key FROM gated WHERE verdict = 'listed'"))
            to_read = gate_listed & {(g, key) for g, key, _ in in_part}  # a block read in part that the gate listed
            if not to_read:
                return lookup_tables(engine, temp, record, asked_id, at_least)
        read_whole(engine, to_read, blocks, ids)


def read_whole(engine: Engine, to_read: set, blocks: dict, ids: set) -> None:
    """Add every record of the blocks `to_read`, as (g, key), to `blocks` and `ids`, from the run's key index."""
    index = engine.rows("SELECT g, key, id FROM every_key WHERE key IN UNNEST(@keys)",
                        {"keys": sorted({key for _, key in to_read})})
    for g, key, record_id in index:
        if (g, key) in to_read:
            blocks[g, key][1].add(record_id)
            ids.add(record_id)


def lookup_tables(engine: Engine, temp: set, record: str | None, asked_id: str, at_least: float) -> tuple:
    """Run lookup.sql on the scored temporary tables `temp`, and return the record as compared and lookup.sql's tables.

    That is (the record as compared, candidates, entities, checked), as score_asked returns them.
    """
    c = config()
    stage(engine, "lookup", temp=temp, at_least=at_least, likely_from=float(c["lookup"]["likely_from"]),
          oversized=int(c["score"]["oversized"]), stored=record is not None)
    shown = ", ".join(SHOWN) + ("" if record is not None else ", kind")
    return (engine.frame(f"SELECT {shown} FROM records WHERE id = @id", {"id": asked_id}).iloc[0],
            engine.frame("SELECT * FROM candidates ORDER BY points DESC, id"),
            engine.frame("SELECT * FROM entities ORDER BY rule IS NULL, ROUND(points, 2) DESC, points DESC, id"),
            engine.frame("SELECT * FROM checked ORDER BY position"))


def score_in_scratch(engine: Engine, record: str | None, values: dict | None, ids: list, until: str | None = None,
                     outside: int = 0, sized: list = ()) -> set:
    """Score the record asked about in temporary tables of the run's names, and return those tables' names.

    The temporary tables hold the run as the lookup sees it (copy_for_lookup), with the record asked about as a batch
    of its own (add_asked_record). score.sql then runs on them, up to the table `until` makes. `outside` is how many
    of the run's records the temporary records table doesn't hold; `sized` gives each block it holds in part with its
    whole size, as (g, key, n).
    """
    temp = copy_for_lookup(engine, ids, sized)
    add_asked_record(engine, record, values, temp)
    engine.run(for_lookup(statement_making("fit", "compared"), temp))  # the columns score compares: fit.sql's view
    score(engine, temp=temp, until=until, outside=outside)
    return temp


def copy_for_lookup(engine: Engine, ids: list, sized: list) -> set:
    """Copy the run's tables a lookup reads into temporary tables of the same names, and return their names.

    records and gold hold `ids` alone, each read by ID (on BigQuery, from its clustering's blocks); placeholders is
    copied whole. block_size holds `sized`. A statement reads a temporary table before the run's of the same name.
    """
    if sized:  # three arrays, as a parameter is an array of values on both engines
        engine.run("CREATE OR REPLACE TEMP TABLE block_size AS SELECT g, @key[OFFSET(i)] AS key, @n[OFFSET(i)] AS n "
                   "FROM UNNEST(@g) AS g WITH OFFSET AS i",
                   {"g": [g for g, _, _ in sized], "key": [key for _, key, _ in sized], "n": [n for _, _, n in sized]})
    else:
        engine.run("CREATE OR REPLACE TEMP TABLE block_size (g INT64, key STRING, n INT64)")
    temp = {"block_size"}
    for table in ("records", "gold"):
        engine.run(f"CREATE TEMP TABLE {table} AS SELECT * FROM {table} WHERE id IN UNNEST(@ids)", {"ids": ids})
        temp.add(table)
    engine.run("CREATE TEMP TABLE placeholders AS SELECT * FROM placeholders")
    temp.add("placeholders")
    return temp


def add_asked_record(engine: Engine, record: str | None, values: dict | None, temp: set) -> None:
    """Make the record asked about a batch of its own in the temporary tables.

    A stored record (`record`) gets the next batch number. A typed one (`values`) is made a record by records.sql,
    as a file's would be; InputError is raised when every value it gives reads as missing.
    """
    if record is not None:
        temp.add("this_batch")
        engine.run("CREATE OR REPLACE TEMP TABLE this_batch AS SELECT MAX(batch) + 1 AS batch FROM records")
        engine.run("UPDATE records SET batch = (SELECT batch FROM this_batch) WHERE id = @id", {"id": record})
        return
    inputs = config()["input"]
    given = list(({x: values.get(x) for x in inputs["columns"]} | {inputs["id"]: QUERY}).items())
    temp.add("input")
    cells = ", ".join(f"CAST({'NULL' if v is None else f'@v{i}'} AS STRING) AS `{x}`" for i, (x, v) in enumerate(given))
    engine.run(f"CREATE OR REPLACE TEMP TABLE input AS SELECT {cells}",
               {f"v{i}": str(v) for i, (_, v) in enumerate(given) if v is not None})
    records(engine, None, temp=temp)
    filled = f"SELECT COUNT(*) FROM records WHERE id = @id AND COALESCE({', '.join(SHOWN)}) IS NOT NULL"
    if not engine.value(filled, {"id": QUERY}):
        shown = [f"{k}={v}" for k, v in values.items() if v not in (None, "")]
        raise InputError(f"{', '.join(shown)}: read as missing, as a file's would be" if shown else "no value given",
                         fix="give a value a record holds: a name, a phone, a postal code")


def lookup_answer(record: str | None, asked_record, candidates: pd.DataFrame, entities: pd.DataFrame,
                  checked: pd.DataFrame, at_least: float, most: int) -> dict:
    """Return what a lookup gives back (docs/data.md, "A lookup's answer"), from lookup.sql's tables."""
    answers = [entity_found(x) for _, x in entities.iterrows()]
    near = candidates.iloc[0] if len(candidates) and not answers else None
    closest = None if near is None else dict(record=near["id"], entity=near["entity"],
                                             points=round(float(near["points"]), 2), shown=shown_fields(near))
    return dict(record={"id": record, **{k: as_text(asked_record[k]) for k in asked_record.index}},
                entities=answers[:most], entities_total=len(answers), at_least=at_least, candidates=len(candidates),
                likely=sum(e["likely"] for e in answers), closest=closest,
                checked=[generator_checked(x) for _, x in checked.iterrows()])


def as_text(v) -> str | None:
    """Return a cell as text, or None where it is missing."""
    return None if pd.isna(v) else str(v)


def shown_fields(x) -> dict:
    """Return the fields a lookup shows of a record (SHOWN), from its row."""
    return {f: as_text(x[f]) for f in SHOWN}


def entity_found(x) -> dict:
    """Return one entity of a lookup's answer, from its row of lookup.sql's entities."""
    generators = sorted(x["generators"].split("+")) if as_text(x["generators"]) else []
    return dict(entity=x["entity"], record=x["id"], points=round(float(x["points"]), 2), likely=bool(x["likely"]),
                rule=as_text(x["rule"]), generators=generators, compared={k: x[f"level_{k}"] for k in COMPARISONS},
                records=int(x["records"]), shown=shown_fields(x))


def generator_checked(x) -> dict:
    """Return one generator (or rule) of a lookup's answer, from its row of lookup.sql's checked: the records its
    keys found in its blocks of normal size (in_blocks), and why not more."""
    out = dict(generator=x["generator"], in_blocks=int(x["in_blocks"]))
    if x["lacks"]:
        out["why"] = "the record has no value for it"
    if not pd.isna(x["untrusted"]):
        out["why"] = f"its value is on {int(x['untrusted']):,} records: the rule doesn't trust it"
    # a frame made from Arrow holds a list as an array, one made from rows as a list; NULL (no oversized block) neither
    if isinstance(x["oversized"], (list, np.ndarray)) and len(x["oversized"]):
        out["oversized"] = [dict(records=int(b["records"]), sampled=int(b["sampled"]),
                                 best=None if b["best"] is None else round(float(b["best"]), 2), verdict=b["verdict"])
                            for b in x["oversized"]]
    return out


# ---------- the jobs ----------

def unchanged(engine: Engine, fix: str) -> None:
    """Raise InputError (CHANGED, then `fix`) unless the run was built by this method: its fingerprint."""
    try:
        stored = engine.value("SELECT fingerprint FROM method")
    except engine.MISSING:  # no method table: a run this build didn't make
        stored = None
    if stored != fingerprint():
        raise InputError(CHANGED, fix=fix)


def build_again(job: str, out: object = None) -> str:
    """Return the fix where the method changed since the build (CHANGED): build again, or run `job` with its code.

    Where the run's folder `out` is given, the fix gives the build's command too.
    """
    command = "" if out is None else f" (python -m nayose build FILE --out {out} --overwrite)"
    return f"build the run again with them{command}, or {job} with the code the build ran"


def run_stage(name: str, do, *args) -> None:
    """Run a stage of build as it is: build's default `timed`. The CLI passes one that times each stage."""
    do(*args)


def build(engine: Engine, files: list, model: str | None = None, timed=run_stage) -> None:
    """Make a run from its first batch on `engine`, an empty run: its records, its model, its scores and its entities.

    With `model`, a model fitted elsewhere (what fit returned), the model is kept and only its u measured on these
    records. The entities are those people's decisions make: none yet, or those the run kept from before. Each stage
    is run by `timed(name, stage, *arguments)`. O(N·L + n + S·K + ΣP + C·K·L²): P a block's pairs, C the
    candidates, L a value's length.
    """
    timed("records", records, engine, files)
    timed("fit", fit, engine, model)
    timed("score", score, engine)
    timed("decide", decide, engine, [])
    engine.run(METHOD, {"fingerprint": fingerprint()})


def update(engine: Engine, files: list) -> None:
    """Add a batch to the run on `engine`.

    The batch's records are made (one already in the run is set aside), the pairs touching the batch, or a record made
    again, are scored with the model the build left, and the entities are made again. O(Δ·(L + b) + C_Δ·K·L²), plus
    O(N) scans of the run's records and keys.
    """
    unchanged(engine, build_again("update", "RUN"))
    records(engine, files)
    score(engine)
    decide(engine, [])


def decide(engine: Engine, files: list) -> None:
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
    keep_from = float(config()["score"]["keep_from"])
    if threshold < keep_from:
        raise InputError(f"threshold {threshold:g}: the run keeps the pairs from {keep_from:g} points up only",
                         fix=f"give a threshold of {keep_from:g} or more, "
                             "or lower [score] keep_from in config.toml and build the run again")


def match(engine: Engine, threshold: float) -> None:
    """Run the match job on `engine`, after decide: match.sql at `threshold` points (check_threshold). O(C + P·F)."""
    check_threshold(threshold)
    stage(engine, "functions")
    stage(engine, "match", threshold=float(threshold))


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
    stage_file = (SQL / f"{stage_name}.sql").read_text(encoding="utf-8")
    return next(s for s in statements(stage_file) if table_made(s) == table)


def stage(engine: Engine, name: str, temp: set | None = None, until: str | None = None, **values: object) -> None:
    """Run the stage nayose/sql/<name>.sql on `engine`, its statements in order (run_file)."""
    run_file(engine, SQL / f"{name}.sql", temp=temp, until=until, **values)


def run_file(engine: Engine, path: Path, temp: set | None = None, until: str | None = None,
             **values: object) -> None:
    """Run the SQL file at `path` on `engine`, its statements in order.

    Each statement is given the values it names as @name, and only those: BigQuery refuses a parameter a statement
    doesn't read. A statement whose leading comments say `-- when: <condition>` runs only where the condition holds;
    in a deployed procedure, the condition becomes an IF (engines.procedures). With `temp`, a lookup's temporary
    tables, each statement first goes through for_lookup, so that it writes temporary tables alone. With `until`, the
    file stops after the statement that makes that table, whether or not it ran.
    """
    for sql in statements(path.read_text(encoding="utf-8")):
        run_statement(engine, sql, values, temp, path.name)
        if until is not None and table_made(sql) == until:
            return


def run_statement(engine: Engine, sql: str, values: dict, temp: set | None, file: str) -> None:
    """Run one statement of `file` with the values it names, unless its `-- when:` condition is false (run_file)."""
    parameters = set(PARAMETER.findall(NOT_CODE.sub("", sql)))
    guard = when(sql)
    guard_values = set(PARAMETER.findall(guard)) if guard else set()
    if missing := (parameters | guard_values) - set(values):
        raise ValueError(f"{file} names @{', @'.join(sorted(missing))}, which no value gives")
    if guard and not engine.value(f"SELECT {guard}", {k: values[k] for k in guard_values}):
        return
    runnable = sql if temp is None else for_lookup(sql, temp)
    if runnable is None:  # a table the lookup holds already: for_lookup skips it
        return
    engine.run(runnable, {k: values[k] for k in parameters})


def table_made(sql: str) -> str | None:
    """Return the table a statement writes (WRITE), or None where it writes none."""
    head = WRITE.match(sql)
    return head["table"] if head else None


def verb_of(head: re.Match) -> str:
    """Return the verb of a statement WRITE matched, in capitals with single spaces: CREATE OR REPLACE TEMP TABLE."""
    return " ".join(head["verb"].upper().split())


def when(sql: str) -> str | None:
    """Return a statement's condition, from a `-- when: <condition>` line among its leading comments, or None.

    Only a -- line carries a condition: one within a /* */ comment is that comment's text. A comment after the
    condition is left out. Raises ValueError where a statement holds two conditions, where a function holds one (the
    deploy makes functions apart from the procedures), or where one stands past the statement's leading comments.
    """
    def lines(text: str) -> list[str]:  # the conditions of text's -- lines, outside its /* */ comments
        return WHEN.findall(NOT_CODE.sub(lambda m: " " if m[0].startswith("/*") else m[0], text))

    conditions = lines(re.match(LEAD, sql, re.S)["lead"])
    start = sql.strip()[:80]  # the statement's start, for a refusal
    if len(conditions) > 1:
        raise ValueError(f"a statement holds one condition at most: {start}")
    if conditions and TEMP_FUNCTION.match(sql):
        raise ValueError(f"a function holds no condition, as the deploy makes functions apart from procedures: {start}")
    if len(lines(sql)) > len(conditions):
        raise ValueError(f"a statement's condition stands in its leading comments: {start}")
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
    verb, table = verb_of(head), head["table"]
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
    """Return the hash of what every job after a build needs unchanged since it.

    It covers every stage file, the values (config.toml), the input's mapping and the name model, each by name and
    content, every function the deploy makes outside the SQL files (engines.functions: the comparisons, the hash,
    nfkc and the Python UDFs, em.py's and entities.py's whole source), and every value the stages read as the Python
    makes it from config.toml (values_of: the regexes, the kana maps, the name model's terms). Any byte counts, a
    comment's too: a run built before an edit is built again. DuckDB's twins of the comparisons are held to them by
    tests/test_functions.py. A build stores the hash in the table method; every other job (update, decide, match,
    lookup) refuses a run whose hash differs. `root` is the nayose folder to hash; `mapping_file` is the deployment's
    mapping, where the deploy has one.
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
    made = {stage: values_of(stage) for stage in ("mapping", "records", "fit", "score", "decide", "report")}
    digest.update(json.dumps(made, sort_keys=True, ensure_ascii=False, default=str).encode())  # the Python's part
    return digest.hexdigest()


# report.txt is reporting.py's; the package names it too, as __main__ and deploy/run.py call it (nayose.report_text)
from nayose.reporting import report, report_text  # noqa: F401
