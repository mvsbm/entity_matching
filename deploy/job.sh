#!/bin/sh
# A job's run: the run's folder copied from the bucket (mounted at /gcs) onto the job's own disk, python -m er run on
# it with the words given, and copied back when the job changes it. A run takes its lock on a disk, never on object
# storage, so a job works on a copy; one job at a time writes a run (each job's parallelism is 1).
#   job.sh RUN JOB WORD...      RUN: its path in the bucket (runs/main); JOB WORD...: python -m er's job and its words
set -eu
ws="/gcs/$1"
shift
mkdir -p "$ws" /tmp/run
cp -Rp "$ws/." /tmp/run/  # -p: the files' times kept, which the index's stamp reads
python -m er "$@" --out /tmp/run
case "$1" in
  build|update|decide|match) cp -Rp /tmp/run/. "$ws/" ;;  # the jobs that write into the run
esac
