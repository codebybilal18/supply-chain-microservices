# =============================================================================
# Monitoring Module — GCP Cloud Monitoring alert policies
#
# Provisions:
#   1. HTTP 5xx error rate alert  (Cloud Run request_count, 5xx class > 1%)
#   2. Request latency alert      (p95 > 2000 ms on any Cloud Run service)
#   3. DLQ depth alert            (undelivered messages on DLQ subscriptions)
# =============================================================================

variable "project_id" { type = string }
variable "notification_channels" {
  type        = list(string)
  default     = []
  description = "List of Cloud Monitoring notification channel IDs to alert."
}

# ── 1. HTTP 5xx error rate > 1 % ─────────────────────────────────────────────
resource "google_monitoring_alert_policy" "http_5xx_error_rate" {
  project      = var.project_id
  display_name = "SCF — Cloud Run 5xx Error Rate > 1%"
  combiner     = "OR"

  conditions {
    display_name = "5xx error rate on any Cloud Run service"

    condition_threshold {
      filter = <<-EOT
        resource.type = "cloud_run_revision"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
      EOT

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.labels.service_name"]
      }

      # Trigger when 5xx rate exceeds 1 request/second (sustained for 5 min)
      threshold_value = 1.0
      duration        = "300s"
      comparison      = "COMPARISON_GT"
    }
  }

  notification_channels = var.notification_channels
  severity              = "ERROR"

  alert_strategy {
    auto_close = "1800s"  # Auto-close after 30 min of no data
  }
}

# ── 2. Request latency p95 > 2000 ms ─────────────────────────────────────────
resource "google_monitoring_alert_policy" "high_latency" {
  project      = var.project_id
  display_name = "SCF — Cloud Run p95 Latency > 2000 ms"
  combiner     = "OR"

  conditions {
    display_name = "p95 request latency > 2s on any Cloud Run service"

    condition_threshold {
      filter = <<-EOT
        resource.type = "cloud_run_revision"
        AND metric.type = "run.googleapis.com/request_latencies"
      EOT

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.labels.service_name"]
      }

      threshold_value = 2000.0  # milliseconds
      duration        = "300s"
      comparison      = "COMPARISON_GT"
    }
  }

  notification_channels = var.notification_channels
  severity              = "WARNING"

  alert_strategy {
    auto_close = "1800s"
  }
}

# ── 3. DLQ depth > 0 ─────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "dlq_messages" {
  project      = var.project_id
  display_name = "SCF — Dead-Letter Queue has undelivered messages"
  combiner     = "OR"

  conditions {
    display_name = "Undelivered messages on any DLQ subscription"

    condition_threshold {
      filter = <<-EOT
        resource.type = "pubsub_subscription"
        AND metric.type = "pubsub.googleapis.com/subscription/num_undelivered_messages"
        AND resource.labels.subscription_id =~ ".*-dlq-sub$"
      EOT

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.labels.subscription_id"]
      }

      threshold_value = 0.0
      duration        = "60s"
      comparison      = "COMPARISON_GT"
    }
  }

  notification_channels = var.notification_channels
  severity              = "CRITICAL"

  alert_strategy {
    auto_close = "3600s"
  }
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "alert_policy_ids" {
  description = "IDs of all created alert policies."
  value = {
    http_5xx_error_rate = google_monitoring_alert_policy.http_5xx_error_rate.id
    high_latency        = google_monitoring_alert_policy.high_latency.id
    dlq_messages        = google_monitoring_alert_policy.dlq_messages.id
  }
}
