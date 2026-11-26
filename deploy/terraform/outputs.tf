# What Jenkins and the runbook need (docs/operations.md)
output "bucket" {
  value = google_storage_bucket.runs.name
}

output "dataset" {
  value = google_bigquery_dataset.runs.dataset_id
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "deployer_service_account" {
  value = google_service_account.deployer.email
}

output "mapping_secret" {
  value = google_secret_manager_secret.mapping.secret_id
}

output "workload_identity_provider" {
  description = "For the deployer's credential configuration (gcloud iam workload-identity-pools create-cred-config)."
  value       = var.jenkins_oidc_issuer == "" ? null : google_iam_workload_identity_pool_provider.jenkins[0].name
}
