"""The deploy (deploy/): the image installs the engine at requirements.txt's pins, and each Cloud Run job runs a
job python -m er takes, on a run in the bucket. The image itself is built and run by hand (deploy/Dockerfile's
header), not here: it needs Docker."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def pins(path: Path) -> dict[str, str]:  # package → version, from a requirements file's name==version lines
    return {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s#]+)", path.read_text(encoding="utf-8"), flags=re.M)}


def test_the_image_installs_the_engine_at_the_pins_the_tests_run_with():
    image, tests = pins(DEPLOY / "requirements.txt"), pins(ROOT / "requirements.txt")
    shared = set(image) & set(tests)
    assert {"numpy", "pandas", "duckdb", "pyarrow", "scipy", "rapidfuzz", "scikit-learn"} <= shared
    assert {p: (image[p], tests[p]) for p in shared if image[p] != tests[p]} == {}
    assert set(image) - shared == {"google-cloud-bigquery", "google-cloud-bigquery-storage"}  # the BigQuery engine's client: the image's alone


@pytest.mark.parametrize("job", sorted(p.stem for p in (DEPLOY / "jobs").glob("*.yaml")))
def test_each_job_runs_a_job_python_m_er_takes_on_a_run_in_the_bucket(job):
    from er.__main__ import parser
    spec = (DEPLOY / "jobs" / f"{job}.yaml").read_text(encoding="utf-8")
    args = json.loads(re.search(r"^\s*args: (\[.*\])$", spec, flags=re.M).group(1))
    workspace, *words = args
    assert not workspace.startswith("/") and ".." not in workspace  # a path in the bucket (job.sh puts /gcs/ before it)
    parser().parse_args([*words, "--out", "/tmp/run"])  # what job.sh runs: python -m er takes it
    assert all(f"${{{x}}}" in spec for x in ("IMAGE", "SERVICE_ACCOUNT", "BUCKET")) and "parallelism: 1" in spec  # one writer at a time
