"""A Cloud Run job's run (deploy/jobs/*.yaml): python -m er on a copy of a run kept in the bucket, published whole.

    runner.py RUN JOB WORD...   RUN: the run's path in the bucket (runs/main); JOB WORD...: python -m er's words
    runner.py RUN check         whether the run must be built again before an increment: writes RUN/CHECK.json

The bucket keeps each run as versions, RUN/v/<version>/, and RUN/CURRENT names the one jobs read.
- **A job that writes** (build, update, decide, match) holds the run's lock, RUN/LOCK, made only where none is: one
  writer per run, however many executions start. It copies the current version onto its own disk, runs there, writes
  the result as a new version, moves CURRENT to it, and drops all but the newest KEEP versions. A job that fails or
  is cut short publishes nothing, so the run stays as it was.
- **A lookup** reads the current version; it takes no lock and writes nothing.
- **check** compares the fingerprint of this image's code and settings (er.steps.write.run_config) with the current
  version's state/config.txt. It writes rebuild_due to RUN/CHECK.json, which the deploy reads (deploy/Jenkinsfile).

On Cloud Run the bucket is mounted at /gcs (GCS FUSE), which carries the run's files. The lock, CURRENT and CHECK.json
go through the Storage API (BUCKET names the bucket), whose preconditions make a create, and a move of CURRENT, happen
once. Without BUCKET (Docker on one machine, the tests) they are files under the mount.

Exit codes: python -m er's; 75 when another job holds the lock past LOCK_WAIT seconds.
shortcut: the run is copied onto the job's disk, which Cloud Run keeps in its memory: about 1.1 GB a million records,
so up to some 20M records in a 32 GiB job; past that the run's state moves into BigQuery (docs/roadmap.md).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

MOUNT = Path(os.environ.get("RUNS_MOUNT", "/gcs"))  # where the bucket's files are
WORK = Path(os.environ.get("RUN_WORK", "/tmp/run"))  # the job's own copy of the run
KEEP = 3  # versions kept: the current one and two before it, a data rollback (docs/operations.md)
LOCK_WAIT = float(os.environ.get("LOCK_WAIT", 3600))  # seconds a job waits for another's lock before it exits 75
LEASE = 26 * 3600  # a lock older than this outlived the longest job's timeout (24 h, deploy/jobs/build.yaml): its job is gone
POLL = 30  # seconds between looks at a held lock
WRITES = {"build", "update", "decide", "match"}
ME = os.environ.get("CLOUD_RUN_EXECUTION") or f"local-{os.getpid()}"


def say(severity: str = "INFO", **event: object) -> None:  # a JSON line Cloud Logging reads, severity and all
    print(json.dumps({"severity": severity, "runner": ME, **event}, ensure_ascii=False, default=str), file=sys.stderr, flush=True)


class Files:
    """The bucket's small objects as files under the mount, each version-stamped by its write time: one machine (Docker,
    the tests), where only the lock's holder writes CURRENT."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def read(self, name: str) -> tuple[str, int] | None:  # its text and generation, or None
        p = self.root / name
        try:
            return p.read_text(encoding="utf-8"), p.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def create(self, name: str, text: str) -> int | None:  # made only where none is: its generation, else None
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return p.stat().st_mtime_ns

    def put(self, name: str, text: str, generation: int | None) -> int | None:  # written only if still at `generation` (None: absent)
        now = self.read(name)
        if (now[1] if now else None) != generation:
            return None
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{ME}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
        return p.stat().st_mtime_ns

    def delete(self, name: str, generation: int) -> None:  # gone only if still at `generation`
        if (now := self.read(name)) and now[1] == generation:
            (self.root / name).unlink(missing_ok=True)


class Bucket:
    """The same objects through the Storage API (google-cloud-storage), each write under a precondition on its
    generation: two jobs can't both make the lock, nor both move CURRENT from one version."""

    def __init__(self, name: str, client: object | None = None) -> None:
        if client is None:
            from google.cloud import storage
            client = storage.Client()
        self.bucket = client.bucket(name)

    def read(self, name: str) -> tuple[str, int] | None:
        for _ in range(5):  # a write between reading the generation and the text: read again
            blob = self.bucket.get_blob(name)
            if blob is None:
                return None
            if (text := self._if(lambda: blob.download_as_text(if_generation_match=blob.generation))) is not None:
                return text, blob.generation
        raise RuntimeError(f"gs://{self.bucket.name}/{name} changes faster than it can be read")

    def create(self, name: str, text: str) -> int | None:
        return self.put(name, text, None)

    def put(self, name: str, text: str, generation: int | None) -> int | None:
        blob = self.bucket.blob(name)
        done = self._if(lambda: blob.upload_from_string(text, content_type="application/json", if_generation_match=generation or 0) or True)
        return blob.generation if done else None

    def delete(self, name: str, generation: int) -> None:
        self._if(lambda: self.bucket.blob(name).delete(if_generation_match=generation))  # changed or gone: not ours to delete

    @staticmethod
    def _if(call):  # the call's result, or None when its precondition failed (412) or the object is gone (404)
        try:
            return call()
        except Exception as e:
            if getattr(e, "code", None) in (404, 412):
                return None
            raise


