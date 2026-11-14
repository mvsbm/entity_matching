"""How a written run found what it found, its pairs scored again with the run's model (scored_again): one pair, step by
step (explain_pair, pair_tests); one record against others (compare_records); the pairs inside an entity
(entity_pairs); one pair key (describe_key); the patterns of the whole run (list_patterns); and the method, with the
pairs people decided and the changes worth trying (describe_method)."""
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd

from er.config import DeletionKeys, InputError, KeyBlocker, Pipeline, SortedNeighbourhood, lit, q
from er.folder import TRIALS, latest_decisions, method, rounds, runs
from er.io import read_parquet
from er.match import levels, named_sql, review_floor, scaled_prior, score_fs
from er.probe import keys_for
from er.report import households, key_found, key_listed, likely_links, no_run, reached_by_gamma
from er.review_state import applied, read, trust_state
from er.standardize import prepared

if TYPE_CHECKING:
    from er.settings import Settings


def line_change(decided: pd.DataFrame, t: float, lo: float = -math.inf, hi: float = math.inf) -> tuple[float, int] | None:
    """The acceptance line in [lo, hi] that sets right the most pairs people decided, against the model alone
    (accepted: named and at the line or above), and sets wrong none it gets right at `t`; the nearest such line on a
    tie. None: no line does better. Rows: weight, named, same (people said match). Lines tried: the half bit at or
    just below each pair's weight, and the next one up. [lo, hi] is the band people review: past it, the pairs a line
    would take or drop are pairs nobody looked at. O(D·B) with numpy, D decided, B the half bits in the band."""
    if decided.empty:
        return None
    w, named, same = decided["weight"].to_numpy(), decided["named"].to_numpy(bool), decided["same"].to_numpy(bool)
    right = lambda x: (named & (w >= x)) == same
    now, best = right(t), None
    for x in sorted({float(v) for f in np.floor(w * 2) / 2 for v in (f, f + 0.5) if lo <= v <= hi}):
        at = right(x)
        if (now & ~at).any():
            continue
        fixes = int((at & ~now).sum())
        if fixes and (best is None or (fixes, -abs(x - t)) > (best[1], -abs(best[0] - t))):
            best = (x, fixes)
    return best



def run_model(out: Path) -> dict:  # the model the run in `out` scored with: its u from the file, else as fitted
    scoring, fitted = out / "state" / "scoring.json", out / "state" / "model.json"
    if not fitted.exists():
        raise no_run(out)
    return json.loads(scoring.read_text(encoding="utf-8"))["model"] if scoring.exists() else json.loads(fitted.read_text(encoding="utf-8"))


def scored_again(con: duckdb.DuckDBPyConnection, db: object, out: Path, uid: str, pairs: str, into: str) -> dict:
    """The pairs of the table `pairs` (uid_l, uid_r) scored as the run in `out` scored its candidates: its model, λ for
    its size, on its standardized records (those the pairs touch), into the table `into`. Returns the model.
    O(N) to find the records + O(P·K)."""
    l, r, model = q(f"{uid}_l"), q(f"{uid}_r"), run_model(out)
    stored = read(out, "state/records/*.parquet")
    con.execute(f"CREATE OR REPLACE TABLE er_touched AS SELECT * FROM {stored} WHERE {q(uid)} IN (SELECT {l} FROM {pairs} UNION SELECT {r} FROM {pairs})")
    n = con.execute(f"SELECT count(*) FROM read_parquet({lit(out / 'gold.parquet')})").fetchall()[0][0]
    score_fs(model, "er_touched", pairs, db, uid, into=into, n_records=n)
    return model



