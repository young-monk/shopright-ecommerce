# ShopRight - HomeDepot-Style Ecommerce Platform

A full-stack ecommerce platform with AI-powered chatbot (LLM + RAG) and chat analytics, deployed on Google Cloud Platform.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        GitHub Repo                          │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│ frontend │ backend  │   ai/    │  infra/  │   .github/     │
│ Next.js  │ FastAPI  │ chatbot  │Terraform │  workflows     │
│          │ services │ analytics│          │                │
└──────────┴──────────┴──────────┴──────────┴────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Cloud Run       Cloud SQL       Vertex AI
         (services)     (PostgreSQL)   (Gemini+Embed)
              │               │               │
         Cloud Storage   BigQuery        Vector Search
         (assets)       (analytics)     (RAG index)
```

## Services

| Service | Path | Port | Description |
|---------|------|------|-------------|
| Frontend | `frontend/` | 3000 | Next.js storefront |
| API Gateway | `backend/api-gateway/` | 8000 | Entry point, auth, routing |
| Product Service | `backend/product-service/` | 8001 | Product catalog CRUD |
| Order Service | `backend/order-service/` | 8002 | Orders, cart, checkout |
| User Service | `backend/user-service/` | 8003 | Auth, profiles |
| Chatbot Service | `ai/chatbot/` | 8004 | LLM+RAG chat |
| Analytics Service | `ai/analytics/` | 8005 | Chat log analysis |

## Quick Start

### Prerequisites
- Node.js 20+, Python 3.11+, Docker, Terraform 1.7+
- GCP project with billing enabled
- `gcloud` CLI authenticated

### Local Development
```bash
# Clone and setup
git clone https://github.com/YOUR_ORG/ecommerce-platform.git
cd ecommerce-platform
cp .env.example .env  # fill in values

# Start all services
docker compose up

# Frontend only
cd frontend && npm install && npm run dev

# A specific backend service
cd backend/product-service && pip install -r requirements.txt && uvicorn main:app --reload --port 8001
```

### GCP Deployment
```bash
cd infra/terraform
terraform init
terraform plan -var-file="prod.tfvars"
terraform apply -var-file="prod.tfvars"
```

## GCP Services Used
- **Cloud Run** - All containerized microservices
- **Cloud SQL (PostgreSQL 15)** - Product, order, user data + pgvector for RAG
- **Vertex AI** - Gemini 1.5 Pro (LLM) + text-embedding-004 (embeddings)
- **BigQuery** - Chat log storage and analytics
- **Cloud Storage** - Product images, static assets
- **Artifact Registry** - Docker images
- **Secret Manager** - API keys, DB passwords
- **Cloud CDN + Load Balancer** - Global distribution
- **Firebase Authentication** - User auth
- **Pub/Sub** - Event streaming between services
