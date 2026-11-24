#!/bin/sh
# Every job of deploy/jobs/ deployed to one project, on one image (by digest), named as deploy/terraform makes them:
# the bucket PROJECT-nayose-runs, the jobs' account nayose-runtime@PROJECT, the secret nayose-settings.
#   deploy.sh PROJECT REGION IMAGE@sha256:…
set -eu
project=$1 region=$2 image=$3
case "$image" in *@sha256:*) ;; *) echo "deploy.sh: give the image by digest (…@sha256:…), not a tag: $image" >&2; exit 2 ;; esac
export IMAGE="$image" BUCKET="$project-nayose-runs" SERVICE_ACCOUNT="nayose-runtime@$project.iam.gserviceaccount.com" SETTINGS_SECRET="nayose-settings"
filled=$(mktemp)
trap 'rm -f "$filled"' EXIT
for job in "$(dirname "$0")"/jobs/*.yaml; do
  # shellcheck disable=SC2016  # the names envsubst fills, not their values
  envsubst '$IMAGE $SERVICE_ACCOUNT $BUCKET $SETTINGS_SECRET' < "$job" > "$filled"
  gcloud run jobs replace "$filled" --project="$project" --region="$region" --quiet
done
