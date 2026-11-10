"""How fast the index is built, one record looked up in it, a search answered as a person types, and the index kept up
to date after an increment, on a generated population; whether each lookup lists and scores what the batch path does
for that record alone, and whether the index kept up to date answers as one built again.

    .venv/bin/python scripts/benchmark_lookup.py --entities 800000     # about a million records: some minutes
    .venv/bin/python scripts/benchmark_lookup.py --entities 20000      # quick

Holds out --lookups records and an increment of --added, runs the rest (nayose resolve records), builds the index (nayose
build index), looks each held-out record up by its values, in one process, as the page's server does, searches by the
start of its name as a person types it, and checks --checked of them against er.candidates and er.match.score_fs on the
stored records plus that one. Then adds the increment (nayose add records, which keeps the index up to date) and asks
--checked lookups and searches of the index kept up to date and of one built again. Writes reports/benchmark_lookup.md.
"""
import argparse
import contextlib
import io
import json
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
    index._attach(con, ws, m)
    n, kind = con.execute("SELECT count(*) FROM records").fetchall()[0][0] + 1, index._classifier(ws, s, fitted, m)
    for _, rec in records.iterrows():
        values = {c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}
        query = index._query(con, s, fitted, values, None, kind).assign(**{uid: rec[uid]})
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


