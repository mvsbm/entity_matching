# Operations: nayose on Google Cloud

For the DevOps team and the people who run the jobs. The code is in `deploy/`. This page covers what people do: once per environment, on every release, for each job, and when something goes wrong.

## What runs where

| Part | What it does | Defined in |
|---|---|---|
| GitHub Actions | gates every pull request: the lint, the tests, the Terraform formatted and valid | `.github/workflows/` |
| Jenkins | ships what main holds: staging, a person's approval, then prod; runs one job in prod when asked | `deploy/Jenkinsfile` |
| dataset `nayose` | the run: its tables, the functions, one procedure per job, the name model | `deploy/terraform/main.tf`; its contents by `deploy/deploy.py` |
| dataset `nayose_ci` (staging only) | the sandbox for the BigQuery parity check; its tables expire after a day | `deploy/terraform/main.tf` |
| bucket `PROJECT-nayose-runs` | the jobs' input files, in `in/`; a deleted object can be brought back for a week | `deploy/terraform/main.tf` |
| secret `nayose-mapping` | prod's `mapping.sql`, which the prod deploy builds the procedures with | `deploy/terraform/main.tf`; the value is the DevOps team's |
| service accounts | `nayose-deployer` makes the dataset's functions and procedures; `nayose-runtime` loads inputs and calls the procedures | `deploy/terraform/iam.tf` |
| Workload Identity Federation | exchanges Jenkins' OIDC token for either account, so no key is needed (optional) | `deploy/terraform/iam.tf` |
| budget | the month's spending, with alerts at 50%, 90% and 100% (optional) | `deploy/terraform/main.tf` |

Staging and prod are each a project of their own, made by the same Terraform with their own variables. A run on BigQuery is its dataset's tables. The bucket holds only inputs.

## Setting up an environment

Once per project, staging first.

