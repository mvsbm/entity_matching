"""Benchmark the reader (er.intake) on a synthetic population as Parquet: a clean copy, and a damaged one with each
fix the reader makes at a known rate, what it read back and how long it took. Writes reports/benchmark_intake.md.

    .venv/bin/python scripts/benchmark_intake.py                    # 40,000 entities
    .venv/bin/python scripts/benchmark_intake.py --entities 800000  # about a million records

The clean copy (every column text) must read back value for value: a blank is missing, as a run reads it. The damaged
copy holds, at the rates below, a zero-width character and a NUL around a value, NULL for no value, a number a
spreadsheet wrote (5851.0) and a value written as a list (["…"]). Each value is compared with what it was before the
damage. A value changed that was never damaged is a wrong fix: there must be none.
"""
import argparse
import random
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from er import intake
from er.generate import generate, load_reference, load_spec
from er.io import markdown, read_parquet
from er.settings import load_settings

S = load_settings()
RATES = {"controls": 0.01, "placeholders": 0.01, "numbers": 0.005, "lists": 0.005}
NUMBERS = ("PHONE_NUM_4", "POST_CD")  # columns of digits: where a spreadsheet writes 5851.0


def damaged(df: pd.DataFrame, rng: random.Random) -> tuple[pd.DataFrame, dict[str, set]]:
    """The damaged records, and which cells each kind of damage touched; df is what they should read back as."""
    out, touched = df.copy(), {k: set() for k in RATES}
    for j, c in enumerate(df.columns):
        if c == "CONT_ID":  # the ID stays as it is: each record is found by it
            continue
        for i, v in enumerate(df[c]):
            filled = not pd.isna(v)
            if not filled and rng.random() < RATES["placeholders"]:
                raw, kind = "NULL", "placeholders"
            elif filled and c in NUMBERS and rng.random() < RATES["numbers"]:
                raw, kind = f"{v}.0", "numbers"
            elif filled and rng.random() < RATES["lists"]:
                raw, kind = f'["{v}"]', "lists"
            elif filled and not v.isascii() and rng.random() < RATES["controls"]:
                raw, kind = "​" + v + "\x00", "controls"
            else:
                continue
            out.iat[i, j] = raw
            touched[kind].add((i, j))
    return out, touched


def read(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, float]:
    with tempfile.TemporaryDirectory() as t:
        part = Path(t)
        df.to_parquet(part / "records.parquet", index=False)
        start = time.time()
        r = intake.take(part, {part / "records.parquet": "records.parquet"}, S.input)
        took = time.time() - start
        return read_parquet(part / r["files"][0]["read"]), r, took


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--entities", type=int, default=40_000)
    args = parser.parse_args()
    persons, companies, towns = load_reference(S.paths["reference"])
    persons = persons if args.entities <= len(persons) else pd.concat([persons] * (args.entities // len(persons) + 1), ignore_index=True)  # past them, personas repeat: the reader reads each row alone
    g = generate(replace(load_spec(S.root / "config" / "generator.toml")[0], entities=args.entities), persons, companies, towns)
    df = g.df.astype("string").reset_index(drop=True)
    df = df.mask(df == "")  # a blank is missing, as a run reads it
    back, r, took = read(df)
    changed = int((back[list(df.columns)].fillna("\x00") != df.fillna("\x00")).to_numpy().sum())
    bad, touched = damaged(df, random.Random(0))
    got, r2, took2 = read(bad)
    aligned = got.set_index("CONT_ID", drop=False).reindex(df["CONT_ID"]).reset_index(drop=True)[list(df.columns)]  # each record's row, as read
    equal = (aligned.fillna("\x00") == df.fillna("\x00")).to_numpy(dtype=bool)
    hit = {k: sum(bool(equal[i, j]) for i, j in cells) for k, cells in touched.items()}
    damaged_mask = np.zeros_like(equal)
    for cells in touched.values():
        for i, j in cells:
            damaged_mask[i, j] = True
    wrong = int((~equal & ~damaged_mask).sum())
    words = {"controls": "a zero-width character and a NUL", "placeholders": "NULL for no value", "numbers": "a number a spreadsheet wrote (5851.0)",
             "lists": 'a value written as a list (["…"])'}
    table = pd.DataFrame([dict(damage=words[k], values=len(touched[k]), read_back=hit[k], share=f"{hit[k] / max(len(touched[k]), 1):.1%}") for k in RATES])
    per_million = lambda s: s * 1_000_000 / len(df)
    lines = [f"`.venv/bin/python scripts/benchmark_intake.py --entities {args.entities}`", "",
             f"{len(df):,} records × {len(df.columns)} columns, generated from config/generator.toml, as Parquet, every column text.", "",
             "## The clean copy", "",
             f"Read in {took:.1f} s ({per_million(took):.1f} s a million records); {changed} values read back differently; "
             f"fixed as read: {', '.join(f'{n:,} {k}' for k, n in sorted(r['fixed'].items())) or 'nothing'}.", "",
             "## The damaged copy", "",
             f"Read in {took2:.1f} s ({per_million(took2):.1f} s a million records); fixed as read: "
             f"{', '.join(f'{n:,} {k}' for k, n in sorted(r2['fixed'].items())) or 'nothing'}.", "",
             markdown(table), "",
             f"Values changed that were never damaged (wrong fixes): {wrong}.", ""]
    out = S.root / "reports" / "benchmark_intake.md"
    out.write_text("# The reader on damaged files\n\n" + "\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
