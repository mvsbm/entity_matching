"""Entity resolution: accepted pairs → clusters.

connected_components  transitive closure via Splink: A–B and B–C make one entity even if A–C never matched. O((N + E)·d).
constrained           greedy union-find over edges, strongest first; refuses a merge when the two clusters hold disjoint
                      values in a cannot-link column (e.g. two different given names). O(E·α(N) + N log N).
"""
import pandas as pd
from splink import DuckDBAPI
from splink.clustering import cluster_pairwise_predictions_at_threshold

from er.config import Resolver


def connected_components(ids: pd.Series, edges: pd.DataFrame, db: DuckDBAPI, uid: str) -> pd.Series:
    if edges.empty:
        return pd.Series(ids.to_numpy(), index=ids.to_numpy(), dtype="string")
    out = cluster_pairwise_predictions_at_threshold(
        nodes=db.register(ids.to_frame()), edges=db.register(edges[[f"{uid}_l", f"{uid}_r"]].reset_index(drop=True)),
        db_api=db, node_id_column_name=uid).as_pandas_dataframe()
    return out.set_index(uid)["cluster_id"].astype("string").reindex(ids.to_numpy())


def constrained(ids: pd.Series, edges: pd.DataFrame, records: pd.DataFrame, cannot_link: tuple[str, ...],
                uid: str) -> pd.Series:
    parent = {i: i for i in ids}
    by_id = records.set_index(uid)
    values = {i: {c: ({by_id.at[i, c]} if pd.notna(by_id.at[i, c]) else set()) for c in cannot_link} for i in ids}
    size = dict.fromkeys(ids, 1)

    def find(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in edges.sort_values("score", ascending=False, kind="stable")[[f"{uid}_l", f"{uid}_r"]].itertuples(index=False):
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        if any(values[ra][c] and values[rb][c] and values[ra][c].isdisjoint(values[rb][c]) for c in cannot_link):
            continue  # refused: the two clusters conflict
        if size[ra] < size[rb]:
            ra, rb = rb, ra
        parent[rb], size[ra] = ra, size[ra] + size[rb]
        for c in cannot_link:
            values[ra][c] |= values[rb][c]
    return pd.Series([find(i) for i in ids], index=ids.to_numpy(), dtype="string")


def resolve(resolver: Resolver, ids: pd.Series, edges: pd.DataFrame, records: pd.DataFrame, db: DuckDBAPI,
            uid: str) -> pd.Series:
    if resolver.method == "connected_components":
        return connected_components(ids, edges, db, uid)
    return constrained(ids, edges, records, resolver.cannot_link, uid)
