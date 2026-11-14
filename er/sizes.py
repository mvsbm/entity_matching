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
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from er import index
from er.config import InputError, KeyBlocker, Pipeline, lit, q
from er.match import ELSE, _ranked, fit_model, fit_sample_sql, levels, prior_bits, review_floor, scaled_prior, train_fs
from er.settings import Settings
from er.strings import connect

FIRST = 1_000      # the first sample's records
SETTLED = 0.005    # pairs at the floor added and taken away, as a share of them, a step may change and still change nothing
FILE = "sample_sizes.txt"


def models(p: Pipeline) -> dict[str, object]:  # the two ways EM learns, as a run's fit would (er.match.fit_model): as the method has it, and one session per equality key
    m = replace(p.fs.model, em_from_keys=False, em_median=False)
    keys = replace(m, em_from_keys=True, em_median=True)
    return {"rules": m, **({"keys": fit_model(replace(p.fs, model=keys))} if any(isinstance(b, KeyBlocker) for b in p.fs.blockers) else {})}


def weights(fitted: dict, n: int) -> tuple[float, dict[tuple[str, int], float]]:  # the start at n records, and each level's points by its gamma
    return prior_bits(fitted, n), {(c, g): v for c, by in levels(fitted).items() for g, (_, v) in by.items() if g >= 0}


def score_sql(start: float, w: dict[tuple[str, int], float]) -> str:  # a kept pair's points from the levels it holds
    names = sorted({c for c, _ in w})
    return f"{start!r} + " + " + ".join(f"CASE {q('gamma_' + c)} {' '.join(f'WHEN {g} THEN {v!r}' for (x, g), v in w.items() if x == c)} ELSE 0 END" for c in names)


