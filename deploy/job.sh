#!/bin/sh
# A job's run: the workspace copied from the bucket (mounted at /gcs) onto the job's own disk, nayose run on it with
# the words given, and copied back when the command changes it. A workspace takes its lock on a disk, never on
# object storage, so a job works on a copy; one job at a time writes a workspace (each job's parallelism is 1).
#   job.sh WORKSPACE WORD...      WORKSPACE: its path in the bucket (runs/main); WORD...: a nayose command and its words
set -eu
ws="/gcs/$1"
shift
mkdir -p "$ws" /tmp/run
cp -Rp "$ws/." /tmp/run/  # -p: the files' times kept, which the index's stamp reads
nayose "$@" --workspace /tmp/run --format json
case "$1" in
  resolve|add|apply|build) cp -Rp /tmp/run/. "$ws/" ;;  # the commands that change the workspace
esac
