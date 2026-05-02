# =============================================================================
# Networking Module — VPC, Subnets, Private IP range, VPC Connector
# =============================================================================

variable "project_id" { type = string }
variable "region"     { type = string }
variable "suffix"     { type = string }

# ── VPC ───────────────────────────────────────────────────────────────────────
resource "google_compute_network" "vpc" {
  name                    = "scf-vpc-${var.suffix}"
  auto_create_subnetworks = false
  project                 = var.project_id
}

# ── Subnet ────────────────────────────────────────────────────────────────────
resource "google_compute_subnetwork" "main" {
  name          = "scf-subnet-${var.region}-${var.suffix}"
  ip_cidr_range = "10.10.0.0/20"
  region        = var.region
  network       = google_compute_network.vpc.id
  project       = var.project_id

  private_ip_google_access = true
}

# ── Private IP address range for Cloud SQL / Memorystore ─────────────────────
resource "google_compute_global_address" "private_ip_range" {
  name          = "scf-private-ip-${var.suffix}"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
  project       = var.project_id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

# ── VPC Serverless Access Connector (Cloud Run → private VPC) ─────────────────
resource "google_vpc_access_connector" "connector" {
  name          = "scf-connector-${var.suffix}"
  region        = var.region
  project       = var.project_id
  ip_cidr_range = "10.9.0.0/28"
  network       = google_compute_network.vpc.name
  min_throughput = 200
  max_throughput = 1000
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "vpc_id"                    { value = google_compute_network.vpc.id }
output "subnet_id"                 { value = google_compute_subnetwork.main.id }
output "vpc_connector_id"          { value = google_vpc_access_connector.connector.id }
output "sql_private_ip_range_name" { value = google_compute_global_address.private_ip_range.name }
