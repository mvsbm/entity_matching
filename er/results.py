"""What a finished run holds, for people to see without running anything again (the pages Results, Review and
Explore): the pairs it scored at 0 points or more, each with the level every comparison reached (scored/); its
entities; each record's full row as the file gave it; and the conditions under which pairs merge without people.

Everything here reads the workspace's own files. The pair index alone is written, once, for a workspace whose run
kept none (written before runs did): from the pairs that run stored, rescored, never by running again."""
import math
from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd

from er import folder
from er.cluster import merge
from er.config import InputError, Pipeline, bits, lit, q
from er.kind import sheet_parts
from er.match import levels, named_sql
from er.report import applied, no_run, run_model, scored_again
from er.settings import Settings, norm_name

BANDS = (-20, -10, 0, 6, 8, 10, 12, 16, 20)  # the score chart's edges, in points: as report.txt's SCORES
SIZES = ((1, 1, "1 record"), (2, 2, "2 records"), (3, 9, "3–9"), (10, 49, "10–49"), (50, None, "50 or more"))


def read(out: Path, name: str) -> str:
    return f"read_parquet({lit(out / name)}, union_by_name = true)"


def joined_by(p: Pipeline) -> str:  # gold's resolved_by as people read it: you, the model, or a rule
    return f"CASE WHEN resolved_by = 'review' THEN 'you' WHEN resolved_by = {lit(p.fs.model.name)} THEN 'model' WHEN resolved_by IS NOT NULL THEN 'rule' END"


def pair_index(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline) -> str:
    """scored/ as SQL: every pair the run scored at 0 points or more, the rules' pairs too, with how it was found
    (sources: its keys; rule: the rule that matched it), whether a name was compared (named) and one gamma per
    comparison. A run written before runs kept it gets it here, once, from the pairs it stored (matches/, proposed/,
    rule_kept/, the sheet's pairs to decide), rescored: O(N + P·K) once, under the lock; O(1) after."""
    index = out / folder.SCORED
    if not any(index.glob("part-*.parquet")):
        with folder.run_lock(out):
            folder.finish_writes(out)  # a write cut short is finished first: staging the index replaces its list of moves
            if not any(index.glob("part-*.parquet")):
                _index(con, db, out, s, p)
    return read(out, f"{folder.SCORED}/*.parquet")


def _index(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline) -> None:
    uid = s.data.unique_id
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    have = lambda name: any((out / name).glob("*.parquet"))
    parts = [f"SELECT {l}, {r}, match_weight, sources, NULL::VARCHAR AS rule, 'model' AS part FROM {read(out, x + '/*.parquet')}" for x in ("matches", "proposed") if have(x)]
    parts += [f"SELECT {l}, {r}, match_weight, NULL::VARCHAR AS sources, rule, 'rule' AS part FROM {read(out, 'rule_kept/*.parquet')}"] if have("rule_kept") else []
    if (out / "review.parquet").exists():
        parts.append(f"SELECT {l}, {r}, match_weight, sources, NULL::VARCHAR AS rule, 'sheet' AS part FROM read_parquet({lit(out / 'review.parquet')}) WHERE why = 'decide'")
    if not parts:
        raise no_run(out)
    # the sheet names a rule pair's rule where a model pair's keys go: a rule pair's keys come from the model's files alone
    con.execute(f"""CREATE OR REPLACE TABLE er_index AS SELECT {l}, {r}, max(match_weight) AS match_weight, coalesce(max(sources) FILTER (WHERE part = 'model'),
        CASE WHEN bool_or(part = 'rule') THEN NULL ELSE max(sources) END) AS sources, max(rule) AS rule
        FROM ({' UNION ALL BY NAME '.join(parts)}) WHERE {l} IS NOT NULL GROUP BY {l}, {r}""")
    scored_again(con, db, out, uid, "er_index", "er_index_scores")
    gammas = [c for c, *_ in con.execute("DESCRIBE er_index_scores").fetchall() if c.startswith("gamma_")]
    fs = replace(p.fs, needs=tuple(c for c in p.fs.needs if f"gamma_{c}" in gammas))  # the name check on the comparisons that run had
    con.execute(f"""CREATE OR REPLACE TABLE er_scored_index AS SELECT i.{l}, i.{r}, coalesce(i.match_weight, x.match_weight) AS match_weight,
        x.match_probability, i.sources, i.rule, {named_sql(fs, 'x')} AS named, TRUE AS keep, {', '.join(f'x.{q(g)}' for g in gammas)}
        FROM er_index i JOIN er_index_scores x USING ({l}, {r})""")
    folder.stage(con, out, [("SELECT * FROM er_scored_index", out / folder.SCORED / "part-00000.parquet")])


