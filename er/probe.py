"""The matches no pair key lists, measured without labels, after a full run clusters.

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
import itertools
import math

import duckdb

from er.cluster import merge
from er.config import FSSpec, Key, Probe, bits, q
from er.match import bound_tests, named_sql, score_fs

EXAMPLES = 200  # hit pairs kept per stratum, for people to see


def missed(con: duckdb.DuckDBPyConnection, db: object, model: dict, fs: FSSpec, spec: Probe, records: str, links: str, uid: str,
           resolved: str | None = None, apart: str | None = None) -> list[dict]:
    """Each stratum of `spec`, measured on `records` (the run's standardized records) with the run's `model`, against
    `links` (SQL: uid_l, uid_r, the model's likely links): its pairs, the share of records drawn, the pairs scored,
    the hits, the estimate with its interval, and the first hits (id_l, id_r, weight, why). `resolved` (SQL: the uids
    the rules joined to others) names the hits between two of the rules' entities, which a method without bridge never
    joins: why "rules", not "keys", so a key can't find them. `apart` (SQL: uid_l, uid_r) are pairs people said are
    different: never hits."""
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    have = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {records}").fetchall()}
    con.execute(f"CREATE OR REPLACE TABLE er_pr_single AS SELECT {u}, {u} AS cluster_id FROM {records}")
    merge(con, db, "er_pr_single", f"({links})", "er_pr_joined", uid)
    out = []
    for name, keys in spec.strata:
        cols = [k.name for k in keys]
        if not set(cols) <= have:
            continue
        filled, by = " AND ".join(f"{q(c)} IS NOT NULL" for c in cols), ", ".join(map(q, cols))
        squares, pairs = con.execute(f"SELECT coalesce(sum(c * c), 0), coalesce(sum(c * (c - 1) // 2), 0) FROM (SELECT count(*) AS c FROM {records} WHERE {filled} GROUP BY {by})").fetchall()[0]
        if not squares:  # no record holds the stratum's value: nothing to draw from
            continue
        cut = max(1, round(min(1.0, spec.pairs / squares) * 2**32))  # the share drawn, as the draw makes it: at any size at least one in 2³²
        f = cut / 2**32
        con.execute(f"""CREATE OR REPLACE TABLE er_pr_pairs AS SELECT DISTINCT least(a.{u}, b.{u}) AS {l}, greatest(a.{u}, b.{u}) AS {r}
            FROM (SELECT * FROM {records} WHERE {filled} AND hash({u}) % 4294967296 < {cut}) a
            JOIN {records} b USING ({by}) WHERE a.{u} <> b.{u}""")
        scored = con.execute("SELECT count(*) FROM er_pr_pairs").fetchall()[0][0]
        hits = []
        if scored:
            score_fs(model, records, "er_pr_pairs", db, uid, into="er_pr_scores", floor=fs.min_match_weight, bound=bound_tests(fs.model))  # a hit is at the line
            between = f"s.{l} IN {resolved} AND s.{r} IN {resolved}" if resolved else "FALSE"
            hits = con.execute(f"""SELECT s.{l}, s.{r}, round(s.match_weight, 2), CASE WHEN {between} THEN 'rules' ELSE 'keys' END
                FROM er_pr_scores s JOIN er_pr_joined a ON a.{u} = s.{l}
                JOIN er_pr_joined b ON b.{u} = s.{r} WHERE s.match_weight >= {bits(fs.min_match_weight)} AND {named_sql(fs)}
                AND a.cluster_id <> b.cluster_id {f"AND NOT EXISTS (SELECT 1 FROM ({apart}) x WHERE x.{l} = s.{l} AND x.{r} = s.{r})" if apart else ""}
                ORDER BY hash(s.{l}, s.{r})""").fetchall()  # in hash order: the first are a random sample of them
        drawn = 1 - (1 - f) ** 2  # a pair is drawn when either of its records is
        h = len(hits)
        low, high = (max(h - 1.96 * math.sqrt(h), 0.0), h + 1.96 * math.sqrt(h)) if h else (0.0, 3.0)  # none: the rule of three
        by_keys = sum(why == "keys" for *_, why in hits)
        out.append(dict(stratum=name, fields=[k.column for k in keys], pairs=int(pairs), drawn=f, scored=int(scored), hits=h,
                        between_rules=h - by_keys, keys_missed=round(by_keys / drawn) if drawn else None,
                        missed=round(h / drawn) if drawn else None, low=round(low / drawn) if drawn else None, high=round(high / drawn) if drawn else None,
                        examples=[[a, b, w, why] for a, b, w, why in hits[:EXAMPLES]]))
    return out


# the fields a key to find them may join: each as the run keeps it (a field, or its normalized copy)
MENU = (("phone", ()), ("postal_code", ("first3",)), ("postal_code", ()), ("city", ()), ("prefecture", ()), ("town_code", ()), ("address_code", ()),
        ("any_name", ("initial",)), ("given_name", ("kana_fold",)), ("person_name", ("kana_fold",)), ("birth_date", ()))


def keys_for(con: duckdb.DuckDBPyConnection, records: str, uid: str, strata: list[dict], have: list[tuple[Key, ...]], most: float, top: int = 3) -> list[dict]:
    """Pair keys that would list the matches the probe found no key lists (its hits of why "keys"): each one or two
    fields of MENU the run's records hold, not a key the method has (`have`), on which both records of at least a
    fifth of the hits agree; within `most` pairs per record, the budget's; best first, by the hits it lists, then its
    cost. Each: its fields (field or field:normalizer, as method.toml add_keys takes them), the hits it lists of how
    many, its pairs per record, and about how many matches it would find (the share it lists of a stratum's hits, of
    that stratum's estimate; the largest). O(hits) to check each key, O(N) to price each of at most ten."""
    hits = [(i, a, b) for i, st in enumerate(strata) for a, b, _, why in st["examples"] if why == "keys"]
    if not hits:
        return []
    cols = {c for c, *_ in con.execute(f"DESCRIBE SELECT * FROM {records}").fetchall()}
    menu = [k for k in (Key(f, n) for f, n in MENU) if k.name in cols]
    u = q(uid)
    ids = sorted({x for _, a, b in hits for x in (a, b)})
    con.execute("CREATE OR REPLACE TEMP TABLE er_hit_ids (id VARCHAR)")
    con.executemany("INSERT INTO er_hit_ids VALUES (?)", [(x,) for x in ids])
    rows = con.execute(f"SELECT {u}, {', '.join(q(k.name) for k in menu)} FROM {records} WHERE {u} IN (SELECT id FROM er_hit_ids)").fetchall()
    value = {r[0]: dict(zip((k.name for k in menu), r[1:])) for r in rows}
    owned = {frozenset(k.name for k in keys) for keys in have}
    found = []
    for keys in [*((k,) for k in menu), *itertools.combinations(menu, 2)]:
        if frozenset(k.name for k in keys) in owned:
            continue
        agree = [(i, a, b) for i, a, b in hits if a in value and b in value and all(value[a][k.name] is not None and value[a][k.name] == value[b][k.name] for k in keys)]
        if len(agree) >= max(1, len(hits) / 5):
            found.append((keys, agree))
    n = con.execute(f"SELECT count(*) FROM {records}").fetchall()[0][0]
    out = []
    for keys, agree in sorted(found, key=lambda x: -len(x[1]))[:10]:
        filled, by = " AND ".join(f"{q(k.name)} IS NOT NULL" for k in keys), ", ".join(q(k.name) for k in keys)
        pairs = con.execute(f"SELECT coalesce(sum(c * (c - 1) // 2), 0) FROM (SELECT count(*) AS c FROM {records} WHERE {filled} GROUP BY {by})").fetchall()[0][0]
        if pairs / n > most:
            continue
        finds = max(sum(1 for i, *_ in agree if i == j) / len(st["examples"]) * st["hits"] / (1 - (1 - st["drawn"]) ** 2) if st["examples"] and st["drawn"] else 0
                    for j, st in enumerate(strata))  # of the stratum's hits, the share this key lists, scaled as the stratum's estimate (a pair drawn with either record)
        out.append(dict(keys=[k.column + "".join(f":{x}" for x in k.normalize) for k in keys], lists=len(agree), of=len(hits),
                        pairs_per_record=round(pairs / n, 2), finds=round(finds)))
    return sorted(out, key=lambda x: (-x["lists"], x["pairs_per_record"]))[:top]
