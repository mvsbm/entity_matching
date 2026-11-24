"""The deploy's smoke test in staging: one generated file built by BigQuery (deploy/run.py, in the staging dataset)
and here by DuckDB (python -m nayose build), the two runs' scored pairs and entities compared row for row (floats to
9 places). The same answer means the functions, the procedures, the account and the dataset all work, and give what
the repository gives.

    python deploy/smoke.py PROJECT.DATASET gs://BUCKET/in/smoke.parquet LOCAL.parquet
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run  # noqa: E402
from nayose.engines import BigQuery, DuckDB  # noqa: E402

COMPARED = {"scored": "SELECT id_l, id_r, ROUND(match_weight, 9) AS w, rule, sources FROM scored ORDER BY id_l, id_r",
            "gold": "SELECT id, cluster_id, customer_kind FROM gold ORDER BY id"}


def main(argv: list[str] | None = None) -> int:
    dataset, uri, local = sys.argv[1:4] if argv is None else argv
    if run.main([dataset, "build", uri]):
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "nayose", "build", local, "--out", tmp], check=True, capture_output=True)
        here, there = DuckDB(Path(tmp) / "run.duckdb"), BigQuery(dataset, dataset)
        differ = [name for name, sql in COMPARED.items() if not here.frame(sql).astype("string").fillna("").equals(there.frame(sql).astype("string").fillna(""))]
        here.close()
        there.close()
    print(f"smoke: {'the same' if not differ else 'different: ' + ', '.join(differ)} on BigQuery and DuckDB")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