def grow(ws: Path, s: Settings, p: Pipeline, line: Callable[..., None] | None = None) -> dict:
    """The steps (records, em, seconds, start, change, pairs at the floor and the line, added and taken away, m of each
    comparison's first level and else level), each way's settled size, and the report written to the workspace."""
    con, db = connect(s.compute)
    parts = sorted((ws / "state" / "records").glob("part-*.parquet"))
    scoring = ws / "state" / "scoring.json"
    if not parts or not (ws / "state" / "model.json").exists() or not list((ws / "scored").glob("*.parquet")):
        raise InputError(f"no run in {ws} to measure a sample against", fix="find matches first: nayose resolve records --workspace …")
    model = index._scorable(ws)  # a model that adjusts by term frequency scores a pair by more than its levels: refused, as a lookup refuses it
    if scoring.exists():  # u measured on the file (u_from_scored), as the run scored with them
        model = json.loads(scoring.read_text(encoding="utf-8"))["model"]
    con.execute(f"CREATE TABLE records AS SELECT * FROM read_parquet([{', '.join(lit(x) for x in parts)}], union_by_name = true)")
    p = index.to_file(s, p, [c for c, *_ in con.execute("DESCRIBE records").fetchall()])  # the method's keys, as a run's fit sees them: not those it kept after
    uid, n = s.data.unique_id, con.execute("SELECT count(*) FROM records").fetchall()[0][0]
    if [(c["output_column_name"], [lv["label_for_charts"] for g, lv in _ranked(c) if g >= 0]) for c in model["comparisons"]] != \
            [(c.name, [*(lv.label for lv in c.levels), ELSE]) for c in p.fs.model.comparisons]:  # the levels the kept pairs hold are this method's
        raise InputError(f"the method compares otherwise than the run in {ws} did", fix=f"run it again first: nayose rerun records --workspace {ws}")
    u = {c["output_column_name"]: {lv["label_for_charts"]: lv["u_probability"] for g, lv in _ranked(c) if g >= 0} for c in model["comparisons"]}
    con.execute(f"CREATE TABLE kept AS SELECT * FROM read_parquet({lit(str(ws / 'scored' / '*.parquet'))})")
    floor, at = review_floor(p), p.fs.min_match_weight
    ways, rows, last, quiet, settled, fits = models(p), [], {}, {}, {}, {}
    con.execute(f"CREATE TABLE er_ordered AS {fit_sample_sql(ways.values(), uid, {c for c, *_ in con.execute('DESCRIBE records').fetchall()})}")  # the run's fit sample at each size
    size, top = FIRST, n
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
                rows.append(dict(records=size, em=way, floor=floor, error=str(e).split("\n")[0][:200]))
                line and line(f"{size:,} records, {way}: {rows[-1]['error']}", row=rows[-1])
                continue
            start, w = weights(fitted, n)
            now, fits[way, size] = score_sql(start, w), fitted
            pairs = con.execute(f"SELECT count(*) FILTER (WHERE x >= {floor}), count(*) FILTER (WHERE x >= {at}) FROM (SELECT {now} AS x FROM kept)").fetchall()[0]
            row = dict(records=size, em=way, floor=floor, seconds=round(time.perf_counter() - t, 2), start=round(start, 2), pairs_floor=pairs[0], pairs_line=pairs[1],
                       m={c["output_column_name"]: {lv["label_for_charts"]: round(lv["m_probability"], 4) for g, lv in _ranked(c) if g >= 0} for c in fitted["comparisons"]})
            if way in last:
                was_start, was_w, was_sql, was_size = last[way]
                moves = {("start", -1): abs(start - was_start), **{k: abs(v - was_w.get(k, v)) for k, v in w.items()}}
                (mc, mg), moved = max(moves.items(), key=lambda kv: kv[1])
                added, lost = con.execute(f"SELECT count(*) FILTER (WHERE x >= {floor} AND y < {floor}), count(*) FILTER (WHERE x < {floor} AND y >= {floor}) "
                                          f"FROM (SELECT {now} AS x, {was_sql} AS y FROM kept)").fetchall()[0]
                row.update(change=round(moved, 2), moved="start" if mc == "start" else f"{mc} {levels(fitted)[mc][mg][0]}", added=added, lost=lost)
                quiet[way] = quiet.get(way, 0) + 1 if added + lost <= SETTLED * max(pairs[0], 1) else 0  # the pairs people see: a rare level's swing alone changes none
                if quiet[way] >= 2:
                    settled[way] = was_size  # the first of the two quiet steps: no larger sample changed it
            last[way] = (start, w, now, size)
            rows.append(row)
            line and line(f"{size:,} records, {way}: {pairs[0]:,} pairs at {floor:g}+, start {start:.2f}" + (f", {row['added']:,} added, {row['lost']:,} taken away" if "added" in row else ""), row=row)
        if size >= top or len(settled) == len(ways):
            break
        size *= 2
    run_start, run_w, named = *weights(model, n), levels(model)  # named: each level's label by its gamma
    chosen = {way: settled.get(way) or max(size for w_, size in fits if w_ == way) for way in ways if any(w_ == way for w_, _ in fits)}
    points, gained, checks = [dict(comparison="start", level="", run=round(run_start, 2), **{way: round(weights(fits[way, size], n)[0], 2) for way, size in chosen.items()})], {}, {}
    for (c, g), v in run_w.items():
        points.append(dict(comparison=c, level=named[c][g][0], run=round(v, 2), **{way: round(weights(fits[way, size], n)[1][c, g], 2) for way, size in chosen.items()}))
    names = [x["output_column_name"] for x in model["comparisons"]]
    for way, size in chosen.items():
        start, w = weights(fits[way, size], n)
        got = con.execute(f"""SELECT {', '.join(q('gamma_' + c) for c in names)}, count(*) AS n FROM (SELECT *, {score_sql(start, w)} AS x, {score_sql(run_start, run_w)} AS y FROM kept)
            WHERE x >= {floor} AND y < {floor} GROUP BY ALL ORDER BY n DESC LIMIT {PATTERNS}""").fetchall()
        gained[way] = [dict(pattern={c: named[c][g][0] for c, g in zip(names, r[:-1])}, pairs=r[-1]) for r in got]
        line and line(f"checking {size:,} records, {way}: pairs no key lists, and pairs the run's cutoff left out")
        try:
            checks[way] = check(ws, s, p, model, fits[way, size], n)
        except Exception as e:  # said in the report: the sizes stand without it
            checks[way] = dict(error=str(e).split("\n")[0][:300])
    out = dict(records=n, floor=floor, line=at, steps=rows, settled=settled, chosen=chosen, levels=points, gained=gained, checks=checks, file=str(ws / FILE))
    out["report"] = text(out)
    (ws / FILE).write_text(out["report"], encoding="utf-8")
    con.close()
    return out


