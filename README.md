# SupplyChainForge

> A production-grade, cloud-native supply chain management system built on Python microservices — inspired by [noon.com](https://noon.com)'s backend architecture.

**Status: ✅ All 6 Milestones Complete — 74 tests passing**

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Event Flow](#event-flow)
4. [Tech Stack](#tech-stack)
5. [Project Structure](#project-structure)
6. [API Reference](#api-reference)
7. [Getting Started — Local Development](#getting-started--local-development)
8. [Running Tests](#running-tests)
9. [GCP Deployment Overview](#gcp-deployment-overview)
10. [Design Decisions](#design-decisions)
11. [Mapping to noon.com Workflows](#mapping-to-nooncom-workflows)
12. [Milestone Progress](#milestone-progress)

---

## Project Overview

SupplyChainForge simulates the core backend workflows of a supply chain platform:

| Domain | What it does |
|---|---|
| **Inventory** | Product catalogue, stock levels, reservations, low-stock alerts |
| **Orders** | Order creation with inventory validation, lifecycle state machine |
| **Fulfillment** | Warehouse assignment, picking, shipping, completion |

All three services are independently deployable, communicate asynchronously via **Google Cloud Pub/Sub**, and are backed by isolated **MySQL** databases (database-per-service pattern).

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          Client / API Gateway                              │
└──────────────────────┬──────────────────────┬─────────────────────────────┘
                       │ REST/HTTPS
           ┌───────────┼──────────────┐
           ▼           ▼              ▼
  ┌─────────────┐ ┌──────────┐ ┌─────────────┐
  │  Inventory  │ │  Order   │ │ Fulfillment │
  │  Service    │ │ Service  │ │  Service    │
  │  :8001      │ │  :8002   │ │   :8003     │
  │             │ │          │ │             │
  │  FastAPI    │ │ FastAPI  │ │  FastAPI    │
  │  aiomysql   │ │ aiomysql │ │  aiomysql   │
  │  Redis      │ │  Redis   │ │             │
  └──────┬──────┘ └────┬─────┘ └──────┬──────┘
         │              │              │
         └──────────────┴──────────────┘
                        │
           ┌────────────▼────────────┐
           │  MySQL 8 / Cloud SQL    │
           │  inventory_db           │
           │  order_db               │
           │  fulfillment_db         │
           └─────────────────────────┘

           ┌──────────────────────────────────────────┐
           │              Cloud Pub/Sub               │
           │                                          │
           │  order-events ──────► inventory-sub      │
           │                  └──► fulfillment-sub    │
           │                                          │
           │  fulfillment-events ► order-assigned-sub │
           │                  └──► order-completed-sub│
           │                  └──► inventory-comp-sub │
           └──────────────────────────────────────────┘

           ┌────────────────────────────────┐
           │  Redis / Memorystore           │
           │  (rate limiting + cache)       │
           └────────────────────────────────┘
```

---

## Event Flow

```
  POST /api/v1/orders
        │
        ▼
  Order Service
  ├─ validates stock via HTTP → Inventory Service
  ├─ creates Order (status: CONFIRMED)
  └─ publishes ──► order.created
                        │
              ┌─────────┼─────────────────────────┐
              ▼                                    ▼
  Inventory Service                    Fulfillment Service
  └─ reserves stock items              ├─ creates Fulfillment (status: ASSIGNED)
                                       └─ publishes ──► fulfillment.assigned
                                                              │
                                              ┌───────────────┘
                                              ▼
                                        Order Service
                                        └─ status: PROCESSING

  POST /api/v1/fulfillments/{id}/complete
        │
        ▼
  Fulfillment Service
  ├─ status: COMPLETED
  └─ publishes ──► fulfillment.completed
                        │
              ┌─────────┼──────────────────┐
              ▼                             ▼
        Order Service             Inventory Service
        └─ status: DELIVERED       └─ records audit trail
```

---

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.13 | Async-native, type-safe |
| Framework | FastAPI 0.111 | Auto OpenAPI docs, high throughput, async handlers |
| ORM | SQLAlchemy 2.0 (async) | Type-safe queries, `async_sessionmaker`, Alembic migrations |
| Database | MySQL 8 / Cloud SQL | ACID transactions, row-level locking for reservations |
| Migrations | Alembic | Version-controlled schema: `0001 → 0002 → 0003` per service |
| Caching | Redis 7 / Memorystore | Stock read cache + rate limiting |
| Messaging | Cloud Pub/Sub | Durable at-least-once delivery, DLQ for failed events |
| Idempotency | `processed_events` table | `(service_name, event_id)` unique constraint prevents duplicates |
| Containers | Docker (multi-stage builds) | Lean ~200 MB runtime images |
| Orchestration | Docker Compose (local) / Cloud Run (GCP) | |
| IaC | Terraform >= 1.6 (`google ~> 5.0`) | 9 modules, full GCP infra as code |
| CI/CD | Cloud Build | `cloudbuild.yaml` triggers on push to `main` |
| Testing | pytest + pytest-asyncio + respx | In-memory SQLite fixtures, HTTP mocking |
| Config | pydantic-settings | Type-validated env vars, Secret Manager integration |
| Logging | Structured JSON | Maps to GCP Cloud Logging severity levels |
| Monitoring | Cloud Monitoring alerts | 5xx rate, p95 latency, DLQ depth |

---

## Project Structure

```
supplychainforge/
├── services/
│   ├── inventory/
│   │   ├── app/
│   │   │   ├── main.py             # FastAPI app + lifespan (startup/shutdown)
│   │   │   ├── config.py           # pydantic-settings (all env vars)
│   │   │   ├── database.py         # async engine + session factory
│   │   │   ├── cache.py            # Redis CacheService (connect/ping/get/set)
│   │   │   ├── dependencies.py     # FastAPI DI providers
│   │   │   ├── exceptions.py       # domain HTTP exceptions
│   │   │   ├── logging_config.py   # structured JSON logger
│   │   │   ├── models/product.py   # SQLAlchemy ORM model
│   │   │   ├── schemas/product.py  # Pydantic request/response schemas
│   │   │   ├── routers/
│   │   │   │   ├── health.py       # /health  /health/live  /health/ready
│   │   │   │   └── products.py     # /api/v1/products CRUD + stock ops
│   │   │   ├── services/
│   │   │   │   └── inventory_service.py   # business logic + SELECT FOR UPDATE
│   │   │   └── subscribers/
│   │   │       ├── order_created.py        # consumes order.created
│   │   │       └── fulfillment_completed.py# consumes fulfillment.completed
│   │   ├── alembic/versions/
│   │   │   ├── 0001_initial.py
│   │   │   ├── 0002_add_indexes.py
│   │   │   └── 0003_add_processed_events.py
│   │   ├── tests/
│   │   │   ├── conftest.py
│   │   │   ├── test_health.py
│   │   │   ├── test_products.py
│   │   │   └── test_subscribers.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── order/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── models/order.py     # OrderStatus enum + state machine
│   │   │   ├── schemas/order.py
│   │   │   ├── routers/orders.py   # CRUD + cancel
│   │   │   ├── services/
│   │   │   │   └── order_service.py
│   │   │   └── subscribers/
│   │   │       ├── fulfillment_assigned.py  # → PROCESSING
│   │   │       └── fulfillment_completed.py # → DELIVERED
│   │   ├── alembic/versions/
│   │   │   ├── 0001_initial.py
│   │   │   ├── 0002_add_indexes.py
│   │   │   └── 0003_add_processed_events.py
│   │   └── tests/
│   │       ├── test_orders.py
│   │       └── test_subscribers.py
│   │
│   └── fulfillment/
│       ├── app/
│       │   ├── main.py
│       │   ├── models/fulfillment.py  # FulfillmentStatus enum
│       │   ├── schemas/fulfillment.py
│       │   ├── routers/fulfillments.py# pick/ship/complete/fail
│       │   ├── services/
│       │   │   └── fulfillment_service.py
│       │   └── subscribers/
│       │       └── order_created.py   # creates Fulfillment + publishes assigned
│       ├── alembic/versions/
│       │   ├── 0001_initial.py
│       │   ├── 0002_add_indexes.py
│       │   └── 0003_add_processed_events.py
│       └── tests/
│           ├── test_fulfillments.py
│           └── test_event_publishing.py
│
├── shared/
│   ├── events/
│   │   ├── envelope.py             # EventEnvelope wrapper (event_id, source, type)
│   │   ├── order_events.py         # OrderCreatedData, OrderItemData
│   │   ├── inventory_events.py     # StockReservedData
│   │   └── fulfillment_events.py   # FulfillmentAssignedData, FulfillmentCompletedData
│   ├── pubsub/
│   │   ├── publisher.py            # publish_event helper
│   │   └── subscriber.py           # PullSubscriber ABC
│   ├── db/
│   │   └── idempotency.py          # ProcessedEvent model + is_already_processed / mark_processed
│   ├── gcp/
│   │   └── secrets.py              # Secret Manager helper
│   └── middleware/
│       ├── rate_limit.py           # Redis sliding-window rate limiter
│       └── request_id.py           # X-Request-ID injection
│
├── terraform/
│   ├── main.tf                     # root module wiring
│   ├── variables.tf
│   ├── outputs.tf
│   └── modules/
│       ├── networking/             # VPC, subnets, VPC Access Connector
│       ├── cloud_sql/              # MySQL 8, private IP, per-service DBs
│       ├── memorystore/            # Redis single-node
│       ├── pubsub/                 # topics, subscriptions, DLQ topics
│       ├── artifact_registry/      # Docker image repository
│       ├── cloud_run/              # 3 Cloud Run services
│       ├── iam/                    # service accounts + roles
│       ├── secret_manager/         # DB password secrets
│       └── monitoring/             # Cloud Monitoring alert policies
│
├── infra/
│   ├── mysql/init/01_init.sql      # per-service DB + user creation
│   └── pubsub/setup_topics.sh      # local emulator topic/subscription setup
│
├── tests/
│   └── e2e/
│       └── test_e2e_flow.py        # end-to-end integration test script
│
├── docker-compose.yml
├── cloudbuild.yaml
├── .env.example
├── README.md
└── PRODUCTION_GUIDE.md
```

---

## API Reference

Full interactive docs (Swagger UI) are available at `/docs` on each running service.

### Inventory Service — `http://localhost:8001`

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/live` | Explicit liveness alias |
| `GET` | `/health/ready` | Readiness (DB + Redis) |
| `GET` | `/api/v1/products` | List products (`page`, `page_size`, `category`, `low_stock_only`) |
| `POST` | `/api/v1/products` | Create product |
| `GET` | `/api/v1/products/{id}` | Get product by ID |
| `PUT` | `/api/v1/products/{id}` | Partial update |
| `DELETE` | `/api/v1/products/{id}` | Hard delete |
| `POST` | `/api/v1/products/{id}/reserve` | Reserve stock (row-level lock) |
| `POST` | `/api/v1/products/{id}/release` | Release reserved stock |

### Order Service — `http://localhost:8002`

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness (DB + Redis) |
| `GET` | `/api/v1/orders` | List orders (`page`, `page_size`, `customer_id`, `status`) |
| `POST` | `/api/v1/orders` | Create order (validates + publishes `order.created`) |
| `GET` | `/api/v1/orders/{id}` | Get order by ID |
| `POST` | `/api/v1/orders/{id}/cancel` | Cancel order + release reserved stock |

**Order status machine:** `PENDING → CONFIRMED → PROCESSING → SHIPPED → DELIVERED`

### Fulfillment Service — `http://localhost:8003`

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness (DB + Redis) |
| `GET` | `/api/v1/fulfillments` | List fulfillments (`page`, `page_size`, `status`) |
| `GET` | `/api/v1/fulfillments/{id}` | Get fulfillment by ID |
| `GET` | `/api/v1/fulfillments/by-order/{id}` | Get fulfillment by order ID |
| `POST` | `/api/v1/fulfillments/{id}/pick` | Start picking |
| `POST` | `/api/v1/fulfillments/{id}/ship` | Mark shipped (requires `tracking_number`) |
| `POST` | `/api/v1/fulfillments/{id}/complete` | Mark completed → publishes `fulfillment.completed` |
| `POST` | `/api/v1/fulfillments/{id}/fail` | Mark failed |

**Fulfillment status machine:** `ASSIGNED → PICKING → SHIPPED → COMPLETED`

---

## Getting Started — Local Development

### Prerequisites

- Docker Desktop >= 4.x
- Python 3.11+ (for running tests locally)

### 1 — Clone and configure

```bash
git clone https://github.com/your-username/supply-chain-forge.git
cd supply-chain-forge/supplychainforge
cp .env.example .env
```

### 2 — Start the full local stack

```bash
docker compose up --build
```

| Container | URL |
|---|---|
| Inventory Service | http://localhost:8001/docs |
| Order Service | http://localhost:8002/docs |
| Fulfillment Service | http://localhost:8003/docs |
| MySQL 8 | localhost:3306 |
| Redis 7 | localhost:6379 |
| Pub/Sub Emulator | localhost:8085 |

### 3 — Run database migrations

```bash
for svc in inventory order fulfillment; do
  docker compose exec $svc sh -c "cd /app && alembic upgrade head"
done
```

### 4 — Try the complete order flow

```bash
# 1. Create a product
curl -s -X POST http://localhost:8001/api/v1/products \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "NOON-TV-65-001",
    "name": "Samsung 65\" QLED TV",
    "category": "electronics",
    "unit_price": "1999.99",
    "quantity_available": 50,
    "reorder_point": 5
  }' | python3 -m json.tool

# 2. Place an order
curl -s -X POST http://localhost:8002/api/v1/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "cust-00123",
    "shipping_address": "Al Quoz Industrial Area, Dubai, UAE",
    "items": [
      {"product_id": 1, "sku": "NOON-TV-65-001", "quantity": 2, "unit_price": "1999.99"}
    ]
  }' | python3 -m json.tool

# 3. Check fulfillment (created automatically via Pub/Sub)
curl -s http://localhost:8003/api/v1/fulfillments/by-order/1 | python3 -m json.tool

# 4. Advance through fulfillment lifecycle
FULFILLMENT_ID=1
curl -s -X POST http://localhost:8003/api/v1/fulfillments/$FULFILLMENT_ID/pick
curl -s -X POST http://localhost:8003/api/v1/fulfillments/$FULFILLMENT_ID/ship \
  -H "Content-Type: application/json" \
  -d '{"tracking_number": "1Z-NOON-0001"}'
curl -s -X POST http://localhost:8003/api/v1/fulfillments/$FULFILLMENT_ID/complete

# 5. Order should now be DELIVERED
curl -s http://localhost:8002/api/v1/orders/1 | python3 -m json.tool
```

### 5 — Run the E2E test script

```bash
pip install httpx
python tests/e2e/test_e2e_flow.py
```

---

## Running Tests

Tests use in-memory SQLite — no Docker required.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r services/inventory/requirements.txt \
            -r services/inventory/requirements-dev.txt

python -m pytest services/inventory/tests -q
python -m pytest services/order/tests -q
python -m pytest services/fulfillment/tests -q
```

**Current counts:** 30 inventory + 22 order + 22 fulfillment = **74 tests, all passing**

---

## GCP Deployment Overview

> Full step-by-step instructions: see **[PRODUCTION_GUIDE.md](PRODUCTION_GUIDE.md)**

```
Cloud Run (inventory / order / fulfillment)
         │
         ▼  (VPC connector)
  ┌──────────────────────────────────┐
  │   Private VPC                    │
  │   Cloud SQL (MySQL 8)            │
  │   Memorystore (Redis 7)          │
  └──────────────────────────────────┘
         │
         ▼
  Cloud Pub/Sub  (order-events / fulfillment-events / DLQs)
         │
  Secret Manager  ·  Artifact Registry  ·  Cloud Build
  Cloud Logging   ·  Cloud Monitoring
```

### Terraform Modules

| Module | Resources |
|---|---|
| `networking` | VPC, subnets, VPC Access Connector |
| `cloud_sql` | MySQL 8 instance, private IP, 3 databases + users |
| `memorystore` | Redis 7 single-node |
| `pubsub` | 3 topics, 5+ subscriptions, 3 DLQ topics |
| `artifact_registry` | Docker image registry |
| `cloud_run` | 3 Cloud Run services with env vars + secrets |
| `iam` | Service accounts, Cloud SQL / Pub/Sub roles |
| `secret_manager` | DB password secrets |
| `monitoring` | 5xx error rate, p95 latency, DLQ depth alerts |

---

## Design Decisions

### Database-per-Service
Each service owns its database. No cross-service SQL joins. Cross-service reads go through REST APIs or Pub/Sub events. This enables independent scaling and schema evolution.

### `SELECT … FOR UPDATE` on Stock Operations
`reserve_stock` acquires a row-level lock before modifying `quantity_reserved`. This prevents concurrent order requests from both successfully over-reserving stock without requiring application-level distributed locks.

### Idempotent Event Processing
Every Pub/Sub subscriber checks a `processed_events` table (indexed on `(service_name, event_id)`) before processing. If the event has already been seen (Pub/Sub at-least-once delivery), it is silently skipped.

### Alembic Migrations (never `create_all`)
Schema changes are applied via Alembic upgrade scripts. This gives rollback capability and supports safe rolling deploys where Cloud Run instances may run old and new code briefly.

### Structured JSON Logging
Every log line is `{"severity": "INFO", "message": "...", "service": "...", "request_id": "..."}`. GCP Cloud Logging maps the `severity` field automatically.

### Multi-stage Docker Builds
Stage 1 installs build tools and compiles wheels. Stage 2 copies only the compiled packages into a clean Python base image, producing ~200 MB images with no compiler toolchain.

### Graceful Shutdown
FastAPI `lifespan` context managers stop Pub/Sub subscriber threads and dispose the SQLAlchemy connection pool before exit. Cloud Run gives 10 seconds between SIGTERM and SIGKILL.

### Rate Limiting (fail-open)
Every service enforces per-IP rate limits via Redis. If Redis is unavailable, the middleware fails open so service availability is not coupled to the cache tier.

---

## Mapping to noon.com Workflows

| noon.com Concept | SupplyChainForge Implementation |
|---|---|
| Product catalogue | Inventory Service — SKU, quantity, reorder points |
| Stock reservation on checkout | `POST /products/{id}/reserve` with `SELECT FOR UPDATE` |
| Order management | Order Service — PENDING → CONFIRMED → DELIVERED state machine |
| Warehouse assignment | Fulfillment Service — assigns warehouse + carrier on `order.created` |
| Pick & pack | `POST /fulfillments/{id}/pick` |
| Dispatch to carrier | `POST /fulfillments/{id}/ship` — records tracking number |
| Delivery confirmation | `POST /fulfillments/{id}/complete` → `fulfillment.completed` event |
| Event-driven updates | Cloud Pub/Sub — no polling between services |
| Inventory reconciliation | `fulfillment.completed` subscriber audits stock consumed |
| Operational observability | Cloud Monitoring: 5xx, latency, DLQ depth alerts |
| Independent scaling | Cloud Run autoscaling (0 → N instances per service) |

---

## Milestone Progress

| # | Milestone | Status | Deliverables |
|---|---|---|---|
| 1 | Project Setup & Inventory Service | ✅ Complete | 10 inventory endpoints, 24 tests |
| 2 | Order + Fulfillment Services | ✅ Complete | 6 order endpoints, 9 fulfillment endpoints, +30 tests |
| 3 | Containerisation & Local Testing | ✅ Complete | Multi-stage Dockerfiles, docker-compose, Pub/Sub emulator |
| 4 | GCP Infrastructure as Code | ✅ Complete | Terraform (9 modules), Cloud Build CI/CD, Secret Manager |
| 5 | Production-Grade Enhancements | ✅ Complete | Idempotency, health checks, monitoring alerts, 74 tests |
| 6 | Documentation & Polish | ✅ Complete | OpenAPI metadata, E2E test script, README, PRODUCTION_GUIDE.md |

**Total: 74 tests passing**
