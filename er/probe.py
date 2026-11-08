"""The matches no pair key lists, measured without labels, after a full run clusters.

A match the keys can't find shares none of what they look at, so nothing built from the links found can count it.
So the probe samples pairs directly, within groups matches tend to share ([probe] strata: the same phone, the same
postal area). A hash-stable random share f of a stratum's records is drawn. Each is paired with every record of its
group, and the pairs are scored with the run's model.

A hit is a pair at the model's line or above, with a name compared, whose records the model's likely links don't join,
directly or through others: no key listed it, or (a method without bridge) it lies between two entities the rules formed. Those links are its matches, its pairs waiting at the line or above, the rules' pairs, and
people's "same". A pair is drawn when either record is, so hits / (1 − (1 − f)²) estimates the hits among all the
stratum's pairs, with a Poisson interval. Pairs that share no stratum's group stay unmeasured: each estimate is a lower
bound of the matches the keys miss.

O(N) to group and draw, O(P·K) to score the P pairs drawn, O(L) to join the L links.
"""
import math

import duckdb

from er.candidates import q
from er.cluster import merge
from er.config import FSSpec, Probe
from er.match import named_sql, score_fs

EXAMPLES = 200  # hit pairs kept per stratum, for people to see


def bits(v: float) -> str:
    return repr(float(v))


def missed(con: duckdb.DuckDBPyConnection, db: object, model: dict, fs: FSSpec, spec: Probe, records: str, links: str, uid: str,
           resolved: str | None = None) -> list[dict]:
    """Each stratum of `spec`, measured on `records` (the run's standardized records) with the run's `model`, against
    `links` (SQL: uid_l, uid_r, the model's likely links): its pairs, the share of records drawn, the pairs scored,
    the hits, the estimate with its interval, and the first hits (id_l, id_r, weight, why). `resolved` (SQL: the uids
    the rules joined to others) names the hits between two of the rules' entities, which a method without bridge never
    joins: why "rules", not "keys", so a key can't find them."""
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    have = {c for c, *_ in con.execute(f"DESCRIBE {records}").fetchall()}
    con.execute(f"CREATE OR REPLACE TABLE er_pr_single AS SELECT {u}, {u} AS cluster_id FROM {records}")
    merge(con, db, "er_pr_single", f"({links})", "er_pr_joined", uid)
    out = []
    for name, keys in spec.strata:
        cols = [k.name for k in keys]
        if not set(cols) <= have:
            continue
        filled, by = " AND ".join(f"{q(c)} IS NOT NULL" for c in cols), ", ".join(map(q, cols))
        squares, pairs = con.execute(f"SELECT coalesce(sum(c * c), 0), coalesce(sum(c * (c - 1) // 2), 0) FROM (SELECT count(*) AS c FROM {records} WHERE {filled} GROUP BY {by})").fetchone()
        f = min(1.0, spec.pairs / squares) if squares else 0.0
        con.execute(f"""CREATE OR REPLACE TABLE er_pr_pairs AS SELECT DISTINCT least(a.{u}, b.{u}) AS {l}, greatest(a.{u}, b.{u}) AS {r}
            FROM (SELECT * FROM {records} WHERE {filled} AND hash({u}) % 1000000 < {round(f * 1_000_000)}) a
            JOIN {records} b USING ({by}) WHERE a.{u} <> b.{u}""")
        scored = con.execute("SELECT count(*) FROM er_pr_pairs").fetchone()[0]
        hits = []
        if scored:
            score_fs(model, records, "er_pr_pairs", db, uid, into="er_pr_scores")
            between = f"s.{l} IN {resolved} AND s.{r} IN {resolved}" if resolved else "FALSE"
            hits = con.execute(f"""SELECT s.{l}, s.{r}, round(s.match_weight, 2), CASE WHEN {between} THEN 'rules' ELSE 'keys' END
                FROM er_pr_scores s JOIN er_pr_joined a ON a.{u} = s.{l}
                JOIN er_pr_joined b ON b.{u} = s.{r} WHERE s.match_weight >= {bits(fs.min_match_weight)} AND {named_sql(fs)}
                AND a.cluster_id <> b.cluster_id ORDER BY s.match_weight DESC""").fetchall()
        drawn = 1 - (1 - f) ** 2  # a pair is drawn when either of its records is
        h = len(hits)
        low, high = (max(h - 1.96 * math.sqrt(h), 0.0), h + 1.96 * math.sqrt(h)) if h else (0.0, 3.0)  # none: the rule of three
        out.append(dict(stratum=name, fields=[k.column for k in keys], pairs=int(pairs), drawn=round(f, 6), scored=int(scored), hits=h,
                        between_rules=sum(why == "rules" for *_, why in hits),
                        missed=round(h / drawn) if drawn else None, low=round(low / drawn) if drawn else None, high=round(high / drawn) if drawn else None,
                        examples=[[a, b, w, why] for a, b, w, why in hits[:EXAMPLES]]))
    return out
