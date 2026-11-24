"""nayose: entity resolution for Japanese customer records, as BigQuery SQL run by a few lines of Python.

The method is SQL, in BigQuery's dialect, one file per stage (nayose/sql/<stage>.sql), read top to bottom. BigQuery
runs it as written; DuckDB, on a laptop or in CI, runs it after sqlglot translates it (nayose/engines.py). A run is
a set of tables: a BigQuery dataset, or a DuckDB database file.

    records(engine, files)          stage 1: the input files read and mapped (mapping.sql), made records (records.sql)
    fit(engine)                     stage 2: the model learned on a sample, u on the file (fit.sql; EM in nayose/em.py)
    score(engine)                   stage 3: the rules' pairs, the keys' candidates and their scores (score.sql)
    decide(engine, files)           people's decisions stored, the entities made from them (decide.sql; a build: none given)
    match(engine, threshold)        the pairs at a threshold people set, less those they said differ, for them (match.sql)
    stage(engine, name, **values)   a stage's statements in order, each given the values it names (@name)
    statements(text)                a stage file's statements: each ends with a line that ends in ;
    fingerprint()                   what an increment needs unchanged since the full run: the SQL and the values
"""
import hashlib
import json
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


def records(engine, files: list) -> None:
    """Stage 1 on `engine`: the input files as the table input (every column mapping.sql reads that a file lacks,
    missing), the name model's weights as name_weights; then mapping.sql, then records.sql. O(N·L)."""
    c = config()
    if bad := [x for x in c["input"]["columns"] if not NAME.match(x)]:
        raise ValueError(f"config.toml [input] columns: {bad} are no plain column names")
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
          min_block=int(r["min_block"]), spread=int(r["spread"]), crowd=int(r["crowd"]))


def fit(engine) -> None:
    """Stage 2 on `engine`, after records: fit.sql, with config.toml [fit]. O(n + S·K) on the sample, O(N + S·K) on the file."""
    c = config()["fit"]
    stage(engine, "functions")
    stage(engine, "fit", fit_rows=int(c["fit_rows"]), seed=str(c["seed"]), fit_u_max_pairs=float(c["fit_u_max_pairs"]),
          u_max_pairs=float(c["u_max_pairs"]), settings=json.dumps(c))


def score(engine) -> None:
    """Stage 3 on `engine`, after fit: score.sql, with config.toml [score]. O(N·L + ΣP_g) + O(C·K·L²)."""
    c = config()["score"]
    stage(engine, "functions")
    stage(engine, "score", keep_from=float(c["keep_from"]), search_floor=float(c["search_floor"]), oversized=int(c["oversized"]))


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
