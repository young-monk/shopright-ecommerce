# ShopRight — AI Chatbot & Analytics Platform

A home improvement e-commerce platform built to demonstrate production-grade AI: a RAG-powered chatbot with deep observability, a multi-agent analytics system, and full GCP deployment via Terraform and GitHub Actions.

**Live URLs**
- Store: https://shopright-store.web.app
- Analytics Dashboard: https://shopright-dash.web.app

---

## Architecture Overview

```
User Browser
    │
    ▼
Firebase Hosting (shopright-store.web.app)
    │  Cloud Run rewrite
    ▼
Frontend (Next.js) ──────────────────────────────────────────┐
    │                                               chip-click │
    │  POST /stream                                  events    │
    ▼                                                          │
API Gateway (FastAPI)                                          │
    │                                                          │
    ▼                                                          │
Chatbot Service (FastAPI + Google ADK)                         │
    ├── Safety detection layer (regex, rules)                  │
    ├── Google ADK LlmAgent + Runner                           │
    │       └── search_products tool                           │
    │               ├── Gemini text-embedding-004 (3072-dim)   │
    │               ├── pgvector ANN (Cloud SQL PostgreSQL)    │
    │               └── Vertex AI Ranking API (rerank)        │
    ├── Gemini 2.5-flash (generation + intent classification)  │
    ├── OpenTelemetry → Cloud Trace (4 named spans)            │
    ├── Exponential backoff retry (ResourceExhausted 429)      │
    └── BigQuery async logging (fire-and-forget) ◄─────────── ┘
                    │
                    ▼
        BigQuery — chat_analytics dataset
        (chat_logs · feedback · chat_events · session_reviews)
                    │
                    ▼
     Analytics Service (FastAPI + Google ADK)
          ├── Orchestrator agent (Gemini)
          │       ├── DevOps sub-agent  → infra health reports
          │       ├── Tech sub-agent    → ML/RAG performance reports
          │       └── Business sub-agent → satisfaction/conversion reports
          ├── MCP Toolbox sidecar (45 named BigQuery queries)
          └── Gmail API (automated HTML email reports)
                    │
                    ▼
     Streamlit Dashboard (Cloud Run)
     shopright-dash.web.app → 301 → Cloud Run
```

---

## AI Chatbot

### RAG Pipeline

Every user message triggers a two-stage retrieval pipeline before the LLM generates a response.

**Stage 1 — Hybrid ANN search (pgvector)**
- Query is embedded with Gemini `text-embedding-004` (`task_type=RETRIEVAL_QUERY`, 3072-dim)
- PostgreSQL `knowledge_embeddings` table is searched using cosine distance on a `halfvec(3072)` HNSW index
- `halfvec` lifts pgvector's 2000-dim ANN limit to 16,000 dims while halving storage
- A keyword bonus score (`CASE WHEN content ~ 'regex' THEN 0.15 ELSE 0`) is subtracted from cosine distance to create a hybrid rank
- Optional SQL filters applied: price limit (regex-extracted from query) and product category (keyword-matched from 11 categories)
- Fetches 50 candidates

**Stage 2 — Vertex AI Ranking API (rerank)**
- Top-16 candidates from ANN search are sent to Vertex AI Ranking API
- Semantically reranked against the original query
- Falls back to hybrid score if Ranking API is unavailable
- Deduplication: products with the same name are deduplicated; FAQs and review summaries are kept as-is
- Returns top 8 documents to the LLM

**Knowledge base — three document types:**

| Type | Source | Content |
|---|---|---|
| `product` | PostgreSQL products table | Name, SKU, category, brand, price, description, specs |
| `faq` | `data/faqs.json` | 82 Q&A pairs: store policies, battery compatibility, paint/sealant selection, pricing, power tools, building materials |
| `review_summary` | `data/reviews.json` | Avg rating + top 5 review snippets per product |

**Ingestion:** `python ai/chatbot/ingest.py` — embeds all three doc types with `task_type=RETRIEVAL_DOCUMENT` and upserts into `knowledge_embeddings` via `ON CONFLICT (doc_type, source_id) DO UPDATE`.

