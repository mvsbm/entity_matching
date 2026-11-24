locals {
  # named as deploy/deploy.sh and deploy/Jenkinsfile expect them
  bucket = "${var.project}-nayose-runs"
  services = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudscheduler.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "billingbudgets.googleapis.com",
  ]
}

data "google_project" "this" {}

resource "google_project_service" "on" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# The runs: each a set of versions and the CURRENT that names one (deploy/runner.py); the jobs' inputs in in/.
resource "google_storage_bucket" "runs" {
  name                        = local.bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  soft_delete_policy {
    retention_duration_seconds = 7 * 24 * 3600 # a version deleted by mistake can be brought back for a week
  }
  depends_on = [google_project_service.on]
}

# The column mapping (config/settings.toml's form), which the jobs mount: its value is the DevOps team's to add,
# never Terraform's state's (docs/operations.md).
resource "google_secret_manager_secret" "settings" {
  secret_id = "nayose-settings"
  replication {
    auto {}
  }
  depends_on = [google_project_service.on]
}

# The run's tables once its state moves into BigQuery (docs/roadmap.md), and staging's sandbox for the engine-parity
# check, whose tables expire in a day.
resource "google_bigquery_dataset" "runs" {
  dataset_id = "nayose"
  location   = var.bigquery_location
  depends_on = [google_project_service.on]
}

resource "google_bigquery_dataset" "sandbox" {
  count                       = var.environment == "staging" ? 1 : 0
  dataset_id                  = "nayose_ci"
  location                    = var.bigquery_location
  default_table_expiration_ms = 24 * 3600 * 1000
  depends_on                  = [google_project_service.on]
}

resource "google_artifact_registry_repository" "images" {
  count         = var.create_registry ? 1 : 0
  repository_id = "nayose"
  location      = var.region
  format        = "DOCKER"
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 30 # enough to roll back across weeks of deploys
    }
  }
  cleanup_policies {
    id     = "drop-old"
    action = "DELETE"
    condition {
      older_than = "${90 * 24 * 3600}s"
    }
  }
  depends_on = [google_project_service.on]
}

# nayose-update by itself, when update_schedule is set: the batch that landed in in/batch.parquet added.
resource "google_cloud_scheduler_job" "update" {
  count     = var.update_schedule == "" ? 0 : 1
  name      = "nayose-update"
  schedule  = var.update_schedule
  time_zone = var.time_zone
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project}/locations/${var.region}/jobs/nayose-update:run"
    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  depends_on = [google_project_service.on]
}

# Told: a job's execution that failed, and the month's spending.
resource "google_monitoring_notification_channel" "email" {
  for_each     = toset(var.alert_emails)
  display_name = "nayose: ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
}

resource "google_monitoring_alert_policy" "failed" {
  display_name          = "nayose: a job failed (${var.environment})"
  combiner              = "OR"
  notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
  conditions {
    display_name = "a failed execution"
    condition_threshold {
      filter          = "resource.type = \"cloud_run_job\" AND metric.type = \"run.googleapis.com/job/completed_execution_count\" AND metric.labels.result = \"failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  documentation {
    content = "A nayose job failed: its execution's log says why (severity ERROR). docs/operations.md: what each exit means."
  }
  depends_on = [google_project_service.on]
}

resource "google_billing_budget" "month" {
  count           = var.billing_account == "" ? 0 : 1
  billing_account = var.billing_account
  display_name    = "nayose (${var.environment})"
  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }
  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.monthly_budget)
    }
  }
  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }
  all_updates_rule {
    monitoring_notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
  }
}
