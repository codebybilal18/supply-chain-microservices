# =============================================================================
# Pub/Sub Module — topics, DLQ topics, subscriptions
# =============================================================================

variable "project_id" { type = string }

# ── Topics ────────────────────────────────────────────────────────────────────
resource "google_pubsub_topic" "order_events" {
  name    = "order-events"
  project = var.project_id
  message_retention_duration = "604800s"  # 7 days
}

resource "google_pubsub_topic" "inventory_events" {
  name    = "inventory-events"
  project = var.project_id
  message_retention_duration = "604800s"
}

resource "google_pubsub_topic" "fulfillment_events" {
  name    = "fulfillment-events"
  project = var.project_id
  message_retention_duration = "604800s"
}

# ── Dead-Letter Topics ────────────────────────────────────────────────────────
resource "google_pubsub_topic" "order_events_dlq" {
  name    = "order-events-dlq"
  project = var.project_id
  message_retention_duration = "2592000s"  # 30 days for DLQ
}

resource "google_pubsub_topic" "fulfillment_events_dlq" {
  name    = "fulfillment-events-dlq"
  project = var.project_id
  message_retention_duration = "2592000s"
}

resource "google_pubsub_topic" "inventory_events_dlq" {
  name    = "inventory-events-dlq"
  project = var.project_id
  message_retention_duration = "2592000s"
}

# ── Subscriptions ─────────────────────────────────────────────────────────────

# Inventory Service: consumes order.created
resource "google_pubsub_subscription" "inventory_order_created" {
  name    = "inventory-order-created-sub"
  topic   = google_pubsub_topic.order_events.name
  project = var.project_id

  ack_deadline_seconds       = 30
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  enable_exactly_once_delivery = false

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.order_events_dlq.id
    max_delivery_attempts = 5
  }
}

# Inventory Service: consumes fulfillment.completed (to deduct reserved stock)
resource "google_pubsub_subscription" "inventory_fulfillment_completed" {
  name    = "inventory-fulfillment-completed-sub"
  topic   = google_pubsub_topic.fulfillment_events.name
  project = var.project_id

  ack_deadline_seconds = 30
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.fulfillment_events_dlq.id
    max_delivery_attempts = 5
  }
}

# Order Service: consumes fulfillment.assigned
resource "google_pubsub_subscription" "order_fulfillment_assigned" {
  name    = "order-fulfillment-assigned-sub"
  topic   = google_pubsub_topic.fulfillment_events.name
  project = var.project_id

  ack_deadline_seconds = 30
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.fulfillment_events_dlq.id
    max_delivery_attempts = 5
  }
}

# Order Service: consumes fulfillment.completed → transitions order to DELIVERED
resource "google_pubsub_subscription" "order_fulfillment_completed" {
  name    = "order-fulfillment-completed-sub"
  topic   = google_pubsub_topic.fulfillment_events.name
  project = var.project_id

  ack_deadline_seconds       = 30
  message_retention_duration = "604800s"
  retain_acked_messages      = false

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.fulfillment_events_dlq.id
    max_delivery_attempts = 5
  }
}

# Fulfillment Service: consumes order.created
resource "google_pubsub_subscription" "fulfillment_order_created" {
  name    = "fulfillment-order-created-sub"
  topic   = google_pubsub_topic.order_events.name
  project = var.project_id

  ack_deadline_seconds = 30
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.order_events_dlq.id
    max_delivery_attempts = 5
  }
}

# ── DLQ Subscriptions (for monitoring / replay tooling) ──────────────────────
resource "google_pubsub_subscription" "order_events_dlq_sub" {
  name    = "order-events-dlq-sub"
  topic   = google_pubsub_topic.order_events_dlq.name
  project = var.project_id
  ack_deadline_seconds = 600  # DLQ messages need manual inspection
}

resource "google_pubsub_subscription" "fulfillment_events_dlq_sub" {
  name    = "fulfillment-events-dlq-sub"
  topic   = google_pubsub_topic.fulfillment_events_dlq.name
  project = var.project_id
  ack_deadline_seconds = 600
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "topic_ids" {
  value = {
    order_events       = google_pubsub_topic.order_events.id
    inventory_events   = google_pubsub_topic.inventory_events.id
    fulfillment_events = google_pubsub_topic.fulfillment_events.id
    order_events_dlq   = google_pubsub_topic.order_events_dlq.id
    fulfillment_events_dlq = google_pubsub_topic.fulfillment_events_dlq.id
  }
}
