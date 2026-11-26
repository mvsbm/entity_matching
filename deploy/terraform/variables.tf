variable "project" {
  description = "The environment's project ID."
  type        = string
}

variable "environment" {
  description = "staging or prod: staging holds the CI sandbox dataset, and its runtime account writes the bucket (the smoke test's file)."
  type        = string
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment is staging or prod."
  }
}

variable "region" {
  description = "Where the bucket is."
  type        = string
  default     = "asia-northeast1"
}

variable "dataset" {
  description = "The run's dataset: its tables, functions and procedures (deploy/deploy.py PROJECT.DATASET). Staging's CI sandbox is DATASET_ci. The same in staging and prod, as Jenkins' NAYOSE_DATASET names both."
  type        = string
  default     = "nayose"
}

variable "bucket" {
  description = "The bucket of the jobs' input files; empty: PROJECT-nayose-runs."
  type        = string
  default     = ""
}

variable "bigquery_location" {
  description = "Where the datasets are."
  type        = string
  default     = "asia-northeast1"
}

variable "jenkins_oidc_issuer" {
  description = "Jenkins' OIDC issuer URL, for Workload Identity Federation (no key to keep); empty: the deployer uses a service account key."
  type        = string
  default     = ""
}

variable "jenkins_oidc_subject" {
  description = "With jenkins_oidc_issuer: the token subject (sub) of the Jenkins job that may act as the deployer and the runtime account."
  type        = string
  default     = ""
}

variable "alert_emails" {
  description = "Who is told when the month's spending passes a budget threshold."
  type        = list(string)
  default     = []
}

variable "billing_account" {
  description = "The billing account, for a budget alert; empty: no budget."
  type        = string
  default     = ""
}

variable "monthly_budget" {
  description = "With billing_account: the month's budget, in budget_currency; told at 50%, 90% and 100%."
  type        = number
  default     = 0
}

variable "budget_currency" {
  description = "The billing account's currency."
  type        = string
  default     = "JPY"
}