def describe_method(out: Path, p: Pipeline, s: "Settings") -> dict:
    """What the run in the workspace `out` shows about its method, for people improving it: each round so far
    (rounds.json), with the links it made and the audits people decided in it; the line, the weight bands, and each pair
    people decided, scored again with the run's model; each match rule's pairs, how many of them score below the
    line, and how many people said are different; each pair key's pairs and seconds, the links it found and those only
    it found; each comparison step's bits and the pairs that reached it; and the changes worth trying. Changes nothing.
    O((D + R)·K) to score the D decided pairs and the R rule pairs again, + O(E) over the run's files."""
    from scipy.stats import beta

    from er.strings import connect
    if not (out / "gold.parquet").exists():
        raise no_run(out)
    uid, t, fs = s.data.unique_id, p.fs.min_match_weight, p.fs
    l, r = f"{uid}_l", f"{uid}_r"
    con, db = connect(s.compute)

    # the pairs people decided, the latest decision per pair, and the rules' pairs: scored again, with the name check
    latest = latest_decisions(out, uid, ("decision", "why", "round"))
    con.execute(f"CREATE TABLE er_decided AS SELECT * FROM {latest}" if latest else
                f"CREATE TABLE er_decided ({q(l)} VARCHAR, {q(r)} VARCHAR, decision VARCHAR, why VARCHAR, round INTEGER)")
    con.execute(f"CREATE TABLE er_rule AS SELECT {q(l)}, {q(r)}, rule FROM {read(out, 'rule_kept/*.parquet')}")
    con.execute(f"CREATE TABLE er_pairs AS SELECT {q(l)}, {q(r)} FROM er_decided UNION SELECT {q(l)}, {q(r)} FROM er_rule")
    model = scored_again(con, db, out, uid, "er_pairs", "er_scored")
    scored = f"SELECT {q(l)}, {q(r)}, match_weight AS weight, {named_sql(fs)} AS named FROM er_scored s"
    decided = con.execute(f"""SELECT d.*, s.weight, s.named, d.decision = 'match' AS same, x.rule FROM er_decided d JOIN ({scored}) s USING ({q(l)}, {q(r)})
        LEFT JOIN (SELECT {q(l)}, {q(r)}, min(rule) AS rule FROM er_rule GROUP BY ALL) x USING ({q(l)}, {q(r)}) ORDER BY s.weight""").df()
    rules = {name: (pairs, below, apart, alone) for name, pairs, below, apart, alone in con.execute(f"""SELECT x.rule, count(*), count(*) FILTER (WHERE s.weight < {t} OR NOT s.named),
        count(d.decision) FILTER (WHERE d.decision = 'no_match'), count(d.decision) FILTER (WHERE d.decision = 'no_match' AND (s.weight < {t} OR NOT s.named))
        FROM er_rule x JOIN ({scored}) s USING ({q(l)}, {q(r)})
        LEFT JOIN er_decided d USING ({q(l)}, {q(r)}) GROUP BY 1""").fetchall()}

    # what the run's log and files say: the rounds, each key's pairs and seconds, each step's reach, the links by key
    log = runs(out)
    facts = [x for run in log for x in run["steps"]]
    listed, reached = key_listed(facts), reached_by_gamma(facts)
    found = key_found(con, likely_links(out, p), q(l), q(r))  # as describe matching counts them
    ran = rounds(out)
    now = len(ran)
    audits = decided[(decided["why"] == "audit") & (decided["round"] == now)] if now else decided.iloc[:0]
    false = int((~audits["same"].astype(bool)).sum())
    review = read_parquet(out / "review.parquet") if (out / "review.parquet").exists() else pd.DataFrame(columns=["why", "decision"])
    bands = next((x for x in reversed(facts) if x["step"] == "report"), {}).get("weight_bands", [])  # as qa.md shows them
    by_round = lambda i, x: decided[(decided["round"] == i) & x(decided)]
    ran = [dict(round=i, method=x["method"], at=x["at"], matched=x["matched"], expected_false=x["expected_false"],
                   decided=len(by_round(i, lambda d: True)), audited=len(by_round(i, lambda d: d["why"] == "audit")),
                   false_found=len(by_round(i, lambda d: (d["why"] == "audit") & ~d["same"].astype(bool))))
              for i, x in enumerate(ran, 1)]

    # the changes worth trying: none applies itself
    proposals = []
    if line := line_change(decided[decided["rule"].isna()], t, review_floor(p), t + 4):  # within the band people decide and audit
        proposals.append(dict(change=dict(line=line[0]), why=f"sets right {line[1]:,} pair{'s' if line[1] > 1 else ''} people decided, and wrong none"))
    proposals += [dict(change=dict(drop_rules=[name]), why=f"people said {apart:,} of its pairs {'are' if apart > 1 else 'is'} different"
                       + (f", {alone:,} of them joined by it alone" if alone < apart else ""))
                  for name, (_, _, apart, alone) in rules.items() if alone]  # one the model links anyway stays joined without the rule
    total = sum(pairs for pairs, _ in listed.values())  # a key worth leaving out: a tenth of the pairs or more, and no link only it finds
    proposals += [dict(change=dict(drop_keys=[b.name]), why=f"{listed[b.name][0] / total:.0%} of the pairs, and no link only it finds")
                  for b in fs.blockers if listed.get(b.name, (0,))[0] >= total / 10 and not found.get(b.name, (0, 0))[1]]
    probed = [x for x in facts if x["step"] == "probe"]  # a key for the matches the probe found no key lists (er.probe)
    if probed and (out / "state" / "records").is_dir():
        have = [k.keys for k in fs.blockers if isinstance(k, KeyBlocker)]
        proposals += [dict(change=dict(add_keys=[k["keys"]]), adds=k, why=f"lists {k['lists']:,} of the {k['of']:,} matches the method missed that the probe found, "
                           f"about {k['finds']:,} in all; {k['pairs_per_record']:g} more pairs a record")
                      for k in keys_for(con, read(out, "state/records/*.parquet"), uid, probed[-1]["strata"], have, fs.budget.max_pairs_per_record)]
    by_gamma = levels(model)
    return dict(
        line=t, review_from=review_floor(p), method=method(out), round=now, rounds=ran,
        audits=dict(checked=len(audits), false=false,  # the false rate's one-sided 95% bound, as er.evaluate.fp_upper (design time)
                    at_most=float(beta.ppf(0.95, false + 1, len(audits) - false)) if len(audits) > false else 1.0),
        to_decide=int(((review["why"] == "decide") & review["decision"].isna()).sum()),
        bands=[dict(weight_from=float(a), pairs=int(b), accepted=int(c)) for a, b, c in bands],
        decided=[dict(id_l=x[l], id_r=x[r], decision=x["decision"], why=x["why"], round=None if pd.isna(x["round"]) else int(x["round"]),
                      weight=round(float(x["weight"]), 2), named=bool(x["named"]), rule=x["rule"]) for x in decided.to_dict("records")],
        rules=[dict(name=x.name, pairs=rules.get(x.name, (0, 0, 0, 0))[0], below=rules.get(x.name, (0, 0, 0, 0))[1],
                    different=rules.get(x.name, (0, 0, 0, 0))[2]) for _, _, x in p.rules.each()],
        keys=[dict(name=b.name, pairs=listed.get(b.name, (0, 0.0))[0], seconds=round(listed.get(b.name, (0, 0.0))[1], 2),
                   matched=found.get(b.name, (0, 0))[0], only=found.get(b.name, (0, 0))[1]) for b in fs.blockers],
        steps=[dict(comparison=c, level=label, bits=round(bits, 2), reached=reached.get((c, g), 0))
               for c, by in by_gamma.items() for g, (label, bits) in sorted(by.items(), reverse=True)],
        proposals=proposals, trust=trust_state(con, out, p, uid),
        trials=sorted((json.loads(f.read_text(encoding="utf-8")) for f in (out / TRIALS).glob("*.json") if f.stem.isdigit()), key=lambda x: x["trial"]))