1. **Terraform** (`deploy/terraform/`: Terraform 1.6 or later; the google provider 6.x, at `.terraform.lock.hcl`'s hashes). Copy `staging.tfvars.example` or `prod.tfvars.example` to `ENV.tfvars` and fill it in. Then run:
   ```
   terraform init -backend-config="bucket=STATE_BUCKET" -backend-config="prefix=nayose/ENV"
   terraform apply -var-file=ENV.tfvars
   ```
   The state lives in a bucket of the team's, never in the repository. The apply also turns on the APIs the jobs use (`main.tf` `services`).

   | Variable | Sets | Default |
   |---|---|---|
   | `project` | the environment's project | required |
   | `environment` | `staging` or `prod`. Staging also gets `nayose_ci`, and its runtime account may write the bucket (for the smoke test's file) | required |
   | `region`, `bigquery_location` | where the bucket and the datasets are | `asia-northeast1` |
   | `jenkins_oidc_issuer`, `jenkins_oidc_subject` | Jenkins' OIDC issuer, and the token subject of its job; empty means keys instead | empty |
   | `alert_emails` | who the budget emails | none |
   | `billing_account`, `monthly_budget`, `budget_currency` | the budget; with no billing account there is none | empty, 0, `JPY` |

   Outputs: `bucket`, `runtime_service_account`, `deployer_service_account`, `mapping_secret`, `workload_identity_provider`.
2. **The column mapping, in prod:** `gcloud secrets versions add nayose-mapping --project=PROD_PROJECT --data-file=mapping.sql`. The file is the deployment's mapping, in `nayose/mapping.sql`'s form ([data](data.md#the-mapping-columns-to-fields)). It holds column names, never a record. Staging deploys the repository's `nayose/mapping.sql` instead, because the smoke test's generated file needs it; staging's secret stays empty.
3. **Credentials:** four Jenkins file credentials, one per account and project: `nayose-staging-deployer`, `nayose-staging-runtime`, `nayose-prod-deployer`, `nayose-prod-runtime`.
   - **Best:** a Workload Identity Federation configuration, where Jenkins issues OIDC tokens (its OpenID Connect Provider plugin): `gcloud iam workload-identity-pools create-cred-config WORKLOAD_IDENTITY_PROVIDER --service-account=ACCOUNT_EMAIL --credential-source-file=TOKEN_FILE --output-file=FILE`. No key exists to leak.
   - **Otherwise:** a key of the account, rotated at least every 90 days.
4. **The Jenkins job:** a multibranch pipeline on the repository, with script path `deploy/Jenkinsfile`.
   - **Environment:** `STAGING_PROJECT`, `PROD_PROJECT`, and `APPROVERS` (the Jenkins users or group that may promote to prod).
   - **Agents need:** Python 3.12 or later with `venv`, and the gcloud CLI. The BigQuery client comes from pip (`deploy/requirements.txt`).
   - **Plugins:** Pipeline and Credentials Binding.

## A release

Every push to main goes through these stages (`deploy/Jenkinsfile`, one build at a time):

| Stage | What happens | Runs as |
|---|---|---|
| Checks | every push, on any branch: `ruff check` and the tests, except the slow ones | — |
| Staging | `deploy/deploy.py STAGING_PROJECT.nayose`: the functions, the procedures and the name model. Then the smoke test (`deploy/smoke.py`): a generated file of 2,000 entities is copied to `in/smoke.parquet`, built by BigQuery there and by DuckDB on the agent, and the two runs' scored pairs and entities are compared row for row, with an edit distance on kanji (BigQuery's own counts characters, as the twin does) | deployer, then runtime |
| Approve | someone in `APPROVERS` promotes the commit; this waits up to 7 days | — |
| Prod | the same commit made in prod's `nayose`, with the secret's mapping | deployer |

Every deploy statement is `CREATE OR REPLACE`, so deploying again gives the same result, and rolling back means replaying an earlier commit. A deploy leaves the run's tables alone: a change to the method reaches them only through a build. Nobody changes the datasets, the bucket or the accounts by hand: a change is a pull request, applied by Jenkins or Terraform.

## Running a job in prod

Start the Jenkins job on main with `JOB` and `ARGS` (space-separated). Only the Run stage runs, as `nayose-runtime` (`deploy/run.py`):

| JOB | ARGS | What it does |
|---|---|---|
| `build` | `gs://PROJECT-nayose-runs/in/…parquet` … | makes the run again from these records; people's decisions stay |
| `update` | the batch's `gs://` files | adds a batch to the run |
| `decide` | a filled-in match table's `gs://` files | stores people's decisions and makes the entities again |
| `match` | a threshold, in points (`8`) | writes the table `nayose.matched`: the pairs at that threshold or more |
| `undo` | none | undoes a job whose process died: every table as that job found it |

build and update print `report.txt`, which Jenkins archives. It holds no record's value, so it can be shared. On BigQuery it has no COLUMNS NOT MAPPED section, and STEPS has one line, for the whole job. A refusal, such as a decisions file with a bad row, fails the build with BigQuery's error, which says what to fix. People put the input files in `in/`; the runtime account only reads them.

**All or nothing.** A job first makes the table `job_running` (the job, its start, the dataset's tables) and clones each table as `before__<table>`. A clone bills no bytes, and it shares the table's storage until either changes. A job that fails is undone: each table is made again from its clone, and a table the job made is dropped. Then the clones go. A job that finds `job_running` exits 75: another job is running, or one's process died. For the latter, run `undo`. BigQuery carries on a procedure its caller left, so `undo` exits 75 while a query of that job's session still runs (it reads its own jobs: the custom role `nayoseRuntimeJobs`, `bigquery.jobs.list`), and undoes it once none does; an undo stopped partway can run again. `name_weights` is the deploy's, so no undo brings an older one back. The run's views (`compared`, `u_records`) aren't tables: a first build that fails leaves them, and the next build makes them again. A procedure called other than through `deploy/run.py` is neither marked nor undone.

## Running locally

```
python -m nayose build records.parquet --out runs/main         a run's first batch
python -m nayose update batch.parquet --out runs/main          a batch added
python -m nayose match --out runs/main --threshold 8           matched/points-8.parquet
python -m nayose decide decided.parquet --out runs/main        people's decisions applied
python -m nayose lookup --out runs/main --record 1234          or COLUMN=VALUE …, or --file FILE
```

- **A run is a folder:** `run.duckdb` (its tables), `report.txt` and `matched/`.
- **One writer at a time:** build, update and decide take the folder's lock (`.lock`). The system frees the lock when the process ends, even if it dies, so none is ever left behind. A writer works on `run.duckdb.new` and puts it in place whole when done, so a job that fails or is killed leaves `run.duckdb` as it was; the next writer removes a leftover `run.duckdb.new`. match and lookup each read a copy of their own and never wait. Every job needs free disk for one more copy of `run.duckdb`.
- **What a job prints:** one JSON object on stdout, and each stage's seconds as a JSON line on stderr.

| Exit | Means | Then |
|---|---|---|
| 0 | done, including an update with nothing new (`added: 0`) | |
| 2 | a mistake people fix: the JSON's `error` says what is wrong, and `fix` how to fix it | fix it and run again |
| 75 | another job is writing the run | try again later |
| 1 | a bug: a traceback on stderr; the run is as it was | report it |

- **Limits:** `--compute` gives build and update DuckDB's settings, such as `memory_limit=8GB threads=4 temp_directory=/big/disk`. Past `memory_limit`, DuckDB spills to `temp_directory`.
- **Building again:** `python -m nayose build FILES --out runs/main --overwrite` replaces the run and keeps people's decisions. The old run stays until the new one is complete. Build again after any change to `nayose/sql/`, `config.toml` or `mapping.sql`. report.txt's second line names the method the run was made by (`method <fingerprint>`). An update by a different method, values or mapping is refused (exit 2; on BigQuery, the procedure's error).
- **Backup and restore:** copy `run.duckdb` at any time, since writers never change it in place. To restore, copy it back while no job is writing.
- **Another config or mapping:** set `NAYOSE_CONFIG` or `NAYOSE_MAPPING` to its path.

## What isn't there yet

- **Lookups on BigQuery.** There is no lookup procedure, so lookups run only locally. A lookup is an update of one record that is then rolled back, and BigQuery takes no DDL in a transaction.
- **Nothing has run on BigQuery yet.** `tests/test_deploy.py` checks the deploy and the jobs against a client that records what it is sent. The parity check (the tests' population built in `nayose_ci` and held to the same digests as DuckDB) waits for the sandbox. Confirm these on the first staging deploy: the Python functions (`python-3.11`) can be made in the dataset's location; the OIDC token each WIF configuration reads is on the agent, since the Jenkinsfile binds only the configuration file; the smoke test says `the same`.

## What the DevOps team decides

These are good practice the repository can't set for you:

- **No service account keys:** Workload Identity Federation, and an organisation policy that forbids keys.
- **A VPC Service Controls perimeter** around both projects: Storage, BigQuery and Secret Manager.
- **Customer-managed encryption keys** for the bucket, the datasets and the secret, where policy asks for them.
- **Data Access audit logs** for Storage and BigQuery, and how long logs, time travel and the bucket's soft delete keep things.
- **Who is in `APPROVERS`,** who receives `alert_emails`, and who may write prod's `in/`.
