"""decide's connected components (decide.sql): turn the pairs people said match into each record's entity.

An entity is named by its smallest ID, in a string's order, so A–B and B–C make one entity even if A–C was never
decided. of() is a pure function, JSON in and JSON out, using the standard library only. decide.sql calls it as
entities_of, on BigQuery as a Python UDF (nayose.procedures.functions) and on DuckDB alike. O(D log D) for D pairs.
"""
import json


def of(pairs: str) -> str:
    """Return each ID the pairs name, with its entity's smallest ID.

    `pairs` is {"pairs": [{"l": id, "r": id}, ...]}, or {"pairs": null} for none. The result is
    [{"id": id, "entity": id}, ...].
    """
    parent: dict[str, str] = {}  # union–find: each ID's parent; a root is its entity's smallest ID

    def root(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]  # path halving: the next walk is shorter
            x = parent[x]
        return x

    for p in json.loads(pairs)["pairs"] or []:
        a, b = root(p["l"]), root(p["r"])
        parent[max(a, b)] = min(a, b)  # of two roots, the smaller stays one
    return json.dumps([{"id": x, "entity": root(x)} for x in parent])
