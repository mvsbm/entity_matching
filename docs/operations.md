# Operations: nayose on Google Cloud

For the team that sets up and runs the jobs. Everything that is code is in the repository (`deploy/`). This page is
what people do: once per environment, on every release, and when something goes wrong.

## What runs where

| Part | What it does | Where it is defined |
|---|---|---|
| GitHub Actions | gates every pull request: the lint and the tests; the image built and run; the Terraform valid | `.github/workflows/` |
| Jenkins | ships what main holds, the same image from staging to prod | `deploy/Jenkinsfile` |
| Artifact Registry `nayose` (prod) | one image per commit, deployed by digest | `deploy/Dockerfile`, `deploy/terraform/` |
| Cloud Run jobs `nayose-*` | build, update, decide, match, lookup, check | `deploy/jobs/`, `deploy/runner.py` |
| bucket `PROJECT-nayose-runs` | the jobs' inputs and the runs | `deploy/terraform/main.tf` |
| secret `nayose-settings` | the column mapping the jobs read | `deploy/terraform/main.tf` (the value: people) |
| datasets `nayose`, `nayose_ci` (staging) | the run's tables, once its state moves to BigQuery (`docs/roadmap.md`); the parity check's sandbox | `deploy/terraform/main.tf` |
| service accounts | `nayose-runtime` (the jobs), `nayose-deployer` (Jenkins), `nayose-scheduler` | `deploy/terraform/iam.tf` |
| Cloud Scheduler, Monitoring, a budget | nayose-update nightly (optional); an alert on a failed job; spending | `deploy/terraform/main.tf` |

Staging and prod are each a project of their own, made by the same Terraform with their own variables.

## The bucket

```
in/records.parquet        the records a full run reads (nayose-build)
in/batch.parquet          a batch to add (nayose-update)
in/decisions.parquet      a match table filled in, or any file of the two IDs and a decision (nayose-decide)
runs/main/CURRENT         the version every job reads
runs/main/v/<version>/    a whole run: gold.parquet, scored/, state/, index/, decisions/, matched/, report.txt, steps.json
runs/main/LOCK            there while a job writes the run
runs/main/CHECK.json      nayose-check's answer: rebuild_due
```

- **One writer at a time.** A job that writes the run (build, update, decide, match) holds `LOCK`. A second one waits up to an hour, then exits 75; a lookup reads meanwhile.
- **All or nothing.** The writing job works on a copy of the current version and writes its result as a new version. Only then does it move `CURRENT`. A job that fails, or is stopped, leaves the run as it was.
- **Three versions kept.** The newest three versions stay, and older ones are deleted. The bucket keeps a deleted object for a week (soft delete).
- **Where people find their files.** A match run's table is in the new version's `matched/` (`points-8.parquet` for threshold 8), with both records' compared fields side by side for people to decide on. The run's page is `report.txt`, which holds no record's value.

## Setting up an environment

Once per project, staging first.

1. **Terraform** (`deploy/terraform/`, Terraform 1.6 or later):
   - Copy `staging.tfvars.example` or `prod.tfvars.example` to `ENV.tfvars` and fill it in. Leave `create_registry` true in prod only, and put staging's job account in prod's `registry_readers`.
   - Then run:
     ```
     terraform init -backend-config="bucket=STATE_BUCKET" -backend-config="prefix=nayose/ENV"
     terraform apply -var-file=ENV.tfvars
     ```
   - The state lives in a bucket of yours, never in the repository. The outputs are what the steps below need.
2. **The column mapping:** `gcloud secrets versions add nayose-settings --data-file=FILE`. The file is a whole settings file in `config/settings.toml`'s form.
   - **Staging:** `config/settings.toml` itself, because the smoke test compares staging's run with one built from the repository.
   - **Prod:** the mapping of the real file's columns. It holds column names, never a record.
3. **Jenkins' identity in each project** (the deployer account):
   - **Best:** Workload Identity Federation. Set `jenkins_oidc_issuer` and `jenkins_oidc_subject` for Jenkins' OIDC tokens (its OpenID Connect Provider plugin), then make a credential configuration with `gcloud iam workload-identity-pools create-cred-config` (output `workload_identity_provider`). No key exists to leak.
   - **Otherwise:** a key of `nayose-deployer`, rotated at least every 90 days.
   - Either way, the file is a Jenkins file credential:
     - `nayose-staging`: staging's deployer;
     - `nayose-prod`: prod's deployer;
     - `nayose-registry`: prod's deployer again, which pushes the image.
4. **The Jenkins job:**
   - **The job itself:** a multibranch pipeline on the repository, with script path `deploy/Jenkinsfile`.
   - **Its environment:**
     - `STAGING_PROJECT` and `PROD_PROJECT`;
     - `REGION`;
     - `REGISTRY` (the output `registry`);
     - `APPROVERS`: the Jenkins group that may promote to prod and start a full run.
   - **Agents need:** Docker (building for linux/amd64), the gcloud CLI, Python 3.12, and `envsubst` (gettext).
   - **Plugins:** Pipeline and Credentials Binding.
