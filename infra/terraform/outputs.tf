output "frontend_url" {
  value       = google_cloud_run_v2_service.frontend.uri
  description = "Frontend URL"
}

output "api_gateway_url" {
  value       = google_cloud_run_v2_service.api_gateway.uri
  description = "API Gateway URL"
}

output "chatbot_url" {
  value       = google_cloud_run_v2_service.chatbot.uri
  description = "Chatbot service URL"
}

output "postgres_connection" {
  value       = google_sql_database_instance.postgres.connection_name
  description = "Cloud SQL connection name"
  sensitive   = true
}

output "assets_bucket" {
  value       = google_storage_bucket.assets.name
  description = "GCS assets bucket name"
}