def explain_pair(out: Path, p: Pipeline, s: "Settings", first: str, second: str, cap: int = 400) -> dict:
    """One pair of the run in `out`, as the model saw it: per comparison, each step top to bottom with its tests, the
    values each compared (after its normalization), the function, threshold and the score it gave; the step the pair
    reached and its points; the points two records start from (this file's pairs, and those the model expects are one
    customer: their ratio) and the total. What found the pair (a rule, the keys, people), whether it
    merged; and when its records are in different customers of which one holds more, both customers' records and every
    pair across them (at most `cap`), scored: a "same" merges them all. O(cap·K)."""
    from er.strings import connect
    uid = s.data.unique_id
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    shown = lambda v: None if pd.isna(v) else v  # a value as JSON carries it: no NaN
    if not (out / "gold.parquet").exists():
        raise no_run(out)
    a, b = sorted((str(first), str(second)))
    con, db = connect(s.compute)
    gold = con.execute(f"""SELECT {u}, cluster_id FROM {read(out, 'gold.parquet')} WHERE cluster_id IN
        (SELECT cluster_id FROM {read(out, 'gold.parquet')} WHERE {u} IN (?, ?))""", [a, b]).df()
    cluster = dict(zip(gold[uid], gold["cluster_id"]))
    if missing := [x for x in (a, b) if x not in cluster]:
        raise InputError(f"{missing}: no record of the run in {out}", fix="check the IDs as the run wrote them: a spreadsheet may read 0000000151 as the number 151")
    side = lambda x: sorted(gold.loc[gold["cluster_id"] == cluster[x], uid])
    group_a, group_b = side(a), side(b)
    across = cluster[a] != cluster[b] and (len(group_a) > 1 or len(group_b) > 1)
    pairs = [(a, b)] + ([(min(x, y), max(x, y)) for x in group_a for y in group_b if {x, y} != {a, b}][:cap] if across else [])
    con.register("er_xp_df", pd.DataFrame(pairs, columns=[f"{uid}_l", f"{uid}_r"]))
    con.execute("CREATE TABLE er_xp AS SELECT * FROM er_xp_df")
    model = scored_again(con, db, out, uid, "er_xp", "er_xs")
    scores = con.execute("SELECT * FROM er_xs").df().set_index([f"{uid}_l", f"{uid}_r"])
    me = scores.loc[(a, b)]
    recs = con.execute("SELECT * FROM er_touched").df().set_index(uid)

    comparisons, tests = pair_tests(p, s, recs, me, model, a, b)
    reached = {c["comparison"]: (c["reached"], c["bits"]) for c in comparisons}
    n = con.execute(f"SELECT count(*) FROM {read(out, 'gold.parquet')}").fetchall()[0][0]
    lam = scaled_prior(model, n)
    where = f"WHERE {l} = ? AND {r} = ?"
    found = dict(rule=None, keys=None, people=None, merged=False)
    if any((out / "rule_kept").glob("*.parquet")):
        if hit := con.execute(f"SELECT rule, merged FROM {read(out, 'rule_kept/*.parquet')} {where}", [a, b]).fetchall():
            found.update(rule=hit[0][0], merged=bool(hit[0][1]))
    for name, merged in (("matches", True), ("proposed", False)):
        if any((out / name).glob("*.parquet")) and (hit := con.execute(f"SELECT sources FROM {read(out, name + '/*.parquet')} {where}", [a, b]).fetchall()):
            found.update(keys=hit[0][0].split("+"), merged=found["merged"] or merged)
    if not found["rule"] and not found["keys"] and (out / "review.parquet").exists():  # below the line with no trust line: only the sheet keeps them
        if (hit := con.execute(f"SELECT sources FROM {read(out, 'review.parquet')} {where}", [a, b]).fetchall()) and hit[0][0]:
            found["keys"] = hit[0][0].split("+")
    decided = applied(out, uid)
    if len(decided) and len(said := decided[(decided[f"{uid}_l"] == a) & (decided[f"{uid}_r"] == b)]):
        found["people"] = said["decision"].iloc[-1]
    fields = [f for f in s.columns if f not in ("id", "entity") and f in recs.columns]
    record = lambda x: {"id": x, **{f: shown(recs.at[x, f]) for f in fields}} if x in recs.index else {"id": x}
    groups = dict(group_a=[], group_b=[], across=[])
    if across:
        con.register("er_xg", pd.DataFrame({uid: sorted(set(group_a) | set(group_b))}))
        stored = read(out, "state/records/*.parquet")
        everyone = con.execute(f"SELECT * FROM {stored} WHERE {u} IN (SELECT {u} FROM er_xg)").df().set_index(uid)
        show = lambda x: {"id": x, **{f: shown(everyone.at[x, f]) for f in fields if f in everyone.columns}}
        groups = dict(group_a=[show(x) for x in group_a], group_b=[show(x) for x in group_b],
                      across=[dict(id_l=x, id_r=y, weight=round(float(scores.at[(x, y), "match_weight"]), 2)) for x, y in pairs])
    trust, weight, prior = p.trust.line, float(me["match_weight"]), math.log2(lam / (1 - lam))
    home = bool(households(con, read(out, "state/records/*.parquet"), f"SELECT * FROM er_xp WHERE {l} = {lit(a)} AND {r} = {lit(b)}", uid, p))
    return dict(id_l=a, id_r=b, weight=round(weight, 2), probability=float(me["match_probability"]), prior=round(prior, 2), household=home,
                pairs_all=n * (n - 1) // 2, pairs_same=round(lam * n * (n - 1) / 2),  # the prior in counts: λ is their ratio
                common=round(weight - prior - sum(bits for _, bits in reached.values()), 2),  # term frequencies: how common the values agreed on are
                line=None if trust is None else "none" if math.isinf(trust) else trust, threshold=p.fs.min_match_weight,
                same_customer=cluster[a] == cluster[b], records=[record(a), record(b)], comparisons=comparisons, tests=tests, found=found, **groups)


