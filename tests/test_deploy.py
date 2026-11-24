"""The deploy (deploy/): the image installs the engine at requirements.txt's pins; each Cloud Run job runs a job
python -m er takes, on a run in the bucket; and the runner (deploy/runner.py) lets one job at a time write a run and
publishes its result whole, or not at all. The image itself is built and run in CI (.github/workflows/tests.yml),
not here: it needs Docker."""
import importlib.util
import json
import re
import time
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
spec = importlib.util.spec_from_file_location("runner", DEPLOY / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def pins(path: Path) -> dict[str, str]:  # package → version, from a requirements file's name==version lines
    return {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s#]+)", path.read_text(encoding="utf-8"), flags=re.M)}


def test_the_image_installs_the_engine_at_the_pins_the_tests_run_with():
    image, tests = pins(DEPLOY / "requirements.txt"), pins(ROOT / "requirements.txt")
    shared = set(image) & set(tests)
    assert {"numpy", "pandas", "duckdb", "pyarrow", "scipy", "rapidfuzz", "scikit-learn"} <= shared
    assert {p: (image[p], tests[p]) for p in shared if image[p] != tests[p]} == {}
    assert set(image) - shared == {"google-cloud-bigquery", "google-cloud-bigquery-storage", "google-cloud-storage"}  # the image's alone


@pytest.mark.parametrize("job", sorted(p.stem for p in (DEPLOY / "jobs").glob("*.yaml")))
def test_each_job_runs_a_job_the_runner_takes_on_a_run_in_the_bucket(job):
    from er.__main__ import parser
    spec = (DEPLOY / "jobs" / f"{job}.yaml").read_text(encoding="utf-8")
    run, *words = json.loads(re.search(r"^\s*args: (\[.*\])$", spec, flags=re.M).group(1))
    assert not run.startswith("/") and ".." not in run  # a path in the bucket, under the mount
    if words != ["check"]:  # the runner's own; the rest are python -m er's
        parser().parse_args([*words, "--out", "/tmp/run"])
    assert all(f"${{{x}}}" in spec for x in ("IMAGE", "SERVICE_ACCOUNT", "BUCKET", "SETTINGS_SECRET")) and "parallelism: 1" in spec
    assert "ER_SETTINGS, value: /secrets/settings/settings.toml" in spec and "maxRetries: 0" in spec  # the mapping from Secret Manager; a failure is looked at, not retried


@pytest.fixture
def r(tmp_path, monkeypatch):  # the runner on a bucket that is a folder: Files, as on one machine
    monkeypatch.setattr(runner, "MOUNT", tmp_path / "gcs")
    monkeypatch.setattr(runner, "WORK", tmp_path / "work")
    monkeypatch.setattr(runner, "LOCK_WAIT", 0)
    monkeypatch.setattr(runner, "POLL", 0.01)
    return runner


def appends(words: list[str]) -> int:  # a job as python -m er runs it: changes the run in --out (one more line), exit 0
    gold = Path(words[-1]) / "gold.parquet"
    gold.write_text((gold.read_text() if gold.exists() else "") + words[0] + "\n")
    return 0


def test_a_writing_job_publishes_a_new_version_each_from_the_one_before_and_keeps_the_newest_three(r):
    store = r.Files(r.MOUNT)
    assert r.main(["runs/main", "build", "x"], store, appends) == 0
    for _ in range(4):
        assert r.main(["runs/main", "update", "y"], store, appends) == 0
    current = store.read("runs/main/CURRENT")[0]
    versions = sorted(p.name for p in (r.MOUNT / "runs/main/v").iterdir())
    assert len(versions) == r.KEEP == 3 and versions[-1] == current
    assert (r.MOUNT / "runs/main/v" / current / "gold.parquet").read_text() == "build\n" + "update\n" * 4
    assert store.read("runs/main/LOCK") is None  # given back


def test_a_job_that_fails_or_dies_publishes_nothing_and_gives_the_lock_back(r):
    store = r.Files(r.MOUNT)
    r.main(["runs/main", "build", "x"], store, appends)
    before, versions = store.read("runs/main/CURRENT"), sorted((r.MOUNT / "runs/main/v").iterdir())

    def fails(words):  # changes the run, then exits 2
        appends(words)
        return 2

    def dies(words):
        appends(words)
        raise MemoryError
    assert r.main(["runs/main", "update", "y"], store, fails) == 2
    with pytest.raises(MemoryError):
        r.main(["runs/main", "update", "y"], store, dies)
    assert store.read("runs/main/CURRENT") == before and sorted((r.MOUNT / "runs/main/v").iterdir()) == versions
    assert store.read("runs/main/LOCK") is None


def test_a_second_writer_waits_for_the_lock_and_a_lookup_reads_meanwhile_and_a_dead_job_s_lock_is_taken_over(r):
    store, ran = r.Files(r.MOUNT), []
    r.main(["runs/main", "build", "x"], store, appends)
    before = store.read("runs/main/CURRENT")
    store.create("runs/main/LOCK", json.dumps(dict(execution="another", at=time.time())))
    assert r.main(["runs/main", "update", "y"], store, lambda w: ran.append(w) or 0) == 75 and not ran  # never ran
    assert r.main(["runs/main", "lookup", "--record", "1"], store, lambda w: ran.append(w) or 0) == 0 and ran  # reads, takes no lock
    assert store.read("runs/main/CURRENT") == before  # a lookup publishes nothing
    held = store.read("runs/main/LOCK")
    store.delete("runs/main/LOCK", held[1])
    store.create("runs/main/LOCK", json.dumps(dict(execution="gone", at=time.time() - r.LEASE - 1)))  # outlived any job's timeout
    assert r.main(["runs/main", "update", "y"], store, appends) == 0 and store.read("runs/main/CURRENT") != before
    assert store.read("runs/main/LOCK") is None


class FakeGcs:
    """The Storage API as runner.Bucket uses it: objects with generations, and a write or a delete refused with 412
    when if_generation_match isn't the object's (0: absent)."""

    class Refused(Exception):
        def __init__(self, code: int) -> None:
            self.code = code

    def __init__(self) -> None:
        self.objects, self.next, self.name = {}, 1, "b"

    def bucket(self, name):
        return self

    def get_blob(self, name):
        return self.blob(name) if name in self.objects else None

    def blob(self, name):
        gcs, blob = self, type("Blob", (), {})()
        blob.generation = gcs.objects.get(name, (None, None))[1]

        def check(want):
            if gcs.objects.get(name, (None, 0))[1] != want:
                raise FakeGcs.Refused(412)

        def upload_from_string(text, content_type=None, if_generation_match=None):
            check(if_generation_match)
            gcs.objects[name], gcs.next = (text, gcs.next), gcs.next + 1
            blob.generation = gcs.objects[name][1]

        def download_as_text(if_generation_match=None):
            if name not in gcs.objects:
                raise FakeGcs.Refused(404)
            check(if_generation_match)
            return gcs.objects[name][0]

        def delete(if_generation_match=None):
            if name not in gcs.objects:
                raise FakeGcs.Refused(404)
            check(if_generation_match)
            del gcs.objects[name]
        blob.upload_from_string, blob.download_as_text, blob.delete = upload_from_string, download_as_text, delete
        return blob


def test_the_bucket_makes_the_lock_once_and_moves_current_only_from_the_version_it_read(r):
    store = r.Bucket("b", client=FakeGcs())
    first = store.create("runs/main/LOCK", "a")
    assert first is not None and store.create("runs/main/LOCK", "b") is None  # one holder, however many try
    store.delete("runs/main/LOCK", first + 1)  # another's generation: not deleted
    assert store.read("runs/main/LOCK") == ("a", first)
    store.delete("runs/main/LOCK", first)
    assert store.read("runs/main/LOCK") is None
    one = store.put("runs/main/CURRENT", "v1", None)
    assert store.put("runs/main/CURRENT", "v2", None) is None and store.put("runs/main/CURRENT", "v2", one) is not None  # from v1 only
    assert r.main(["runs/main", "build", "x"], r.Bucket("b", client=FakeGcs()), appends) == 0  # a run's first version, through the API


def test_check_says_a_rebuild_is_due_unless_the_current_version_has_this_image_s_fingerprint(r):
    from er.config import load_pipeline
    from er.settings import load_settings
    from er.steps.write import run_config
    s = load_settings()
    p = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    store = r.Files(r.MOUNT)
    due = lambda: r.main(["runs/main", "check"], store) == 0 and json.loads(store.read("runs/main/CHECK.json")[0])["rebuild_due"]
    assert due()  # no run yet
    (r.MOUNT / "runs/main/v/1/state").mkdir(parents=True)
    (r.MOUNT / "runs/main/v/1/state/config.txt").write_text(run_config(p, s), encoding="utf-8")
    store.put("runs/main/CURRENT", "1", None)
    assert not due()
    (r.MOUNT / "runs/main/v/1/state/config.txt").write_text("another pipeline", encoding="utf-8")
    assert due()


def test_the_runner_builds_updates_and_looks_up_a_run_with_python_m_er(r, population):
    s, p, g = population
    uid = s.data.unique_id
    (r.MOUNT / "in").mkdir(parents=True)
    new = g.df[uid].isin(g.df[uid].sample(40, random_state=0))
    g.df[~new].to_parquet(r.MOUNT / "in/records.parquet", index=False)
    g.df[new].to_parquet(r.MOUNT / "in/batch.parquet", index=False)
    store = r.Files(r.MOUNT)
    assert r.main(["runs/main", "build", str(r.MOUNT / "in/records.parquet"), "--overwrite"], store) == 0
    assert r.main(["runs/main", "update", str(r.MOUNT / "in/batch.parquet")], store) == 0
    version = r.MOUNT / "runs/main/v" / store.read("runs/main/CURRENT")[0]
    assert len(pd.read_parquet(version / "gold.parquet")) == len(g.df) and (version / "index").is_dir()  # the batch in, the index kept current
    assert r.main(["runs/main", "lookup", "--record", str(g.df[uid].iloc[0])], store) == 0
