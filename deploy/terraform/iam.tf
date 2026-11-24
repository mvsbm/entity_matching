# Who does what, each with the least it needs:
#   nayose-runtime    the jobs: reads and writes the run's bucket and datasets, reads the column mapping
#   nayose-deployer   Jenkins: deploys the jobs and starts them, as nayose-runtime; pushes the image where the registry is
#   nayose-scheduler  starts nayose-update on its schedule (update_schedule)

resource "google_service_account" "runtime" {
  account_id   = "nayose-runtime"
  display_name = "nayose jobs"
}

resource "google_service_account" "deployer" {
  account_id   = "nayose-deployer"
  display_name = "nayose delivery (Jenkins)"
}

resource "google_service_account" "scheduler" {
  count        = var.update_schedule == "" ? 0 : 1
  account_id   = "nayose-scheduler"
  display_name = "nayose schedule"
}

# the jobs
resource "google_storage_bucket_iam_member" "runtime" {
  bucket = google_storage_bucket.runs.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.runtime.member
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  secret_id = google_secret_manager_secret.settings.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.runtime.member
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

# Jenkins: deploy and start the jobs (as the jobs' account), and read what nayose-check wrote; in staging, also write
# the bucket (the smoke test's file) and the sandbox (the parity check)
resource "google_project_iam_member" "deployer" {
  project = var.project
  role    = "roles/run.developer"
  member  = google_service_account.deployer.member
}

resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deployer.member
}

resource "google_storage_bucket_iam_member" "deployer" {
  bucket = google_storage_bucket.runs.name
  role   = var.environment == "staging" ? "roles/storage.objectAdmin" : "roles/storage.objectViewer"
  member = google_service_account.deployer.member
}

resource "google_bigquery_dataset_iam_member" "deployer_sandbox" {
  count      = var.environment == "staging" ? 1 : 0
  dataset_id = google_bigquery_dataset.sandbox[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.deployer.member
}

resource "google_project_iam_member" "deployer_sandbox_jobs" {
  count   = var.environment == "staging" ? 1 : 0
  project = var.project
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.deployer.member
}

# the registry, where it lives: the deployer pushes, every environment's jobs pull
resource "google_artifact_registry_repository_iam_member" "deployer" {
  count      = var.create_registry ? 1 : 0
  repository = google_artifact_registry_repository.images[0].name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.deployer.member
}

resource "google_artifact_registry_repository_iam_member" "readers" {
  for_each   = var.create_registry ? toset(concat([google_service_account.runtime.email], var.registry_readers)) : toset([])
  repository = google_artifact_registry_repository.images[0].name
  location   = var.region
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value}"
}

# the schedule starts nayose-update, and nothing else runs as it
resource "google_project_iam_member" "scheduler" {
  count   = var.update_schedule == "" ? 0 : 1
  project = var.project
  role    = "roles/run.invoker"
  member  = google_service_account.scheduler[0].member
}

# Jenkins without a key: its OIDC token, for the one job named, exchanged for the deployer's (Workload Identity Federation)
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

resource "google_service_account_iam_member" "jenkins_is_deployer" {
  count              = var.jenkins_oidc_issuer == "" ? 0 : 1
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.jenkins[0].name}/subject/${var.jenkins_oidc_subject}"
}