def pair_tests(p: Pipeline, s: "Settings", recs: pd.DataFrame, me: pd.Series, model: dict, a: str, b: str) -> tuple[list[dict], list[dict]]:
    """One scored pair (its row `me` of scored_again's table; `recs`, the records it touched), as people can follow it,
    `a`'s side first: per comparison the step it reached and its bits; and every step's tests, top to bottom, with the
    values each compared as written (raw), after each normalizer (prep) and as compared (a, b), its score and whether it
    passed. The engine stops at a comparison's first test that passes; these are all of them. O(K·L)."""
    from er.strings import FUNCTIONS
    shown = lambda v: None if pd.isna(v) else v  # a value as JSON carries it: no NaN
    by_gamma, comps = levels(model), [c for c in p.fs.model.comparisons if f"gamma_{c.name}" in me.index]

    def test(c: object, step: str, col: str, comp: object) -> dict:
        name = comp.column(col)
        va, vb = (shown(recs.at[x, name]) if name in recs.columns else None for x in (a, b))
        raw = [shown(recs.at[x, col]) if col in recs.columns else None for x in (a, b)]  # as written, before the normalizers
        steps = [prepared(str(v), comp.normalize, s.standardize) if v is not None and comp.normalize else [] for v in raw]
        chain = next((x for x in steps if x), [])  # both sides go through the same steps; a missing side has none
        prep = [[step_, *(side[k][1] if side else None for side in steps)] for k, (step_, _) in enumerate(chain)]
        if va is None or vb is None:
            score, passed = None, False
        elif comp.function == "exact":
            score, passed = float(va == vb), va == vb
        else:
            f = FUNCTIONS[comp.function]
            score = float(f.scorer(str(va), str(vb)))
            score = float(np.float32(score)) if comp.function in ("jaro", "jaro_winkler") else score  # as the engine tests it: rapidfuzz's score is a float32
            passed = score >= comp.threshold if f.similarity else score <= comp.threshold
        return dict(comparison=c.name, step=step, field=col, function=comp.function, threshold=comp.threshold, normalize=" ".join(comp.normalize),
                    raw=raw, prep=prep, a=va, b=vb, score=None if score is None else round(score, 4), passed=bool(passed))
    comparisons = [dict(comparison=c.name, reached=label, bits=round(bits, 2)) for c in comps for label, bits in [by_gamma[c.name][int(me[f"gamma_{c.name}"])]]]
    return comparisons, [test(c, lv.label, col, comp) for c in comps for lv in c.levels for col, comp in lv.any_of]