PATTERNS = 12  # the patterns of pairs a fit lifts to the floor, the most first


def check(ws: Path, s: Settings, p: Pipeline, base: dict, fitted: dict, n: int) -> dict:
    """What a run with this fit would find that the run in ws didn't keep, and what no key lists, by the gap's sample
    (er.keys.discover: records drawn by hash, each paired with every record sharing a value or a near one, scored
    with this fit): per threshold, the pairs at it, those a key or a rule lists, those the run kept, those a key lists
    the run didn't keep (its cutoff, at its own model: a run with this fit finds them), those no key lists (with a 95%
    interval), and the fields those agree on. Scaled to the file."""
    from er.keys import agree_counts, discover, gap_records, generator_atoms, key_lists, poisson, thresholds
    from er.run import BLOCKS, Run, stored_keys
    p = stored_keys(ws, p, s)  # the keys the run listed by
    run = Run(p, s)
    con = run.con
    parts = sorted((ws / "state" / "records").glob("part-*.parquet"))
    con.execute(f"CREATE TABLE records AS SELECT * FROM read_parquet([{', '.join(lit(x) for x in parts)}], union_by_name = true)")
    con.execute(f"CREATE TABLE rule_clusters AS SELECT * FROM read_parquet({lit(str(ws / 'state' / 'rule_clusters.parquet'))})")
    kept_rules = list((ws / "rule_kept").glob("*.parquet")) if (ws / "rule_kept").is_dir() else []
    con.execute(f"CREATE TABLE rule_kept AS SELECT {q(run.l)}, {q(run.r)} FROM read_parquet([{', '.join(lit(x) for x in kept_rules)}])" if kept_rules
                else f"CREATE TABLE rule_kept ({q(run.l)} VARCHAR, {q(run.r)} VARCHAR)")
    run.n, run.pipeline = n, p
    run.scoring = run.model = {**base, "comparisons": fitted["comparisons"], "probability_two_random_records_match": scaled_prior(fitted, n),
                               "er": {**base["er"], "fit_rows": n}}  # the file's u (train_fs was given them), this fit's m and start
    try:
        d = discover(run, gap_records(p))
        blocks = ws / "state" / BLOCKS
        kept = json.loads(blocks.read_text(encoding="utf-8")) if blocks.exists() else {}  # the oversized blocks the run listed
        t, w, m = d.targets, d.weight, p.fs.budget.min_oversized()
        col = {a.column: i for i, a in reversed(list(enumerate(d.atoms)))}
        keyed = t["ruled"].to_numpy().copy()
        for b in p.fs.blockers:
            keyed |= key_lists(b, t, col, d.rec, m, kept)
        d.rec.close()
        con.execute(f"CREATE TABLE er_run_kept AS SELECT {q(run.l)}, {q(run.r)} FROM read_parquet({lit(str(ws / 'scored' / '*.parquet'))})")
        con.register("er_t", t[[run.l, run.r]])
        stored = con.execute(f"SELECT k.{q(run.l)} IS NOT NULL FROM er_t t LEFT JOIN er_run_kept k USING ({q(run.l)}, {q(run.r)}) ORDER BY t.{q(run.l)}, t.{q(run.r)}").fetchnumpy()
        stored = next(iter(stored.values())).astype(bool)
        rows = []
        for at in thresholds(p):
            x = (t["match_weight"] >= at).to_numpy()
            missed = int((x & ~keyed).sum())
            lo, hi = poisson(missed)
            rows.append(dict(bits=at, pairs=round(x.sum() * w), listed=round((x & keyed).sum() * w), kept=round((x & stored).sum() * w),
                             gained=round((x & keyed & ~stored).sum() * w), missed=round(missed * w), missed_lo=round(lo * w), missed_hi=round(hi * w)))
        lost = t[(t["match_weight"] >= review_floor(p)).to_numpy() & ~keyed]
        return dict(sampled=d.facts["sampled_records"], reachable=d.facts["reachable"], thresholds=rows, missed_agree=agree_counts(d.atoms, lost, w),
                    uncounted=[b.name for b in p.fs.blockers if generator_atoms(b) is None],  # sorted, TF-IDF: what they list isn't told, so "no key" may hold some
                    seconds=round(d.facts["draw_seconds"] + d.facts["score_seconds"], 1))
    finally:
        con.close()


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
    out += ["", "SETTLED  " + (" · ".join(f"{k}: {v:,} records" for k, v in r["settled"].items()) or "not yet: the largest sample still changed pairs"),
            "  largest move at each step: " + " · ".join(f"{x['records']:,} {x['em']}: {x['moved']} {x['change']}" for x in r["steps"] if x.get("moved")), ""]
    ways = list(r.get("chosen", {}))
    if r.get("levels"):
        out += [f"LEVELS  (points: the run's model, then each way's fit at {', '.join(f'{r['chosen'][w]:,} records ({w})' for w in ways)}; the start first)",
                f"  {'comparison':12} {'level':16} {'run':>8} " + " ".join(f"{w:>8}" for w in ways)]
        out += [f"  {x['comparison']:12} {x['level']:16} {x['run']:>8} " + " ".join(f"{x[w]:>8}" for w in ways) for x in r["levels"]]
        out.append("")
    for w in ways:
        if r["gained"].get(w):
            out += [f"GAINED  ({w}: the kept pairs this fit puts at {r['floor']:g}+ that the run's model didn't, by pattern, the most first)"]
            out += ["  " + " · ".join(f"{c} {lv}" for c, lv in x["pattern"].items() if lv != "missing") + f"  {x['pairs']:,}" for x in r["gained"][w]]
            out.append("")
    for w in ways:
        c = r["checks"].get(w, {})
        if "error" in c:
            out += [f"CHECK  ({w}): not made: {c['error']}", ""]
            continue
        out += [f"CHECK  ({w}, {r['chosen'][w]:,} records; {c['sampled']:,} records sampled, each paired with every record sharing a value or a near one, "
                f"scored with this fit; scaled to the file; {c['seconds']:,} s)",
                f"  {'bits':>5}  {'pairs':>9}  {'keys list':>9}  {'run kept':>9}  {'a run adds':>10}  {'no key':>8}  interval"]
        out += [f"  {x['bits']:>4g}+  {x['pairs']:>9,}  {x['listed']:>9,}  {x['kept']:>9,}  {x['gained']:>10,}  {x['missed']:>8,}  {x['missed_lo']:,}–{x['missed_hi']:,}" for x in c["thresholds"]]
        if c["missed_agree"]:
            out.append("  pairs no key lists agree on: " + " · ".join(f"{x['atom']} {x['pairs']:,}" for x in c["missed_agree"][:12]))
        if c.get("uncounted"):
            out.append(f"  not counted: {', '.join(c['uncounted'])} (they don't list by agreement)")
        out.append("")
    for x in (x for x in r["steps"] if "m" in x and r.get("chosen", {}).get(x["em"]) == x["records"]):  # each way's chosen fit's m, by comparison and level
        out.append(f"M  ({x['em']}, {x['records']:,} records)")
        out += [f"  {c:10} " + " · ".join(f"{lab} {v:.4g}" for lab, v in by.items()) for c, by in x["m"].items()]
        out.append("")
    return "\n".join(out)

