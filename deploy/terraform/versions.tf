# One environment of nayose (staging or prod) in its own Google Cloud project: what docs/operations.md sets up once,
# and what deploy/deploy.sh then deploys the jobs into. Applied by the DevOps team, once per project:
#   terraform init -backend-config="bucket=STATE_BUCKET" -backend-config="prefix=nayose/ENVIRONMENT"
#   terraform apply -var-file=ENVIRONMENT.tfvars
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  backend "gcs" {} # the state, in a bucket of the DevOps team's, given at init
}

provider "google" {
  project = var.project
  region  = var.region
  default_labels = {
    app         = "nayose"
    environment = var.environment
  }
}
