terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    bucket = "shopright-tf-state"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "project" {}

# ── Enable APIs ───────────────────────────────────────────────────────────────
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sql-component.googleapis.com",
    "sqladmin.googleapis.com",
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# ── VPC ───────────────────────────────────────────────────────────────────────
resource "google_compute_network" "vpc" {
  name                    = "shopright-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "subnet" {
  name          = "shopright-subnet"
  ip_cidr_range = "10.0.0.0/24"
  region        = var.region
  network       = google_compute_network.vpc.id
}

# VPC connectors require a dedicated /28 subnet
resource "google_compute_subnetwork" "connector_subnet" {
  name          = "shopright-connector-subnet"
  ip_cidr_range = "10.8.0.0/28"
  region        = var.region
  network       = google_compute_network.vpc.id
}

resource "google_vpc_access_connector" "connector" {
  name   = "shopright-connector"
  region = var.region
  subnet {
    name = google_compute_subnetwork.connector_subnet.name
  }
  machine_type = "f1-micro"
}

# ── Private Services Access (required for Cloud SQL private IP) ───────────────
resource "google_compute_global_address" "private_ip_range" {
  name          = "shopright-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
  depends_on    = [google_project_service.apis]
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

# ── Cloud SQL (PostgreSQL + pgvector) ─────────────────────────────────────────
resource "google_sql_database_instance" "postgres" {
  name             = "shopright-postgres"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.db_tier
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
  }
  deletion_protection = var.environment == "prod"
  depends_on = [
    google_project_service.apis,
    google_service_networking_connection.private_vpc_connection,
  ]
}