def describe_key(out: Path, p: Pipeline, s: "Settings", name: str, cap: int = 12) -> dict:
    """One pair key of the run in `out`, to inspect: what it lists and on which fields; the pairs it listed, the links it
    found and those only it found (up to 3, to explain). For a key of equal values or of one-letter deletions, how many
    records share each of its values (1 … 9, 10 or more), its largest values, and one group: the records of the value
    behind a link only it found (else any link it found), at most `cap`. For sorted neighbours, the records around such
    a link in its sort order. O(N) for the sizes (O(N·L) with deletions), on the run's prepared records."""
    from er.candidates import Records, _rows, block_cols
    from er.config import keys_of
    b = next((x for x in p.fs.blockers if x.name == name), None)
    if b is None:
        raise InputError(f"{name}: no pair key of the method has that name", fix="see them: nayose describe matching --workspace …")
    if not (out / "gold.parquet").exists():
        raise no_run(out)
    uid, l, r = s.data.unique_id, q(f"{s.data.unique_id}_l"), q(f"{s.data.unique_id}_r")
    from er.strings import connect
    con = connect(s.compute)[0]
    con.execute(f"CREATE TABLE er_dk AS SELECT * FROM {read(out, 'state/records/*.parquet')}")
    have = {c for c, in con.execute("SELECT column_name FROM (DESCRIBE er_dk)").fetchall()}
    keys = keys_of(b)
    log = runs(out)
    listed = key_listed([x for run in log for x in run["steps"]]).get(name, (0,))[0]
    likely = likely_links(out, p)
    links = f"SELECT {l} AS a, {r} AS z, match_weight, sources FROM ({likely})"
    matched, only_n = key_found(con, likely, l, r).get(name, (0, 0))[:2]  # as describe matching counts them
    only = [[a, z, round(float(w), 1)] for a, z, w in con.execute(f"SELECT a, z, match_weight FROM ({links}) WHERE sources = ? ORDER BY hash(a || z) LIMIT 3", [name]).fetchall()]
    pick = only[0][:2] if only else next(iter(con.execute(f"SELECT a, z FROM ({links}) WHERE list_contains(string_split(sources, '+'), ?) ORDER BY hash(a || z) LIMIT 1",
                                                          [name]).fetchall()), None)
    shown = [c for c in dict.fromkeys([*(k.column for k in keys), "full_name", "company_name", "address"]) if c in have]
    row = lambda x: {"id": x[0], **{c: (None if pd.isna(v) else v) for c, v in zip(shown, x[1:])}}
    cols = ", ".join([q(uid), *(q(c) for c in shown)])
    out_ = dict(name=name, method=type(b).__name__, keys=[dict(field=k.column, normalize=list(k.normalize)) for k in keys], pairs=listed,
                matched=matched, only=only_n, examples=only, sizes=None, largest=[], group=None, around=None)
    if not all(k.name in have for k in keys):  # turned off: a field it reads is not in the file
        return out_
    rec = Records("er_dk", uid, con)
    if isinstance(b, (KeyBlocker, DeletionKeys)):
        bc = block_cols(b)
        groups = f"SELECT {', '.join(bc)}, count(*) AS n FROM {_rows(b, rec)} GROUP BY ALL"
        out_["sizes"] = [dict(records=a, values=c) for a, c in con.execute(f"SELECT least(n, 10), count(*) FROM ({groups}) GROUP BY 1 ORDER BY 1").fetchall()]
        out_["largest"] = [dict(value=" · ".join(str(v) for v in x[:-1]), records=x[-1]) for x in con.execute(f"SELECT * FROM ({groups}) ORDER BY n DESC LIMIT 3").fetchall()]
        if pick:
            rows_ = _rows(b, rec)
            ids = [x for x, in con.execute(f"""SELECT x.{q(uid)} FROM {rows_} x JOIN (SELECT {', '.join(bc)} FROM {rows_} WHERE {q(uid)} = ? INTERSECT
                SELECT {', '.join(bc)} FROM {rows_} WHERE {q(uid)} = ? LIMIT 1) k USING ({', '.join(c.strip('"') for c in bc)}) ORDER BY 1 LIMIT {cap + 1}""", list(pick)).fetchall()]
            got = {x[0]: x for x in con.execute(f"SELECT {cols} FROM er_dk WHERE {q(uid)} IN (SELECT unnest(?))", [ids]).fetchall()}
            value = con.execute(f"""SELECT {', '.join(bc)} FROM {rows_} WHERE {q(uid)} = ? INTERSECT SELECT {', '.join(bc)} FROM {rows_} WHERE {q(uid)} = ? LIMIT 1""", list(pick)).fetchall()
            out_["group"] = dict(value=" · ".join(str(v) for v in value[0]) if value else None, pair=list(pick), records=[row(got[x]) for x in ids[:cap] if x in got],
                                 more=len(ids) > cap)
    elif isinstance(b, SortedNeighbourhood) and pick:  # the records around the pair in the key's order
        k = q(b.key.name)
        at = con.execute(f"""SELECT min(pos), max(pos) FROM (SELECT {q(uid)}, row_number() OVER (ORDER BY {k}, {q(uid)}) AS pos FROM er_dk WHERE {k} IS NOT NULL)
            WHERE {q(uid)} IN (?, ?)""", list(pick)).fetchall()[0]
        if at[0] is not None:
            got = con.execute(f"""SELECT {cols}, {k} FROM (SELECT *, row_number() OVER (ORDER BY {k}, {q(uid)}) AS pos FROM er_dk WHERE {k} IS NOT NULL)
                WHERE pos BETWEEN ? AND ? ORDER BY pos""", [max(at[0] - 2, 1), at[1] + 2]).fetchall()
            out_["around"] = dict(window=b.window, pair=list(pick), records=[{**row(x[:-1]), "sorted_as": x[-1]} for x in got])
    rec.close()
    return out_