def answers(ws: Path, s, p, asks: list) -> list[dict]:  # what each lookup and search answers, all of it but its time
    out = []
    for values, record in asks:
        r = index.look_up(ws, s, p, values=values, record=record, at_least=-1e9, most=10**6)
        out.append({**{k: r[k] for k in ("record", "entities", "found", "candidates", "likely", "checked")}, "records": r["index"]["records"]})
        r = index.search(ws, s, p, values, most=10**6)
        out.append({**{k: r[k] for k in ("entities", "found", "listed", "candidates", "typed", "over")}, "records": r["index"]["records"]})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    parser.add_argument("--entities", type=int, default=20_000, help="the generated population's entities")
    parser.add_argument("--lookups", type=int, default=1_000, help="records held out and looked up")
    parser.add_argument("--added", type=int, default=1_000, help="records held out and added as an increment")
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
    held, added = np.zeros(len(g.df), dtype=bool), np.zeros(len(g.df), dtype=bool)
    out = rng.choice(len(g.df), size=min(args.lookups + args.added, len(g.df) // 10), replace=False)
    held[out[:args.lookups]], added[out[args.lookups:]] = True, True
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    g.df[~held & ~added].to_parquet(OUT / "stored.parquet", index=False)
    g.df[added].to_parquet(OUT / "added.parquet", index=False)
    print(f"generated {len(g.df):,} records in {time.perf_counter() - t:.0f}s", flush=True)
    ws, compute = OUT / "ws", [f"memory_limit={args.memory_limit}"] if args.memory_limit else []
    t = time.perf_counter()
    assert cli.main(["resolve", "records", str(OUT / "stored.parquet"), "--workspace", str(ws), "--format", "json", *(["--compute", *compute] if compute else [])]) == 0
    run_seconds = time.perf_counter() - t
    s2, p, _ = cli.setup({"workspace": str(ws), "compute": compute})
    t = time.perf_counter()
    built = index.build(ws, s2, p)
    build_seconds = time.perf_counter() - t
    m = index.manifest(ws)
    size = sum((ws / index.INDEX / f).stat().st_size for f in m["files"].values() if f)
    fitted, model = index._pipeline(ws, s2, p, m["columns"]), run_model(ws)
    sources = sorted({c for d in fitted.fs.standardize.derived for alt in d.sources for c in alt})
    times, compared, parts, sought, listed = [], [], [], [], []
    for i, (_, rec) in enumerate(g.df[held].iterrows()):
        values = {c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}
        t = time.perf_counter()
        r = index.look_up(ws, s2, p, values=values)
        took = time.perf_counter() - t
        if i:
            times.append(took)
        else:  # the first opens the index: kept open for the rest
            opened = took
        compared.append(r["candidates"])
        parts.append(r["seconds"])
        name = rec["FULL_NAME_KANA"] if pd.notna(rec["FULL_NAME_KANA"]) else rec["NYS_CNV_P_NAME_KANA"]
        for k in range(2, 6) if isinstance(name, str) else ():  # a name as it is typed
            t = time.perf_counter()
            r = index.search(ws, s2, p, {"FULL_NAME_KANA" if pd.notna(rec["FULL_NAME_KANA"]) else "NYS_CNV_P_NAME_KANA": name[:k]})
            sought.append(time.perf_counter() - t)
            listed.append(r["listed"])
    print(f"{len(times):,} lookups, p95 {np.percentile(times, 95) * 1000:.0f} ms; {len(sought):,} searches, p95 {np.percentile(sought, 95) * 1000:.0f} ms", flush=True)
    checks = pd.DataFrame(checked(ws, s2, p, fitted, model, m, g.df[held].head(args.checked), sources))
    asks = [({c: rec[c] for c in sources if c in rec and pd.notna(rec[c])}, None) for _, rec in g.df[held | added].sample(args.checked, random_state=0).iterrows()]
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        assert cli.main(["add", "records", str(OUT / "added.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    kept = next(json.loads(x) for x in said.getvalue().splitlines() if '"result"' in x)["index"]
    now = answers(ws, s2, p, asks)
    t = time.perf_counter()
    index.build(ws, s2, p)
    rebuilt_seconds = time.perf_counter() - t
    same = sum(a == b for a, b in zip(now, answers(ws, s2, p, asks)))
    ms = lambda q, x=times: f"{np.percentile(x, q) * 1000:,.0f} ms"
    tables = pd.DataFrame([dict(table=k, of=v["of"], rows=f"{v['rows']:,}", seconds=v["seconds"]) for k, v in built["tables"].items() if v["rows"] is not None])
    stages = pd.DataFrame(parts).mean().mul(1000).round(1).rename("mean ms").to_frame().reset_index(names="part")
    report = ["# Benchmark: look up", "",
              f"Written by `{shlex.join(['scripts/benchmark_lookup.py', *sys.argv[1:]])}` on a generated population of {len(g.df):,} records: "
              f"{(~held & ~added).sum():,} run (`nayose resolve records`, {run_seconds:,.0f} s), {held.sum():,} held out and looked up one at a time by their values "
              f"(`nayose match record`), and {added.sum():,} added afterwards as an increment."
              + (f" Past {len(load_reference(s.paths['reference'])[0]):,} entities personas repeat: clones, in blocks larger than a real file's, so the times are an upper bound." if many else ""), "",
              "## The index", "",
              f"Built in **{build_seconds:,.1f} s** from the run's own files (`nayose build index`), **{size / 2**20:,.0f} MB** on disk in the workspace's `index/`.", "",
              markdown(tables), "",
              "## A lookup", "",
              f"**p50 {ms(50)}, p95 {ms(95)}, max {ms(100)}**, the index kept open by the process as the page's server keeps it; the first, which opens it, "
              f"{opened * 1000:,.0f} ms. Records compared: median {int(np.median(compared)):,}, max {max(compared):,}.", "",
              markdown(stages), "",
              "## A search, as a person types", "",
              f"Each held-out record's name searched by its first 2, 3, 4 and 5 characters (`nayose search records`): **p50 {ms(50, sought)}, "
              f"p95 {ms(95, sought)}, max {ms(100, sought)}** over {len(sought):,} searches; records listed: median {int(np.median(listed)):,}.", "",
              "## Kept up to date", "",
              f"`nayose add records` of {added.sum():,} records: the index brought up to date in **{kept['seconds']:,.1f} s** "
              f"({kept['added']:,} records added, {kept['moved']:,} whose entity or rule cluster moved){'; built again: ' + kept['rebuilt'] if kept['rebuilt'] else ''}; "
              f"built again in full, {rebuilt_seconds:,.1f} s. Of {len(asks):,} records looked up and searched by all their values, "
              f"**{same:,} of {len(now):,} answers** of the index kept up to date equal those of the one built again.", "",
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