---

### Google ADK — Agent Orchestration

The chatbot uses **Google Agent Developer Kit (ADK)** for structured tool-calling and session management.

```python
_agent = LlmAgent(
    name="shopright_assistant",
    model="gemini-2.5-flash",
    instruction=SYSTEM_PROMPT,
    tools=[search_products],          # RAG tool
)
_runner = Runner(
    agent=_agent,
    app_name="shopright",
    session_service=InMemorySessionService(),
)
```

- `LlmAgent` defines the agent: model, system prompt, available tools
- `Runner.run_async()` manages the tool-call → tool-response → generation loop automatically, emitting `Event` objects
- Events with `is_final_response()=True` carry generated text, streamed token-by-token as SSE
- `InMemorySessionService` holds per-session state within a pod (stateless across pod restarts by design — client sends full history on every request)

**System prompt — gap fixes informed by real traffic analysis:**
- **Pricing follow-ups**: bot infers product context from conversation history — never asks customers to repeat themselves
- **Battery compatibility**: explicit guidance that DeWalt/Milwaukee/Ryobi/Makita batteries are NOT cross-compatible; within a brand, same-voltage tools share batteries
- **Zero-result queries**: when search returns no matches (e.g. paint, sealant), bot explains key specs and attributes to look for, then directs to a store associate — never says "I don't know"

**Streaming:** `/stream` endpoint returns `Content-Type: text/event-stream`. Each token:
```
data: {"token": "The DeWalt ", "done": false}
data: {"done": true, "message_id": "...", "sources": [...], "session_id": "..."}
```

---

### Safety & Detection Layer

All detectors are **pure regex/rule-based** — zero LLM cost, deterministic, sub-millisecond.

| Detector | Method | Trigger |
|---|---|---|
| Prompt injection | 9 regex patterns | "ignore previous instructions", persona override, jailbreak |
| Vulgar/sexual content | 14 patterns with negative lookaheads | Excludes false positives (e.g. `cockpit`, `cocktail`) |
| Wellbeing/crisis | 26 keyword phrases | Immediate hardcoded crisis response (988 helpline) |
| Session ending | Phrase list + ambiguity resolution | Triggers star-rating prompt |
| Frustration | Regex + Jaccard word overlap >60% | Detects repeated rephrasing without LLM |
| Category detection | 11-category keyword map | Feeds RAG category filter |
| Price extraction | 9 regex patterns | Feeds RAG price filter SQL clause |

---

### Intent Classification

Every message is classified into one of 6 labels: `product_lookup`, `project_advice`, `compatibility`, `pricing_availability`, `troubleshooting`, `general_chat`.

- Uses **Gemini 2.5-flash** — same model as generation, ensuring consistent availability
- Runs **async and non-blocking** via `asyncio.create_task()` inside `log_to_bigquery()` — user never waits
- Two calls are `asyncio.gather()`'d in parallel: `classify_intent` + `extract_intent_target`
- `user_intent_target` extracts the specific topic (e.g. "cordless drill", "deck lumber") for recommendation gap analysis

---

### Reliability — Rate Limit Handling

The chatbot wraps `runner.run_async()` in an **exponential backoff retry loop** to handle Gemini API 429 errors without surfacing them to customers:

```python
_max_retries, _retry_delay = 3, 2.0
for _attempt in range(_max_retries):
    try:
        async for event in _runner.run_async(...):
            ...
        break  # success
    except Exception as e:
        is_rate_limit = "ResourceExhausted" in type(e).__name__ or "429" in str(e)
        if is_rate_limit and _attempt < _max_retries - 1:
            wait = _retry_delay * (2 ** _attempt)   # 2s → 4s
            await asyncio.sleep(wait)
            continue
        raise
```

- Up to 3 attempts, delays of 2s then 4s
- Only retries `ResourceExhausted` / 429 — other errors fail immediately

---

## Analytics Agent

### Architecture