def take(objects: Files | Bucket, name: str) -> int | None:
    """The lock `name` held by this job: its generation; None if another job still holds it after LOCK_WAIT seconds.
    A lock older than LEASE is taken over: its job is gone (Cloud Run ended it at its timeout)."""
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        if (generation := objects.create(name, json.dumps(dict(execution=ME, at=time.time())))) is not None:
            return generation
        if (held := objects.read(name)) is None:  # freed in between: try again
            continue
        who = json.loads(held[0])
        if time.time() - who["at"] > LEASE:
            say("WARNING", event="lock taken over", lock=name, held_by=who["execution"])
            objects.delete(name, held[1])
            continue
        if time.monotonic() >= deadline:
            return None
        say(event="waiting for the lock", lock=name, held_by=who["execution"])
        time.sleep(POLL)


def run_er(words: list[str]) -> int:  # python -m er, its output passed through as it comes
    return subprocess.run([sys.executable, "-m", "er", *words]).returncode


def version() -> str:  # a new version's name: sorts by when it was made
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S.%fZ}-{ME}"


def main(argv: list[str], objects: Files | Bucket | None = None, job=run_er) -> int:
    run, *words = argv
    objects = objects or (Bucket(os.environ["BUCKET"]) if os.environ.get("BUCKET") else Files(MOUNT))
    if words == ["check"]:
        return check(run, objects)
    writes, lock = words[0] in WRITES, None
    if writes and (lock := take(objects, f"{run}/LOCK")) is None:
        say("WARNING", event="another job holds the lock", run=run, waited=LOCK_WAIT)
        return 75
    try:
        current = objects.read(f"{run}/CURRENT")
        was = current[0].strip() if current else None
        shutil.rmtree(WORK, ignore_errors=True)
        if was:
            shutil.copytree(MOUNT / run / "v" / was, WORK, copy_function=shutil.copy2)  # copy2: the files' times, which the index's stamp reads
        else:
            WORK.mkdir(parents=True)
        code = job([*words, "--out", str(WORK)])
        if code or not writes:
            return code
        new = version()
        shutil.copytree(WORK, MOUNT / run / "v" / new, copy_function=shutil.copy2)
        if objects.put(f"{run}/CURRENT", new, current[1] if current else None) is None:  # moved by a job that took the lock over
            say("ERROR", event="CURRENT moved while this job held the lock: its version is kept, not published", run=run, version=new)
            return 1
        say(event="published", run=run, version=new, previous=was)
        for old in sorted(p.name for p in (MOUNT / run / "v").iterdir())[:-KEEP]:
            shutil.rmtree(MOUNT / run / "v" / old, ignore_errors=True)
        return 0
    finally:
        if lock is not None:
            objects.delete(f"{run}/LOCK", lock)


def check(run: str, objects: Files | Bucket) -> int:
    """RUN/CHECK.json: rebuild_due, when this image's fingerprint (its code's pipeline and the settings mounted) differs
    from the current version's, or there is none; so increments, match runs and lookups would refuse until a full run."""
    from er.config import load_pipeline
    from er.settings import load_settings
    from er.steps.write import run_config
    s = load_settings()
    p = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    current = objects.read(f"{run}/CURRENT")
    stored = MOUNT / run / "v" / current[0].strip() / "state" / "config.txt" if current else None
    due = stored is None or not stored.is_file() or stored.read_text(encoding="utf-8") != run_config(p, s)
    verdict = dict(run=run, version=current[0].strip() if current else None, rebuild_due=due, checked_by=ME)
    was = objects.read(f"{run}/CHECK.json")
    objects.put(f"{run}/CHECK.json", json.dumps(verdict), was[1] if was else None)
    say("WARNING" if due else "INFO", event="check", **verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
