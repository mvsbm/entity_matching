"""What people have said of a written run, read from its folder: each pair's latest decision, applied (decisions/)
or typed into the sheet and not applied yet (said)."""
from pathlib import Path

import pandas as pd

from er.config import lit
from er.folder import DECISIONS
from er.io import read_parquet


def said(out: Path, uid: str) -> pd.DataFrame:
    """Each pair's latest decision: applied (decisions/), else typed into the sheet and not applied yet (applied False)."""
    l, r = f"{uid}_l", f"{uid}_r"
    done = applied(out, uid)[[l, r, "decision"]].assign(applied=True)
    sheet = out / "review.parquet"
    typed = read_parquet(sheet, columns=[l, r, "decision"]).dropna(subset=["decision"]).assign(applied=False) if sheet.exists() else done.iloc[:0]
    kept = set(zip(done[l], done[r], done["decision"]))  # the sheet keeps what was applied: only a different answer is newer
    typed = typed[[x not in kept for x in zip(typed[l], typed[r], typed["decision"])]]
    both = pd.concat([typed, done], ignore_index=True).astype({l: "string", r: "string"})
    return both.drop_duplicates([l, r], keep="first")  # a decision typed since overrides the applied one


def applied(out: Path, uid: str) -> pd.DataFrame:  # each pair's latest decision the folder holds
    parts = sorted((out / DECISIONS).glob("part-*.parquet"))
    if not parts:
        return pd.DataFrame(columns=[f"{uid}_l", f"{uid}_r", "decision"])
    return pd.concat([read_parquet(f) for f in parts]).drop_duplicates([f"{uid}_l", f"{uid}_r"], keep="last")


def read(out: Path, name: str) -> str:  # SQL: the run's files under `name` (a glob of parts, or one file), their columns by name
    return f"read_parquet({lit(out / name)}, union_by_name = true)"
