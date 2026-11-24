# The image every Cloud Run job runs: the er package with its run-time dependencies (deploy/requirements.txt, pip only),
# the method (config/), and deploy/runner.py, which runs python -m er on a copy of a run in the bucket mounted at /gcs.
#   docker build -f deploy/Dockerfile -t nayose .
#   docker run --rm -v "$PWD/bucket:/gcs" nayose runs/main build /gcs/in/records.parquet --overwrite   # no BUCKET: one machine
# the base by digest: the same on every build (.github/dependabot.yml proposes the next)
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY deploy/requirements.lock deploy/requirements.lock
RUN pip install --require-hashes --no-deps -r deploy/requirements.lock  # each file checked against its hash
COPY pyproject.toml README.md ./
COPY er er
COPY config config
COPY deploy/runner.py deploy/runner.py
RUN pip install --no-deps -e . && useradd --create-home --uid 10001 nayose  # editable: er finds config/ beside it (settings.project_root)
USER nayose
ENTRYPOINT ["python", "/app/deploy/runner.py"]
