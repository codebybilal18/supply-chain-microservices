# =============================================================================
# IAM Module — service accounts, roles, and bindings
# =============================================================================

variable "project_id" { type = string }
variable "region"     { type = string }

# ── Cloud Run service account ─────────────────────────────────────────────────
resource "google_service_account" "cloud_run" {
  account_id   = "scf-cloud-run-sa"
  display_name = "SupplyChainForge Cloud Run Service Account"
  project      = var.project_id
}

# ── IAM Bindings ──────────────────────────────────────────────────────────────

# Pub/Sub: publish + consume
resource "google_project_iam_member" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_project_iam_member" "pubsub_subscriber" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Secret Manager: read secrets
resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Cloud SQL: connect via Cloud SQL Proxy
resource "google_project_iam_member" "sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Cloud Logging: write structured logs
resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Cloud Monitoring: write metrics
resource "google_project_iam_member" "metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Artifact Registry: pull images
resource "google_project_iam_member" "ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# ── Cloud Build service account bindings ─────────────────────────────────────

data "google_project" "project" {
  project_id = var.project_id
}

locals {
  cloud_build_sa = "${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

resource "google_project_iam_member" "cloud_build_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${local.cloud_build_sa}"
}

resource "google_project_iam_member" "cloud_build_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${local.cloud_build_sa}"
}

resource "google_project_iam_member" "cloud_build_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${local.cloud_build_sa}"
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "cloud_run_sa_email" { value = google_service_account.cloud_run.email }
