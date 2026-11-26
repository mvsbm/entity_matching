# Who does what, each with the least it needs (both are Jenkins', deploy/Jenkinsfile):
#   nayose-runtime    the jobs (deploy/run.py): reads the bucket's inputs, writes the run's tables, calls its procedures,
#                     reads the column mapping (a lookup's)
#   nayose-deployer   the deploy (deploy/deploy.py): makes the run's functions and procedures, reads the column mapping

resource "google_service_account" "runtime" {
  account_id   = "nayose-runtime"
  display_name = "nayose jobs"
}

resource "google_service_account" "deployer" {
  account_id   = "nayose-deployer"
  display_name = "nayose delivery (Jenkins)"
}

# the jobs
resource "google_storage_bucket_iam_member" "runtime" {
  bucket = google_storage_bucket.runs.name
  role   = var.environment == "staging" ? "roles/storage.objectAdmin" : "roles/storage.objectViewer" # staging's writes the smoke test's file
  member = google_service_account.runtime.member
}


resource "google_bigquery_dataset_iam_member" "runtime" {
  dataset_id = google_bigquery_dataset.runs.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.runtime.member
}

resource "google_project_iam_member" "runtime" {
  for_each = toset(["roles/bigquery.jobUser", "roles/bigquery.readSessionUser"])
  project  = var.project
  role     = each.value
  member   = google_service_account.runtime.member
}

# undo (deploy/run.py) waits while a dead job's procedure still runs: it reads its own jobs (INFORMATION_SCHEMA.JOBS_BY_USER)
resource "google_project_iam_custom_role" "runtime_jobs" {
  project     = var.project
  role_id     = "nayoseRuntimeJobs"
  title       = "nayose jobs: list its own"
  permissions = ["bigquery.jobs.list"]
}

resource "google_project_iam_member" "runtime_jobs" {
  project = var.project
  role    = google_project_iam_custom_role.runtime_jobs.id
  member  = google_service_account.runtime.member
}

# the deploy: the run's functions, procedures and name model, and the column mapping it builds them with
resource "google_bigquery_dataset_iam_member" "deployer" {
  dataset_id = google_bigquery_dataset.runs.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.deployer.member
}

resource "google_project_iam_member" "deployer" {
  project = var.project
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.deployer.member
}

resource "google_secret_manager_secret_iam_member" "deployer" {
  secret_id = google_secret_manager_secret.mapping.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.deployer.member
}

# a lookup maps typed values, and checks the run's method, with prod's column mapping
resource "google_secret_manager_secret_iam_member" "runtime" {
  secret_id = google_secret_manager_secret.mapping.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.runtime.member
}

# Jenkins without a key: its OIDC token, for the one job named, exchanged for either account's (Workload Identity Federation)
resource "google_iam_workload_identity_pool" "jenkins" {
  count                     = var.jenkins_oidc_issuer == "" ? 0 : 1
  workload_identity_pool_id = "jenkins"
  display_name              = "Jenkins"
  depends_on                = [google_project_service.on]
}

resource "google_iam_workload_identity_pool_provider" "jenkins" {
  count                              = var.jenkins_oidc_issuer == "" ? 0 : 1
  workload_identity_pool_id          = google_iam_workload_identity_pool.jenkins[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "jenkins-oidc"
  attribute_mapping                  = { "google.subject" = "assertion.sub" }
  attribute_condition                = "assertion.sub == \"${var.jenkins_oidc_subject}\""
  oidc {
    issuer_uri = var.jenkins_oidc_issuer
  }
}

resource "google_service_account_iam_member" "jenkins" {
  for_each           = var.jenkins_oidc_issuer == "" ? {} : { deployer = google_service_account.deployer.name, runtime = google_service_account.runtime.name }
  service_account_id = each.value
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.jenkins[0].name}/subject/${var.jenkins_oidc_subject}"
}