resource "google_sql_database" "shopright" {
  name     = "shopright"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "shopright" {
  name     = "shopright"
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}

# ── Artifact Registry ─────────────────────────────────────────────────────────
resource "google_artifact_registry_repository" "shopright" {
  location      = var.region
  repository_id = "shopright"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ── Cloud Run: Product Service ─────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "product_service" {
  name     = "product-service"
  location = var.region

  template {
    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/shopright/product-service:latest"
      ports { container_port = 8001 }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+asyncpg://shopright:${var.db_password}@/shopright?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "product_public" {
  service  = google_cloud_run_v2_service.product_service.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Cloud Run: Order Service ───────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "order_service" {
  name     = "order-service"
  location = var.region

  template {
    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/shopright/order-service:latest"
      ports { container_port = 8002 }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+asyncpg://shopright:${var.db_password}@/shopright?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "order_public" {
  service  = google_cloud_run_v2_service.order_service.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Cloud Run: User Service ────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "user_service" {
  name     = "user-service"
  location = var.region

  template {
    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/shopright/user-service:latest"
      ports { container_port = 8003 }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+asyncpg://shopright:${var.db_password}@/shopright?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret.secret_id
            version = "latest"
          }
        }
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "user_public" {
  service  = google_cloud_run_v2_service.user_service.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Cloud Run: Chatbot Service ─────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "chatbot" {
  name     = "chatbot-service"
  location = var.region

  template {
    service_account = google_service_account.chatbot_sa.email
    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/shopright/chatbot:latest"
      ports { container_port = 8004 }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "VERTEX_AI_LOCATION"
        value = var.region
      }
      env {
        name  = "BIGQUERY_DATASET"
        value = "chat_analytics"
      }
      env {
        name  = "DATABASE_URL"
        value = "postgresql://shopright:${var.db_password}@/shopright?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
      }
      env {
        name  = "GEMINI_API_KEY"
        value = var.gemini_api_key
      }
      resources {
        limits = { cpu = "2", memory = "2Gi" }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "chatbot_public" {
  service  = google_cloud_run_v2_service.chatbot.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Cloud Run: Frontend ────────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "frontend" {
  name     = "frontend"
  location = var.region

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/shopright/frontend:latest"
      ports { container_port = 3000 }
      env {
        name  = "API_GATEWAY_URL"
        value = google_cloud_run_v2_service.api_gateway.uri
      }
      env {
        name  = "CHATBOT_SERVICE_URL"
        value = google_cloud_run_v2_service.chatbot.uri
      }
      env {
        name  = "ANALYTICS_SERVICE_URL"
        value = google_cloud_run_v2_service.analytics.uri
      }
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "frontend_public" {
  service  = google_cloud_run_v2_service.frontend.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Cloud Run: API Gateway ─────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "api_gateway" {
  name     = "api-gateway"
  location = var.region

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/shopright/api-gateway:latest"
      ports { container_port = 8000 }
      env {
        name  = "PRODUCT_SERVICE_URL"
        value = google_cloud_run_v2_service.product_service.uri
      }
      env {
        name  = "ORDER_SERVICE_URL"
        value = google_cloud_run_v2_service.order_service.uri
      }
      env {
        name  = "USER_SERVICE_URL"
        value = google_cloud_run_v2_service.user_service.uri
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "gateway_public" {
  service  = google_cloud_run_v2_service.api_gateway.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── BigQuery ───────────────────────────────────────────────────────────────────
resource "google_bigquery_dataset" "chat_analytics" {
  dataset_id  = "chat_analytics"
  location    = "US"
  description = "ShopRight chat log analytics"
  depends_on  = [google_project_service.apis]
}

resource "google_bigquery_table" "chat_logs" {
  dataset_id = google_bigquery_dataset.chat_analytics.dataset_id
  table_id   = "chat_logs"

  schema = jsonencode([
    # Core identifiers
    { name = "session_id", type = "STRING", mode = "REQUIRED" },
    { name = "message_id", type = "STRING", mode = "REQUIRED" },
    { name = "timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    # Message content
    { name = "user_message", type = "STRING", mode = "REQUIRED" },
    { name = "assistant_response", type = "STRING", mode = "REQUIRED" },
    { name = "sources_used", type = "STRING", mode = "NULLABLE" },
    { name = "message_length", type = "INTEGER", mode = "NULLABLE" },
    { name = "response_length", type = "INTEGER", mode = "NULLABLE" },
    # Performance
    { name = "latency_ms", type = "INTEGER", mode = "NULLABLE" },
    { name = "embed_ms", type = "INTEGER", mode = "NULLABLE" },
    { name = "db_ms", type = "INTEGER", mode = "NULLABLE" },
    { name = "rag_ms", type = "INTEGER", mode = "NULLABLE" },
    { name = "llm_ms", type = "INTEGER", mode = "NULLABLE" },
    { name = "ttft_ms", type = "INTEGER", mode = "NULLABLE" },
    { name = "embed_model", type = "STRING", mode = "NULLABLE" },
    # LLM
    { name = "tokens_in", type = "INTEGER", mode = "NULLABLE" },
    { name = "tokens_out", type = "INTEGER", mode = "NULLABLE" },
    { name = "estimated_cost_usd", type = "FLOAT", mode = "NULLABLE" },
    { name = "llm_error", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "llm_error_type", type = "STRING", mode = "NULLABLE" },
    # RAG
    { name = "sources_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "rag_confidence", type = "FLOAT", mode = "NULLABLE" },
    { name = "rag_empty", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "detected_category", type = "STRING", mode = "NULLABLE" },
    { name = "price_filter_used", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "price_filter_value", type = "FLOAT", mode = "NULLABLE" },
    { name = "query_rewritten", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "dedup_removed_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "unique_brands_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "unique_categories_count", type = "INTEGER", mode = "NULLABLE" },
    # Quality signals
    { name = "is_unanswered", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "hallucination_flag", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "wellbeing_triggered", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "context_pct", type = "FLOAT", mode = "NULLABLE" },
    # Conversation
    { name = "turn_number", type = "INTEGER", mode = "NULLABLE" },
    { name = "session_started_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "scope_rejected", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "rerank_used", type = "BOOLEAN", mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }
}

resource "google_bigquery_table" "feedback" {
  dataset_id = google_bigquery_dataset.chat_analytics.dataset_id
  table_id   = "feedback"

  schema = jsonencode([
    { name = "message_id", type = "STRING", mode = "REQUIRED" },
    { name = "session_id", type = "STRING", mode = "REQUIRED" },
    { name = "timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "rating", type = "INTEGER", mode = "REQUIRED" },
    { name = "user_message", type = "STRING", mode = "NULLABLE" },
    { name = "assistant_response", type = "STRING", mode = "NULLABLE" },
    { name = "turn_number", type = "INTEGER", mode = "NULLABLE" },
    { name = "detected_category", type = "STRING", mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }
}

resource "google_bigquery_table" "chat_events" {
  dataset_id = google_bigquery_dataset.chat_analytics.dataset_id
  table_id   = "chat_events"

  schema = jsonencode([
    { name = "event_type", type = "STRING", mode = "REQUIRED" },
    { name = "session_id", type = "STRING", mode = "REQUIRED" },
    { name = "timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "message_id", type = "STRING", mode = "NULLABLE" },
    { name = "product_id", type = "STRING", mode = "NULLABLE" },
    { name = "product_name", type = "STRING", mode = "NULLABLE" },
    { name = "product_price", type = "FLOAT", mode = "NULLABLE" },
    { name = "product_category", type = "STRING", mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }
}

resource "google_bigquery_table" "session_reviews" {
  dataset_id = google_bigquery_dataset.chat_analytics.dataset_id
  table_id   = "session_reviews"

  schema = jsonencode([
    { name = "session_id", type = "STRING", mode = "REQUIRED" },
    { name = "timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "stars", type = "INTEGER", mode = "REQUIRED" },
    { name = "turn_count", type = "INTEGER", mode = "NULLABLE" },
    { name = "unanswered_count", type = "INTEGER", mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }
}

# ── Cloud Storage ──────────────────────────────────────────────────────────────
resource "google_storage_bucket" "assets" {
  name          = "${var.project_id}-shopright-assets"
  location      = "US"
  force_destroy = var.environment != "prod"

  uniform_bucket_level_access = true
  cors {
    origin          = ["*"]
    method          = ["GET", "HEAD"]
    response_header = ["Content-Type"]
    max_age_seconds = 3600
  }
  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "assets_public" {
  bucket = google_storage_bucket.assets.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# ── Cloud Run: Analytics Service ──────────────────────────────────────────────
resource "google_service_account" "analytics_sa" {
  account_id   = "shopright-analytics"
  display_name = "ShopRight Analytics Service Account"
}

resource "google_project_iam_member" "analytics_bigquery" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.analytics_sa.email}"
}

resource "google_project_iam_member" "analytics_bigquery_job" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.analytics_sa.email}"
}

resource "google_cloud_run_v2_service" "analytics" {
  name     = "analytics"
  location = var.region

  template {
    service_account = google_service_account.analytics_sa.email
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/shopright/analytics:latest"
      ports { container_port = 8005 }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BIGQUERY_DATASET"
        value = "chat_analytics"
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "analytics_public" {
  service  = google_cloud_run_v2_service.analytics.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Service Account for Chatbot ───────────────────────────────────────────────
resource "google_service_account" "chatbot_sa" {
  account_id   = "shopright-chatbot"
  display_name = "ShopRight Chatbot Service Account"
}

resource "google_project_iam_member" "chatbot_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.chatbot_sa.email}"
}

resource "google_project_iam_member" "chatbot_bigquery" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.chatbot_sa.email}"
}

# ── Secret Manager ────────────────────────────────────────────────────────────
resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "jwt-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "jwt_secret_v1" {
  secret      = google_secret_manager_secret.jwt_secret.id
  secret_data = var.jwt_secret
}

# Grant Cloud Run default SA access to read secrets
resource "google_project_iam_member" "compute_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# Grant Cloud Run default SA access to connect to Cloud SQL
resource "google_project_iam_member" "compute_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# ── Monitoring & Alerting ──────────────────────────────────────────────────────

# Email notification channel (only created when alert_email is provided)
resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "ShopRight Alerts Email"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.apis]
}

locals {
  notification_channels = var.alert_email != "" ? [google_monitoring_notification_channel.email[0].name] : []
  # Cloud Run resource filter shared across alert policies
  chatbot_filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"chatbot-service\""
  sql_filter     = "resource.type=\"cloudsql_database\""
}

# ── Alert: chatbot 5xx error rate > 1% ───────────────────────────────────────
resource "google_monitoring_alert_policy" "chatbot_5xx" {
  display_name = "Chatbot 5xx Error Rate > 1%"
  combiner     = "OR"
  depends_on   = [google_project_service.apis]

  conditions {
    display_name = "5xx rate above threshold"
    condition_threshold {
      filter          = "${local.chatbot_filter} AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.01
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_MEAN"
        group_by_fields      = ["resource.labels.service_name"]
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy { auto_close = "1800s" }
}

# ── Alert: chatbot p95 latency > 10s ─────────────────────────────────────────
resource "google_monitoring_alert_policy" "chatbot_latency" {
  display_name = "Chatbot p95 Latency > 10s"
  combiner     = "OR"
  depends_on   = [google_project_service.apis]

  conditions {
    display_name = "p95 latency above 10s"
    condition_threshold {
      filter          = "${local.chatbot_filter} AND metric.type=\"run.googleapis.com/request_latencies\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 10000  # milliseconds
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_99"
        cross_series_reducer = "REDUCE_MEAN"
        group_by_fields      = ["resource.labels.service_name"]
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy { auto_close = "1800s" }
}

# ── Alert: Cloud SQL CPU > 80% ────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "sql_cpu" {
  display_name = "Cloud SQL CPU Utilization > 80%"
  combiner     = "OR"
  depends_on   = [google_project_service.apis]

  conditions {
    display_name = "SQL CPU above 80%"
    condition_threshold {
      filter          = "${local.sql_filter} AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
      duration        = "600s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy { auto_close = "1800s" }
}

# ── Alert: Cloud SQL connections > 80 ────────────────────────────────────────
resource "google_monitoring_alert_policy" "sql_connections" {
  display_name = "Cloud SQL Connections > 80"
  combiner     = "OR"
  depends_on   = [google_project_service.apis]

  conditions {
    display_name = "Connection count above 80"
    condition_threshold {
      filter          = "${local.sql_filter} AND metric.type=\"cloudsql.googleapis.com/database/postgresql/num_backends\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 80
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy { auto_close = "1800s" }
}

# ── Log-based metric: BigQuery insert errors ──────────────────────────────────
resource "google_logging_metric" "bq_insert_errors" {
  name        = "chatbot/bq_insert_errors"
  description = "Count of BigQuery insert errors logged by the chatbot service"
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"chatbot-service\" AND textPayload=~\"BigQuery insert errors\""
  depends_on  = [google_project_service.apis]

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# ── Alert: BQ insert errors ───────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "bq_insert_errors" {
  display_name = "Chatbot BQ Insert Errors"
  combiner     = "OR"
  depends_on   = [google_logging_metric.bq_insert_errors, google_project_service.apis]

  conditions {
    display_name = "BQ insert error count > 0"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/chatbot/bq_insert_errors\" AND resource.type=\"cloud_run_revision\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = local.notification_channels
  alert_strategy { auto_close = "3600s" }
}

# ── Dashboard ─────────────────────────────────────────────────────────────────
resource "google_monitoring_dashboard" "shopright" {
  dashboard_json = jsonencode({
    displayName = "ShopRight Operations"
    mosaicLayout = {
      columns = 12
      tiles = [
        # Row 1: Cloud Run request rate + 5xx rate
        {
          width = 6, height = 4, xPos = 0, yPos = 0
          widget = {
            title = "Chatbot Request Rate"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "${local.chatbot_filter} AND metric.type=\"run.googleapis.com/request_count\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields = ["metric.labels.response_code_class"]
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 6, height = 4, xPos = 6, yPos = 0
          widget = {
            title = "Chatbot p95 Latency (ms)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "${local.chatbot_filter} AND metric.type=\"run.googleapis.com/request_latencies\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_PERCENTILE_95"
                      crossSeriesReducer = "REDUCE_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 2: Instance count + memory
        {
          width = 6, height = 4, xPos = 0, yPos = 4
          widget = {
            title = "Chatbot Instance Count"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "${local.chatbot_filter} AND metric.type=\"run.googleapis.com/container/instance_count\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MAX"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 6, height = 4, xPos = 6, yPos = 4
          widget = {
            title = "Chatbot Memory Utilization"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "${local.chatbot_filter} AND metric.type=\"run.googleapis.com/container/memory/utilizations\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_PERCENTILE_95"
                      crossSeriesReducer = "REDUCE_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 3: Cloud SQL CPU + connections
        {
          width = 6, height = 4, xPos = 0, yPos = 8
          widget = {
            title = "Cloud SQL CPU Utilization"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "${local.sql_filter} AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 6, height = 4, xPos = 6, yPos = 8
          widget = {
            title = "Cloud SQL Active Connections"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "${local.sql_filter} AND metric.type=\"cloudsql.googleapis.com/database/postgresql/num_backends\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        # Row 4: BQ insert errors + Cloud SQL memory
        {
          width = 6, height = 4, xPos = 0, yPos = 12
          widget = {
            title = "BQ Insert Errors"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/chatbot/bq_insert_errors\" AND resource.type=\"cloud_run_revision\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        },
        {
          width = 6, height = 4, xPos = 6, yPos = 12
          widget = {
            title = "Cloud SQL Memory Utilization"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "${local.sql_filter} AND metric.type=\"cloudsql.googleapis.com/database/memory/utilization\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_MEAN"
                    }
                  }
                }
                plotType = "LINE"
              }]
            }
          }
        }
      ]
    }
  })
  depends_on = [google_project_service.apis]
}
