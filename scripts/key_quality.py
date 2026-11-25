"""Each generator's candidates in a run, and the matches among them, as counts alone (no record's value), so a run on
real records can be read anywhere: which generators find a match no other generator or rule finds, and which can go
together losing none.

    python scripts/key_quality.py RUN [--truth TRUTH.parquet] [--points 6]

RUN: a build's run folder (its run.duckdb, read-only; an update keeps its last batch's candidates alone, so refused).
A match: a pair the run scored at --points or more with a name compared ([lookup] likely_from: as people review), or a
rule's pair. A generator's candidates: the pairs its keys list (cands' generators). Only it: a match no other generator
lists and no rule finds, lost were the generator to go. Can go together: the generators that list no match alone, less,
one at a time, the one whose
return keeps the most matches, until none is lost. TRUTH (a generated population's: CONT_ID, ENTITY_ID) splits each
count into true and false. O(C·G) for C candidates.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nayose  # noqa: E402
from nayose.engines import DuckDB  # noqa: E402


def measure(run: Path, truth: Path | None, points: float) -> dict:
    engine = DuckDB(run / "run.duckdb", read_only=True)
    con = engine.con
    if con.execute("SELECT MAX(batch) FROM records").fetchone()[0]:
        raise SystemExit(f"{run}: updated since its build, and cands holds its last batch's pairs alone: count a build's run")
    engine.run(nayose.statement_making("score", "generators"), {"generators": list(nayose.config()["score"]["generators"])})  # score.sql's: each one's bit
    made = engine.rows("SELECT name, used FROM generators ORDER BY g")
    names, used = [n for n, _ in made], {n for n, on in made if on}
    same = "a.entity = b.entity" if truth else "NULL"
    if truth:
        con.execute(f"CREATE TEMP TABLE truth AS SELECT CAST(CONT_ID AS VARCHAR) AS id, CAST(ENTITY_ID AS VARCHAR) AS entity FROM read_parquet('{truth}')")
        if con.execute("SELECT COUNT(*) FROM records WHERE id NOT IN (SELECT id FROM truth)").fetchone()[0]:
            raise SystemExit(f"{truth}: it lacks some of the run's IDs (read as text, as the run's are)")
    join = "LEFT JOIN truth AS a ON a.id = s.id_l LEFT JOIN truth AS b ON b.id = s.id_r" if truth else ""
    con.execute(f"""CREATE TEMP TABLE m AS
        SELECT string_split(COALESCE(s.generators, ''), '+') AS generators, s.rule IS NOT NULL AS ruled, {same} AS same
        FROM scored AS s {join} WHERE s.rule IS NOT NULL OR (s.points >= ? AND s.named)""", [points])
    rows = []  # each generator the run uses, one with no rows too: 0, and it can go
    for g, k in enumerate(names):
        if k not in used:
            continue
        cands = con.execute("SELECT COUNT(*) FROM cands WHERE list_contains(string_split(generators, '+'), ?)", [k]).fetchone()[0]
        got = con.execute("""SELECT COUNT(*), COUNT(CASE WHEN same THEN 1 END), COUNT(CASE WHEN NOT ruled AND generators = [?] THEN 1 END),
                                    COUNT(CASE WHEN NOT ruled AND generators = [?] AND same THEN 1 END) FROM m WHERE list_contains(generators, ?)""", [k, k, k]).fetchone()
        index = con.execute("SELECT COUNT(*) FROM every_key WHERE g = ?", [g]).fetchone()[0]
        rows.append(dict(generator=k, candidates=cands, matches=got[0], true=got[1], only=got[2], only_true=got[3], index=index))

    def lost(drop: list[str]) -> int:  # matches every generator of which would go, and no rule finds
        return con.execute("SELECT COUNT(*) FROM m WHERE NOT ruled AND generators <> [''] AND list_has_all(?, generators)", [drop]).fetchone()[0] if drop else 0
    drop = [r["generator"] for r in rows if r["only"] == 0]
    while lost(drop):
        drop.remove(min(drop, key=lambda k: lost([x for x in drop if x != k])))
    totals = con.execute("SELECT COUNT(*), COUNT(CASE WHEN same THEN 1 END) FROM m").fetchone()
    index_all = con.execute("SELECT COUNT(*) FROM every_key").fetchone()[0]
    index_drop = con.execute("SELECT COUNT(*) FROM every_key WHERE list_contains(?, g)", [[names.index(k) for k in drop]]).fetchone()[0]
    cands_all, cands_drop = con.execute("SELECT COUNT(*), COUNT(CASE WHEN list_has_all(?, string_split(generators, '+')) THEN 1 END) FROM cands", [drop]).fetchone()
    records = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    return dict(records=records, matches=totals[0], true=totals[1] if truth else None, generators=rows, drop=sorted(drop),
                index=(index_drop, index_all), candidates=(cands_drop, cands_all))


def report(got: dict, truth: bool) -> str:
    head = ["generator", "candidates", "matches", "share", "only it"] + (["true", "only it, true"] if truth else []) + ["index rows"]
    lines = [" | ".join(head), " | ".join("---" for _ in head)]
    for r in sorted(got["generators"], key=lambda r: (-(r["only_true"] if truth else r["only"]), -r["candidates"])):
        share = f"{100 * r['matches'] / r['candidates']:.1f}%" if r["candidates"] else "—"
        cells = [r["generator"], f"{r['candidates']:,}", f"{r['matches']:,}", share, f"{r['only']:,}"]
        cells += [f"{r['true']:,}", f"{r['only_true']:,}"] if truth else []
        lines.append(" | ".join(cells + [f"{r['index']:,}"]))
    (di, ai), (dc, ac) = got["index"], got["candidates"]
    out = [f"{got['records']:,} records, {got['matches']:,} matches" + (f" ({got['true']:,} true)" if truth else ""), "", *lines, ""]
    out.append(f"can go together, losing no match: {', '.join(got['drop']) or 'none'}")
    out.append(f"  their index rows: {di:,} of {ai:,} ({100 * di / max(ai, 1):.0f}%); the candidates only they list: {dc:,} of {ac:,} ({100 * dc / max(ac, 1):.0f}%)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("run", type=Path, help="a run folder")
    p.add_argument("--truth", type=Path, help="a generated population's truth: CONT_ID, ENTITY_ID")
    p.add_argument("--points", type=float, default=float(nayose.config()["lookup"]["likely_from"]), help="the matches' line, in points")
    a = p.parse_args(argv)
    try:
        nayose.check_threshold(a.points)
    except nayose.InputError as e:
        p.error(f"--points: {e}")
    print(report(measure(a.run, a.truth, a.points), a.truth is not None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