```
POST /analyze/run  →  Orchestrator Agent
                            ├── AgentTool(devops_agent)
                            ├── AgentTool(tech_agent)
                            └── AgentTool(business_agent)
                                        │
                            ┌───────────┴───────────┐
                            │                       │
                    Report tools              MCP Toolbox tools
                (BQ → Gemini → Gmail)     (45 named BQ queries)
```

The orchestrator routes requests to specialist sub-agents based on audience. Each sub-agent has two modes:

1. **Scheduled/triggered reports** (`POST /analyze/run`): pull BigQuery data → Gemini writes narrative → send styled HTML email with dashboard link
2. **Ad-hoc Q&A** (`POST /analyze/chat`): use MCP Toolbox named queries to answer natural language questions about metrics

### MCP Toolbox

The analytics service runs a **Google MCP Toolbox for Databases** sidecar (`analytics-toolbox` Cloud Run service) exposing 45 parameterized BigQuery queries as MCP tools.

**Why named queries over LLM-generated SQL:**
- LLMs can produce SQL injection, schema errors, and unbounded queries
- Named queries are tested, parameterized, and cost-predictable
- Agents pick which tool to call and pass parameters — they never write SQL

| Toolset | Tools | Audience |
|---|---|---|
| `devops` | 12 tools | Engineers, on-call SREs |
| `tech` | 15 tools | ML engineers, data scientists |
| `business` | 18 tools | Product managers, executives |

At startup, the orchestrator calls `ToolboxClient.load_toolset()` to fetch tool schemas over OIDC-authenticated HTTPS.

### Sub-agents

| Agent | Metrics focus | Alert thresholds |
|---|---|---|
| DevOps | Error rate, latency, TTFT, security events | Error rate > 2%, p95 > 8s, TTFT > 3s |
| Tech | RAG confidence, citation gap, rec gap, frustration, cost | RAG confidence > 0.6, citation gap > 5%, frustration > 15% |
| Business | Star rating, thumbs-up rate, chip-click conversion | Stars < 3.0, positive reviews < 50%, conversion < 10% |

### Streamlit Dashboard

Three-page dashboard at `shopright-dash.web.app`:

- **DevOps page:** Total requests, sessions, error rate, p95 latency, unanswered rate, scope rejected rate + daily volume chart, latency trend, TTFT trend, security events, error type breakdown
- **Technical page:** RAG confidence, RAG empty rate, avg brands/query, citation gap rate, rec gap rate, frustration rate, total LLM cost, avg tokens in/out, avg turn depth + RAG confidence trend, frustration trend, latency breakdown, intent distribution, catalog gaps table
- **Business page:** Avg star rating, positive reviews, thumbs-up rate, chip-click conversion, cost/session + star rating trend, conversion trend, top clicked products, intent distribution, category demand

**WebSocket note:** Streamlit requires a direct WebSocket connection. Firebase CDN cannot forward `HTTP → WebSocket Upgrade` requests. The `shopright-dash` Firebase site uses a **301 redirect** to the Cloud Run URL, bypassing the CDN entirely.

---

## Observability

### BigQuery — Chat Analytics

Every chat turn is logged asynchronously to BigQuery. 25+ fields per row:

| Field | What it measures |
|---|---|
| `latency_ms` | End-to-end response time |
| `ttft_ms` | Time to first token |
| `rag_confidence` | Avg cosine distance of retrieved docs (lower = better) |
| `min_vec_distance` | Closest doc distance |
| `rerank_used` | Whether Vertex AI Ranking API was invoked |
| `tokens_in` / `tokens_out` | For cost calculation |
| `estimated_cost_usd` | Generation cost + intent classification cost |
| `intent` | Gemini-classified intent label |
| `user_intent_target` | Extracted topic (e.g. "cordless drill") |
| `rec_gap` | User wanted X but bot returned different products |
| `frustration_signal` | Rule-based frustration detection |
| `hallucination_flag` | Bot had sources but didn't cite product names |
| `is_unanswered` | 0 sources + uncertainty phrase |
| `scope_rejected` | Out-of-scope refusal |
| `vulgar_flag` / `prompt_injection_flag` | Security events |

