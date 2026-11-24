#!/bin/sh
# The deploy's smoke test in one project: a generated file built there by nayose-build (as runs/smoke) and here with
# python -m er, and the two runs' files compared (deploy/digest.py). The same answer means the image, the bucket, the
# secret, the account and the runner all work, and give what the repository gives. The project's nayose-settings
# secret holds config/settings.toml for this, as the staging project's does (docs/operations.md).
#   smoke.sh PROJECT REGION       (run from the repository, with .venv installed from requirements.txt)
set -eu
project=$1 region=$2 bucket="$1-nayose-runs"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
.venv/bin/python scripts/generate.py --entities 2000 --seed 7 --out "$work/gen"
gcloud storage cp "$work/gen/records.parquet" "gs://$bucket/in/smoke.parquet" --project="$project"
gcloud run jobs execute nayose-build --project="$project" --region="$region" --wait --args="runs/smoke,build,/gcs/in/smoke.parquet,--overwrite"
version=$(gcloud storage cat "gs://$bucket/runs/smoke/CURRENT" --project="$project")
mkdir "$work/cloud"
gcloud storage cp --recursive "gs://$bucket/runs/smoke/v/$version/*" "$work/cloud/" --project="$project"
.venv/bin/python -m er build "$work/gen/records.parquet" --out "$work/here" > /dev/null
.venv/bin/python deploy/digest.py "$work/here" "$work/cloud"
