"""er.cluster.merge against Splink 5.0.0's connected components, the clustering it replaces, as recorded in
tests/fixtures/splink-5.0.0.json for the same graphs: the same cluster per record."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from er.cluster import merge
from er.config import q

UID = "uid"
RECORDED = json.loads((Path(__file__).parent / "fixtures" / "splink-5.0.0.json").read_text(encoding="utf-8"))["cluster"]


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


@pytest.mark.parametrize("args", list(RECORDED))
def test_merge_gives_each_record_the_cluster_splink_s_connected_components_gave(engine, args):
    base, edges = graph(*json.loads(args))
    engine.register("er_t_base", base)
    engine.register("er_t_edges", edges)
    try:
        merge(engine, "er_t_base", "er_t_edges", "er_t_ours", UID)
        ours = [list(x) for x in engine.rows(f"SELECT {q(UID)}, cluster_id FROM er_t_ours ORDER BY 1")]
    finally:
        engine.unregister("er_t_base")
        engine.unregister("er_t_edges")
    theirs = RECORDED[args]
    assert (len(ours), len({c for _, c in ours})) == (theirs["records"], theirs["clusters"])
    assert hashlib.sha256(json.dumps(ours).encode()).hexdigest() == theirs["sha256"]
    assert len(edges) == 0 or theirs["clusters"] < theirs["records"]  # pairs merged something
