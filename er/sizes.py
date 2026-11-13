"""How large a sample the model's fit needs: the fit made on 1,000 records, then 2,000, 4,000, … (each sample the
smaller one and more: records in the fit's order, whole postal areas by hash), with EM as the method has it (rules) and
in one session per equality key (keys), until a larger sample changes nothing people would see. Each step is scored on
the pairs the workspace's run kept, from the levels each holds (no comparison made again), so a step costs its fit:
EM on that sample against the file's u, measured by the run, never sampled again. O(Σ fits) ≈ twice the last.

A step changes nothing when the pairs at the review floor it adds and takes away are under SETTLED of them; two such
steps in a row settle the fit. The largest move of a level's points, or the start's, is said beside: a level a small
sample barely reaches swings without moving a pair. The pairs the run left
below 0 aren't kept, so a step that raises scores is seen only through the pairs the run kept."""
import json
import math
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from er import index
from er.config import InputError, KeyBlocker, Pipeline, keys_sql, lit, q
from er.match import ELSE, _bits, _ranked, fs_settings, read_by, review_floor, scaled_prior, train_fs
from er.settings import Settings
from er.strings import connect

FIRST = 1_000      # the first sample's records
SETTLED = 0.005    # pairs at the floor added and taken away, as a share of them, a step may change and still change nothing
FILE = "sample_sizes.txt"


def models(p: Pipeline) -> dict[str, object]:  # the two ways EM learns: as the method has it, and one session per equality key
    m = replace(p.fs.model, em_from_keys=False, em_median=False)
    keys = tuple(dict.fromkeys(b.keys for b in p.fs.blockers if isinstance(b, KeyBlocker)))
    return {"rules": m, **({"keys": replace(m, em_rules=keys, em_from_keys=True, em_median=True)} if keys else {})}


def weights(fitted: dict, n: int) -> tuple[float, dict[tuple[str, int], float]]:  # the start at n records, and each level's points by its gamma
    lam = scaled_prior(fitted, n)
    return math.log2(lam / (1 - lam)), {(c["output_column_name"], g): _bits(g, lv) for c in fitted["comparisons"] for g, lv in _ranked(c) if g >= 0}


def score_sql(start: float, w: dict[tuple[str, int], float]) -> str:  # a kept pair's points from the levels it holds
    names = sorted({c for c, _ in w})
    return f"{start!r} + " + " + ".join(f"CASE {q('gamma_' + c)} {' '.join(f'WHEN {g} THEN {v!r}' for (x, g), v in w.items() if x == c)} ELSE 0 END" for c in names)


