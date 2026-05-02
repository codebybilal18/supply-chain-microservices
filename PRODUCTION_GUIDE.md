# SupplyChainForge — Production Deployment Guide

This guide covers everything needed to take SupplyChainForge from a local docker compose stack to a production Google Cloud Platform environment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [GCP Project Setup](#gcp-project-setup)
3. [Enable Required GCP APIs](#enable-required-gcp-apis)
4. [Configure Terraform Variables](#configure-terraform-variables)
5. [Terraform: First-Time Deploy](#terraform-first-time-deploy)
6. [Secret Manager: Database Passwords](#secret-manager-database-passwords)
7. [Build & Push Docker Images](#build--push-docker-images)
8. [Cloud SQL: Run Migrations](#cloud-sql-run-migrations)
9. [Cloud Build: CI/CD Setup](#cloud-build-cicd-setup)
10. [Monitoring: Alert Notification Channels](#monitoring-alert-notification-channels)
11. [Post-Deploy Verification](#post-deploy-verification)
12. [Rollback Procedures](#rollback-procedures)
13. [Scaling Recommendations](#scaling-recommendations)
14. [Security Hardening Checklist](#security-hardening-checklist)
15. [Cost Optimisation Notes](#cost-optimisation-notes)
16. [Disaster Recovery](#disaster-recovery)
17. [Runbook: Common Operations](#runbook-common-operations)

---

## Prerequisites

| Tool | Minimum version | Install guide |
|---|---|---|
| `gcloud` CLI | 450+ | https://cloud.google.com/sdk/docs/install |
| `terraform` | 1.6.0 | https://developer.hashicorp.com/terraform/install |
| `docker` | 24.0 | https://docs.docker.com/engine/install/ |
| `python3` | 3.11 | https://www.python.org/downloads/ |

```bash
# Verify installations
gcloud version
terraform version
docker version --format '{{.Server.Version}}'
```

---

## GCP Project Setup

```bash
# 1. Set your project (create one in Cloud Console first if needed)
PROJECT_ID="supply-chain-forge-prod"    # change to your project ID
REGION="me-central1"                    # Dubai / Middle East region

gcloud config set project $PROJECT_ID
gcloud config set compute/region $REGION

# 2. Authenticate (choose one)
gcloud auth login                       # for interactive use
gcloud auth application-default login   # for Terraform ADC

# 3. Create the project if it does not exist
gcloud projects create $PROJECT_ID --name="SupplyChainForge Production"
gcloud billing projects link $PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
```

---

## Enable Required GCP APIs

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com \
  pubsub.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  vpcaccess.googleapis.com \
  cloudresourcemanager.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  compute.googleapis.com \
  servicenetworking.googleapis.com \
  --project=$PROJECT_ID
```

Allow 2-3 minutes for APIs to propagate before running Terraform.

---

## Configure Terraform Variables

```bash
cd supplychainforge/terraform
cp terraform.tfvars.example terraform.tfvars   # create this file if it doesn't exist
```

Edit `terraform.tfvars`:

```hcl
project_id = "supply-chain-forge-prod"
region     = "me-central1"

# Cloud SQL
db_tier              = "db-n1-standard-2"     # 2 vCPU / 7.5 GB RAM
db_deletion_protection = true

# Redis
redis_memory_size_gb = 2

# Cloud Run
inventory_image  = "me-central1-docker.pkg.dev/supply-chain-forge-prod/scf-images/inventory:latest"
order_image      = "me-central1-docker.pkg.dev/supply-chain-forge-prod/scf-images/order:latest"
fulfillment_image = "me-central1-docker.pkg.dev/supply-chain-forge-prod/scf-images/fulfillment:latest"

# Monitoring (set after creating notification channels — see step 10)
notification_channels = []
```

> **Tip:** Store `terraform.tfvars` in Secret Manager or use a separate `*.auto.tfvars` file that is git-ignored. Never commit credentials to source control.

---

## Terraform: First-Time Deploy

```bash
cd supplychainforge/terraform

# Initialise providers and modules
terraform init

# Review the plan — check that ~100 resources will be created
terraform plan -out=tfplan

# Apply (takes 15-25 minutes on first run due to Cloud SQL provisioning)
terraform apply tfplan
```

**Important Cloud SQL note:** First-time provisioning takes 8-12 minutes. The Cloud Run services will be deployed but will fail to connect until Cloud SQL is fully ready and migrations have been applied (see next steps).

Save the outputs:

```bash
terraform output -json > terraform_outputs.json
cat terraform_outputs.json
```

Key outputs to note:
- `cloud_run_inventory_url`
- `cloud_run_order_url`
- `cloud_run_fulfillment_url`
- `cloud_sql_instance_connection_name`
- `artifact_registry_url`

---

## Secret Manager: Database Passwords

Terraform creates the Secret Manager secrets, but you must populate the actual values. The Cloud Run services mount these as environment variables at runtime.

```bash
# Generate strong passwords
INVENTORY_DB_PASS=$(openssl rand -base64 32)
ORDER_DB_PASS=$(openssl rand -base64 32)
FULFILLMENT_DB_PASS=$(openssl rand -base64 32)

# Add secret versions
echo -n "$INVENTORY_DB_PASS" | gcloud secrets versions add \
  "inventory-db-password" --data-file=- --project=$PROJECT_ID

echo -n "$ORDER_DB_PASS" | gcloud secrets versions add \
  "order-db-password" --data-file=- --project=$PROJECT_ID

echo -n "$FULFILLMENT_DB_PASS" | gcloud secrets versions add \
  "fulfillment-db-password" --data-file=- --project=$PROJECT_ID
```

> The passwords you set here must match the MySQL user passwords in Cloud SQL. If you rotated them, run `ALTER USER` on the Cloud SQL instance and update the secret.

---

## Build & Push Docker Images

```bash
cd supplychainforge

# Configure Docker to authenticate with Artifact Registry
gcloud auth configure-docker me-central1-docker.pkg.dev

REGISTRY="me-central1-docker.pkg.dev/$PROJECT_ID/scf-images"

# Build and push all three services
for svc in inventory order fulfillment; do
  docker build \
    -f services/$svc/Dockerfile \
    -t $REGISTRY/$svc:latest \
    -t $REGISTRY/$svc:$(git rev-parse --short HEAD) \
    services/$svc/
  docker push $REGISTRY/$svc:latest
  docker push $REGISTRY/$svc:$(git rev-parse --short HEAD)
done
```

After pushing, update Cloud Run to use the new image:

```bash
for svc in inventory order fulfillment; do
  gcloud run services update scf-$svc-service \
    --image=$REGISTRY/$svc:latest \
    --region=$REGION \
    --project=$PROJECT_ID
done
```

---

## Cloud SQL: Run Migrations

Alembic migrations must be applied before the services can handle traffic. The safest way is via Cloud SQL Auth Proxy.

### Option A: Cloud SQL Auth Proxy (recommended)

```bash
# Install the proxy
curl -o cloud-sql-proxy \
  https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.9.0/cloud-sql-proxy.darwin.amd64
chmod +x cloud-sql-proxy

# Get the instance connection name
INSTANCE=$(terraform output -raw cloud_sql_instance_connection_name)

# Start the proxy (listens on localhost:3306)
./cloud-sql-proxy "$INSTANCE" &
PROXY_PID=$!

# Run migrations for each service
cd supplychainforge

for svc in inventory order fulfillment; do
  cd services/$svc
  DB_PASS=$(gcloud secrets versions access latest \
    --secret="${svc}-db-password" --project=$PROJECT_ID)
  DATABASE_URL="mysql+aiomysql://${svc}_user:${DB_PASS}@localhost:3306/${svc}_db" \
    alembic upgrade head
  cd ../..
done

# Stop the proxy
kill $PROXY_PID
```

### Option B: Cloud Run Job (for automated deploys)

Create a one-off Cloud Run Job that runs `alembic upgrade head` on each deploy. Add it as a step in `cloudbuild.yaml` before deploying the new service revision.

---

## Cloud Build: CI/CD Setup

### 1 — Connect your repository

```bash
# Open Cloud Build repository connection wizard
gcloud builds connections create github \
  --region=$REGION \
  --project=$PROJECT_ID
```

Follow the OAuth flow in the browser to link your GitHub repository.

### 2 — Create a trigger

```bash
gcloud builds triggers create github \
  --name="scf-main-push" \
  --repo-name="supply-chain-forge" \
  --repo-owner="your-github-username" \
  --branch-pattern="^main$" \
  --build-config="supplychainforge/cloudbuild.yaml" \
  --region=$REGION \
  --project=$PROJECT_ID
```

### 3 — Grant Cloud Build service account permissions

```bash
CB_SA="$(gcloud projects describe $PROJECT_ID \
  --format='value(projectNumber)')@cloudbuild.gserviceaccount.com"

for role in \
  roles/run.admin \
  roles/iam.serviceAccountUser \
  roles/artifactregistry.writer \
  roles/cloudsql.client \
  roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$CB_SA" \
    --role="$role"
done
```

### 4 — Test the trigger

```bash
gcloud builds triggers run scf-main-push \
  --branch=main \
  --region=$REGION \
  --project=$PROJECT_ID
```

---

## Monitoring: Alert Notification Channels

### 1 — Create an email notification channel

```bash
# Create a notification channel (email)
gcloud beta monitoring channels create \
  --display-name="SCF Ops Email" \
  --type=email \
  --channel-labels=email_address=ops@yourcompany.com \
  --project=$PROJECT_ID

# Get the channel ID
gcloud beta monitoring channels list \
  --filter='displayName="SCF Ops Email"' \
  --format='value(name)' \
  --project=$PROJECT_ID
```

### 2 — Wire into Terraform

Update `terraform.tfvars` with the channel name:

```hcl
notification_channels = [
  "projects/supply-chain-forge-prod/notificationChannels/1234567890"
]
```

Re-apply Terraform to attach the channel to alert policies:

```bash
terraform apply -target=module.monitoring
```

### Alert Policies Created

| Alert | Threshold | Window | Severity |
|---|---|---|---|
| 5xx error rate | > 1 req/s | 5 minutes | Critical |
| p95 request latency | > 2000 ms | 5 minutes | Warning |
| DLQ subscription depth | > 0 messages | 1 minute | Critical |

---

## Post-Deploy Verification

```bash
INVENTORY=$(terraform output -raw cloud_run_inventory_url)
ORDER=$(terraform output -raw cloud_run_order_url)
FULFILLMENT=$(terraform output -raw cloud_run_fulfillment_url)

# Health checks
curl -sf "$INVENTORY/health/ready" && echo "Inventory: OK"
curl -sf "$ORDER/health/ready"      && echo "Order: OK"
curl -sf "$FULFILLMENT/health/ready" && echo "Fulfillment: OK"

# Run the E2E test script against the deployed services
INVENTORY_URL=$INVENTORY \
ORDER_URL=$ORDER \
FULFILLMENT_URL=$FULFILLMENT \
python tests/e2e/test_e2e_flow.py
```

---

## Rollback Procedures

### Rollback a Cloud Run service to a previous revision

```bash
# List revisions for a service
gcloud run revisions list \
  --service=scf-inventory-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --sort-by=~LAST_DEPLOYED

# Migrate 100% traffic back to a specific revision
gcloud run services update-traffic scf-inventory-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --to-revisions=scf-inventory-service-00023-abc=100
```

### Rollback Alembic migrations

```bash
# Connect via Cloud SQL Auth Proxy (see step: Run Migrations)
cd services/inventory
DATABASE_URL="mysql+aiomysql://..." alembic downgrade -1   # one step back
DATABASE_URL="mysql+aiomysql://..." alembic downgrade 0002  # to specific revision
```

> Always test downgrade migrations in a staging environment first. The `processed_events` table (0003) can be dropped safely — idempotency will simply reset.

### Rollback Terraform changes

```bash
# Roll back to a previous Terraform state (use with caution)
terraform apply -target=module.cloud_run -var 'inventory_image=...:<previous_tag>'
```

---

## Scaling Recommendations

### Cloud Run concurrency and instances

Edit the `cloud_run` Terraform module or apply directly via `gcloud`:

```bash
gcloud run services update scf-inventory-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --concurrency=80 \           # requests per instance
  --min-instances=1 \          # keep warm (avoids cold starts)
  --max-instances=20 \         # cap to control costs
  --cpu=2 \
  --memory=1Gi
```

**Recommended starting values per service:**

| Service | Min instances | Max instances | CPU | Memory | Concurrency |
|---|---|---|---|---|---|
| Inventory | 1 | 20 | 2 | 1Gi | 80 |
| Order | 1 | 20 | 2 | 1Gi | 80 |
| Fulfillment | 1 | 10 | 1 | 512Mi | 40 |

### Cloud SQL

- Start with `db-n1-standard-2` (2 vCPU / 7.5 GB)
- Enable **read replicas** when inventory read QPS exceeds 500/s
- Enable **automatic storage increases** (prevents outage from disk full)
- Enable **point-in-time recovery** (PITR) for up to 7 days of transaction log retention

```hcl
# In terraform/modules/cloud_sql/main.tf
backup_configuration {
  enabled                        = true
  point_in_time_recovery_enabled = true
  transaction_log_retention_days = 7
  backup_retention_settings {
    retained_backups = 7
  }
}
```

### Redis (Memorystore)

- `BASIC` tier (single node) is fine up to ~10,000 rate-limit checks/second
- Upgrade to `STANDARD_HA` for automatic failover in production:

```hcl
tier = "STANDARD_HA"
```

### Pub/Sub throughput

Pub/Sub scales automatically. Increase subscriber parallelism if events are backing up:

```python
# In shared/pubsub/subscriber.py
flow_control = pubsub_v1.types.FlowControl(max_messages=200)   # default is 100
```

---

## Security Hardening Checklist

- [ ] **Restrict Cloud Run ingress**: Set `--ingress=internal-and-cloud-load-balancing` so services are not publicly accessible — route external traffic through Cloud Load Balancing + Cloud Armor
- [ ] **Enable Cloud Armor**: Add WAF rules (OWASP CRS) and geo-restriction for the Load Balancer target
- [ ] **mTLS between services**: Use Assured Workloads or Cloud Service Mesh for mutual TLS on internal service-to-service calls
- [ ] **Secret rotation**: Configure Secret Manager rotation for DB passwords every 90 days; update Cloud Run service to pick up the new version on each deploy
- [ ] **VPC Service Controls**: Create a VPC Service Control perimeter to prevent data exfiltration from Cloud SQL and Secret Manager
- [ ] **Cloud SQL IAM auth**: Replace password-based DB auth with IAM database authentication — eliminates static passwords entirely
- [ ] **Least-privilege service accounts**: Each Cloud Run service already has a dedicated SA; audit IAM roles quarterly
- [ ] **Binary Authorization**: Require all deployed container images to be built and attested by Cloud Build
- [ ] **Disable public Cloud SQL IP**: Ensure `ipv4_enabled = false` in `cloud_sql` module; all connections go through Private IP + VPC
- [ ] **Private Google Access**: Enable on subnets so VMs/serverless can reach Google APIs without NAT
- [ ] **Container vulnerability scanning**: Enable Artifact Registry vulnerability scanning; block deploys with CRITICAL CVEs in Cloud Build
- [ ] **Log-based alerting**: Create Cloud Monitoring alerts on `severity=ERROR` logs from any service
- [ ] **Rate limiting**: Current Redis sliding-window rate limits are 200 req/60s (inventory) and 100 req/60s (order+fulfillment) — adjust for your traffic profile
- [ ] **CORS**: If adding a web frontend, configure explicit CORS origins in FastAPI middleware — never allow `*` in production
- [ ] **Pydantic input validation**: All API inputs are validated by Pydantic schemas — ensure `model_config = {"str_strip_whitespace": True}` to prevent whitespace injection

---

## Cost Optimisation Notes

| Resource | Recommendation |
|---|---|
| Cloud Run | Use `--min-instances=0` for non-critical services to scale to zero during off-hours |
| Cloud SQL | Use `db-f1-micro` or `db-g1-small` in staging; `db-n1-standard-2` in prod |
| Memorystore | `BASIC` tier saves ~40% vs `STANDARD_HA`; acceptable for non-critical caching |
| Pub/Sub | No idle costs — pay only for message volume |
| Artifact Registry | Tag images with git SHA; add a retention policy to delete images older than 30 days |
| Cloud Build | Free tier (120 build-minutes/day) is sufficient for small teams |

Enable **Cloud Billing Budget Alerts** to get email notifications when spend exceeds thresholds:

```bash
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="SCF Monthly Budget" \
  --budget-amount=500USD \
  --threshold-rules-percent=0.5,0.9,1.0
```

---

## Disaster Recovery

### RTO / RPO Targets

| Scenario | RTO target | RPO target | Strategy |
|---|---|---|---|
| Cloud Run service crash | < 30 s | 0 (stateless) | Cloud Run auto-restarts |
| Cloud SQL primary failure | < 2 min | < 5 min | Enable High Availability (HA) failover |
| Redis failure | < 1 min | N/A (cache is expendable) | Rate limiter fails open |
| Pub/Sub outage | 0 (Google SLA) | 0 | Messages durable on Google's infra |
| Region-wide outage | Manual failover | Last Cloud SQL backup | Multi-region Cloud SQL replica |

### Cloud SQL High Availability

```hcl
# terraform/modules/cloud_sql/main.tf
availability_type = "REGIONAL"    # automatic failover to standby
```

### Multi-region disaster recovery

For RPO < 5 minutes in a full regional failure:

1. Create a **cross-region read replica** in a second region
2. Promote the replica to primary manually during a DR event
3. Update Cloud Run env vars to point to the new primary
4. Redirect DNS / Load Balancer to the secondary region

---

## Runbook: Common Operations

### Check service logs

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="scf-inventory-service"' \
  --limit=50 \
  --format=json \
  --project=$PROJECT_ID | python3 -m json.tool
```

### View Pub/Sub DLQ messages

```bash
# Pull up to 10 undelivered messages from the DLQ
gcloud pubsub subscriptions pull projects/$PROJECT_ID/subscriptions/order-events-dlq-sub \
  --limit=10 \
  --auto-ack=false \
  --format=json
```

### Replay DLQ messages after a fix

1. Fix the bug and deploy the corrected service image
2. Pull messages from DLQ subscription with `--auto-ack=false`
3. Re-publish them to the original topic with the same `event_id` attribute (idempotency guards prevent duplicate processing)

### Manually trigger a Pub/Sub message

```bash
gcloud pubsub topics publish projects/$PROJECT_ID/topics/order-events \
  --message='{"event_id":"test-001","event_type":"order.created","source":"manual","data":{...}}'
```

### Scale a service to zero (maintenance mode)

```bash
gcloud run services update scf-inventory-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --max-instances=0
```

### Add a new environment variable to all services

```bash
for svc in inventory order fulfillment; do
  gcloud run services update scf-${svc}-service \
    --region=$REGION \
    --project=$PROJECT_ID \
    --update-env-vars=NEW_VAR=value
done
```

### Force re-deploy (no code change)

```bash
gcloud run services update scf-inventory-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --image=$REGISTRY/inventory:latest
```

---

## Environment Variable Reference

These variables are injected by Terraform into each Cloud Run service. For local development, set them in your `.env` file.

### Inventory Service

| Variable | Example | Description |
|---|---|---|
| `DATABASE_URL` | `mysql+aiomysql://inv_user:pass@/inventory_db?unix_socket=/cloudsql/conn-name` | Cloud SQL connection string |
| `REDIS_URL` | `redis://10.0.0.5:6379` | Memorystore Redis URL |
| `GCP_PROJECT_ID` | `supply-chain-forge-prod` | GCP project for Pub/Sub |
| `PUBSUB_TOPIC_INVENTORY_EVENTS` | `projects/.../topics/inventory-events` | Topic for publishing stock events |
| `PUBSUB_SUBSCRIPTION_ORDER_CREATED` | `projects/.../subscriptions/inventory-order-created-sub` | |
| `PUBSUB_SUBSCRIPTION_FULFILLMENT_COMPLETED` | `projects/.../subscriptions/inventory-fulfillment-completed-sub` | |
| `SERVICE_VERSION` | `1.0.0` | Appears in OpenAPI metadata |
| `LOG_LEVEL` | `INFO` | Python log level |
| `RATE_LIMIT_REQUESTS` | `200` | Requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window |

### Order Service

| Variable | Description |
|---|---|
| `DATABASE_URL` | Cloud SQL order_db connection |
| `REDIS_URL` | Memorystore Redis URL |
| `INVENTORY_SERVICE_URL` | Internal URL of Inventory Cloud Run service |
| `PUBSUB_TOPIC_ORDER_EVENTS` | Topic for publishing order.created |
| `PUBSUB_SUBSCRIPTION_FULFILLMENT_ASSIGNED` | |
| `PUBSUB_SUBSCRIPTION_FULFILLMENT_COMPLETED` | |

### Fulfillment Service

| Variable | Description |
|---|---|
| `DATABASE_URL` | Cloud SQL fulfillment_db connection |
| `REDIS_URL` | Memorystore Redis URL |
| `PUBSUB_SUBSCRIPTION_ORDER_CREATED` | |
| `PUBSUB_TOPIC_FULFILLMENT_EVENTS` | Topic for publishing fulfillment.assigned / fulfillment.completed |
