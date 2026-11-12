"""Benchmark the reader (er.intake) on damaged copies of a synthetic population: each kind of damage at a known rate,
what it read back, fixed, proposed and left unread, and how long it took. Writes reports/benchmark_intake.md.

    .venv/bin/python scripts/benchmark_intake.py                    # 40,000 entities
    .venv/bin/python scripts/benchmark_intake.py --entities 800000  # about a million records

The clean copy (UTF-8 CSV) must read back value for value: a blank is missing, as a run reads it. The damaged copy
holds, at the rates below, values in CP932 and EUC-JP, control and invisible characters, placeholders, spreadsheet
numbers, names garbled upstream (UTF-8 read as CP932, then saved) and an unquoted comma inside an address. It is read
with every kind of proposal accepted, and each value compared with what it was before the damage. A value changed that
was never damaged is a wrong repair: there must be none.
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
RATES = {"cp932": 0.10, "euc-jp": 0.02, "controls": 0.01, "placeholders": 0.01, "numbers": 0.005, "garbled": 0.005, "comma": 0.002}
NAMES, ADDRESS, NUMBERS = ("FULL_NAME_KANA", "O_PERSON_NAME_KANA"), "ORIGINAL_ADDRESS", ("PHONE_NUM_4", "POST_CD")


def damaged(df: pd.DataFrame, rng: random.Random) -> tuple[bytes, pd.DataFrame, dict[str, set]]:
    """The file's bytes, the values it should read back as, and which cells each kind of damage touched."""
    cols, truth, touched = list(df.columns), df.copy(), {k: set() for k in RATES}
    lines = [",".join(cols).encode()]
    for i, row in enumerate(df.itertuples(index=False)):
        vals = ["" if pd.isna(v) else v for v in row]
        enc = "cp932" if rng.random() < RATES["cp932"] else "euc-jp" if rng.random() < RATES["euc-jp"] / (1 - RATES["cp932"]) else "utf-8"
        cells = []
        for j, (c, v) in enumerate(zip(cols, vals)):
            raw = None
            if not v and rng.random() < RATES["placeholders"]:
                raw, kind = b"NULL", "placeholders"
            elif v and c in NUMBERS and rng.random() < RATES["numbers"]:
                raw, kind = f"{v}.0".encode(), "numbers"
            elif v and c in NAMES and rng.random() < RATES["garbled"]:
                try:
                    raw, kind = v.encode("utf-8").decode("cp932").encode("utf-8"), "garbled"
                except UnicodeDecodeError:
                    pass
            elif v and c == ADDRESS and "　" in v and rng.random() < RATES["comma"]:
                truth.iat[i, j] = v.replace("　", ",")
                raw, kind = truth.iat[i, j].encode("utf-8"), "comma"
            elif v and not v.isascii() and enc == "utf-8" and rng.random() < RATES["controls"]:  # a zero-width character exists in UTF-8 only
                raw, kind = ("\u200b" + v).encode("utf-8") + b"\x00", "controls"
            if raw is None and v and not v.isascii() and enc != "utf-8":
                try:
                    raw, kind = v.encode(enc), enc
                except UnicodeEncodeError:
                    pass
            if raw is None:
                raw, kind = v.encode("utf-8"), None
            if kind:
                touched[kind].add((i, j))
            cells.append(raw)
        lines.append(b",".join(cells))
    return b"\n".join(lines) + b"\n", truth, touched


def read(data: bytes, accepted: frozenset[str]) -> tuple[pd.DataFrame, dict, float]:
    with tempfile.TemporaryDirectory() as t:
        part = Path(t)
        (part / "records.csv").write_bytes(data)
        start = time.time()
        r = intake.take(part, {part / "records.csv": "records.csv"}, S.input, S.paths["reference"], accepted)
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
    intake.model(S.paths["reference"])  # built once, outside the timings
    clean = df.to_csv(index=False).encode("utf-8")
    back, r, took = read(clean, frozenset())
    changed = int((back[list(df.columns)].fillna("\x00") != df.fillna("\x00")).to_numpy().sum())
    data, truth, touched = damaged(df, random.Random(0))
    proposed = read(data, frozenset())[1]["proposed"]
    got, r2, took2 = read(data, frozenset(intake.KINDS))
    aligned = got.set_index("CONT_ID", drop=False).reindex(truth["CONT_ID"]).reset_index(drop=True)[list(truth.columns)]  # each record's row, as read
    equal = (aligned.fillna("\x00") == truth.fillna("\x00")).to_numpy(dtype=bool)
    hit = {k: sum(bool(equal[i, j]) for i, j in cells) for k, cells in touched.items()}
    damaged_mask = np.zeros_like(equal)
    for cells in touched.values():
        for i, j in cells:
            damaged_mask[i, j] = True
    wrong = int((~equal & ~damaged_mask).sum())
    words = {"cp932": "a value in CP932", "euc-jp": "a value in EUC-JP", "controls": "a zero-width character and a NUL", "placeholders": "NULL for no value",
             "numbers": "a number a spreadsheet wrote (5851.0)", "garbled": "a name garbled upstream", "comma": "an unquoted comma inside an address"}
    how = {"cp932": "by itself", "euc-jp": "by itself, or proposed (encoding)", "controls": "by itself", "placeholders": "by itself", "numbers": "by itself",
           "garbled": "proposed (garbled)", "comma": "proposed (realign)"}
    table = pd.DataFrame([dict(damage=words[k], values=len(touched[k]), read_back=hit[k], share=f"{hit[k] / max(len(touched[k]), 1):.1%}", how=how[k]) for k in RATES])
    per_million = lambda s: s * 1_000_000 / len(df)
    lines = [f"`.venv/bin/python scripts/benchmark_intake.py --entities {args.entities}`", "",
             f"{len(df):,} records × {len(df.columns)} columns, generated from config/generator.toml.", "",
             "## The clean copy", "",
             f"A UTF-8 CSV of the records: read in {took:.1f} s ({per_million(took):.1f} s a million records); "
             f"{changed} values read back differently, nothing proposed: {r['proposed'] or 'none'}, nothing unread: {r['unread']}.", "",
             "## The damaged copy", "",
             f"Read with every proposal accepted, in {took2:.1f} s ({per_million(took2):.1f} s a million records). Before any is accepted, the "
             f"reader proposed {', '.join(f'{n:,} {k}' for k, n in sorted(proposed.items())) or 'nothing'}; {r2['unread']} rows were left unread.", "",
             markdown(table), "",
             f"Values changed that were never damaged (wrong repairs): {wrong}.", ""]
    out = S.root / "reports" / "benchmark_intake.md"
    out.write_text("# The reader on damaged files\n\n" + "\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
