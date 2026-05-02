# =============================================================================
# SupplyChainForge — Terraform Root Module
# =============================================================================
# Provisions all GCP infrastructure for the SupplyChainForge platform:
#   - Networking (VPC, subnets, VPC Access Connector for Cloud Run)
#   - Cloud SQL (MySQL 8.0, private IP, per-service databases & users)
#   - Memorystore Redis (single-node, private IP)
#   - Cloud Pub/Sub (topics, subscriptions, DLQ topics)
#   - Artifact Registry (Docker image hosting)
#   - Cloud Run services (inventory, order, fulfillment)
#   - IAM (service accounts, roles, bindings)
#   - Secret Manager (DB passwords, service URLs)
#
# Prerequisites:
#   1. terraform init
#   2. gcloud auth application-default login
#   3. Enable required APIs (see apis.tf or run bootstrap/enable_apis.sh)
#
# Usage:
#   terraform plan -var-file=environments/prod.tfvars
#   terraform apply -var-file=environments/prod.tfvars
# =============================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state — uncomment and configure for production
  # backend "gcs" {
  #   bucket = "scf-tfstate"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ── Random suffix for globally unique resource names ─────────────────────────
resource "random_id" "suffix" {
  byte_length = 4
}

# ── Modules ───────────────────────────────────────────────────────────────────

module "networking" {
  source     = "./modules/networking"
  project_id = var.project_id
  region     = var.region
  suffix     = random_id.suffix.hex
}

module "iam" {
  source     = "./modules/iam"
  project_id = var.project_id
  region     = var.region
}

module "secret_manager" {
  source     = "./modules/secret_manager"
  project_id = var.project_id
  region     = var.region
  depends_on = [module.iam]
}

module "cloud_sql" {
  source              = "./modules/cloud_sql"
  project_id          = var.project_id
  region              = var.region
  suffix              = random_id.suffix.hex
  network_id          = module.networking.vpc_id
  private_ip_address  = module.networking.sql_private_ip_range_name
  db_root_password    = module.secret_manager.db_root_password
  depends_on          = [module.networking, module.secret_manager]
}

module "memorystore" {
  source         = "./modules/memorystore"
  project_id     = var.project_id
  region         = var.region
  suffix         = random_id.suffix.hex
  network_id     = module.networking.vpc_id
  depends_on     = [module.networking]
}

module "pubsub" {
  source     = "./modules/pubsub"
  project_id = var.project_id
  depends_on = [module.iam]
}

module "artifact_registry" {
  source     = "./modules/artifact_registry"
  project_id = var.project_id
  region     = var.region
  suffix     = random_id.suffix.hex
}

module "cloud_run" {
  source                       = "./modules/cloud_run"
  project_id                   = var.project_id
  region                       = var.region
  image_tag                    = var.image_tag
  registry_url                 = module.artifact_registry.registry_url
  vpc_connector_id             = module.networking.vpc_connector_id
  cloud_run_sa_email           = module.iam.cloud_run_sa_email
  redis_host                   = module.memorystore.redis_host
  redis_port                   = module.memorystore.redis_port
  cloud_sql_connection_name    = module.cloud_sql.connection_name
  inventory_db_secret          = module.secret_manager.inventory_db_secret_id
  order_db_secret              = module.secret_manager.order_db_secret_id
  fulfillment_db_secret        = module.secret_manager.fulfillment_db_secret_id
  depends_on                   = [
    module.cloud_sql,
    module.memorystore,
    module.pubsub,
    module.artifact_registry,
    module.iam,
  ]
}
