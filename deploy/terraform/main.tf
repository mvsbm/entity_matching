locals {
  # named as deploy/Jenkinsfile expects them
  bucket = var.bucket != "" ? var.bucket : "${var.project}-nayose-runs"
  services = [
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
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

# The jobs' input files, in in/: what deploy/run.py loads into the run's dataset.
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

# The deployment's column mapping (mapping.sql), which the deploy reads: its value is the DevOps team's to add, never
# Terraform's state's (docs/operations.md).
resource "google_secret_manager_secret" "mapping" {
  secret_id = "nayose-mapping"
  replication {
    auto {}
  }
  depends_on = [google_project_service.on]
}

# The run: its tables, functions and procedures (deploy/deploy.py). The run's storage is billed by its compressed bytes (PHYSICAL), as its tables
# compress about 5 times (a BigQuery sandbox's run: 13.0 MB logical, 2.4 MB physical) and a physical byte costs 2
# logical ones. Physical billing also bills time travel, so it keeps 2 days, the least BigQuery keeps: every job
# replaces some of the run's tables (gold, cands, matched). Undo needs none: it clones.
resource "google_bigquery_dataset" "runs" {
  dataset_id            = var.dataset
  location              = var.bigquery_location
  storage_billing_model = "PHYSICAL"
  max_time_travel_hours = 48
  depends_on            = [google_project_service.on]
}

# Told: the month's spending.
resource "google_monitoring_notification_channel" "email" {
  for_each     = toset(var.alert_emails)
  display_name = "nayose: ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
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
