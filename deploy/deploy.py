"""Deploy nayose into one BigQuery dataset, the run's. It makes:
- the functions (nayose.procedures.functions): the comparisons, in JavaScript or over BigQuery's own EDIT_DISTANCE;
  EM and the entities, in Python; the hash;
- the method's SQL functions, and one procedure a job, declaring the values config.toml gives
  (nayose.procedures.procedures);
- the name model the records read (the table name_weights).
Each statement is CREATE OR REPLACE, so a deploy run again makes the same.

    python deploy/deploy.py PROJECT.DATASET [--mapping mapping.sql] [--sql DIR]

--mapping: the deployment's own column mapping (its secret, nayose-mapping); without it, NAYOSE_MAPPING's, else
nayose/mapping.sql's.
--sql DIR: send nothing; write the deploy to DIR as deploy.sql, to run in the BigQuery console, and name_weights.csv,
to upload as the table name_weights (docs/console.md). No Google account is needed to make them.
Runs as nayose-deployer (deploy/Jenkinsfile).
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's nayose

import nayose  # noqa: E402
from nayose.engines import BigQuery  # noqa: E402
from nayose.procedures import functions, procedures  # noqa: E402


def main(argv: list[str] | None = None, client: object = None, bigquery: object = None) -> int:
    """Make nayose in the dataset the arguments name, and return the exit code.

    `client` and `bigquery` go to engines.BigQuery: a test's fakes, or None for BigQuery's own.
    """
    p = argparse.ArgumentParser(prog="deploy/deploy.py", description="nayose made in a BigQuery dataset")
    p.add_argument("dataset", help="PROJECT.DATASET: the run's")
    p.add_argument("--mapping", type=Path, help="the deployment's mapping.sql (else NAYOSE_MAPPING's, or nayose's)")
    p.add_argument("--sql", type=Path, metavar="DIR", help="write deploy.sql and name_weights.csv to DIR, send nothing")
    a = p.parse_args(argv)
    statements = [*functions(a.dataset), *procedures(a.dataset, a.mapping)]
    if a.sql:
        a.sql.mkdir(parents=True, exist_ok=True)
        (a.sql / "deploy.sql").write_text(";\n\n".join(statements) + ";\n", encoding="utf-8")
        # every term quoted, so a term of spaces or digits reads as text; each weight in 17 digits, read back exactly
        nayose.name_weights().to_csv(a.sql / "name_weights.csv", index=False, quoting=csv.QUOTE_NONNUMERIC,
                                     float_format="%.17g")
        return 0
    engine = BigQuery(a.dataset, client=client, bigquery=bigquery)
    try:
        for sql in statements:
            engine.run(sql)
        engine.put("name_weights", nayose.name_weights())
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
