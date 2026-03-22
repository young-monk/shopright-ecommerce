# ShopRight — AI-Powered Ecommerce Platform

A HomeDepot-style ecommerce platform with an AI chatbot (Gemini LLM + RAG), real-time analytics dashboard, and full GCP deployment via Terraform.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│  Next.js Frontend (Cloud Run :3000)                          │
│    ├── /api-proxy/*         → API Gateway                    │
│    ├── /chatbot-proxy/*     → Chatbot Service                │
│    └── /analytics-proxy/*   → Analytics Service              │
└──────────────────┬───────────────────────────────────────────┘
                   │
   ┌───────────────┼────────────────────┐
   ▼               ▼                    ▼
API Gateway     Chatbot             Analytics
(port 8000)     (port 8004)         (port 8005)
   │            Gemini 2.5-flash    BigQuery queries
   ├── Product   RAG + pgvector
   ├── Order     SSE streaming
   └── User
         │
    Cloud SQL (PostgreSQL 15 + pgvector)
```

## Services

| Service | Path | Port | Stack |
|---|---|---|---|
| Frontend | `frontend/` | 3000 | Next.js 14, TypeScript, Tailwind, Recharts |
| API Gateway | `backend/api-gateway/` | 8000 | FastAPI, httpx |
| Product Service | `backend/product-service/` | 8001 | FastAPI, SQLAlchemy, asyncpg |
| Order Service | `backend/order-service/` | 8002 | FastAPI, SQLAlchemy, asyncpg |
| User Service | `backend/user-service/` | 8003 | FastAPI, JWT, bcrypt |
| Chatbot | `ai/chatbot/` | 8004 | FastAPI, Gemini API, sentence-transformers, pgvector |
| Analytics | `ai/analytics/` | 8005 | FastAPI, google-cloud-bigquery |

---

## AI Features

### Chatbot (RAG + Gemini)
- **LLM**: Gemini 2.5-flash with 1M context window
- **Embeddings**: `multi-qa-mpnet-base-dot-v1` (768-dim, runs locally on CPU, ~10-20ms)
- **Vector store**: pgvector with IVFFlat index
- **Retrieval**: Hybrid vector + keyword search across 11 product categories
- **Query rewriting**: Resolves follow-up questions using conversation history
- **Streaming**: Server-Sent Events for real-time token delivery
- **Source filtering**: Product recommendation chips only show items Gemini explicitly named in its response
- **Fine-tuning pipeline**: `ai/chatbot/finetune/` — Gemini generates per-product training queries, model fine-tuned with MultipleNegativesRankingLoss

### Analytics Dashboard (`/metrics`)

Three-tab dashboard backed by BigQuery live queries:

| Tab | Metrics |
|---|---|
| **Infra** | Request volume, error rate, p50/p95 latency |
| **Model** | LLM cost trend, unanswered rate, RAG confidence, catalog gaps by category |
| **Business** | Star ratings trend, thumbs up/down ratio, chip-click conversions, top clicked products |

BigQuery tables: `chat_logs` (51 columns, daily partitioned), `feedback`, `chat_events`, `session_reviews`

---

## GCP Infrastructure

All resources provisioned via Terraform (`infra/terraform/`):

| GCP Service | Usage |
|---|---|
| **Cloud Run** | All 7 services — auto-scaling, private VPC networking |
| **Cloud SQL** | PostgreSQL 15 + pgvector extension, private IP, PITR backups |
| **BigQuery** | Chat analytics, daily partitioned tables |
| **Artifact Registry** | Docker image storage |
| **Cloud Storage** | Product images and static assets |
| **Secret Manager** | JWT secret, DB password |
| **VPC + VPC Connector** | Private Cloud Run → Cloud SQL connectivity |
| **Workload Identity** | Keyless GitHub Actions → GCP authentication |

---

## Local Development

### Prerequisites
- Docker & Docker Compose
- Node.js 20+, Python 3.11+
- A `GEMINI_API_KEY` (required for chatbot responses)

### Start everything

```bash
git clone https://github.com/young-monk/shopright-ecommerce.git
cd shopright-ecommerce

cp .env.example .env   # set GEMINI_API_KEY at minimum

docker compose up
```

| URL | Service |
|---|---|
| http://localhost:3000 | Frontend storefront |
| http://localhost:8000/docs | API Gateway (Swagger) |
| http://localhost:8004/docs | Chatbot |
| http://localhost:8005/docs | Analytics |

### Run a single service

```bash
# Frontend
cd frontend && npm install && npm run dev

# Any backend service
cd backend/product-service
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

---

## Deployment

### 1. Set GitHub secrets

```
WIF_PROVIDER          # Workload Identity provider resource name
WIF_SERVICE_ACCOUNT   # shopright-github-actions@PROJECT_ID.iam.gserviceaccount.com
GCP_PROJECT_ID
DB_PASSWORD
JWT_SECRET
GEMINI_API_KEY
```

### 2. First-time Terraform deploy

```bash
cd infra/terraform

# Edit prod.tfvars with your project_id
terraform init
terraform plan  -var-file="prod.tfvars" \
                -var="db_password=..." \
                -var="jwt_secret=..." \
                -var="gemini_api_key=..."
terraform apply -var-file="prod.tfvars" ...
```

### 3. Subsequent deploys — just push to `main`

| Workflow | Trigger | What it does |
|---|---|---|
| **CI** | Push / PR to main | Lint, typecheck, pytest for all 7 services |
| **Deploy** | Push to main | Docker build → Artifact Registry → Cloud Run rolling update |
| **Terraform** | Push to main touching `infra/terraform/**` | Plan + apply GCP infrastructure |

---

## Project Structure

```
shopright-ecommerce/
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── api-proxy/        # Runtime proxy → API Gateway
│       │   ├── chatbot-proxy/    # Runtime proxy → Chatbot
│       │   ├── analytics-proxy/  # Runtime proxy → Analytics
│       │   └── metrics/          # Analytics dashboard page
│       ├── components/
│       │   └── chatbot/          # ChatbotWidget (SSE streaming, chips, ratings)
│       └── lib/api.ts
│
├── backend/
│   ├── api-gateway/              # CORS, routing
│   ├── product-service/          # Catalog CRUD, search, filtering
│   ├── order-service/            # Cart, checkout, orders
│   └── user-service/             # Auth, JWT, profiles
│
├── ai/
│   ├── chatbot/
│   │   ├── main.py               # Gemini + RAG + SSE streaming
│   │   └── finetune/             # Embedding fine-tune pipeline
│   └── analytics/
│       └── main.py               # BigQuery analytics endpoints
│
├── infra/
│   ├── terraform/                # All GCP resources
│   └── sql/                      # Schema + seed data
│
└── .github/workflows/
    ├── ci.yml
    ├── deploy.yml
    └── terraform.yml
```

---

## Environment Variables

| Variable | Where | Description |
|---|---|---|
| `GEMINI_API_KEY` | Local + Cloud | Google Gemini API key |
| `DATABASE_URL` | Local + Cloud | PostgreSQL connection string |
| `JWT_SECRET` | Local + Cloud | JWT signing secret |
| `GCP_PROJECT_ID` | Cloud | GCP project for BigQuery / Vertex AI |
| `API_GATEWAY_URL` | Cloud | Internal Cloud Run service URL |
| `CHATBOT_SERVICE_URL` | Cloud | Internal Cloud Run service URL |
| `ANALYTICS_SERVICE_URL` | Cloud | Internal Cloud Run service URL |

Copy `.env.example` to `.env` for local development — only `GEMINI_API_KEY` is required to get the chatbot working.
