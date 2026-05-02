#!/usr/bin/env bash
# =============================================================================
# setup_topics.sh — Create all Pub/Sub topics, subscriptions, and DLQ topics
# on the local emulator (or real GCP if PUBSUB_EMULATOR_HOST is unset).
#
# Run inside the pubsub-setup container (see docker-compose.yml) or locally:
#   PUBSUB_EMULATOR_HOST=localhost:8085 bash infra/pubsub/setup_topics.sh
# =============================================================================
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-local-project}"
BASE_URL="http://${PUBSUB_EMULATOR_HOST:-localhost:8085}"
API="$BASE_URL/v1/projects/$PROJECT"

# ── helpers ──────────────────────────────────────────────────────────────────

create_topic() {
  local topic="$1"
  echo "→ Creating topic: $topic"
  curl -s -X PUT "$API/topics/$topic" \
    -H "Content-Type: application/json" \
    -d '{}' | grep -E '"name"|"error"' || true
}

create_subscription() {
  local sub="$1"
  local topic="$2"
  local ack_deadline="${3:-30}"
  local dlq_topic="${4:-}"

  local body
  body=$(cat <<JSON
{
  "topic": "projects/$PROJECT/topics/$topic",
  "ackDeadlineSeconds": $ack_deadline,
  "retryPolicy": {
    "minimumBackoff": "10s",
    "maximumBackoff": "300s"
  }
}
JSON
)

  # Add dead-letter policy when a DLQ topic is specified
  if [ -n "$dlq_topic" ]; then
    body=$(echo "$body" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['deadLetterPolicy'] = {
  'deadLetterTopic': 'projects/$PROJECT/topics/$dlq_topic',
  'maxDeliveryAttempts': 5
}
print(json.dumps(d))
")
  fi

  echo "→ Creating subscription: $sub → $topic"
  curl -s -X PUT "$API/subscriptions/$sub" \
    -H "Content-Type: application/json" \
    -d "$body" | grep -E '"name"|"error"' || true
}

# ── Topics ────────────────────────────────────────────────────────────────────

echo ""
echo "=== Creating Topics ==="

# Main event topics
create_topic "order-events"
create_topic "inventory-events"
create_topic "fulfillment-events"

# Dead-letter topics (DLQ — messages land here after max_delivery_attempts)
create_topic "order-events-dlq"
create_topic "inventory-events-dlq"
create_topic "fulfillment-events-dlq"

# ── Subscriptions ─────────────────────────────────────────────────────────────

echo ""
echo "=== Creating Subscriptions ==="

# Inventory Service: consumes order.created events
create_subscription \
  "inventory-order-created-sub" \
  "order-events" \
  30 \
  "order-events-dlq"

# Inventory Service: consumes fulfillment.completed events (to deduct stock)
create_subscription \
  "inventory-fulfillment-completed-sub" \
  "fulfillment-events" \
  30 \
  "fulfillment-events-dlq"

# Order Service: consumes fulfillment.assigned events
create_subscription \
  "order-fulfillment-assigned-sub" \
  "fulfillment-events" \
  30 \
  "fulfillment-events-dlq"

# Fulfillment Service: consumes order.created events
create_subscription \
  "fulfillment-order-created-sub" \
  "order-events" \
  30 \
  "order-events-dlq"

echo ""
echo "=== Pub/Sub setup complete ==="
echo ""

# Verify: list all topics
echo "Topics:"
curl -s "$API/topics" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('topics', []):
    print('  ', t['name'])
"

echo ""
echo "Subscriptions:"
curl -s "$API/subscriptions" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for s in d.get('subscriptions', []):
    print('  ', s['name'], '->', s.get('topic','?'))
"