def _said(out: Path, uid: str) -> pd.DataFrame:
    """Each pair's latest decision: applied (decisions/), else typed into the sheet and not applied yet."""
    l, r = f"{uid}_l", f"{uid}_r"
    done = applied(out, uid)[[l, r, "decision"]].assign(applied=True)
    sheet = out / "review.parquet"
    typed = pd.read_parquet(sheet, columns=[l, r, "decision"]).dropna(subset=["decision"]).assign(applied=False) if sheet.exists() else done.iloc[:0]
    kept = set(zip(done[l], done[r], done["decision"]))  # the sheet keeps what was applied: only a different answer is newer
    typed = typed[[x not in kept for x in zip(typed[l], typed[r], typed["decision"])]]
    both = pd.concat([typed, done], ignore_index=True).astype({l: "string", r: "string"})
    return both.drop_duplicates([l, r], keep="first")  # a decision typed since overrides the applied one


def _status_sql(con: duckdb.DuckDBPyConnection, out: Path, uid: str, index: str) -> str:
    """The index with each pair's status: same / different (people's), merged (one entity already), waiting."""
    l, r, u = q(f"{uid}_l"), q(f"{uid}_r"), q(uid)
    con.register("er_said", _said(out, uid))
    return f"""SELECT x.*, d.decision AS said, d.applied, CASE WHEN d.decision = 'match' THEN 'same' WHEN d.decision = 'no_match' THEN 'different'
            WHEN ga.cluster_id = gb.cluster_id THEN 'merged' ELSE 'waiting' END AS status
        FROM {index} x LEFT JOIN er_said d USING ({l}, {r})
        JOIN {read(out, 'gold.parquet')} ga ON ga.{u} = x.{l} JOIN {read(out, 'gold.parquet')} gb ON gb.{u} = x.{r}"""


def list_scored(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline, frm: float | None = None, to: float | None = None,
                source: str | None = None, status: str | None = None, record: str | None = None, page: int = 1, count: int = 100) -> dict:
    """One page of the run's pairs at 0 points or more, best first: both IDs, points, how each was found, its status,
    each comparison's level and points, and both records' compared fields. `total` counts every pair the filters keep,
    so the pages are honest. O(E log E) to order E pairs + O(page·F) for the fields."""
    uid = s.data.unique_id
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    rows = _status_sql(con, out, uid, pair_index(con, db, out, s, p))
    where = [f"match_weight >= {bits(frm)}" if frm is not None else "TRUE", f"match_weight < {bits(to)}" if to is not None else "TRUE"]
    where += {"rules": ["rule IS NOT NULL"], "model": ["rule IS NULL"]}.get(source or "", [])
    # open: waiting, or decided and not applied yet, so a queue holds still while people decide it
    where += ["(status = 'waiting' OR NOT coalesce(applied, TRUE))" if status == "open" else f"status = {lit(status)}"] if status else []
    where += [f"({l} = {lit(record)} OR {r} = {lit(record)})"] if record else []
    sql = f"SELECT * FROM ({rows}) WHERE {' AND '.join(where)}"
    total, typed = con.execute(f"SELECT count(*), count(*) FILTER (said IS NOT NULL AND NOT applied) FROM ({sql})").fetchall()[0]
    page = max(1, int(page))
    frame = con.execute(f"SELECT * FROM ({sql}) ORDER BY match_weight DESC, {l}, {r} LIMIT {int(count)} OFFSET {(page - 1) * int(count)}").df()
    model, uidl, uidr = run_model(out), f"{uid}_l", f"{uid}_r"
    lv = levels(model)
    pairs = []
    for x in frame.to_dict("records"):
        gammas = {c: int(x[f"gamma_{c}"]) for c in lv if f"gamma_{c}" in x and not pd.isna(x[f"gamma_{c}"])}
        compared = {c: dict(level=lv[c][g][0], points=round(lv[c][g][1], 2)) for c, g in gammas.items() if g in lv[c]}
        pairs.append(dict(first=x[uidl], second=x[uidr], points=round(float(x["match_weight"]), 2), sources=x["sources"], rule=x["rule"],
                          status=x["status"], said=x["said"], applied=x["applied"] if not pd.isna(x["applied"]) else None, compared=compared))
    return dict(total=int(total), typed=int(typed), page=page, count=int(count), pairs=_with_fields(con, out, s, p, pairs))


