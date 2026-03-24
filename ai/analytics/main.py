"""
Chat Log Analytics Service — v3 with multi-agent AI analytics.

Endpoints:
  GET  /analytics/*          — existing data endpoints (unchanged)
  POST /analyze/run          — trigger automated report via ADK agents (scheduled + ad-hoc)
  POST /analyze/chat         — interactive Q&A with the orchestrator agent
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
BQ_DATASET  = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE    = os.getenv("BIGQUERY_TABLE", "chat_logs")
BQ_FEEDBACK = os.getenv("BIGQUERY_FEEDBACK_TABLE", "feedback")
BQ_EVENTS   = os.getenv("BIGQUERY_EVENTS_TABLE", "chat_events")
BQ_REVIEWS  = os.getenv("BIGQUERY_REVIEWS_TABLE", "session_reviews")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the ADK orchestrator (loads MCP Toolbox toolsets) at startup."""
    if GCP_PROJECT:
        try:
            from agents.orchestrator import init_orchestrator
            await init_orchestrator()
        except Exception as exc:
            logger.warning("Orchestrator init failed (non-fatal): %s", exc)
    yield


app = FastAPI(title="Chat Analytics Service", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


def get_bq_client():
    return bigquery.Client(project=GCP_PROJECT)


def run_query(sql: str, params: Optional[List] = None) -> List[Dict[str, Any]]:
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    return [dict(row) for row in client.query(sql, job_config=job_config).result()]


def _table(name: str) -> str:
    return f"`{GCP_PROJECT}.{BQ_DATASET}.{name}`"


def _no_gcp():
    return {"error": "GCP not configured"}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "analytics", "version": "3.0.0"}


# ── Existing analytics endpoints (unchanged) ──────────────────────────────────

