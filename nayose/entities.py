"""decide's connected components (decide.sql): the pairs people said match → each record they join and its entity,
named by the entity's smallest ID (in a string's order), so A–B and B–C make one entity even if A–C was never
decided. A pure function, JSON in and JSON out, standard library only: decide.sql calls it as entities_of, BigQuery's
Python UDF (engines.functions) and DuckDB's alike. O(D log D) for D pairs.
"""
import json


def of(pairs: str) -> str:
    """pairs: {"pairs": [{"l": id, "r": id}, ...], or null for none}. Each ID a pair names, with its entity's smallest
    ID: [{"id": id, "entity": id}, ...]."""
    up: dict[str, str] = {}

    def root(x: str) -> str:
        while up.setdefault(x, x) != x:
            up[x] = up[up[x]]  # halved on the way: the next walk is shorter
            x = up[x]
        return x

    for p in json.loads(pairs)["pairs"] or []:
        a, b = root(p["l"]), root(p["r"])
        up[max(a, b)] = min(a, b)  # a root is its entity's smallest ID: the smaller of two roots stays one
    return json.dumps([{"id": x, "entity": root(x)} for x in up])
