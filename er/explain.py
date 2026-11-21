"""The model a written run scored with (run_model), and its pairs scored again with it (scored_again): the index
and the gate read them."""
from __future__ import annotations
import json
from pathlib import Path

import duckdb

from er.config import lit, q
from er.match import read_by, saved, score_fs
from er.report import no_run
from er.review_state import read


def run_model(out: Path) -> dict:  # the model the run in `out` scored with: its u from the file, else as fitted
    scoring, fitted = out / "state" / "scoring.json", out / "state" / "model.json"
    if not fitted.exists():
        raise no_run(out)
    model = json.loads(scoring.read_text(encoding="utf-8"))["model"] if scoring.exists() else json.loads(fitted.read_text(encoding="utf-8"))
    return saved(model, f"the run in {out}", fix=f"run it again: nayose resolve records FILE --workspace {out} --overwrite")


def scored_again(con: duckdb.DuckDBPyConnection, out: Path, uid: str, pairs: str, into: str, narrow: bool = False) -> dict:
    """The pairs of the table `pairs` (uid_l, uid_r) scored as the run in `out` scored its candidates: its model, λ for
    its size, on its standardized records (those the pairs touch, in er_touched: with `narrow`, only the columns the
    model reads), into the table `into`. Returns the model. O(N) to find the records + O(P·K)."""
    l, r, model = q(f"{uid}_l"), q(f"{uid}_r"), run_model(out)
    stored = read(out, "state/records/*.parquet")
    cols = ", ".join(q(c) for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {stored}").fetchall() if c in read_by(model) | {uid}) if narrow else "*"  # a row's every column costs its read
    con.execute(f"CREATE OR REPLACE TABLE er_touched AS SELECT {cols} FROM {stored} WHERE {q(uid)} IN (SELECT {l} FROM {pairs} UNION SELECT {r} FROM {pairs})")
    n = con.execute(f"SELECT count(*) FROM read_parquet({lit(out / 'gold.parquet')})").fetchall()[0][0]
    score_fs(model, "er_touched", pairs, con, uid, into=into, n_records=n)
    return model


