"""The deploy: nayose made in one BigQuery dataset, the run's: its functions (engines.functions: the comparisons in
JavaScript or over BigQuery's own EDIT_DISTANCE, EM and the entities in Python, the hash), the method's SQL functions and one procedure a job
(engines.procedures, the values config.toml gives), and the name model the records read (name_weights). Each statement
is CREATE OR REPLACE: run again, it makes the same.

    python deploy/deploy.py PROJECT.DATASET [--mapping mapping.sql]

--mapping: the deployment's own column mapping (its secret, nayose-mapping); without it, nayose/mapping.sql's.
Runs as nayose-deployer (deploy/Jenkinsfile).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's nayose

import nayose  # noqa: E402
from nayose.engines import BigQuery, functions, procedures  # noqa: E402


def main(argv: list[str] | None = None, client: object = None, bigquery: object = None) -> int:
    p = argparse.ArgumentParser(prog="deploy/deploy.py", description="nayose made in a BigQuery dataset")
    p.add_argument("dataset", help="PROJECT.DATASET: the run's")
    p.add_argument("--mapping", type=Path, help="the deployment's mapping.sql (default: nayose/mapping.sql)")
    a = p.parse_args(argv)
    engine = BigQuery(a.dataset, client=client, bigquery=bigquery)
    try:
        for sql in [*functions(a.dataset), *procedures(a.dataset, a.mapping)]:
            engine.run(sql)
        engine.put("name_weights", nayose.name_weights())
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
