"""nayose: entity resolution for Japanese customer records, as BigQuery SQL run by a few lines of Python.

The method is SQL, in BigQuery's dialect, one file per stage (nayose/sql/<stage>.sql), read top to bottom. BigQuery
runs it as written; DuckDB, on a laptop or in CI, runs it after sqlglot translates it (nayose/engines.py). A run is
a set of tables: a BigQuery dataset, or a DuckDB database file.

    records(engine, files)          stage 1: the input files read, mapped (mapping.sql) and made records (records.sql)
    stage(engine, name, **values)   a stage's statements in order, each given the values it names (@name)
    statements(text)                a stage file's statements: each ends with a line that ends in ;
    fingerprint()                   what an increment needs unchanged since the full run: the SQL and the values
"""
import hashlib
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
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # a column name nayose puts into SQL itself


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


def records(engine, files: list) -> None:
    """Stage 1 on `engine`: the input files as the table input, every column mapping.sql reads that a file lacks added
    as missing, the name model's weights as name_weights; then mapping.sql, then records.sql. O(N·L)."""
    c = config()
    engine.read_parquet("input", files)
    have = {name for name, _ in engine.columns("input")}
    for column in c["input"]["columns"]:
        if not NAME.match(column):
            raise ValueError(f"config.toml [input] columns: {column!r} is no plain column name")
        if column not in have:
            engine.run(f"ALTER TABLE input ADD COLUMN {column} STRING")
    model = np.load(NAME_MODEL)
    engine.put("name_weights", pd.DataFrame({"term": model["terms"].tolist(), "w": model["coef"]}))
    run_file(engine, HERE / "mapping.sql")
    r = c["records"]
    stage(engine, "records", hiragana=HIRAGANA, katakana=KATAKANA, kana_fold_from=r["kana_fold_from"], kana_fold_to=r["kana_fold_to"],
          legal_pattern=legal_pattern(r), prefecture_pattern=f"^(?:{'|'.join(map(re.escape, r['prefectures']))})",
          flag_company=list(r["flag_company"]), name_line=float(r["name_line"]), trust_flag=bool(r["trust_flag"]),
          shared_name_column=bool(r["shared_name_column"]), ngram=int(r["ngram"]), intercept=float(model["intercept"]),
          min_block=int(r["min_block"]), spread=int(r["spread"]), crowd=int(r["crowd"]))


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
