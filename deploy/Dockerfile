# The image every Cloud Run job runs: the er package with its run-time dependencies (deploy/requirements.txt, pip only),
# the method (config/), and deploy/job.sh, which runs python -m er on a copy of a run in the bucket mounted at /gcs.
#   docker build -f deploy/Dockerfile -t nayose .
#   docker run --rm -v "$PWD/bucket:/gcs" nayose runs/main build /gcs/in/records.parquet --overwrite
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY deploy/requirements.txt deploy/requirements.txt
RUN pip install -r deploy/requirements.txt
COPY pyproject.toml README.md ./
COPY er er
COPY config config
COPY deploy/job.sh deploy/job.sh
RUN pip install --no-deps -e . && useradd --create-home --uid 10001 nayose  # editable: er finds config/ beside it (settings.project_root)
USER nayose
ENTRYPOINT ["/app/deploy/job.sh"]
