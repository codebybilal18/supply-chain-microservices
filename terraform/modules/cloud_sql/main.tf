# =============================================================================
# Cloud SQL Module — MySQL 8.0 (private IP, per-service databases & users)
# =============================================================================

variable "project_id"         { type = string }
variable "region"             { type = string }
variable "suffix"             { type = string }
variable "network_id"         { type = string }
variable "private_ip_address" { type = string }
variable "db_root_password" {
  type      = string
  sensitive = true
}

# ── Instance ──────────────────────────────────────────────────────────────────
resource "google_sql_database_instance" "main" {
  name             = "scf-mysql-${var.suffix}"
  database_version = "MYSQL_8_0"
  region           = var.region
  project          = var.project_id

  deletion_protection = false  # set to true in production

  settings {
    tier              = "db-n1-standard-2"
    availability_type = "REGIONAL"   # HA with failover replica
    disk_size         = 20           # GB — auto-increase enabled
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled                                  = false  # private IP only
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled                        = true
      binary_log_enabled             = true  # required for PITR
      start_time                     = "02:00"
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    maintenance_window {
      day          = 7   # Sunday
      hour         = 3
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = false
    }

    database_flags {
      name  = "slow_query_log"
      value = "on"
    }
    database_flags {
      name  = "long_query_time"
      value = "2"
    }
    database_flags {
      name  = "general_log"
      value = "off"
    }
  }
}

# ── Databases ─────────────────────────────────────────────────────────────────
resource "google_sql_database" "inventory" {
  name      = "inventory_db"
  instance  = google_sql_database_instance.main.name
  charset   = "utf8mb4"
  collation = "utf8mb4_unicode_ci"
  project   = var.project_id
}

resource "google_sql_database" "order" {
  name      = "order_db"
  instance  = google_sql_database_instance.main.name
  charset   = "utf8mb4"
  collation = "utf8mb4_unicode_ci"
  project   = var.project_id
}

resource "google_sql_database" "fulfillment" {
  name      = "fulfillment_db"
  instance  = google_sql_database_instance.main.name
  charset   = "utf8mb4"
  collation = "utf8mb4_unicode_ci"
  project   = var.project_id
}

# ── Per-service users (least privilege) ───────────────────────────────────────
resource "random_password" "inventory_db" {
  length  = 24
  special = false
}

resource "random_password" "order_db" {
  length  = 24
  special = false
}

resource "random_password" "fulfillment_db" {
  length  = 24
  special = false
}

resource "google_sql_user" "inventory" {
  name     = "inventory_user"
  instance = google_sql_database_instance.main.name
  password = random_password.inventory_db.result
  project  = var.project_id
}

resource "google_sql_user" "order" {
  name     = "order_user"
  instance = google_sql_database_instance.main.name
  password = random_password.order_db.result
  project  = var.project_id
}

resource "google_sql_user" "fulfillment" {
  name     = "fulfillment_user"
  instance = google_sql_database_instance.main.name
  password = random_password.fulfillment_db.result
  project  = var.project_id
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "connection_name"          { value = google_sql_database_instance.main.connection_name }
output "private_ip"               { value = google_sql_database_instance.main.private_ip_address }
output "inventory_db_password" {
  value     = random_password.inventory_db.result
  sensitive = true
}

output "order_db_password" {
  value     = random_password.order_db.result
  sensitive = true
}

output "fulfillment_db_password" {
  value     = random_password.fulfillment_db.result
  sensitive = true
}
