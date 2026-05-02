# =============================================================================
# Cloud Run Module — deploys all 3 microservices
# =============================================================================

variable "project_id"              { type = string }
variable "region"                  { type = string }
variable "image_tag"               { type = string }
variable "registry_url"            { type = string }
variable "vpc_connector_id"        { type = string }
variable "cloud_run_sa_email"      { type = string }
variable "redis_host"              { type = string; sensitive = true }
variable "redis_port"              { type = number }
variable "cloud_sql_connection_name" { type = string }
variable "inventory_db_secret"     { type = string }
variable "order_db_secret"         { type = string }
variable "fulfillment_db_secret"   { type = string }

locals {
  # Common environment variables shared across all services
  common_env = [
    { name = "GCP_PROJECT_ID",      value = var.project_id },
    { name = "REDIS_HOST",          value = var.redis_host },
    { name = "REDIS_PORT",          value = tostring(var.redis_port) },
    { name = "RATE_LIMIT_ENABLED",  value = "true" },
    { name = "RATE_LIMIT_REQUESTS", value = "200" },
    { name = "RATE_LIMIT_WINDOW",   value = "60" },
    { name = "DEBUG",               value = "false" },
  ]
}

# ── Inventory Service ─────────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "inventory" {
  name     = "scf-inventory"
  location = var.region
  project  = var.project_id

  template {
    service_account = var.cloud_run_sa_email

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "ALL_TRAFFIC"
    }

    containers {
      image = "${var.registry_url}/inventory:${var.image_tag}"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      # DB credentials from Secret Manager
      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.inventory_db_secret
            version = "latest"
          }
        }
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      env { name = "DB_HOST";          value = "127.0.0.1" }
      env { name = "DB_USER";          value = "inventory_user" }
      env { name = "DB_NAME";          value = "inventory_db" }
      env { name = "SERVICE_NAME";     value = "inventory-service" }
      env { name = "PUBSUB_TOPIC_INVENTORY_EVENTS";                value = "inventory-events" }
      env { name = "PUBSUB_SUBSCRIPTION_ORDER_CREATED";            value = "inventory-order-created-sub" }
      env { name = "PUBSUB_SUBSCRIPTION_FULFILLMENT_COMPLETED";    value = "inventory-fulfillment-completed-sub" }

      # Cloud SQL Auth Proxy sidecar handles /cloudsql socket
      ports { container_port = 8000 }

      startup_probe {
        http_get { path = "/health" }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get { path = "/health/live" }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    # Cloud SQL Auth Proxy sidecar
    containers {
      image = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.11"
      args  = [
        "--structured-logs",
        "--port=3306",
        "${var.cloud_sql_connection_name}",
      ]
      resources {
        limits = { cpu = "0.5", memory = "128Mi" }
      }
    }
  }
}

# ── Order Service ─────────────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "order" {
  name     = "scf-order"
  location = var.region
  project  = var.project_id

  template {
    service_account = var.cloud_run_sa_email

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "ALL_TRAFFIC"
    }

    containers {
      image = "${var.registry_url}/order:${var.image_tag}"

      resources {
        limits = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.order_db_secret
            version = "latest"
          }
        }
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      env { name = "DB_HOST";                   value = "127.0.0.1" }
      env { name = "DB_USER";                   value = "order_user" }
      env { name = "DB_NAME";                   value = "order_db" }
      env { name = "SERVICE_NAME";              value = "order-service" }
      env { name = "INVENTORY_SERVICE_URL";     value = google_cloud_run_v2_service.inventory.uri }
      env { name = "PUBSUB_TOPIC_ORDER_EVENTS"; value = "order-events" }
      env { name = "PUBSUB_SUBSCRIPTION_FULFILLMENT_ASSIGNED"; value = "order-fulfillment-assigned-sub" }

      ports { container_port = 8000 }

      startup_probe {
        http_get { path = "/health" }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get { path = "/health/live" }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    containers {
      image = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.11"
      args  = ["--structured-logs", "--port=3306", "${var.cloud_sql_connection_name}"]
      resources { limits = { cpu = "0.5", memory = "128Mi" } }
    }
  }

  depends_on = [google_cloud_run_v2_service.inventory]
}

# ── Fulfillment Service ───────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "fulfillment" {
  name     = "scf-fulfillment"
  location = var.region
  project  = var.project_id

  template {
    service_account = var.cloud_run_sa_email

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "ALL_TRAFFIC"
    }

    containers {
      image = "${var.registry_url}/fulfillment:${var.image_tag}"

      resources {
        limits = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.fulfillment_db_secret
            version = "latest"
          }
        }
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      env { name = "DB_HOST";                      value = "127.0.0.1" }
      env { name = "DB_USER";                      value = "fulfillment_user" }
      env { name = "DB_NAME";                      value = "fulfillment_db" }
      env { name = "SERVICE_NAME";                 value = "fulfillment-service" }
      env { name = "ORDER_SERVICE_URL";            value = google_cloud_run_v2_service.order.uri }
      env { name = "PUBSUB_TOPIC_FULFILLMENT_EVENTS"; value = "fulfillment-events" }
      env { name = "PUBSUB_SUBSCRIPTION_ORDER_CREATED"; value = "fulfillment-order-created-sub" }

      ports { container_port = 8002 }

      startup_probe {
        http_get { path = "/health" }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get { path = "/health/live" }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    containers {
      image = "gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.11"
      args  = ["--structured-logs", "--port=3306", "${var.cloud_sql_connection_name}"]
      resources { limits = { cpu = "0.5", memory = "128Mi" } }
    }
  }

  depends_on = [google_cloud_run_v2_service.order]
}

# ── Allow unauthenticated invocations (public APIs) ───────────────────────────
resource "google_cloud_run_v2_service_iam_member" "inventory_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.inventory.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "order_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.order.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "fulfillment_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.fulfillment.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "inventory_url"   { value = google_cloud_run_v2_service.inventory.uri }
output "order_url"       { value = google_cloud_run_v2_service.order.uri }
output "fulfillment_url" { value = google_cloud_run_v2_service.fulfillment.uri }
