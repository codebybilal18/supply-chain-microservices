#!/usr/bin/env bash
# =============================================================================
# teardown_topics.sh — Delete all Pub/Sub topics and subscriptions
# Useful for resetting local emulator state.
# =============================================================================
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-local-project}"
BASE_URL="http://${PUBSUB_EMULATOR_HOST:-localhost:8085}"
API="$BASE_URL/v1/projects/$PROJECT"

delete_subscription() {
  echo "→ Deleting subscription: $1"
  curl -s -X DELETE "$API/subscriptions/$1" || true
}

delete_topic() {
  echo "→ Deleting topic: $1"
  curl -s -X DELETE "$API/topics/$1" || true
}

delete_subscription "inventory-order-created-sub"
delete_subscription "inventory-fulfillment-completed-sub"
delete_subscription "order-fulfillment-assigned-sub"
delete_subscription "fulfillment-order-created-sub"

delete_topic "order-events"
delete_topic "inventory-events"
delete_topic "fulfillment-events"
delete_topic "order-events-dlq"
delete_topic "inventory-events-dlq"
delete_topic "fulfillment-events-dlq"

echo "Teardown complete."
