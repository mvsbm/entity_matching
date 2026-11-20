"""er.cluster.merge against Splink 5.0's connected components, the clustering it replaces: the same cluster per record."""
import numpy as np
import pandas as pd
import pytest
from splink import DuckDBAPI
from splink.clustering import cluster_pairwise_predictions_at_threshold

from er.cluster import merge
from er.config import q

UID = "uid"


def splink_merge(con, base: str, edges: str, into: str) -> None:  # merge as it was written on Splink's clustering
    u, l, r = q(UID), q(f"{UID}_l"), q(f"{UID}_r")
    con.execute(f"""CREATE OR REPLACE TABLE er_e AS SELECT DISTINCT least(a.cluster_id, b.cluster_id) AS {l},
        greatest(a.cluster_id, b.cluster_id) AS {r} FROM {edges} e JOIN {base} a ON a.{u} = e.{l} JOIN {base} b ON b.{u} = e.{r}
        WHERE a.cluster_id <> b.cluster_id""")
    if not con.execute("SELECT count(*) FROM er_e").fetchall()[0][0]:
        con.execute(f"CREATE OR REPLACE TABLE {into} AS SELECT * FROM {base}")
        return
    db = DuckDBAPI(connection=con)
    comp = cluster_pairwise_predictions_at_threshold(
        nodes=db.register(con.sql(f"SELECT {l} AS {u} FROM er_e UNION SELECT {r} FROM er_e")),
        edges=db.register(con.sql("SELECT * FROM er_e")), db_api=db, node_id_column_name=UID)
    con.execute("DROP TABLE IF EXISTS er_comp")
    comp.as_duckdbpyrelation().project(f"{u} AS node, cluster_id::VARCHAR AS cluster_id").to_table("er_comp")
    comp.drop_table_from_database_and_remove_from_cache()
    con.execute(f"""CREATE OR REPLACE TABLE {into} AS SELECT b.{u}, coalesce(c.cluster_id, b.cluster_id) AS cluster_id
        FROM {base} b LEFT JOIN er_comp c ON c.node = b.cluster_id""")


def graph(seed: int, n: int, e: int, chain: int = 0, grouped: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """n records with ids drawn as numbers written as text ('10' sorts before '9'), e random pairs, a chain of `chain`
    records in shuffled order (a long diameter), and, `grouped`, clusters made before: each record in its group's
    smallest id."""
    rng = np.random.default_rng(seed)
    ids = np.array([str(x) for x in rng.choice(10 * n, n, replace=False)])
    cluster = ids.copy()
    if grouped:  # clusters made before: a record's cluster is its group's smallest id, as merge leaves them
        groups = rng.integers(0, n // 3, n)
        cluster = pd.Series(ids).groupby(groups).transform("min").to_numpy()
    pairs = rng.integers(0, n, (e, 2))
    path = rng.permutation(n)[:chain]
    pairs = np.vstack([pairs, np.column_stack([path[:-1], path[1:]])]) if chain else pairs
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    base = pd.DataFrame({UID: ids, "cluster_id": cluster}, dtype="string")
    edges = pd.DataFrame({f"{UID}_l": ids[pairs[:, 0]], f"{UID}_r": ids[pairs[:, 1]]}, dtype="string")
    return base, edges


@pytest.mark.parametrize("seed, n, e, chain, grouped", [(0, 50, 30, 0, False), (1, 2_000, 1_500, 0, False), (2, 2_000, 300, 1_500, False),
                                                       (3, 3_000, 2_000, 400, True), (4, 20, 0, 0, False), (5, 500, 2_000, 0, True)])
def test_merge_gives_each_record_the_cluster_splink_s_connected_components_gave(con, seed, n, e, chain, grouped):
    base, edges = graph(seed, n, e, chain, grouped)
    con.register("er_t_base", base)
    con.register("er_t_edges", edges)
    try:
        merge(con, "er_t_base", "er_t_edges", "er_t_ours", UID)
        splink_merge(con, "er_t_base", "er_t_edges", "er_t_splink")
        ours, theirs = (con.execute(f"SELECT {q(UID)}, cluster_id FROM {t} ORDER BY 1").fetchall() for t in ("er_t_ours", "er_t_splink"))
        assert ours == theirs and len(ours) == n
        assert e == 0 or len({c for _, c in ours}) < n  # pairs merged something
    finally:
        con.unregister("er_t_base")
        con.unregister("er_t_edges")
