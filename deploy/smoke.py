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

import run
from nayose.engines import BigQuery, DuckDB

COMPARED = {"scored": "SELECT id_l, id_r, ROUND(points, 9) AS points, rule, generators FROM scored ORDER BY id_l, id_r",
            "gold": "SELECT id, entity, entity_kind FROM gold ORDER BY id",
            # BigQuery's EDIT_DISTANCE (cl_levenshtein's there) counts characters, as the twin does: 3, and the cut's 2,
            # not the bytes' counts
            "levenshtein": "SELECT cl_levenshtein('東京都港区芝', '東京府北区') AS d, "
                           "cl_levenshtein_cut('東京都港区', '大阪府北区', 1) AS c"}


def main(argv: list[str] | None = None) -> int:
    """Build the file on BigQuery and on DuckDB, say whether the two runs agree (COMPARED), and return 0 if they do."""
    dataset, uri, local = sys.argv[1:4] if argv is None else argv
    if run.main([dataset, "build", uri]):
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "nayose", "build", local, "--out", tmp], check=True, capture_output=True)
        here, there = DuckDB(Path(tmp) / "run.duckdb"), BigQuery(dataset)
        def text(frame):  # each cell as text, a missing one empty, so the engines' types don't matter
            return frame.astype("string").fillna("")

        differ = [name for name, sql in COMPARED.items() if not text(here.frame(sql)).equals(text(there.frame(sql)))]
        here.close()
        there.close()
    print(f"smoke: {'the same' if not differ else 'different: ' + ', '.join(differ)} on BigQuery and DuckDB")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