5. **The first release:**
   - Put the records in prod's `in/records.parquet`, then push to main or replay the main branch.
   - Staging deploys and passes its smoke test. Someone in `APPROVERS` promotes the commit.
   - `nayose-check` in prod says a full run is due, because there is no run yet. Starting it runs `nayose-build`.
   - **Confirm on this first deploy** (it can't be checked without Google Cloud):
     - the jobs can write the bucket's mount (`mountOptions`: `uid=10001`, `implicit-dirs`);
     - the secret is read at `/secrets/settings/settings.toml`;
     - the region gives the jobs their memory (32 GiB for build).

## A release

Every merge to main goes through the same stages (`deploy/Jenkinsfile`):

| Stage | What happens | Who |
|---|---|---|
| Checks | the lint and the fast tests, on every push | Jenkins |
| Image | one image built for the commit, pushed once; every later stage deploys it by digest | Jenkins |
| Staging | the jobs deployed to staging (`deploy/deploy.sh`), then the smoke test: a generated file built by Cloud Run and on the agent, the two runs' files compared (`deploy/smoke.sh`, `deploy/digest.py`) | Jenkins |
| Approve | promote the commit, or not | someone in `APPROVERS` |
| Prod | the same digest deployed to prod, then `nayose-check` | Jenkins |
| Rebuild | only when `CHECK.json` says `rebuild_due`: increments, match runs and lookups refuse until `nayose-build` runs, so it asks to start it | someone in `APPROVERS` |

Nobody changes Cloud Run, the bucket's layout or BigQuery by hand: a change is a pull request, applied by Jenkins or Terraform.

## Running a job

In Jenkins, set `RUN` (the job) and `ARGS` (its words, comma-separated); nothing else is built or deployed. Or with gcloud, as `nayose-deployer`:

```
gcloud run jobs execute nayose-update --region=REGION --wait
gcloud run jobs execute nayose-match  --region=REGION --wait --args="runs/main,match,--threshold,10"
gcloud run jobs execute nayose-lookup --region=REGION --wait --args="runs/main,lookup,--record,12345678"
gcloud run jobs execute nayose-decide --region=REGION --wait
```

| Exit | Means | Then |
|---|---|---|
| 0 | done | |
| 2 | a mistake people fix: the log's ERROR line says what is wrong, and the fix | fix it, run it again |
| 75 | another job held the run for over an hour | run it again later |
| 1 | `CURRENT` moved while the job held the lock: a lock was taken over while its job still ran. The job's version is kept, not published | look at both executions; publish by hand only once it is clear |

Every line a job prints is JSON with a `severity`, so Logging shows errors as errors and the alert policy fires on a failed execution.

## When something goes wrong

- **A job failed.** The alert names it. Its execution's log says why (`severity=ERROR`), and nothing was published. Fix it, then run it again.
- **Roll back the code.** Deploy an earlier image by its digest, `deploy/deploy.sh PROJECT REGION REGISTRY/nayose@sha256:…` (the registry keeps the last 30), or replay the earlier commit in Jenkins.
- **Roll back the data.** With no job running (no `runs/main/LOCK`), point `CURRENT` at an earlier version: `printf %s VERSION | gcloud storage cp - gs://BUCKET/runs/main/CURRENT`. The last three versions are there.
- **A lock left behind.** A job stopped outright leaves `LOCK`, and the next job takes it over after 26 hours. With no execution running, `gcloud storage rm gs://BUCKET/runs/main/LOCK` frees it now.
- **A full run due.** `CHECK.json` says `rebuild_due: true`: the method or the mapping changed what an increment needs. Start `nayose-build`; the release asks to.

## Limits

- **A job copies the run onto its own disk, which Cloud Run keeps in memory.** That is about 1.1 GB per million records, so up to some 20M records in a 32 GiB job. Past that, the run's state moves into BigQuery (`docs/roadmap.md`); that needs the staging sandbox dataset to be built and checked against.
- **A lookup is a job:** seconds to start, then the run copied. A service in front of the index answers in well under a second, once lookups need it.

## What the DevOps team decides

These are good practice the repository can't set for you:

- **No service account keys:** Workload Identity Federation, and an organisation policy that forbids keys.
- **A VPC Service Controls perimeter** around both projects: Storage, BigQuery and Secret Manager.
- **Customer-managed encryption keys** for the bucket, the datasets and the secret, where policy asks for them.
- **Data Access audit logs** for Storage and BigQuery, and how long logs and the bucket's soft delete keep things.
- **Who is in `APPROVERS`,** and who receives `alert_emails`.
- **Dependabot's weekly pull requests** for the base image and the actions, reviewed like any other change.
