"""How fast the index is built and one record looked up in it, on a generated population, and whether each lookup lists
and scores what the batch path does for that record alone.

    .venv/bin/python scripts/benchmark_lookup.py --entities 800000     # about a million records: some minutes
    .venv/bin/python scripts/benchmark_lookup.py --entities 20000      # quick

Holds out --lookups records, runs the rest (nayose resolve records), builds the index (nayose build index), looks each
held-out record up by its values, as a person types them, and checks --checked of them against er.candidates and
er.match.score_fs on the stored records plus that one. Writes reports/benchmark_lookup.md.
"""
import argparse
import shlex
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from er import cli, index
from er.candidates import candidates
from er.generate import generate, load_reference, load_spec
from er.io import markdown
from er.match import review_floor, score_fs
from er.report import run_model
from er.settings import load_settings
from er.strings import connect

S = load_settings()
OUT = S.root / "data" / "artifacts" / "benchmark_lookup"


def checked(ws: Path, s, p, fitted, model, m: dict, records: pd.DataFrame, sources: list[str]) -> list[dict]:
    """Each record against the batch path: the pairs er.candidates lists for it alone among the stored records, gated
    alike, and their scores by score_fs, beside the lookup's. One stored table, the record inserted and taken out again."""
    uid, out = s.data.unique_id, []
    con, db = connect(s.compute)
    parts = ", ".join(f"'{f}'" for f in sorted((ws / "state" / "records").glob("part-*.parquet")))
    con.execute(f"CREATE TABLE records AS SELECT * FROM read_parquet([{parts}], union_by_name = true)")
    con.execute(f"ATTACH '{ws / index.INDEX / 'index.duckdb'}' AS ix (READ_ONLY)")
    n = con.execute("SELECT count(*) FROM records").fetchall()[0][0] + 1
    for _, rec in records.iterrows():
        values = {c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}
        query = index._query(con, ws, s, fitted, values, None).assign(**{uid: rec[uid]})
        con.register("er_q", query)
        con.execute("CREATE OR REPLACE TEMP TABLE qry AS SELECT * FROM er_q")
        found, said = index._candidates(con, fitted, uid, rec[uid])
        found = {**found, **index._gate(con, fitted, model, uid, rec[uid], found, said, m["records"])}
        mine = index._scored(con, model, uid, rec[uid], sorted(found), n)
        con.execute("INSERT INTO records BY NAME SELECT * FROM er_q")
        con.execute(f"CREATE OR REPLACE TABLE new_ids AS SELECT '{rec[uid]}' AS \"{uid}\"")
        gate = lambda pairs: score_fs(model, "records", pairs, db, uid, into="er_gate", n_records=n)
        candidates(fitted.fs.blockers, "records", uid, "new_ids", fitted.fs.budget, con=con, into="cands", touching=True, gate=gate, floor=review_floor(fitted))
        score_fs(model, "records", "cands", db, uid, into="scores", n_records=n)
        ref = dict(con.execute(f"""SELECT CASE WHEN "{uid}_l" = '{rec[uid]}' THEN "{uid}_r" ELSE "{uid}_l" END, match_weight FROM scores""").fetchall())
        con.execute(f"DELETE FROM records WHERE \"{uid}\" = '{rec[uid]}'")
        con.unregister("er_q")
        got = dict(zip(mine["uid"], mine["weight"]))
        out.append(dict(record=rec[uid], batch=len(ref), lookup=len(got), missed=len(set(ref) - set(got)), added=len(set(got) - set(ref)),
                        max_weight_gap=max((abs(got[k] - ref[k]) for k in ref if k in got), default=0.0)))
    con.close()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    parser.add_argument("--entities", type=int, default=20_000, help="the generated population's entities")
    parser.add_argument("--lookups", type=int, default=1_000, help="records held out and looked up")
    parser.add_argument("--checked", type=int, default=20, help="of them, checked against the batch path")
    parser.add_argument("--memory-limit", default=S.compute.get("memory_limit", ""), help="DuckDB's, e.g. 8GB (default: [compute])")
    args = parser.parse_args()
    s = replace(S, compute={**S.compute, **({"memory_limit": args.memory_limit} if args.memory_limit else {})})
    rng = np.random.default_rng(0)
    t = time.perf_counter()
    persons, companies, towns = load_reference(s.paths["reference"])
    many = args.entities > len(persons)  # past the personas, they repeat: clones no matcher can tell apart, as scripts/benchmark.py makes them
    persons = pd.concat([persons] * (args.entities // len(persons) + 1), ignore_index=True) if many else persons
    g = generate(replace(load_spec(s.root / "config" / "generator.toml")[0], entities=args.entities), persons, companies, towns)
    held = np.zeros(len(g.df), dtype=bool)
    held[rng.choice(len(g.df), size=min(args.lookups, len(g.df) // 10), replace=False)] = True
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    g.df[~held].to_parquet(OUT / "stored.parquet", index=False)
    print(f"generated {len(g.df):,} records in {time.perf_counter() - t:.0f}s", flush=True)
    ws, compute = OUT / "ws", [f"memory_limit={args.memory_limit}"] if args.memory_limit else []
    t = time.perf_counter()
    assert cli.main(["resolve", "records", str(OUT / "stored.parquet"), "--workspace", str(ws), "--format", "json", *(["--compute", *compute] if compute else [])]) == 0
    run_seconds = time.perf_counter() - t
    s2, p, _ = cli.setup({"workspace": str(ws), "compute": compute})
    t = time.perf_counter()
    built = index.build(ws, s2, p)
    build_seconds = time.perf_counter() - t
    size = sum(f.stat().st_size for f in (ws / index.INDEX).iterdir() if f.is_file())
    m = index.manifest(ws)
    fitted, model = index._pipeline(ws, s2, p, m["columns"]), run_model(ws)
    sources = sorted({c for d in fitted.fs.standardize.derived for alt in d.sources for c in alt})
    times, compared, parts = [], [], []
    for _, rec in g.df[held].iterrows():
        values = {c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}
        t = time.perf_counter()
        r = index.look_up(ws, s2, p, values=values)
        times.append(time.perf_counter() - t)
        compared.append(r["candidates"])
        parts.append(r["seconds"])
    print(f"{len(times):,} lookups, p95 {np.percentile(times, 95) * 1000:.0f} ms", flush=True)
    checks = pd.DataFrame(checked(ws, s2, p, fitted, model, m, g.df[held].head(args.checked), sources))
    ms = lambda q: f"{np.percentile(times, q) * 1000:,.0f} ms"
    tables = pd.DataFrame([dict(table=k, of=v["of"], rows=f"{v['rows']:,}", seconds=v["seconds"]) for k, v in built["tables"].items() if v["rows"] is not None])
    stages = pd.DataFrame(parts).mean().mul(1000).round(1).rename("mean ms").to_frame().reset_index(names="part")
    report = ["# Benchmark: look up", "",
              f"Written by `{shlex.join(['scripts/benchmark_lookup.py', *sys.argv[1:]])}` on a generated population of {len(g.df):,} records: "
              f"{(~held).sum():,} run (`nayose resolve records`, {run_seconds:,.0f} s), {held.sum():,} held out and looked up one at a time by their values, "
              "as a person types them (`nayose match record`), each opening the index afresh."
              + (f" Past {len(load_reference(s.paths['reference'])[0]):,} entities personas repeat: clones, in blocks larger than a real file's, so the times are an upper bound." if many else ""), "",
              "## The index", "",
              f"Built in **{build_seconds:,.1f} s** from the run's own files (`nayose build index`), **{size / 2**20:,.0f} MB** on disk in the workspace's `index/`.", "",
              markdown(tables), "",
              "## A lookup", "",
              f"**p50 {ms(50)}, p95 {ms(95)}, max {ms(100)}**; records compared: median {int(np.median(compared)):,}, max {max(compared):,}.", "",
              markdown(stages), "",
              "## The same as the batch path", "",
              f"{len(checks):,} of the records looked up, each also listed by `er.candidates` among the stored records plus it alone, oversized "
              "blocks gated alike, and scored by `er.match.score_fs` with the run's model: the pairs each lists, those the lookup "
              "missed or added, and the largest gap between the two weights.", "",
              markdown(checks), ""]
    path = S.root / "reports" / "benchmark_lookup.md"
    path.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