def _with_fields(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, p: Pipeline, pairs: list[dict]) -> list[dict]:
    """Each pair with both records' compared fields (as the run standardized them): what a row shows at a glance."""
    if not pairs:
        return pairs
    uid = s.data.unique_id
    have = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {read(out, 'state/records/*.parquet')}").fetchall()}
    fields = [f for f in dict.fromkeys(f for c in p.fs.model.comparisons for f in (*c.null_if_missing, *(x for lv in c.levels for x, _ in lv.any_of))) if f in have]
    ids = sorted({x["first"] for x in pairs} | {x["second"] for x in pairs})
    con.register("er_ids", pd.DataFrame({uid: ids}, dtype="string"))
    got = con.execute(f"SELECT {', '.join(q(c) for c in [uid, *fields])} FROM {read(out, 'state/records/*.parquet')} WHERE {q(uid)} IN (SELECT {q(uid)} FROM er_ids)").df()
    con.unregister("er_ids")
    by = {str(x[uid]): {f: (None if pd.isna(x[f]) else str(x[f])) for f in fields} for x in got.to_dict("records")}
    return [{**x, "fields": {f: [by.get(x["first"], {}).get(f), by.get(x["second"], {}).get(f)] for f in fields}} for x in pairs]


def list_entities(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, p: Pipeline, min_size: int = 2, record: str | None = None,
                    page: int = 1, count: int = 100) -> dict:
    """Entities of `min_size` records or more, largest first: each one's records, what joined most of them (you, the
    model or a rule: joined_by), and a name to know it by. O(N)."""
    if not (out / "gold.parquet").exists():
        raise no_run(out)
    u, gold = q(s.data.unique_id), read(out, "gold.parquet")
    where = f"cluster_id IN (SELECT cluster_id FROM {gold} WHERE {u} = {lit(record)})" if record else "TRUE"
    sizes = f"SELECT cluster_id, count(*) AS records, mode({joined_by(p)}) AS joined_by FROM {gold} GROUP BY 1 HAVING count(*) >= {int(min_size)}"
    total = con.execute(f"SELECT count(*) FROM ({sizes}) WHERE {where}").fetchall()[0][0]
    rows = con.execute(f"""SELECT * FROM ({sizes}) WHERE {where} ORDER BY records DESC, cluster_id
        LIMIT {int(count)} OFFSET {(max(1, int(page)) - 1) * int(count)}""").df()
    stored = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {read(out, 'state/records/*.parquet')}").fetchall()}
    name = next((f for f in ("full_name", "person_name", "company_name") if f in stored), None)  # one the run kept: a field the file lacks isn't
    names = {}
    if len(rows) and name:
        con.register("er_ents", rows[["cluster_id"]])
        got = con.execute(f"""SELECT g.cluster_id, list(DISTINCT r.{q(name)}) FILTER (WHERE r.{q(name)} IS NOT NULL)[1:3] AS names
            FROM {gold} g JOIN er_ents e USING (cluster_id) JOIN {read(out, 'state/records/*.parquet')} r USING ({u}) GROUP BY 1""").fetchall()
        con.unregister("er_ents")
        names = dict(got)
    return dict(total=int(total), page=max(1, int(page)), count=int(count),
                entities=[dict(entity=str(x["cluster_id"]), records=int(x["records"]), joined_by=x["joined_by"], names=names.get(x["cluster_id"]) or [])
                          for x in rows.to_dict("records")])


