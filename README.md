# SupplyChainForge

> A production-grade, cloud-native supply chain management system built on Python microservices — inspired by noon.com's backend architecture.

**Milestone 1 Status: ✅ Complete**

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [Getting Started](#getting-started)
6. [Inventory Service API](#inventory-service-api)
7. [Design Decisions & Reasoning](#design-decisions--reasoning)
8. [Milestone Progress](#milestone-progress)
9. [GCP Deployment Overview](#gcp-deployment-overview)

---

## Project Overview

SupplyChainForge simulates core supply chain workflows:

- **Inventory management** — product catalogue, stock levels, reservation & release
- **Order fulfillment** — order creation, validation, warehouse assignment (Phase 2+)
- **Delivery routing** — carrier integration, status tracking (Phase 3+)

The system is designed for horizontal scale, event-driven consistency, and zero-downtime deployments on GCP.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       Client / API Gateway                       │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTPS REST
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
  ┌───────────────┐ ┌───────────────┐ ┌──────────────────┐
  │   Inventory   │ │     Order     │ │   Fulfillment    │
  │   Service     │ │   Service     │ │    Service       │
  │  (Port 8001)  │ │  (Port 8002)  │ │   (Port 8003)    │
  │               │ │               │ │                  │
  │  FastAPI      │ │  FastAPI      │ │  FastAPI         │
  │  SQLAlchemy   │ │  SQLAlchemy   │ │  SQLAlchemy      │
  └──────┬────────┘ └──────┬────────┘ └────────┬─────────┘
         │                 │                    │
         ▼                 ▼                    ▼
  ┌─────────────────────────────────────────────────────┐
  │                  MySQL 8 / Cloud SQL                 │
  │  inventory_db │ order_db │ fulfillment_db            │
  └─────────────────────────────────────────────────────┘
         │                 │                    │
         └─────────────────┴────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Cloud      │
                    │  Pub/Sub    │  ← event bus (Phase 2)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Redis /    │
                    │ Memorystore │  ← read cache (Phase 2)
                    └─────────────┘
```

### Data Flow (Phase 2+)

```
POST /orders
     │
     ▼
Order Service ──[OrderCreated event]──► Pub/Sub
                                              │
                                              ▼
                              Inventory Service (subscriber)
                              ├─ reserve stock (SELECT FOR UPDATE)
                              └─ [StockReserved event] ──► Pub/Sub
                                                                │
                                                                ▼
                                            Fulfillment Service (subscriber)
                                            ├─ assign warehouse
                                            ├─ calculate route
                                            └─ [FulfillmentAssigned event]
```

---

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Async support, noon JD requirement |
| Framework | FastAPI | Async-native, auto OpenAPI docs, high performance |
| ORM | SQLAlchemy 2 (async) | Type-safe queries, async sessions, Alembic migrations |
| Database | MySQL 8 / Cloud SQL | ACID transactions, noon JD requirement |
| Migrations | Alembic | Version-controlled schema evolution |
| Caching | Redis / Memorystore | O(1) stock reads (Phase 2) |
| Messaging | Cloud Pub/Sub | Durable, at-least-once delivery between services |
| Containers | Docker (multi-stage) | Lean runtime images, no build tools in prod |
| Orchestration | Docker Compose (local) / Cloud Run (GCP) | |
| Testing | pytest + pytest-asyncio | Async test support, in-memory SQLite fixture |
| Config | pydantic-settings | Type-safe env vars, fast-fail on misconfiguration |
| Logging | Structured JSON | Compatible with GCP Cloud Logging severity levels |

---

## Project Structure

```
supplychainforge/
├── services/
│   ├── inventory/               ← Milestone 1: implemented ✅
│   │   ├── app/
│   │   │   ├── main.py          ← FastAPI app factory + lifespan
│   │   │   ├── config.py        ← pydantic-settings (env vars)
│   │   │   ├── database.py      ← async engine + session factory
│   │   │   ├── dependencies.py  ← FastAPI dependency providers
│   │   │   ├── exceptions.py    ← domain-specific HTTP exceptions
│   │   │   ├── logging_config.py← structured JSON logger
│   │   │   ├── models/
│   │   │   │   └── product.py   ← SQLAlchemy ORM model
│   │   │   ├── schemas/
│   │   │   │   └── product.py   ← Pydantic request/response schemas
│   │   │   ├── routers/
│   │   │   │   ├── health.py    ← /health, /health/ready
│   │   │   │   └── products.py  ← /api/v1/products CRUD + stock ops
│   │   │   └── services/
│   │   │       └── inventory_service.py ← business logic layer
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/
│   │   │       └── 0001_initial.py
│   │   ├── tests/
│   │   │   ├── conftest.py      ← async fixtures (SQLite in-memory)
│   │   │   ├── test_health.py
│   │   │   └── test_products.py ← 20+ test cases
│   │   ├── Dockerfile           ← multi-stage build
│   │   ├── alembic.ini
│   │   ├── pyproject.toml       ← pytest config
│   │   └── requirements.txt     ← pinned dependencies
│   ├── order/                   ← Phase 2
│   └── fulfillment/             ← Phase 2
├── shared/                      ← common event schemas (Phase 2)
├── infra/
│   └── mysql/init/
│       └── 01_init.sql          ← per-service DB + user creation
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## Getting Started

### Prerequisites

- Docker Desktop ≥ 4.x
- Python 3.11+ (for running tests locally without Docker)
- `git`

### 1 — Clone and configure

```bash
git clone https://github.com/your-username/supply-chain-forge.git
cd supply-chain-forge/supplychainforge

# Create local env file (edit values if needed)
cp .env.example .env
cp services/inventory/.env.example services/inventory/.env
```

### 2 — Start the full stack

```bash
docker compose up --build
```

Services started:
| Service | URL |
|---|---|
| Inventory API | http://localhost:8001/docs |
| Inventory health | http://localhost:8001/health |
| MySQL | localhost:3306 |
| Redis | localhost:6379 |

### 3 — Run database migrations

```bash
# Apply migrations against the running MySQL container
docker compose exec inventory \
  sh -c "cd /app && alembic upgrade head"
```

Or from your host machine (with a virtualenv):

```bash
cd services/inventory
pip install -r requirements.txt
DB_HOST=127.0.0.1 alembic upgrade head
```

### 4 — Run the tests (no Docker needed)

```bash
cd services/inventory
pip install -r requirements.txt
pytest
```

Expected output: all tests green with coverage report.

### 5 — Try the API

```bash
# Create a product
curl -s -X POST http://localhost:8001/api/v1/products \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "NOON-TV-001",
    "name": "Samsung 65 QLED TV",
    "category": "electronics",
    "unit_price": "1999.99",
    "quantity_available": 50,
    "reorder_point": 10
  }' | python3 -m json.tool

# Reserve 5 units for an order
curl -s -X POST http://localhost:8001/api/v1/products/1/reserve \
  -H "Content-Type: application/json" \
  -d '{"quantity": 5, "order_id": "ORD-20260503-0001"}' | python3 -m json.tool

# List low-stock items
curl -s "http://localhost:8001/api/v1/products?low_stock_only=true" | python3 -m json.tool
```

---

## Inventory Service API

Base URL: `http://localhost:8001`

Full interactive documentation: **http://localhost:8001/docs** (Swagger UI)

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (checks DB) |
| `GET` | `/api/v1/products` | List products (paginated, filterable) |
| `POST` | `/api/v1/products` | Create a product |
| `GET` | `/api/v1/products/{id}` | Get product by ID |
| `PUT` | `/api/v1/products/{id}` | Partial update |
| `DELETE` | `/api/v1/products/{id}` | Hard delete |
| `POST` | `/api/v1/products/{id}/reserve` | Reserve stock for an order |
| `POST` | `/api/v1/products/{id}/release` | Release reserved stock |

### Query Parameters — `GET /api/v1/products`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Items per page (max 100) |
| `category` | string | — | Filter by category |
| `low_stock_only` | bool | false | Return only items at/below reorder point |

---

## Design Decisions & Reasoning

### 1. Layered Architecture from Day One

The service is split into four layers even at this early stage:
- **Router** — HTTP concerns only (status codes, request parsing)
- **Service** — business logic (reservations, stock calculations, logging)
- **Model** — database schema
- **Schema** — API contract (Pydantic)

Reason: prevents logic from creeping into routers, making it testable without HTTP overhead.

### 2. Async SQLAlchemy + aiomysql

FastAPI runs on an asyncio event loop. Using synchronous SQLAlchemy would block the loop during every DB query, destroying concurrency.  `async_sessionmaker` with `aiomysql` keeps I/O fully non-blocking.

### 3. SELECT ... FOR UPDATE on Stock Operations

The `reserve_stock` and `release_stock` methods acquire a row-level lock before modifying `quantity_reserved`.  This prevents two concurrent order requests from both seeing 5 available units and both successfully reserving 5 when only 5 exist total.

### 4. Optimistic Locking (`version` column)

Every write increments `version`.  In Phase 2, the Order Service can pass the `version` it read as a precondition — if it no longer matches, the update is rejected.  This is cheaper than holding locks for cross-service coordination.

### 5. Alembic for Schema Migrations

Table creation is **never** done via `Base.metadata.create_all()` in production.  Alembic provides:
- Rollback (`downgrade`) capability
- Audit trail of schema changes
- Safe incremental deploys on Cloud Run

### 6. Multi-stage Dockerfile

Stage 1 installs build tools + compiles packages. Stage 2 copies only the installed wheel files into a clean image.  Result: ~200 MB runtime image with no compiler toolchain.

### 7. Structured JSON Logging

Log fields are machine-parseable.  GCP Cloud Logging maps the `severity` field to its log levels automatically, enabling severity-based alerting and filtering without custom log sinks.

### 8. pydantic-settings for Configuration

All config is validated at startup. A missing `DB_HOST` or a `DB_POOL_SIZE="abc"` will raise a `ValidationError` immediately — fail fast rather than seeing mysterious runtime errors.

### 9. Per-service Databases

Each microservice owns its data (`inventory_db`, `order_db`, `fulfillment_db`). Services never query each other's database directly — all cross-service reads go through the owning service's REST API or Pub/Sub events.  This preserves service autonomy and enables independent scaling and deployment.

---

## Milestone Progress

| # | Milestone | Status |
|---|---|---|
| 1 | Project Setup & Foundation | ✅ Complete |
| 2 | Core Services Development | 🔜 Next |
| 3 | Containerisation & Local Testing | 🔜 Planned |
| 4 | GCP Deployment | 🔜 Planned |
| 5 | Production-Grade Enhancements | 🔜 Planned |
| 6 | Documentation & Polish | 🔜 Planned |

---

## GCP Deployment Overview

*(Detailed instructions in Milestone 4)*

```
Cloud Run (inventory)  ──────────────────────────────────────────┐
Cloud Run (order)      ─────────────────────────────────────────┐│
Cloud Run (fulfillment)────────────────────────────────────────┐││
                                                                │││
                    ┌──────────────────────────────────────────▼▼▼┐
                    │              VPC (Private Network)           │
                    │                                              │
                    │   Cloud SQL (MySQL)   Memorystore (Redis)    │
                    │                                              │
                    └──────────────────────────────────────────────┘
                                       │
                              Cloud Pub/Sub Topics
                              ├─ order-events
                              ├─ inventory-events
                              └─ fulfillment-events
```

GCP services required:
- Cloud Run (compute)
- Cloud SQL for MySQL (database)
- Memorystore for Redis (cache)
- Cloud Pub/Sub (messaging)
- Secret Manager (credentials)
- VPC Connector (private networking)
- Cloud Build (CI/CD)
- Cloud Logging + Monitoring (observability)
