# What Jenkins and the runbook need (docs/operations.md)
output "bucket" {
  value = google_storage_bucket.runs.name
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "deployer_service_account" {
  value = google_service_account.deployer.email
}

output "settings_secret" {
  value = google_secret_manager_secret.settings.secret_id
}

output "registry" {
  description = "Jenkins' REGISTRY, where create_registry is true."
  value       = var.create_registry ? "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.images[0].repository_id}" : null
}

output "workload_identity_provider" {
  description = "For the deployer's credential configuration (gcloud iam workload-identity-pools create-cred-config)."
  value       = var.jenkins_oidc_issuer == "" ? null : google_iam_workload_identity_pool_provider.jenkins[0].name
}
