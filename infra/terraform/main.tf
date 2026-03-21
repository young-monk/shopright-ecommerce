terraform {
  required_version = ">= 1.7"
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

resource "google_vpc_access_connector" "connector" {
  name   = "shopright-connector"
  region = var.region
  subnet {
    name = google_compute_subnetwork.subnet.name
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
      resources {
        limits = { cpu = "2", memory = "2Gi" }
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
        name  = "NEXT_PUBLIC_API_URL"
        value = google_cloud_run_v2_service.api_gateway.uri
      }
      env {
        name  = "NEXT_PUBLIC_CHATBOT_URL"
        value = google_cloud_run_v2_service.chatbot.uri
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
    { name = "session_id",         type = "STRING",    mode = "REQUIRED" },
    { name = "message_id",         type = "STRING",    mode = "REQUIRED" },
    { name = "timestamp",          type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "user_message",       type = "STRING",    mode = "REQUIRED" },
    { name = "assistant_response", type = "STRING",    mode = "REQUIRED" },
    { name = "sources_used",       type = "STRING",    mode = "NULLABLE" },
    { name = "message_length",     type = "INTEGER",   mode = "NULLABLE" },
    { name = "response_length",    type = "INTEGER",   mode = "NULLABLE" },
    { name = "sources_count",      type = "INTEGER",   mode = "NULLABLE" },
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