def grow(ws: Path, s: Settings, p: Pipeline, line: Callable[..., None] | None = None, most: int | None = None) -> dict:
    """The steps (records, em, seconds, start, change, pairs at the floor and the line, added and taken away, m of each
    comparison's first level and else level), each way's settled size, and the report written to the workspace."""
    con, db = connect(s.compute)
    parts = sorted((ws / "state" / "records").glob("part-*.parquet"))
    scoring = ws / "state" / "scoring.json"
    if not parts or not scoring.exists() or not list((ws / "scored").glob("*.parquet")):
        raise InputError(f"no run in {ws} to measure a sample against", fix="find matches first: nayose resolve records --workspace …")
    con.execute(f"CREATE TABLE records AS SELECT * FROM read_parquet([{', '.join(lit(x) for x in parts)}], union_by_name = true)")
    p = index.fitted(ws, s, p, [c for c, *_ in con.execute("DESCRIBE records").fetchall()])
    uid, n = s.data.unique_id, con.execute("SELECT count(*) FROM records").fetchall()[0][0]
    model = json.loads(scoring.read_text(encoding="utf-8"))["model"]  # the file's u, as the run scored with them
    if [(c["output_column_name"], [lv["label_for_charts"] for g, lv in _ranked(c) if g >= 0]) for c in model["comparisons"]] != \
            [(c.name, [*(lv.label for lv in c.levels), ELSE]) for c in p.fs.model.comparisons]:  # the levels the kept pairs hold are this method's
        raise InputError(f"the method compares otherwise than the run in {ws} did", fix=f"run it again first: nayose rerun records --workspace {ws}")
    u = {c["output_column_name"]: {lv["label_for_charts"]: lv["u_probability"] for g, lv in _ranked(c) if g >= 0} for c in model["comparisons"]}
    con.execute(f"CREATE TABLE kept AS SELECT * FROM read_parquet({lit(str(ws / 'scored' / '*.parquet'))})")
    floor, at = review_floor(p), p.fs.min_match_weight
    cols = set(c for c, *_ in con.execute("DESCRIBE records").fetchall())
    area = q("postal_code__first3") if "postal_code__first3" in cols else None
    order = f"hash({area}), hash({q(uid)})" if area else f"hash({q(uid)})"
    ways, rows, last, quiet, settled = models(p), [], {}, {}, {}
    reads = set().union(*(read_by(fs_settings(m, uid), *(keys_sql(r) for r in (*m.prior_rules, *m.em_rules))) for m in ways.values())) | {uid}
    con.execute(f"CREATE TABLE er_ordered AS SELECT {', '.join(q(c) for c in cols if c in reads)} FROM records ORDER BY {order}")
    size, top = FIRST, min(n, most or n)
    while True:
        size = min(size, top)
        sample = con.execute(f"SELECT * FROM er_ordered LIMIT {size}").df().astype("string")
        for way, m in ways.items():
            if way in settled:
                continue
            t = time.perf_counter()
            try:
                fitted = train_fs(m, sample, db, uid, u=u)
            except Exception as e:  # too few records for its rules: said, and the next size tried
                rows.append(dict(records=size, em=way, error=str(e).split("\n")[0][:200]))
                line and line(f"{size:,} records, {way}: {rows[-1]['error']}", row=rows[-1])
                continue
            start, w = weights(fitted, n)
            now = score_sql(start, w)
            pairs = con.execute(f"SELECT count(*) FILTER (WHERE x >= {floor}), count(*) FILTER (WHERE x >= {at}) FROM (SELECT {now} AS x FROM kept)").fetchall()[0]
            row = dict(records=size, em=way, seconds=round(time.perf_counter() - t, 2), start=round(start, 2), pairs_floor=pairs[0], pairs_line=pairs[1],
                       m={c["output_column_name"]: {lv["label_for_charts"]: round(lv["m_probability"], 4) for g, lv in _ranked(c) if g >= 0} for c in fitted["comparisons"]})
            if way in last:
                was_start, was_w, was_sql, was_size = last[way]
                moved = max([abs(start - was_start), *(abs(v - was_w.get(k, v)) for k, v in w.items())])
                added, lost = con.execute(f"SELECT count(*) FILTER (WHERE x >= {floor} AND y < {floor}), count(*) FILTER (WHERE x < {floor} AND y >= {floor}) "
                                          f"FROM (SELECT {now} AS x, {was_sql} AS y FROM kept)").fetchall()[0]
                row.update(change=round(moved, 2), added=added, lost=lost)
                quiet[way] = quiet.get(way, 0) + 1 if added + lost <= SETTLED * max(pairs[0], 1) else 0  # the pairs people see: a rare level's swing alone changes none
                if quiet[way] >= 2:
                    settled[way] = was_size  # the first of the two quiet steps: no larger sample changed it
            last[way] = (start, w, now, size)
            rows.append(row)
            line and line(f"{size:,} records, {way}: {pairs[0]:,} pairs at {floor:g}+, start {start:.2f}" + (f", {row['added']:,} added, {row['lost']:,} taken away" if "added" in row else ""), row=row)
        if size >= top or len(settled) == len(ways):
            break
        size *= 2
    out = dict(records=n, floor=floor, line=at, steps=rows, settled=settled, file=str(ws / FILE))
    out["report"] = text(out)
    (ws / FILE).write_text(out["report"], encoding="utf-8")
    con.close()
    return out


def text(r: dict) -> str:
    """The report to send: no record's value, only counts, points and m."""
    out = [f"SAMPLE SIZES  ({r['records']:,} records; pairs at {r['floor']:g}+ and {r['line']:g}+ among the pairs the run kept, scored by each step's fit; "
           "added and taken away: since the step before)",
           f"  {'records':>9}  {'em':5}  {'seconds':>7}  {'start':>7}  {'change':>6}  {'at floor':>9}  {'at line':>8}  {'added':>7}  {'taken':>7}"]
    for x in r["steps"]:
        if "error" in x:
            out.append(f"  {x['records']:>9,}  {x['em']:5}  {x['error']}")
            continue
        out.append(f"  {x['records']:>9,}  {x['em']:5}  {x['seconds']:>7.1f}  {x['start']:>7.2f}  {x.get('change', ''):>6}  {x['pairs_floor']:>9,}  {x['pairs_line']:>8,}  "
                   f"{x.get('added', ''):>7}  {x.get('lost', ''):>7}")
    out += ["", "SETTLED  " + (" · ".join(f"{k}: {v:,} records" for k, v in r["settled"].items()) or "not yet: the largest sample still changed pairs"), ""]
    for x in (x for x in r["steps"][-2:] if "m" in x):  # the last fits' m, by comparison and level
        out.append(f"M  ({x['em']}, {x['records']:,} records)")
        out += [f"  {c:10} " + " · ".join(f"{lab} {v:.4g}" for lab, v in levels.items()) for c, levels in x["m"].items()]
        out.append("")
    return "\n".join(out)