def show_records(con: duckdb.DuckDBPyConnection, out: Path, s: Settings, ids: list[str]) -> dict:
    """Each record's full row as the file gave it (every column, in the file's order, from the workspace's copy of
    it: inputs/…/read/), and the fields each column feeds; a record set aside says why. O(N) per call, a scan of
    the ID column."""
    files = _read_files(out)
    if not files:
        raise InputError(f"{out} keeps no copy of its records file", fix="load the file into the workspace: nayose load records … --workspace …")
    uid = s.data.unique_id
    source = f"read_parquet([{', '.join(lit(str(f)) for f in files)}], union_by_name = true)"
    columns = [c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
    key = next((c for c in columns if c == uid), None) or next((c for c in columns if norm_name(c) == norm_name(uid)), None)
    if key is None:
        raise InputError(f"{out}: the copy of the records file has no column {uid}", fix="")
    con.register("er_ids", pd.DataFrame({key: [str(x) for x in ids]}, dtype="string"))
    got = con.execute(f"SELECT * FROM {source} WHERE {q(key)} IN (SELECT {q(key)} FROM er_ids)").df()
    con.unregister("er_ids")
    feeds = {}
    for f, alts in s.columns.items():
        for c in dict.fromkeys(c for alt in alts for c in alt):
            feeds.setdefault(c, []).append(f)
    aside = {}
    if any((out / "set_aside").glob("*.parquet")):
        aside = dict(con.execute(f"SELECT {q(uid)}, any_value(reason) FROM {read(out, 'set_aside/*.parquet')} GROUP BY 1").fetchall())
    rows = {}
    for x in got.to_dict("records"):
        rows.setdefault(str(x[key]), {c: (None if pd.isna(x[c]) else str(x[c])) for c in columns})
    return dict(columns=[dict(column=c, fields=feeds.get(c, [])) for c in columns],
                records=[dict(id=str(i), row=rows.get(str(i)), set_aside=aside.get(str(i))) for i in ids])


def _read_files(out: Path) -> list[Path]:
    """The read/ copies the runs read, as steps.json names them; else every read/ copy the workspace keeps."""
    named = [Path(f["file"]) for run in folder.runs(out) for f in run.get("inputs", []) if f.get("role") == "records"]
    found = [f for f in dict.fromkeys(named) if f.exists()]
    return found or sorted((out / folder.INPUTS).glob("*/read/**/*.parquet"))


def _patterns(out: Path) -> list[dict]:  # the patterns of every pair the run scored: the full run's, and each increment's since (Run._patterns)
    return [x["patterns"] for run in folder.runs(out) for x in run.get("steps", []) if x["step"] == "score" and x.get("patterns")]


def describe_results(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline, review_from: float = 6.0) -> dict:
    """What the run found, for the Results page: how the scores came out (every scored pair, by points: exact from the
    run's patterns, each pattern one weight), the pairs waiting for people from `review_from` up, by range, what
    merged and how, entities by size, the merge conditions and what they merge, whether matches could be missed (the
    probe), the groups too big to compare by the key that made them, and person or company: the records flagged (the
    engine sure against the file's flag), those still open on the sheet, and the measuring draw's open rows. O(N + P + E)."""
    uid, gold = s.data.unique_id, read(out, "gold.parquet")
    pats, index = _patterns(out), pair_index(con, db, out, s, p)
    chart = None
    if pats:  # at 0 or more, every pair, from the index, which keeps them all; below, the keys' from the patterns, the rules' own from the index
        edges = [float("-inf"), *BANDS, float("inf")]
        counts = [0] * (len(edges) - 1)
        for pat in pats:
            k = len(pat["fields"])
            for row in pat["rows"]:
                if (w := float(row[k + 1])) < 0:
                    counts[next(i for i in range(len(counts)) if edges[i] <= w < edges[i + 1])] += int(row[k])
        band = "CASE " + " ".join(f"WHEN match_weight < {e} THEN {i}" for i, e in enumerate(BANDS)) + f" ELSE {len(BANDS)} END"
        for i, n in con.execute(f"SELECT {band}, count(*) FROM {index} WHERE match_weight >= 0 OR (rule IS NOT NULL AND sources IS NULL) GROUP BY 1").fetchall():
            counts[i] += n
        chart = [dict(down_to=None if edges[i] == float("-inf") else edges[i], up_to=None if edges[i + 1] == float("inf") else edges[i + 1], pairs=n)
                 for i, n in enumerate(counts)]
    rows = _status_sql(con, out, uid, index)
    cuts = sorted({review_from, *(c for c in (8.0, 12.0, 20.0) if c > review_from)}, reverse=True)  # the waiting pairs' ranges, from review_from up
    band = "CASE " + " ".join(f"WHEN match_weight >= {bits(c)} THEN {i}" for i, c in enumerate(cuts)) + " END"
    waiting = con.execute(f"""SELECT {band}, count(*) FROM ({rows}) WHERE status = 'waiting' AND match_weight >= {bits(review_from)} GROUP BY 1 ORDER BY 1""").fetchall()
    by_status = dict(con.execute(f"SELECT status, count(*) FROM ({rows}) GROUP BY 1").fetchall())
    sizes = con.execute(f"SELECT n, count(*) FROM (SELECT count(*) AS n FROM {gold} GROUP BY cluster_id) GROUP BY 1").fetchall()
    size_of = lambda lo, hi: sum(c for n, c in sizes if n >= lo and (hi is None or n <= hi))
    joined = dict(con.execute(f"SELECT coalesce({joined_by(p)}, 'none'), count(*) FROM {gold} GROUP BY 1").fetchall())
    steps = {x["step"]: x for run in folder.runs(out) if not run.get("part") for x in run.get("steps", [])}
    probe = [dict(stratum=x["stratum"], fields=x["fields"], pairs=x["pairs"], scored=x["scored"], missed=x["missed"], low=x["low"], high=x["high"])
             for x in steps.get("probe", {}).get("strata", [])]
    cand = steps.get("candidates", {})
    sheet = pd.read_parquet(out / "kind_review.parquet") if (out / "kind_review.parquet").exists() else pd.DataFrame(columns=["why", "kind"])
    open_ = sheet[sheet["kind"].isna()].assign(why=sheet_parts(sheet[sheet["kind"].isna()]))  # a flagged record drawn at random is to check
    has = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {gold}").fetchall()}
    flagged = con.execute(f"SELECT count(*) FROM {gold} WHERE kind_flagged").fetchall()[0][0] if "kind_flagged" in has else 0
    return dict(records=sum(c * n for n, c in sizes), entities=sum(c for _, c in sizes), joined=size_of(2, None),
                sizes=[dict(label=label, entities=size_of(lo, hi)) for lo, hi, label in SIZES],
                scores=chart, candidates=sum(x["pairs"] for x in chart) if chart else cand.get("candidates"),
                review_from=review_from, waiting=[dict(down_to=cuts[i], up_to=cuts[i - 1] if i else None, pairs=n) for i, n in waiting],
                pairs=dict(kept=sum(by_status.values()), **by_status), merged_by=joined,
                merging=merging_of(out, p), missed=probe,
                too_big=dict(skipped=cand.get("oversized_skipped", 0), kept=cand.get("oversized_kept", 0), by=cand.get("skipped_by", {}), min=p.fs.budget.min_oversized()),
                kinds=dict(flagged=int(flagged), to_check=int((open_["why"] == "decide").sum()), to_teach=int((open_["why"] == "measure").sum())))


# ---------- merging without people ----------

def merging_of(out: Path, p: Pipeline) -> dict:
    """The workspace's merge conditions (method.toml `merge`): {join: and|or, when: [...]}, none when unset; and what
    the method merges by itself when there are none (own): pairs at `line` points or more with a name compared, and
    with `rules` every rule's pair; None when nothing does (a trust line above every step)."""
    m = folder.method(out).get("merge") or {}
    return dict(join=m.get("join", "and"), when=list(m.get("when", [])), own=_own(p))


def _own(p: Pipeline) -> dict | None:  # what a run merges with no conditions (Run._accept): the tuned threshold, else the trust line
    line = p.trust.line
    return None if line is not None and math.isinf(line) else dict(line=p.fs.min_match_weight if line is None else line, rules=line is None)


def check_merging(m: dict, p: Pipeline, model: dict | None = None) -> dict:
    """`m` as method.toml may hold it, refused with what to fix when a condition names what the method lacks: points
    (a number), rules (rule names), fields (comparison → the lowest level that counts), the comparisons and levels of
    the run's `model` when given (a comparison of a field the file lacks is not in it)."""
    fix = "each condition: {points = 12}, {rules = [\"…\"]} or {fields = {name = \"…\"}}; join = \"and\" or \"or\""
    if m.get("join", "and") not in ("and", "or") or not isinstance(m.get("when", []), list):
        raise InputError("merge: join is \"and\" or \"or\", when a list of conditions", fix)
    rules = {r.name for _, _, r in p.rules.each()}
    labels = {c: [label for label, _ in by.values()] for c, by in levels(model).items()} if model else {c.name: [lv.label for lv in c.levels] for c in p.fs.model.comparisons}
    for c in m.get("when", []):
        if not isinstance(c, dict) or len(c) != 1 or next(iter(c)) not in ("points", "rules", "fields"):
            raise InputError(f"merge: a condition is one of points, rules, fields: {c}", fix)
        (k, v), = c.items()
        if k == "points" and (isinstance(v, bool) or not isinstance(v, int | float)):
            raise InputError(f"merge: points is a number: {v}", fix)
        if k == "rules" and (not isinstance(v, list) or not v or set(v) - rules):
            raise InputError(f"merge: rules are names among {sorted(rules)}: {v}", fix)
        if k == "fields" and (not isinstance(v, dict) or not v or any(f not in labels or lv not in labels[f] for f, lv in v.items())):
            raise InputError(f"merge: fields are comparisons and one of their levels: {v}", fix=f"{fix}; levels: {labels}")
    return dict(join=m.get("join", "and"), when=list(m.get("when", [])))


def merge_where(m: dict, model: dict, p: Pipeline, x: str = "x") -> str:
    """The pairs the conditions merge, as SQL on scored/ rows aliased `x`. With none, those the method merges by
    itself, as Run._accept does: every rule's pair and the model's kept pairs with a name compared at its threshold,
    or the pairs at the trust line; FALSE with the line above every step."""
    if not m.get("when"):
        own = _own(p)
        if own is None:
            return "FALSE"
        rule = "TRUE" if own["rules"] else f"{x}.match_weight >= {bits(own['line'])}"
        return f"(({x}.rule IS NOT NULL AND {rule}) OR ({x}.named AND {x}.keep AND {x}.match_weight >= {bits(own['line'])}))"
    gamma = {c: {label: g for g, (label, _) in by.items()} for c, by in levels(model).items()}
    parts = []
    for c in m["when"]:
        (k, v), = c.items()
        if k == "points":
            parts.append(f"{x}.match_weight >= {bits(v)}")
        elif k == "rules":
            parts.append(f"{x}.rule IN ({', '.join(lit(n) for n in v)})")
        elif all(lv in gamma.get(f, {}) for f, lv in v.items()):
            parts.append("(" + " AND ".join(f"{x}.{q('gamma_' + f)} >= {gamma[f][lv]}" for f, lv in v.items()) + ")")
        else:  # a comparison this run's model lacks (its field gone from the file): never met
            parts.append("FALSE")
    return "(" + f" {m.get('join', 'and').upper()} ".join(parts) + ")"


def describe_merging(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline, m: dict | None = None) -> dict:
    """What the conditions `m` (else the workspace's) would merge: pairs, per condition and all together, people's
    applied "different" left apart; and the entities that would then hold two records or more. O(E + N)."""
    m = check_merging(m, p) if m is not None else merging_of(out, p)
    model, uid = run_model(out), s.data.unique_id
    l, r, index = q(f"{uid}_l"), q(f"{uid}_r"), pair_index(con, db, out, s, p)
    con.register("er_applied", applied(out, uid)[[f"{uid}_l", f"{uid}_r", "decision"]])
    count = lambda where: con.execute(f"""SELECT count(*) FROM {index} x WHERE {where}
        AND NOT EXISTS (SELECT 1 FROM er_applied d WHERE d.{l} = x.{l} AND d.{r} = x.{r} AND d.decision = 'no_match')""").fetchall()[0][0]  # as _regroup: the applied answers, a newer one typed in waits
    each = [dict(condition=c, pairs=count(merge_where(dict(join="and", when=[c]), model, p))) for c in m["when"]]
    _regroup(con, db, out, s, p, m, model)
    entities = con.execute("SELECT count(*) FROM (SELECT cluster_id FROM gold_new GROUP BY 1 HAVING count(*) > 1)").fetchall()[0][0]
    return dict(join=m["join"], when=m["when"], each=each, pairs=count(merge_where(m, model, p)), entities=int(entities))


def _regroup(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline, m: dict, model: dict) -> None:
    """gold_new: every record's entity from people's "same" and the pairs the conditions merge, people's "different"
    never merged; resolved_by review where people joined it, else the conditions'. O(E·d + N)."""
    uid = s.data.unique_id
    l, r, u = q(f"{uid}_l"), q(f"{uid}_r"), q(uid)
    con.register("er_applied", applied(out, uid)[[f"{uid}_l", f"{uid}_r", "decision"]])  # what merges is what was applied; typed answers wait for Apply
    index = pair_index(con, db, out, s, p)
    con.execute(f"""CREATE OR REPLACE TABLE er_auto AS SELECT {l}, {r}, rule FROM {index} x WHERE {merge_where(m, model, p)}
        AND NOT EXISTS (SELECT 1 FROM er_applied d WHERE d.{l} = x.{l} AND d.{r} = x.{r} AND d.decision = 'no_match')""")
    con.execute(f"CREATE OR REPLACE TABLE er_people AS SELECT {l}, {r} FROM er_applied WHERE decision = 'match'")
    con.execute(f"CREATE OR REPLACE TABLE er_base AS SELECT {u}, {u} AS cluster_id FROM {read(out, 'gold.parquet')}")
    con.execute(f"CREATE OR REPLACE TABLE er_links AS SELECT * FROM er_people UNION SELECT {l}, {r} FROM er_auto")
    merge(con, db, "er_base", "er_links", "gold_new", uid)


def apply_merging(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline) -> dict:
    """gold.parquet rebuilt from people's applied "same" and the pairs the workspace's conditions merge (none: the pairs
    the method merges by itself), as a run would: a condition turned off parts what it joined, people's answers stand.
    No run: O(E·d + N) on the stored pairs."""
    from er.run import customer_kinds  # er.run reads merge_where from here
    uid, m, model = s.data.unique_id, merging_of(out, p), run_model(out)
    u = q(uid)
    with folder.run_lock(out):
        folder.finish_writes(out)
        _regroup(con, db, out, s, p, m, model)
        old = read(out, "gold.parquet")
        cols = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {old}").fetchall()}
        kinds = "kind" in cols
        # what resolved each record, as Run._gold says it: a rule pair of it that merged, the first rule; else the model; else people
        order = " ".join(f"WHEN {lit(rule.name)} THEN {i}" for i, _, rule in p.rules.each())
        l, r, fs = q(f"{uid}_l"), q(f"{uid}_r"), p.fs
        con.execute(f"""CREATE OR REPLACE TABLE gold AS WITH size AS (SELECT cluster_id, count(*) AS n FROM gold_new GROUP BY 1),
                touch AS (SELECT {l} AS id, rule FROM er_auto WHERE rule IS NOT NULL UNION ALL SELECT {r}, rule FROM er_auto WHERE rule IS NOT NULL),
                first AS (SELECT id, arg_min(rule, {f"CASE rule {order} END" if order else "rule"}) AS rule FROM touch GROUP BY id),
                model AS (SELECT {l} AS id FROM er_auto WHERE rule IS NULL UNION SELECT {r} FROM er_auto WHERE rule IS NULL)
                {f", customer AS ({customer_kinds('gold_new', old, u)})" if kinds else ""}
            SELECT c.{u}, c.cluster_id,
                   CASE WHEN f.id IS NOT NULL THEN {lit(fs.previous_stage)} WHEN m.id IS NOT NULL THEN {lit(fs.stage)} WHEN z.n > 1 THEN 'review' END AS resolved_stage,
                   CASE WHEN f.id IS NOT NULL THEN f.rule WHEN m.id IS NOT NULL THEN {lit(fs.model.name)} WHEN z.n > 1 THEN 'review' END AS resolved_by
                   {f", o.kind, o.kind_p, o.kind_by, {'o.kind_flagged' if 'kind_flagged' in cols else 'FALSE AS kind_flagged'}, o.kind_held, k.customer_kind" if kinds else ""}
            FROM gold_new c JOIN size z USING (cluster_id) JOIN {old} o USING ({u}) LEFT JOIN first f ON f.id = c.{u} LEFT JOIN model m ON m.id = c.{u}
            {"JOIN customer k USING (cluster_id)" if kinds else ""} ORDER BY c.{u}""")
        joined = con.execute("SELECT count(*) FROM (SELECT cluster_id FROM gold GROUP BY 1 HAVING count(*) > 1)").fetchall()[0][0]
        folder.stage(con, out, [(f"SELECT * FROM gold ORDER BY {u}", out / "gold.parquet")])
    return dict(join=m["join"], when=m["when"], entities=int(joined), merged=con.execute("SELECT count(*) FROM er_auto").fetchall()[0][0])


def merged_links(con: duckdb.DuckDBPyConnection, db: object, out: Path, s: Settings, p: Pipeline, ids: list[str]) -> pd.DataFrame:
    """The pairs among `ids` that the workspace's conditions merge, less people's "different": describe entity's links
    by 'auto', with their points. O(E) over the index."""
    uid, m = s.data.unique_id, merging_of(out, p)
    l, r = f"{uid}_l", f"{uid}_r"
    if not m["when"]:
        return pd.DataFrame(columns=[l, r, "by", "weight"])
    con.register("er_members", pd.DataFrame({"id": ids}, dtype="string"))
    con.register("er_no", applied(out, uid).query("decision == 'no_match'")[[l, r]].astype("string"))
    return con.execute(f"""SELECT {q(l)}, {q(r)}, 'auto' AS by, match_weight AS weight FROM {pair_index(con, db, out, s, p)} x
        WHERE {q(l)} IN (SELECT id FROM er_members) AND {q(r)} IN (SELECT id FROM er_members) AND {merge_where(m, run_model(out), p)}
        AND NOT EXISTS (SELECT 1 FROM er_no n WHERE n.{q(l)} = x.{q(l)} AND n.{q(r)} = x.{q(r)}) ORDER BY 1, 2""").df()


def save_merging(out: Path, m: dict) -> None:
    """method.toml's merge set to `m` (none: removed), the rest of the method as it was."""
    method = {k: v for k, v in folder.method(out).items() if k != "merge"}
    if m.get("when"):
        method["merge"] = m
    folder.write_method(out, method)