def compare_records(out: Path, p: Pipeline, s: "Settings", first: str, others: list[str], cap: int = 50) -> dict:
    """One record of the run in `out` against others (at most `cap`), each pair scored as the run scores: the records,
    and per other its points, each comparison's step and every test, `first`'s side first (pair_tests). For people to
    compare a record's candidates: another customer's records, or the rest of its own. O(cap·K·L)."""
    from er.strings import connect
    uid, first = s.data.unique_id, str(first)
    others = [x for x in dict.fromkeys(map(str, others)) if x != first][:cap]
    if not (out / "gold.parquet").exists():
        raise no_run(out)
    if not others:
        raise InputError("no other record to compare with", fix="give the first record's ID, then one or more others")
    con, db = connect(s.compute)
    known = {x for x, in con.execute(f"SELECT {q(uid)} FROM read_parquet({lit(out / 'gold.parquet')}) WHERE {q(uid)} IN (SELECT unnest(?))", [[first, *others]]).fetchall()}
    if missing := [x for x in (first, *others) if x not in known]:
        raise InputError(f"{missing}: no record of the run in {out}", fix="check the IDs as the run wrote them: a spreadsheet may read 0000000151 as the number 151")
    pairs = [tuple(sorted((first, x))) for x in others]
    con.register("er_cr_df", pd.DataFrame(pairs, columns=[f"{uid}_l", f"{uid}_r"]))
    con.execute("CREATE TABLE er_cr AS SELECT * FROM er_cr_df")
    model = scored_again(con, db, out, uid, "er_cr", "er_cs")
    scores = con.execute("SELECT * FROM er_cs").df().set_index([f"{uid}_l", f"{uid}_r"])
    recs = con.execute("SELECT * FROM er_touched").df().set_index(uid)
    fields = [f for f in s.columns if f not in ("id", "entity") and f in recs.columns]
    record = lambda x: {"id": x, **{f: None if pd.isna(recs.at[x, f]) else recs.at[x, f] for f in fields}}
    candidates = []
    for x, key in zip(others, pairs):
        me = scores.loc[key]
        comparisons, tests = pair_tests(p, s, recs, me, model, first, x)
        candidates.append(dict(id=x, weight=round(float(me["match_weight"]), 2), comparisons=comparisons, tests=tests))
    return dict(first=first, records=[record(x) for x in (first, *others)], candidates=candidates)


