# =============================================================================
# Outputs — useful values from the provisioned infrastructure
# =============================================================================

output "inventory_service_url" {
  description = "Cloud Run URL for the Inventory Service."
  value       = module.cloud_run.inventory_url
}

output "order_service_url" {
  description = "Cloud Run URL for the Order Service."
  value       = module.cloud_run.order_url
}

output "fulfillment_service_url" {
  description = "Cloud Run URL for the Fulfillment Service."
  value       = module.cloud_run.fulfillment_url
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name (host:region:instance)."
  value       = module.cloud_sql.connection_name
}

output "redis_host" {
  description = "Memorystore Redis host (private IP)."
  value       = module.memorystore.redis_host
  sensitive   = true
}

output "artifact_registry_url" {
  description = "Artifact Registry Docker repository URL."
  value       = module.artifact_registry.registry_url
}

output "pubsub_topics" {
  description = "Map of Pub/Sub topic names to their full resource IDs."
  value       = module.pubsub.topic_ids
}
