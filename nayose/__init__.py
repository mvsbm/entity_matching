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
import re
import tomllib
from pathlib import Path

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
    model = np.load(NAME_MODEL)
    engine.put("name_weights", pd.DataFrame({"term": model["terms"].tolist(), "w": model["coef"]}))
    stage(engine, "functions")
    run_file(engine, HERE / "mapping.sql", nulls=nulls_pattern(c["input"]["nulls"]))
    r = c["records"]
    stage(engine, "records", hiragana=HIRAGANA, katakana=KATAKANA, katakana_block=KATAKANA_BLOCK, one_byte=ONE_BYTE, kana_fold_from=r["kana_fold_from"], kana_fold_to=r["kana_fold_to"],
          legal_pattern=legal_pattern(r), prefecture_pattern=f"^(?:{'|'.join(map(re.escape, r['prefectures']))})",
          flag_company=list(r["flag_company"]), name_line=float(r["name_line"]), trust_flag=bool(r["trust_flag"]),
          shared_name_column=bool(r["shared_name_column"]), ngram=int(r["ngram"]), intercept=float(model["intercept"]),
          min_block=int(r["min_block"]), spread=int(r["spread"]), crowd=int(r["crowd"]), lookup=lookup)


def fit(engine, refit: bool = True) -> None:
    """Stage 2 on `engine`, after records: fit.sql, with config.toml [fit]. O(n + S·K) on the sample, O(N + S·K) on the
    file. refit False (an update): the build's model kept, its u measured again on the run's records."""
    c = config()["fit"]
    stage(engine, "functions")
    stage(engine, "fit", fit_rows=int(c["fit_rows"]), seed=str(c["seed"]), fit_u_max_pairs=float(c["fit_u_max_pairs"]),
          u_max_pairs=float(c["u_max_pairs"]), settings=json.dumps(c), refit=refit)


def score(engine, lookup: bool = False) -> None:
    """Stage 3 on `engine`, after fit: score.sql, with config.toml [score]. O(Δ·b + C·K·L²) + O(N·L) for the keys.
    `lookup`: every candidate scored, whatever its points (lookup)."""
    c = config()["score"]
    stage(engine, "functions")
    stage(engine, "score", keys=list(c["keys"]), rules=list(c["rules"]), keep_from=-math.inf if lookup else float(c["keep_from"]),
          search_floor=float(c["search_floor"]), oversized=int(c["oversized"]))


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
    stage(engine, "decide", blank=BLANK)


def match(engine, threshold: float) -> None:
    """The match job on `engine`, after decide: match.sql at `threshold` points. A threshold below [score] keep_from is
    refused: the run keeps no pair below it. O(C + P·F)."""
    floor = float(config()["score"]["keep_from"])
    if threshold < floor:
        raise InputError(f"threshold {threshold:g}: the run keeps the pairs from {floor:g} points up only",
                         fix=f"give a threshold of {floor:g} or more, or lower [score] keep_from in config.toml and build the run again")
    stage(engine, "functions")
    stage(engine, "match", threshold=float(threshold))


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