def entity_pairs(out: Path, s: "Settings", ids: list[str], links: list[dict], cap: int = 50) -> dict:
    """Inside an entity of 2 to `cap` records (describe_entity's, sorted): every pair scored as the run scores, with
    what linked it directly (a rule, the model, people), none when only other records join it, and the step each
    comparison reached with its bits; and its weakest links, those whose loss would split it. O(n²·K) to score,
    O(E·(n + E)) for the weakest, n records and E links."""
    from er.strings import connect
    uid = s.data.unique_id
    if not 2 <= len(ids) <= cap:
        return dict(pairs=[], weakest=[], capped=len(ids) > cap)
    con, db = connect(s.compute)
    con.register("er_ep_df", pd.DataFrame([(x, y) for i, x in enumerate(ids) for y in ids[i + 1:]], columns=[f"{uid}_l", f"{uid}_r"]))
    con.execute("CREATE TABLE er_ep AS SELECT * FROM er_ep_df")
    model = scored_again(con, db, out, uid, "er_ep", "er_es")
    by: dict[tuple, list] = {}
    for x in links:
        by.setdefault((x[f"{uid}_l"], x[f"{uid}_r"]), []).append(x["by"])
    edges = [e for e, how in by.items() if any(h != "people: no_match" for h in how)]

    def splits(without: tuple) -> bool:
        seen, todo = {ids[0]}, [ids[0]]
        while todo:
            v = todo.pop()
            for e in edges:
                if e != without and v in e and (o := e[1] if e[0] == v else e[0]) not in seen:
                    seen.add(o)
                    todo.append(o)
        return len(seen) < len(ids)
    by_gamma = levels(model)
    gammas = [c for c, *_ in con.execute("DESCRIBE er_es").fetchall() if c.startswith("gamma_") and c.removeprefix("gamma_") in by_gamma]
    rows = con.execute(f"SELECT {q(uid + '_l')}, {q(uid + '_r')}, match_weight, {', '.join(q(g) for g in gammas) or 'NULL'} FROM er_es ORDER BY 1, 2").fetchall()
    steps = lambda gs: [dict(comparison=g.removeprefix("gamma_"), reached=label, bits=round(bits, 2))
                        for g, v in zip(gammas, gs) for label, bits in [by_gamma[g.removeprefix("gamma_")][int(v)]]]
    return dict(pairs=[dict(id_l=x, id_r=y, weight=round(w, 2), by=by.get((x, y), []), comparisons=steps(gs)) for x, y, w, *gs in rows],
                weakest=[dict(id_l=x, id_r=y) for x, y in edges if splits((x, y))], capped=False)


