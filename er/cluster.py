"""Entity resolution: accepted pairs → clusters, by transitive closure (connected components): A–B and B–C make one
entity even if A–C never matched. One implementation for full runs, increments, decisions and design time alike.
"""
import duckdb
from splink import DuckDBAPI
from splink.clustering import cluster_pairwise_predictions_at_threshold

from er.candidates import q


def merge(con: duckdb.DuckDBPyConnection, db: DuckDBAPI, base: str, edges: str, into: str, uid: str) -> None:
    """`into`: `base` (uid → cluster_id, every record) with the pairs of `edges` (<uid>_l, <uid>_r) added. Each existing
    cluster is one node, so the work grows with the edges, not with the file; a merged cluster takes the smallest id, as
    a full rebuild does (Splink names a cluster after its smallest uid). O(E·d + N) for E edges, d the largest
    cluster's diameter."""
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    con.execute(f"""CREATE OR REPLACE TABLE er_e AS SELECT DISTINCT least(a.cluster_id, b.cluster_id) AS {l},
        greatest(a.cluster_id, b.cluster_id) AS {r} FROM {edges} e JOIN {base} a ON a.{u} = e.{l} JOIN {base} b ON b.{u} = e.{r}
        WHERE a.cluster_id <> b.cluster_id""")
    if not con.execute("SELECT count(*) FROM er_e").fetchall()[0][0]:
        con.execute(f"CREATE OR REPLACE TABLE {into} AS SELECT * FROM {base}")
        return
    comp = cluster_pairwise_predictions_at_threshold(
        nodes=db.register(con.sql(f"SELECT {l} AS {u} FROM er_e UNION SELECT {r} FROM er_e")),
        edges=db.register(con.sql("SELECT * FROM er_e")), db_api=db, node_id_column_name=uid)
    con.execute("DROP TABLE IF EXISTS er_comp")
    comp.as_duckdbpyrelation().project(f"{u} AS node, cluster_id::VARCHAR AS cluster_id").to_table("er_comp")
    comp.drop_table_from_database_and_remove_from_cache()
    con.execute(f"""CREATE OR REPLACE TABLE {into} AS SELECT b.{u}, coalesce(c.cluster_id, b.cluster_id) AS cluster_id
        FROM {base} b LEFT JOIN er_comp c ON c.node = b.cluster_id""")
