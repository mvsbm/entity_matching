"""nayose: entity resolution for Japanese customer records, as BigQuery SQL run by a few lines of Python.

The method is SQL, in BigQuery's dialect, one file per stage (nayose/sql/<stage>.sql), read top to bottom. BigQuery
runs it as written; DuckDB, on a laptop or in CI, runs it after sqlglot translates it (nayose/engines.py). A run is
a set of tables: a BigQuery dataset, or a DuckDB database file.

    stage(engine, name, **values)   a stage's statements in order, each given the values it names (@name)
    statements(text)                a stage file's statements: each ends with a line that ends in ;
    fingerprint()                   what an increment needs unchanged since the full run: the SQL and the values
"""
import hashlib
import re
from pathlib import Path

HERE = Path(__file__).parent
SQL = HERE / "sql"


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
    """The stage nayose/sql/<name>.sql on `engine`, its statements in order. Each is given the values it names as
    @name, and only those: BigQuery refuses a parameter a statement doesn't read."""
    for sql in statements((SQL / f"{name}.sql").read_text(encoding="utf-8")):
        named = set(re.findall(r"@(\w+)", re.sub(r"--[^\n]*|'(?:[^'\\]|\\.)*'", "", sql)))
        if missing := named - set(values):
            raise ValueError(f"{name}.sql names @{', @'.join(sorted(missing))}, which no value gives")
        engine.run(sql, {k: values[k] for k in named})


def fingerprint(root: Path = HERE) -> str:
    """What an increment needs to be what the full run was: a hash of every stage file, the values (config.toml) and
    the input's mapping (mapping.sql), by name and content. A change to any refuses increments until a full run."""
    h = hashlib.sha256()
    for f in sorted([*(root / "sql").glob("*.sql"), *(p for p in (root / "config.toml", root / "mapping.sql") if p.exists())]):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()
