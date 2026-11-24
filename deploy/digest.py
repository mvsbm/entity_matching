"""Whether two runs' results are the same: digest.py RUN_A RUN_B. For each Parquet file of the run's folder, its rows'
count and an XOR of their MD5s, order-independent: exactly, and again with every float rounded to 9 decimals. For the
model (state/model.json, state/scoring.json), λ, m and u exactly and to 12 significant digits. It prints each file
that differs, and exits 1 if any differs when rounded, else 0. The deploy's smoke test runs it on a run Cloud Run
built and the same file built on the agent (deploy/smoke.sh)."""
import json
import sys
from pathlib import Path

import duckdb


def digest(run: Path) -> tuple[dict, dict]:  # (exact, rounded), each file → its digest
    con, exact, rounded = duckdb.connect(), {}, {}
    for f in sorted(run.rglob("*.parquet")):
        name = f.relative_to(run).as_posix()
        cols = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(f)]).fetchall()
        both = lambda sel: tuple(con.execute(f"SELECT count(*), bit_xor(md5_number(CAST(t AS VARCHAR)))::VARCHAR FROM (SELECT {sel} FROM read_parquet(?)) t", [str(f)]).fetchone())
        exact[name] = both(", ".join(f'"{c}"' for c, *_ in cols))
        rounded[name] = both(", ".join(f'round("{c}", 9) AS "{c}"' if t in ("DOUBLE", "FLOAT") else f'"{c}"' for c, t, *_ in cols))
    for name in ("state/model.json", "state/scoring.json"):
        if (run / name).is_file():
            d = json.loads((run / name).read_text(encoding="utf-8"))
            d = d.get("model", d)
            levels = lambda f: [[c["output_column_name"], [[lv.get("label_for_charts"), *(f(lv[k]) if isinstance(lv.get(k), float) else lv.get(k)
                                                            for k in ("m_probability", "u_probability"))] for lv in c["comparison_levels"]]] for c in d["comparisons"]]
            exact[name] = [d["probability_two_random_records_match"].hex(), levels(float.hex)]
            rounded[name] = [float(f"{d['probability_two_random_records_match']:.12g}"), levels(lambda v: float(f"{v:.12g}"))]
    return exact, rounded


def main(a: Path, b: Path) -> int:
    (ea, ra), (eb, rb) = digest(a), digest(b)
    for kind, x, y in (("exact", ea, eb), ("rounded", ra, rb)):
        differ = sorted(k for k in x.keys() | y.keys() if x.get(k) != y.get(k))
        print(json.dumps(dict(severity="ERROR" if differ and kind == "rounded" else "INFO", compared=kind, files=len(x.keys() | y.keys()), differ=differ)))
    return 1 if any(ra.get(k) != rb.get(k) for k in ra.keys() | rb.keys()) else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
