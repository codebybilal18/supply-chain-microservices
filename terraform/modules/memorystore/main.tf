# =============================================================================
# Memorystore Redis Module — single-node, private IP
# =============================================================================

variable "project_id" { type = string }
variable "region"     { type = string }
variable "suffix"     { type = string }
variable "network_id" { type = string }

resource "google_redis_instance" "cache" {
  name               = "scf-redis-${var.suffix}"
  tier               = "STANDARD_HA"    # HA with automatic failover
  memory_size_gb     = 1
  region             = var.region
  project            = var.project_id
  redis_version      = "REDIS_7_0"
  display_name       = "SupplyChainForge Redis Cache"
  authorized_network = var.network_id

  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"

  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 3
        minutes = 0
      }
    }
  }
}

output "redis_host" { value = google_redis_instance.cache.host; sensitive = true }
output "redis_port" { value = google_redis_instance.cache.port }
output "redis_auth_string" { value = google_redis_instance.cache.auth_string; sensitive = true }
