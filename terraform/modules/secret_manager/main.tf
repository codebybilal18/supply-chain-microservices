# =============================================================================
# Secret Manager Module — stores all sensitive configuration
# =============================================================================

variable "project_id" { type = string }
variable "region"     { type = string }

# ── Root DB password (used during Cloud SQL provisioning) ────────────────────
resource "random_password" "db_root" {
  length  = 32
  special = false
}

resource "google_secret_manager_secret" "db_root_password" {
  secret_id = "scf-db-root-password"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_root_password" {
  secret      = google_secret_manager_secret.db_root_password.id
  secret_data = random_password.db_root.result
}

# ── Per-service DB credentials (DSN strings) ─────────────────────────────────
# NOTE: these are placeholders; the actual passwords come from cloud_sql module
# outputs and must be injected via a separate terraform apply step or
# a data source after cloud_sql is provisioned.

resource "google_secret_manager_secret" "inventory_db" {
  secret_id = "scf-inventory-db-dsn"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "order_db" {
  secret_id = "scf-order-db-dsn"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "fulfillment_db" {
  secret_id = "scf-fulfillment-db-dsn"
  project   = var.project_id

  replication {
    auto {}
  }
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "db_root_password" {
  value     = random_password.db_root.result
  sensitive = true
}

output "inventory_db_secret_id" {
  value = google_secret_manager_secret.inventory_db.id
}

output "order_db_secret_id" {
  value = google_secret_manager_secret.order_db.id
}

output "fulfillment_db_secret_id" {
  value = google_secret_manager_secret.fulfillment_db.id
}
