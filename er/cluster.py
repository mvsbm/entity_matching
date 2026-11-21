"""Entity resolution: accepted pairs → clusters, by transitive closure (connected components): A–B and B–C make one
entity even if A–C never matched. One implementation for full runs, increments, decisions and design time alike.
"""
import numpy as np
import pyarrow as pa
from scipy.sparse import coo_array
from scipy.sparse.csgraph import connected_components

from er.engine.engine import Engine
from er.config import q


def merge(engine: Engine, base: str, edges: str, into: str, uid: str) -> None:
    """`into`: `base` (uid → cluster_id, every record) with the pairs of `edges` (<uid>_l, <uid>_r) added. Each existing
    cluster is one node, so the work grows with the edges, not with the file; a merged cluster takes the smallest id of
    its nodes, in the ids' own order (a VARCHAR's: '10' before '9'), as a full rebuild does. The nodes are numbered in
    that order, scipy finds the components, and each takes its lowest-numbered node's id: O(E + V) for the components
    and O(V log V) for the numbering, plus O(N) to write `into`."""
    u, l, r = q(uid), q(f"{uid}_l"), q(f"{uid}_r")
    engine.run(f"""CREATE OR REPLACE TABLE er_e AS SELECT DISTINCT least(a.cluster_id, b.cluster_id) AS {l},
        greatest(a.cluster_id, b.cluster_id) AS {r} FROM {edges} e JOIN {base} a ON a.{u} = e.{l} JOIN {base} b ON b.{u} = e.{r}
        WHERE a.cluster_id <> b.cluster_id""")
    if not engine.value("SELECT count(*) FROM er_e"):
        engine.run(f"CREATE OR REPLACE TABLE {into} AS SELECT * FROM {base}")
        return
    try:
        engine.run(f"""CREATE OR REPLACE TEMP TABLE er_nodes AS SELECT node, (row_number() OVER (ORDER BY node) - 1)::BIGINT AS i
            FROM (SELECT {l} AS node FROM er_e UNION SELECT {r} FROM er_e)""")
        ends = engine.numpy(f"SELECT a.i, b.i FROM er_e e JOIN er_nodes a ON a.node = e.{l} JOIN er_nodes b ON b.node = e.{r}")
        a, b = (np.asarray(x, dtype=np.int64) for x in ends.values())
        n = int(engine.value("SELECT count(*) FROM er_nodes"))
        _, label = connected_components(coo_array((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n)), directed=False)
        first = np.full(label.max() + 1, n, dtype=np.int64)
        np.minimum.at(first, label, np.arange(n, dtype=np.int64))  # each component's lowest number: its smallest id
        engine.register("er_rep", pa.table({"i": np.arange(n, dtype=np.int64), "rep": first[label]}))
        engine.run("""CREATE OR REPLACE TABLE er_comp AS SELECT n.node, m.node::VARCHAR AS cluster_id
            FROM er_nodes n JOIN er_rep x ON x.i = n.i JOIN er_nodes m ON m.i = x.rep""")
        engine.run(f"""CREATE OR REPLACE TABLE {into} AS SELECT b.{u}, coalesce(c.cluster_id, b.cluster_id) AS cluster_id
            FROM {base} b LEFT JOIN er_comp c ON c.node = b.cluster_id""")
    finally:
        engine.run("DROP TABLE IF EXISTS er_nodes")
        engine.unregister("er_rep")