def list_patterns(out: Path, p: Pipeline) -> dict:
    """The model's pairs of the whole run as patterns, one step per comparison: per pattern its pairs and their mean
    points, how many merged, how many are on the review sheet for people (wait), how many more were in its band but not
    asked (held: their records are one customer already, another pair of the same two customers is asked, or, with a
    trust line, they are outside its sample), how many stayed apart, and three of them to explain. From the score steps
    in steps.json, the full run's and each increment's (Run.score), and the sheet. O(P + S) for P patterns, S sheet rows."""
    log = runs(out)
    acc: dict[tuple, list] = {}
    fields: list[str] = []
    for x in (x for run in log for x in run["steps"] if x.get("patterns")):
        fields = x["patterns"]["fields"]
        for *g, pairs, points, merged, wait, some in x["patterns"]["rows"]:
            have = acc.setdefault(tuple(g), [0, 0.0, 0, 0, []])
            have[:4] = [have[0] + pairs, have[1] + pairs * points, have[2] + merged, have[3] + wait]
            have[4] = (have[4] + some)[:3]
    by_gamma = levels(run_model(out)) if acc else {}
    sheet = read_parquet(out / "review.parquet") if acc and (out / "review.parquet").exists() else pd.DataFrame()
    shown = [f for f in fields if f in sheet.columns]
    rules = {r.name for _, _, r in p.rules.each()}  # a rule's pairs waiting on the sheet are no pattern's: the model's pairs only
    model = sheet[(sheet["why"] == "decide") & ~sheet["sources"].astype("string").str.split("+").str[0].isin(rules)] if len(sheet) else sheet
    asked = (model.fillna({f: "missing" for f in shown}).groupby(shown).size().to_dict() if len(shown) == len(fields) and len(sheet) else None)  # None: no sheet to read
    on_sheet = lambda steps: asked.get(tuple(steps[f] for f in fields) if len(fields) > 1 else steps[fields[0]], 0)
    rows = []
    for g, (n, total, merged, band, some) in acc.items():
        steps = {f: by_gamma[f][v][0] for f, v in zip(fields, g) if f in by_gamma}
        wait = on_sheet(steps) if asked is not None else band
        rows.append(dict(key=".".join(map(str, g)), steps=steps, bits={f: round(by_gamma[f][v][1], 1) for f, v in zip(fields, g) if f in by_gamma}, pairs=n,
                         points=round(total / n, 2), merged=merged, wait=wait, held=max(band - wait, 0), apart=n - merged - max(band, wait),
                         examples=[dict(id_l=a, id_r=b) for a, b in some]))
    rows.sort(key=lambda x: -x["points"])
    return dict(fields=fields, pairs=sum(x["pairs"] for x in rows), threshold=p.fs.min_match_weight, patterns=rows)
