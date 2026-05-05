# =============================================================================
# Input Variables
# =============================================================================

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Primary GCP region for all resources."
  type        = string
  default     = "me-central1"
}

variable "image_tag" {
  description = "Docker image tag to deploy to Cloud Run (e.g. 'v1.2.3' or git SHA)."
  type        = string
  default     = "latest"
}

variable "environment" {
  description = "Deployment environment: dev | staging | prod."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "min_instance_count" {
  description = "Minimum Cloud Run instance count per service (0 = scale to zero)."
  type        = number
  default     = 0
}

variable "max_instance_count" {
  description = "Maximum Cloud Run instance count per service."
  type        = number
  default     = 10
}

variable "notification_channels" {
  description = "Cloud Monitoring notification channel IDs for alert policies (e.g. email, PagerDuty)."
  type        = list(string)
  default     = []
}
