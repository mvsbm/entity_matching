"""nayose: entity resolution for Japanese customer records, as BigQuery SQL run by a few lines of Python.

The method is SQL, in BigQuery's dialect, one file per stage (nayose/sql/<stage>.sql), read top to bottom. BigQuery
runs it as written; DuckDB, on a laptop or in CI, runs it after sqlglot translates it (nayose/engines.py). A run is
a set of tables: a BigQuery dataset, or a DuckDB database file.

    read(engine, files)             stage 1's intake: the input files as the table input, each value read (intake.sql)
    records(engine, files)          stage 1: the input files read, mapped (mapping.sql) and made records (records.sql)
    em.fit(engine)                  stage 2: the model learned on a sample (fit.sql, u.sql, nayose/em.py), u on the file
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
KATAKANA_BLOCK, ONE_BYTE = "".join(map(chr, range(0x30A0, 0x3100))), "".join(map(chr, range(1, 0x61)))  # the block, each a byte: 0x01–0x60
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # a column name config.toml gives


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


def as_text(name: str, kind: str) -> str:
    """A column of the files as text, in BigQuery SQL: a whole float as its digits (as text, 9e10 would read as a number
    cut short), bytes as UTF-8 (bytes that aren't: U+FFFD, damaged), a list or a record as JSON, the rest cast."""
    c, kind = f"`{name}`", kind.upper()
    if kind.endswith("[]") or kind.startswith(("STRUCT", "RECORD", "MAP", "UNION")):
        return f"TO_JSON_STRING({c})"
    if kind in ("DOUBLE", "FLOAT", "FLOAT64", "REAL"):
        return f"IF({c} = FLOOR({c}) AND ABS({c}) < CAST(9e18 AS FLOAT64), CAST(CAST({c} AS INT64) AS STRING), CAST({c} AS STRING))"
    if kind in ("BLOB", "BYTES"):
        return f"SAFE_CONVERT_BYTES_TO_STRING({c})"
    return f"CAST({c} AS STRING)"


def read(engine, files: list, also: tuple[str, ...] = ()) -> None:
    """The intake on `engine`: the files as the table raw (engine.read_parquet: every column, each name its own), then
    each value read by intake.sql's functions into the table input, and what was fixed counted in the table intake
    (fixed, n). A column of numbers is told over all its values. The columns in `also` the files lack, missing.
    O(bytes)."""
    engine.read_parquet("raw", files)
    columns = engine.columns("raw")
    if bad := [n for n, _ in columns if "`" in n or "\\" in n]:
        raise ValueError(f"a column name nayose can't quote: {bad}")
    text = {n: as_text(n, kind) for n, kind in columns}
    stage(engine, "intake")
    told = engine.rows("SELECT " + ", ".join(f"2 * SUM(numberlike({e})) >= COUNT(numberlike({e})) AND COUNT(numberlike({e})) > 0" for e in text.values()) + " FROM raw")[0]
    numeric = {n: bool(x) for n, x in zip(text, told)}
    engine.run("CREATE OR REPLACE TEMP TABLE listed AS SELECT " + ", ".join(f"listed({e}) AS `{n}`" for n, e in text.items()) + " FROM raw")
    engine.run("CREATE OR REPLACE TEMP TABLE tidied AS SELECT " + ", ".join(
        f"tidied(`{n}`.v, `{n}`.fixed, {str(numeric[n]).upper()}, @nulls) AS `{n}`" for n in text) + " FROM listed", {"nulls": list(config()["input"]["nulls"])})
    lacking = [c for c in also if c.casefold() not in {n.casefold() for n in text}]
    engine.run("CREATE OR REPLACE TEMP TABLE input AS SELECT " + ", ".join([*(f"`{n}`.v AS `{n}`" for n in text), *(f"CAST(NULL AS STRING) AS {c}" for c in lacking)])
               + " FROM tidied")
    engine.run("CREATE OR REPLACE TABLE intake AS SELECT fixed, COUNT(*) AS n FROM (" + " UNION ALL ".join(f"SELECT `{n}`.fixed AS fixed FROM tidied" for n in text)
               + ") WHERE fixed IS NOT NULL GROUP BY fixed")


def records(engine, files: list) -> None:
    """Stage 1 on `engine`: the input files read (read), every column mapping.sql reads that a file lacks added as
    missing, the name model's weights as name_weights; then mapping.sql, then records.sql. O(N·L)."""
    c = config()
    if bad := [x for x in c["input"]["columns"] if not NAME.match(x)]:
        raise ValueError(f"config.toml [input] columns: {bad} are no plain column names")
    read(engine, files, also=tuple(c["input"]["columns"]))
    model = np.load(NAME_MODEL)
    engine.put("name_weights", pd.DataFrame({"term": model["terms"].tolist(), "w": model["coef"]}))
    run_file(engine, HERE / "mapping.sql")
    r = c["records"]
    stage(engine, "records", hiragana=HIRAGANA, katakana=KATAKANA, katakana_block=KATAKANA_BLOCK, one_byte=ONE_BYTE, kana_fold_from=r["kana_fold_from"], kana_fold_to=r["kana_fold_to"],
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
