# =============================================================================
# Artifact Registry Module — Docker image hosting
# =============================================================================

variable "project_id" { type = string }
variable "region"     { type = string }
variable "suffix"     { type = string }

resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "scf-services-${var.suffix}"
  description   = "SupplyChainForge Docker images"
  format        = "DOCKER"
  project       = var.project_id

  cleanup_policies {
    id     = "keep-recent-10"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
}

output "registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}
