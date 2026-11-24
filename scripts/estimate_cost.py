"""What a build costs BigQuery, measured on DuckDB, statement by statement: records (stage 1), fit (2) and score (3).

    python scripts/estimate_cost.py FILE [FILE ...]

On-demand bills bytes: of every column a statement reads, the whole table (a WHERE or LIMIT cuts nothing), at least
10 MB a table, and an UPDATE all of its table's columns too. DuckDB's plan names each scan's table and columns; their
BigQuery sizes (a string 2 bytes + its UTF-8, a number 8, a boolean 1, NULL nothing) are summed here.
Capacity bills slot time: the work, here the rows every step of the plan produced, and the cl_* comparison calls
(JavaScript in BigQuery, the costliest per row), counted exactly.
With two or more files, each statement's cost ≈ a·N^b (b from the two largest files), summed at 1B records.
A scan DuckDB proves empty from its statistics, it never plans, so isn't billed here: BigQuery would bill it.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import nayose
from nayose.engines import FUNCTIONS, DuckDB, compare

MB, TIB = 1e6, 2 ** 40
PRICE_PER_TIB = 6.25  # on-demand list price, US multi-region (cloud.google.com/bigquery/pricing): check the region's
SIZE = {"VARCHAR": "COALESCE(SUM(strlen({c}) + 2), 0)", "BOOLEAN": "COUNT({c})"}  # strlen: bytes; else 8 bytes a filled value


def measured(engine: DuckDB) -> list[dict]:
    """Wraps the engine: each statement's bytes billed, rows produced and comparison calls, appended as it runs."""
    out, calls = [], [0]
    for name in FUNCTIONS:  # every call counted: the Python twins alone, as BigQuery's JavaScript is called for each
        for cut, kinds in (("", ["VARCHAR", "VARCHAR"]), ("_cut", ["VARCHAR", "VARCHAR", "DOUBLE"])):
            engine.con.execute(f"DROP MACRO IF EXISTS cl_{name}{cut}")
            engine.con.create_function(f"cl_{name}{cut}", counting(compare(name, cut=bool(cut)), bool(cut), calls), kinds, "DOUBLE", type="arrow")
    run, rows = engine.run, engine.rows

    def traced(do):
        def go(sql: str, values: dict | None = None):
            engine.con.execute("SET enable_profiling = 'no_output'")  # each plan kept, none printed
            before = calls[0]
            try:
                return do(sql, values)
            finally:
                plan = json.loads(engine.con.get_profiling_information())
                engine.con.execute("RESET enable_profiling")
                out.append(cost(engine, sql, plan, calls[0] - before))
        return go
    engine.run, engine.rows = traced(run), traced(rows)
    return out


def counting(f, cut: bool, calls: list[int]):  # a twin that counts the rows it is called on (DuckDB counts its parameters)
    def bump(a):
        calls[0] += len(a)
    if cut:
        return lambda a, b, t: (bump(a), f(a, b, t))[1]
    return lambda a, b: (bump(a), f(a, b))[1]


def cost(engine: DuckDB, sql: str, plan: dict, calls: int) -> dict:
    scans = defaultdict(set)  # table → the words its scans name: their columns, and those their filters read
    text = lambda x: " ".join([x] if isinstance(x, str) else x or [])

    def walk(op: dict) -> None:
        info = op.get("extra_info") or {}
        if op.get("type") == "TABLE_SCAN" and "Table" in info:
            words = (text(info.get("Projections")) + " " + text(info.get("Filters"))).replace("(", " ").replace(")", " ").replace(",", " ")
            scans[info["Table"].split(".")[-1].strip('"')] |= set(w.strip('"') for w in words.split())
        for child in op.get("children", []):
            walk(child)
    for op in plan.get("operator", []):
        walk(op)
    label = next((x.strip() for x in sql.splitlines() if x.strip() and not x.strip().startswith("--")), "")
    updated = label.split()[1] if label.upper().startswith("UPDATE ") else None  # an UPDATE bills all its table's columns
    billed = 0.0
    for table, cols in scans.items():
        have = dict(engine.con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?", [table]).fetchall())
        read = [c for c in have if c in cols or table == updated]
        sizes = [SIZE.get(have[c], "8 * COUNT({c})").format(c=f'"{c}"') for c in read]
        billed += max(10 * MB, float(engine.con.execute(f'SELECT {" + ".join(sizes) or "0"} FROM "{table}"').fetchall()[0][0] or 0))
    return dict(label=label[:70], billed=billed, rows=plan.get("query", {}).get("total_intermediate_rows", 0), calls=calls)


def build(path: Path) -> dict[str, list[dict]]:  # stage → its statements' costs
    engine = DuckDB()
    got = measured(engine)
    nayose.records(engine, [path])
    stages = {"records": list(got)}
    got.clear()
    nayose.fit(engine)
    stages["fit"] = list(got)
    got.clear()
    nayose.score(engine)
    stages["score"] = list(got)
    engine.close()
    return stages


KINDS = ("billed", "rows", "calls")


def project(x1: float, x2: float, n1: int, n2: int) -> float:  # x at N = 1B from x1 at n1 and x2 at n2, as x ≈ a·N^b
    b = math.log(x2 / x1) / math.log(n2 / n1) if x1 and x2 else 1.0
    return x2 * (1e9 / n2) ** b if x2 else 0.0


def main(files: list[str]) -> None:
    runs = []
    for f in map(Path, files):
        stages, n = build(f), DuckDB().value(f"SELECT COUNT(*) FROM read_parquet('{f}')")
        runs.append((n, stages))
        print(f"\n{f.name}: {n:,} records")
        for stage, statements in stages.items():
            total = {k: sum(s[k] for s in statements) for k in KINDS}
            print(f"  {stage}: {total['billed'] / MB:,.0f} MB billed (${total['billed'] / TIB * PRICE_PER_TIB:,.3f}), {total['rows']:,} rows, "
                  f"{total['calls']:,} comparison calls, {len(statements)} statements; the costliest, by their shares of the three:")
            for s in sorted(statements, key=lambda s: sum(s[k] / total[k] for k in KINDS if total[k]), reverse=True)[:5]:
                print(f"    {s['billed'] / MB:9,.0f} MB {s['rows']:>13,} rows {s['calls']:>11,} calls  {s['label']}")
    if len(runs) > 1:
        (n1, small), (n2, large) = sorted(runs, key=lambda r: r[0])[-2:]
        print("\nAt 1,000,000,000 records: each statement's cost ≈ a·N^b (b from the two largest files), summed:")
        for stage in large:
            at = {k: sum(project(x[k], y[k], n1, n2) for x, y in zip(small[stage], large[stage])) for k in KINDS}
            print(f"  {stage}: {at['billed'] / TIB:,.1f} TiB billed (${at['billed'] / TIB * PRICE_PER_TIB:,.0f}), {at['rows']:,.0f} rows, {at['calls']:,.0f} comparison calls")


if __name__ == "__main__":
    main(sys.argv[1:])