**Logging is fire-and-forget** — `asyncio.create_task(log_to_bigquery(...))` is called after the stream completes. BigQuery latency never affects the user.

**Cost tracking:** `estimated_cost_usd` = Gemini 2.5-flash generation + intent classification
- $0.30/1M input · $2.50/1M output (both calls)
- Token counts estimated via `len(text) // 4` when ADK's event stream doesn't expose `usage_metadata`

---

### Distributed Tracing — OpenTelemetry + Cloud Trace

The chatbot is fully instrumented with **OpenTelemetry**, exporting traces to **Google Cloud Trace**.

```python
# Auto-instrument FastAPI (all HTTP requests)
FastAPIInstrumentor.instrument_app(app)

# Custom spans for each pipeline stage
with _tracer.start_as_current_span("embed_query") as span:
    span.set_attribute("query_length", len(query))

with _tracer.start_as_current_span("vector_search") as span:
    span.set_attribute("candidates_returned", len(rows))
    span.set_attribute("db_ms", db_ms)

with _tracer.start_as_current_span("vertex_rerank") as span:
    span.set_attribute("rerank_used", True)

with _tracer.start_as_current_span("llm_generate") as span:
    span.set_attribute("session_id", session_id)
    span.set_attribute("turn_number", turn_number)
```

**Four named spans per request**, giving end-to-end visibility in Cloud Trace:

| Span | What it covers |
|---|---|
| `embed_query` | Gemini embedding call duration |
| `vector_search` | pgvector ANN query + keyword scoring |
| `vertex_rerank` | Vertex AI Ranking API call (or fallback) |
| `llm_generate` | ADK runner → full generation + streaming |

- `BatchSpanProcessor` + `CloudTraceSpanExporter` — non-blocking, batched export
- Falls back gracefully if Cloud Trace is not enabled in the project

---

## Deployment

### Infrastructure as Code (Terraform)

All GCP resources are provisioned via `infra/terraform/main.tf`:

| Resource | Purpose |
|---|---|
| Cloud Run (×9) | All services — auto-scaling, zero to N instances |
| Cloud SQL (PostgreSQL 15 + pgvector) | Product catalog + knowledge_embeddings |
| BigQuery dataset + tables | Chat analytics, feedback, events, reviews |
| BigQuery view (session_outcomes) | Computed session success/failure/inconclusive |
| Artifact Registry | Docker image storage |
| Workload Identity Federation | Keyless GitHub Actions → GCP auth (no stored keys) |
| Secret Manager | API keys, DB passwords |
| Firebase Hosting (×2 sites) | shopright-store (CDN proxy) + shopright-dash (redirect) |
| Cloud Monitoring alert policies | Error rate > 2%, rerank failures, latency thresholds |
| Log-based metrics | Rerank errors, custom chatbot signals |

**Notable pattern — `time_sleep` for GCP metric propagation:**
GCP needs ~60s to propagate a new log-based metric before alert policies can reference it. A `time_sleep` resource with `depends_on` ensures Terraform waits before creating the alert policy — prevents a repeatable 404 failure.

### GitHub Actions CI/CD

Three-job pipeline on push to `main`:

**Job 1 — `build-and-push` (9 services in parallel matrix):**
```
Checkout → WIF auth → docker build -t $REGISTRY/$IMAGE:$SHA → push to Artifact Registry
```

**Job 2 — `deploy` (needs: build-and-push):**
```
WIF auth → gcloud run services update --image $IMAGE:$SHA
```
Uses SHA-tagged images (not `latest`) for traceability and rollback.

**Job 3 — `firebase-hosting` (needs: deploy):**
```
npm install -g firebase-tools → firebase deploy --only hosting
```
Uses `FIREBASE_TOKEN` (not WIF) — Firebase CLI v15 doesn't resolve project IDs from WIF credentials.

### Workload Identity Federation

GitHub Actions authenticates to GCP without storing service account keys:
```
GitHub OIDC token → WIF provider → short-lived GCP access token
```
`attribute_condition` restricts to `assertion.repository == 'org/repo'` — only this repo can impersonate the service account.