@app.get("/analytics/overview")
async def get_overview(days: int = 7):
    """High-level chat metrics for the last N days."""
    if not GCP_PROJECT:
        return _no_gcp()
    sql = f"""
    SELECT
      COUNT(*) AS total_messages,
      COUNT(DISTINCT session_id) AS unique_sessions,
      AVG(message_length) AS avg_message_length,
      AVG(response_length) AS avg_response_length,
      AVG(sources_count) AS avg_sources_per_response,
      COUNTIF(sources_count = 0) AS messages_without_rag,
      COUNTIF(sources_count > 0) AS messages_with_rag
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    results = run_query(sql)
    return results[0] if results else {}


@app.get("/analytics/top-questions")
async def get_top_questions(days: int = 7, limit: int = 20):
    """Most common user questions by keyword clustering."""
    if not GCP_PROJECT:
        return _no_gcp()
    sql = f"""
    SELECT
      user_message,
      COUNT(*) AS frequency,
      AVG(sources_count) AS avg_rag_sources
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY user_message
    ORDER BY frequency DESC
    LIMIT {limit}
    """
    return {"questions": run_query(sql)}


@app.get("/analytics/daily-volume")
async def get_daily_volume(days: int = 30):
    """Daily message volume trend."""
    if not GCP_PROJECT:
        return _no_gcp()
    sql = f"""
    SELECT
      DATE(timestamp) AS date,
      COUNT(*) AS messages,
      COUNT(DISTINCT session_id) AS sessions
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date DESC
    """
    return {"daily_volume": run_query(sql)}


@app.get("/analytics/rag-performance")
async def get_rag_performance(days: int = 7):
    """How well RAG is performing - source retrieval rates."""
    if not GCP_PROJECT:
        return _no_gcp()
    sql = f"""
    SELECT
      sources_count,
      COUNT(*) AS message_count,
      ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS percentage
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY sources_count
    ORDER BY sources_count
    """
    return {"rag_distribution": run_query(sql)}


@app.get("/analytics/top-products-mentioned")
async def get_top_products(days: int = 7, limit: int = 10):
    """Which products are mentioned most in chat sources."""
    if not GCP_PROJECT:
        return _no_gcp()
    sql = f"""
    SELECT
      JSON_EXTRACT_SCALAR(src, '$.name') AS product_name,
      JSON_EXTRACT_SCALAR(src, '$.price') AS price,
      COUNT(*) AS mentions
    FROM {_table(BQ_TABLE)},
    UNNEST(JSON_EXTRACT_ARRAY(sources_used)) AS src
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND sources_used IS NOT NULL
    GROUP BY product_name, price
    ORDER BY mentions DESC
    LIMIT {limit}
    """
    return {"top_products": run_query(sql)}


@app.get("/analytics/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """Full conversation log for a specific session."""
    if not GCP_PROJECT:
        return _no_gcp()
    sql = f"""
    SELECT
      message_id, timestamp, user_message, assistant_response,
      sources_used, sources_count
    FROM {_table(BQ_TABLE)}
    WHERE session_id = @session_id
    ORDER BY timestamp ASC
    """
    messages = run_query(sql, [bigquery.ScalarQueryParameter("session_id", "STRING", session_id)])
    return {"session_id": session_id, "messages": messages}


@app.get("/analytics/infra")
async def get_infra_metrics(days: int = 14):
    """Infrastructure metrics: daily request volume, error rate, p95 latency."""
    if not GCP_PROJECT:
        return _no_gcp()
    daily_sql = f"""
    SELECT
      DATE(timestamp) AS date,
      COUNT(*) AS requests,
      COUNT(DISTINCT session_id) AS sessions,
      COUNTIF(llm_error = TRUE) AS errors,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error = TRUE) * 100.0, COUNT(*)), 2) AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] AS INT64) AS p95_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(50)] AS INT64) AS p50_latency_ms,
      CAST(AVG(latency_ms) AS INT64) AS avg_latency_ms
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    summary_sql = f"""
    SELECT
      COUNT(*) AS total_requests,
      COUNT(DISTINCT session_id) AS total_sessions,
      COUNTIF(llm_error = TRUE) AS total_errors,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error = TRUE) * 100.0, COUNT(*)), 2) AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] AS INT64) AS p95_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(50)] AS INT64) AS p50_latency_ms,
      CAST(AVG(latency_ms) AS INT64) AS avg_latency_ms
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    daily   = run_query(daily_sql)
    summary = run_query(summary_sql)
    return {"period_days": days, "summary": summary[0] if summary else {}, "daily": daily}


@app.get("/analytics/model")
async def get_model_metrics(days: int = 14):
    """Model metrics: cost trends, RAG quality, TTFT, catalog gaps."""
    if not GCP_PROJECT:
        return _no_gcp()
    daily_sql = f"""
    SELECT
      DATE(timestamp) AS date,
      ROUND(SUM(COALESCE(estimated_cost_usd, 0)), 6) AS cost_usd,
      CAST(AVG(COALESCE(ttft_ms, 0)) AS INT64) AS avg_ttft_ms,
      CAST(AVG(COALESCE(llm_ms, 0)) AS INT64) AS avg_llm_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered = TRUE OR scope_rejected = TRUE) * 100.0, COUNT(*)), 2) AS unanswered_rate_pct,
      ROUND(AVG(COALESCE(rag_confidence, 0)), 4) AS avg_rag_confidence,
      CAST(AVG(COALESCE(tokens_in, 0)) AS INT64) AS avg_tokens_in,
      CAST(AVG(COALESCE(tokens_out, 0)) AS INT64) AS avg_tokens_out
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    summary_sql = f"""
    SELECT
      ROUND(SUM(COALESCE(estimated_cost_usd, 0)), 4) AS total_cost_usd,
      ROUND(AVG(COALESCE(estimated_cost_usd, 0)) * 1000, 4) AS cost_per_1k_requests_usd,
      CAST(APPROX_QUANTILES(ttft_ms, 100)[OFFSET(95)] AS INT64) AS p95_ttft_ms,
      CAST(AVG(COALESCE(ttft_ms, 0)) AS INT64) AS avg_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered = TRUE OR scope_rejected = TRUE) * 100.0, COUNT(*)), 2) AS unanswered_rate_pct,
      ROUND(AVG(COALESCE(rag_confidence, 0)), 4) AS avg_rag_confidence,
      ROUND(SAFE_DIVIDE(COUNTIF(hallucination_flag = TRUE) * 100.0, COUNT(*)), 2) AS citation_gap_rate_pct,
      CAST(AVG(COALESCE(tokens_in, 0)) AS INT64) AS avg_tokens_in,
      CAST(AVG(COALESCE(tokens_out, 0)) AS INT64) AS avg_tokens_out
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    gaps_sql = f"""
    SELECT
      user_message,
      COALESCE(detected_category, 'Unknown') AS category,
      COUNT(*) AS frequency
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND is_unanswered = TRUE
    GROUP BY user_message, category
    ORDER BY frequency DESC
    LIMIT 20
    """
    category_sql = f"""
    SELECT
      COALESCE(detected_category, 'General') AS category,
      COUNT(*) AS requests,
      COUNTIF(is_unanswered = TRUE) AS unanswered,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered = TRUE) * 100.0, COUNT(*)), 2) AS unanswered_rate_pct,
      ROUND(AVG(COALESCE(rag_confidence, 0)), 4) AS avg_rag_confidence
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY category
    ORDER BY requests DESC
    """
    daily      = run_query(daily_sql)
    summary    = run_query(summary_sql)
    gaps       = run_query(gaps_sql)
    categories = run_query(category_sql)
    return {
        "period_days": days,
        "summary": summary[0] if summary else {},
        "daily": daily,
        "catalog_gaps": gaps,
        "category_performance": categories,
    }


@app.get("/analytics/business")
async def get_business_metrics(days: int = 30):
    """Business metrics: satisfaction, chip-click conversion, top products."""
    if not GCP_PROJECT:
        return _no_gcp()
    satisfaction_sql = f"""
    SELECT
      DATE(timestamp) AS date,
      ROUND(AVG(stars), 2) AS avg_stars,
      COUNT(*) AS review_count
    FROM {_table(BQ_REVIEWS)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    feedback_sql = f"""
    SELECT
      COUNTIF(rating = 1)  AS thumbs_up,
      COUNTIF(rating = -1) AS thumbs_down,
      COUNT(*) AS total_feedback,
      ROUND(SAFE_DIVIDE(COUNTIF(rating = 1) * 100.0, COUNT(*)), 2) AS positive_rate_pct
    FROM {_table(BQ_FEEDBACK)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    conversion_sql = f"""
    SELECT
      DATE(timestamp) AS date,
      COUNT(*) AS chip_clicks,
      COUNT(DISTINCT session_id) AS sessions_with_clicks
    FROM {_table(BQ_EVENTS)}
    WHERE event_type = 'chip_click'
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    top_clicked_sql = f"""
    SELECT
      product_name,
      COUNT(*) AS clicks
    FROM {_table(BQ_EVENTS)}
    WHERE event_type = 'chip_click'
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND product_name IS NOT NULL
    GROUP BY product_name
    ORDER BY clicks DESC
    LIMIT 10
    """
    satisfaction_summary_sql = f"""
    SELECT
      ROUND(AVG(stars), 2) AS avg_stars,
      COUNT(*) AS total_reviews,
      COUNTIF(stars >= 4) AS positive_reviews,
      ROUND(SAFE_DIVIDE(COUNTIF(stars >= 4) * 100.0, COUNT(*)), 2) AS positive_rate_pct
    FROM {_table(BQ_REVIEWS)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    return {
        "period_days": days,
        "satisfaction_summary": (run_query(satisfaction_summary_sql) or [{}])[0],
        "feedback_summary": (run_query(feedback_sql) or [{}])[0],
        "satisfaction_trend": run_query(satisfaction_sql),
        "conversion_trend": run_query(conversion_sql),
        "top_clicked_products": run_query(top_clicked_sql),
    }


# ── AI Analytics Endpoints ─────────────────────────────────────────────────────

class AnalyzeRunRequest(BaseModel):
    audience: str = "all"        # "all" | "devops" | "tech" | "business"
    days: int = 7
    devops_email: str = ""
    tech_email: str = ""
    business_email: str = ""


class AnalyzeChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@app.post("/analyze/run")
async def run_analysis(req: AnalyzeRunRequest):
    """
    Trigger multi-agent analytics report generation and email delivery.
    Audience: 'all' sends all three reports; 'devops'/'tech'/'business' sends one.
    Called weekly by Cloud Scheduler and on-demand by admins.
    """
    if not GCP_PROJECT:
        raise HTTPException(status_code=503, detail="GCP not configured")

    # Build prompt for orchestrator
    audience_clause = {
        "all":      "all three audiences (devops, tech, and business)",
        "devops":   "the devops audience only",
        "tech":     "the tech audience only",
        "business": "the business audience only",
    }.get(req.audience, "all three audiences")

    overrides = []
    if req.devops_email:
        overrides.append(f"DevOps email: {req.devops_email}")
    if req.tech_email:
        overrides.append(f"Tech email: {req.tech_email}")
    if req.business_email:
        overrides.append(f"Business email: {req.business_email}")
    override_clause = (" Override recipient emails: " + ", ".join(overrides)) if overrides else ""

    prompt = (
        f"Run the analytics reports for {audience_clause}. "
        f"Use {req.days} days of data.{override_clause} "
        "Generate and send the reports now."
    )

    try:
        from agents.orchestrator import run_analytics
        result = await run_analytics(prompt)
        return {"status": "ok", "audience": req.audience, "days": req.days, "summary": result}
    except Exception as exc:
        logger.exception("Analytics run failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/analyze/chat")
async def analyze_chat(req: AnalyzeChatRequest):
    """
    Interactive natural language interface to the analytics orchestrator.
    Ask questions like 'What was our error rate last week?' or
    'Show me frustration trends for the tech team'.
    """
    if not GCP_PROJECT:
        raise HTTPException(status_code=503, detail="GCP not configured")
    try:
        from agents.orchestrator import run_analytics
        user_id = req.session_id or "interactive"
        result = await run_analytics(req.message, user_id=user_id)
        return {"reply": result}
    except Exception as exc:
        logger.exception("Analytics chat failed")
        raise HTTPException(status_code=500, detail=str(exc))
