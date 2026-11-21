"""The matches no pair key lists, measured without labels, at design time (scripts/benchmark.py), once a run clusters.

A match the keys can't find shares none of what they look at, so nothing built from the links found can count it.
So the probe samples pairs directly, within groups matches tend to share ([probe] strata: the same phone, the same
postal area). A hash-stable random share f of a stratum's records is drawn. Each is paired with every record of its
group, and the pairs are scored with the run's model.

A hit is a pair at the model's line or above, with a name compared, whose records the model's likely links don't join,
directly or through others: no key listed it, or (a method without bridge) it lies between two entities the rules formed. Those links are its matches, its pairs waiting at the line or above, the rules' pairs, and
people's "same". A pair people said is different is no hit: they kept it apart. A pair is drawn when either record is, so hits / (1 − (1 − f)²) estimates the hits among all the
stratum's pairs, with a Poisson interval. Pairs that share no stratum's group stay unmeasured: each estimate is a lower
bound of the matches the keys miss.

O(N) to group and draw, O(P·K) to score the P pairs drawn, O(L) to join the L links.
"""
import math

import duckdb

from er.cluster import merge
from er.config import FSSpec, Probe, bits, q
from er.match import bound_tests, named_sql, score_fs

EXAMPLES = 200  # hit pairs kept per stratum, for people to see


def missed(engine: duckdb.DuckDBPyConnection, model: dict, fs: FSSpec, spec: Probe, records: str, links: str, uid: str,
           resolved: str | None = None, apart: str | None = None) -> list[dict]:
    """Each stratum of `spec`, measured on `records` (the run's standardized records) with the run's `model`, against
    `links` (SQL: uid_l, uid_r, the model's likely links): its pairs, the share of records drawn, the pairs scored,
    the hits, the estimate with its interval, and the first hits (id_l, id_r, weight, why). `resolved` (SQL: the uids
    the rules joined to others) names the hits between two of the rules' entities, which a method without bridge never
    joins: why "rules", not "keys", so a key can't find them. `apart` (SQL: uid_l, uid_r) are pairs people said are
    different: never hits."""
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    have = {c for c, *_ in engine.rows(f"DESCRIBE SELECT * FROM {records}")}
    engine.run(f"CREATE OR REPLACE TABLE er_pr_single AS SELECT {u}, {u} AS cluster_id FROM {records}")
    merge(engine, "er_pr_single", f"({links})", "er_pr_joined", uid)
    out = []
    for name, keys in spec.strata:
        cols = [k.name for k in keys]
        if not set(cols) <= have:
            continue
        filled, by = " AND ".join(f"{q(c)} IS NOT NULL" for c in cols), ", ".join(map(q, cols))
        squares, pairs = engine.row(f"SELECT coalesce(sum(c * c), 0), coalesce(sum(c * (c - 1) // 2), 0) FROM (SELECT count(*) AS c FROM {records} WHERE {filled} GROUP BY {by})")
        if not squares:  # no record holds the stratum's value: nothing to draw from
            continue
        cut = max(1, round(min(1.0, spec.pairs / squares) * 2**32))  # the share drawn, as the draw makes it: at any size at least one in 2³²
        f = cut / 2**32
        engine.run(f"""CREATE OR REPLACE TABLE er_pr_pairs AS SELECT DISTINCT least(a.{u}, b.{u}) AS {l}, greatest(a.{u}, b.{u}) AS {r}
            FROM (SELECT * FROM {records} WHERE {filled} AND hash({u}) % 4294967296 < {cut}) a
            JOIN {records} b USING ({by}) WHERE a.{u} <> b.{u}""")
        scored = engine.value("SELECT count(*) FROM er_pr_pairs")
        hits = []
        if scored:
            score_fs(model, records, "er_pr_pairs", engine, uid, into="er_pr_scores", floor=fs.min_match_weight, bound=bound_tests(fs.model))  # a hit is at the line
            between = f"s.{l} IN {resolved} AND s.{r} IN {resolved}" if resolved else "FALSE"
            hits = engine.rows(f"""SELECT s.{l}, s.{r}, round(s.match_weight, 2), CASE WHEN {between} THEN 'rules' ELSE 'keys' END
                FROM er_pr_scores s JOIN er_pr_joined a ON a.{u} = s.{l}
                JOIN er_pr_joined b ON b.{u} = s.{r} WHERE s.match_weight >= {bits(fs.min_match_weight)} AND {named_sql(fs)}
                AND a.cluster_id <> b.cluster_id {f"AND NOT EXISTS (SELECT 1 FROM ({apart}) x WHERE x.{l} = s.{l} AND x.{r} = s.{r})" if apart else ""}
                ORDER BY hash(s.{l}, s.{r})""")  # in hash order: the first are a random sample of them
        drawn = 1 - (1 - f) ** 2  # a pair is drawn when either of its records is
        h = len(hits)
        low, high = (max(h - 1.96 * math.sqrt(h), 0.0), h + 1.96 * math.sqrt(h)) if h else (0.0, 3.0)  # none: the rule of three
        by_keys = sum(why == "keys" for *_, why in hits)
        out.append(dict(stratum=name, fields=[k.column for k in keys], pairs=int(pairs), drawn=f, scored=int(scored), hits=h,
                        between_rules=h - by_keys, keys_missed=round(by_keys / drawn) if drawn else None,
                        missed=round(h / drawn) if drawn else None, low=round(low / drawn) if drawn else None, high=round(high / drawn) if drawn else None,
                        examples=[[a, b, w, why] for a, b, w, why in hits[:EXAMPLES]]))
    return out


def probe(run) -> list[dict]:
    """Each [probe] stratum measured on a Run that has clustered (missed): its likely links are its matches, the rules'
    pairs people didn't call different, and people's "same"; a pair people called different is never a hit. O(N + P·K + L)."""
    fs, l, r = run.pipeline.fs, q(run.l), q(run.r)
    links = f"""SELECT {l}, {r} FROM matches
        UNION ALL SELECT {l}, {r} FROM rule_kept k WHERE NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = k.{l} AND d.{r} = k.{r} AND d.decision = 'no_match')
        UNION ALL SELECT {l}, {r} FROM er_decisions WHERE decision = 'match'"""
    return missed(run.engine, run.scoring, fs, run.pipeline.probe, "records", links, run.uid, None if fs.bridge else run._sized("rule_clusters", ">"),
                  apart=f"SELECT {l}, {r} FROM er_decisions WHERE decision = 'no_match'")
