"""
Chat Log Analytics Service
Queries BigQuery to surface insights from chat interactions:
- Top questions/topics
- Unanswered/poorly answered queries
- Product mention frequency
- Session metrics
- Infra, model, and business metric dashboards
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import os
import logging

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GCP_PROJECT  = os.getenv("GCP_PROJECT_ID", "")
BQ_DATASET   = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE     = os.getenv("BIGQUERY_TABLE", "chat_logs")
BQ_FEEDBACK  = os.getenv("BIGQUERY_FEEDBACK_TABLE", "feedback")
BQ_EVENTS    = os.getenv("BIGQUERY_EVENTS_TABLE", "chat_events")
BQ_REVIEWS   = os.getenv("BIGQUERY_REVIEWS_TABLE", "session_reviews")

app = FastAPI(title="Chat Analytics Service", version="2.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
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

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "analytics"}

# ── Existing endpoints ────────────────────────────────────────────────────────

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

# ── Infra metrics ─────────────────────────────────────────────────────────────

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

    daily    = run_query(daily_sql)
    summary  = run_query(summary_sql)
    return {
        "period_days": days,
        "summary": summary[0] if summary else {},
        "daily": daily,
    }

# ── Model metrics ─────────────────────────────────────────────────────────────

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
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered = TRUE) * 100.0, COUNT(*)), 2) AS unanswered_rate_pct,
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
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered = TRUE) * 100.0, COUNT(*)), 2) AS unanswered_rate_pct,
      ROUND(AVG(COALESCE(rag_confidence, 0)), 4) AS avg_rag_confidence,
      ROUND(SAFE_DIVIDE(COUNTIF(hallucination_flag = TRUE) * 100.0, COUNT(*)), 2) AS hallucination_rate_pct,
      CAST(AVG(COALESCE(tokens_in, 0)) AS INT64) AS avg_tokens_in,
      CAST(AVG(COALESCE(tokens_out, 0)) AS INT64) AS avg_tokens_out
    FROM {_table(BQ_TABLE)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """

    # Catalog gaps — top unanswered queries
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

    # Category performance
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

# ── Business metrics ──────────────────────────────────────────────────────────

@app.get("/analytics/business")
async def get_business_metrics(days: int = 30):
    """Business metrics: satisfaction, chip-click conversion, top products."""
    if not GCP_PROJECT:
        return _no_gcp()

    # Satisfaction trend from session_reviews
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

    # Feedback ratio (thumbs up/down)
    feedback_sql = f"""
    SELECT
      COUNTIF(rating = 1)  AS thumbs_up,
      COUNTIF(rating = -1) AS thumbs_down,
      COUNT(*) AS total_feedback,
      ROUND(SAFE_DIVIDE(COUNTIF(rating = 1) * 100.0, COUNT(*)), 2) AS positive_rate_pct
    FROM {_table(BQ_FEEDBACK)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """

    # Daily chip clicks (conversion signal)
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

    # Top clicked products
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

    # Overall satisfaction summary
    satisfaction_summary_sql = f"""
    SELECT
      ROUND(AVG(stars), 2) AS avg_stars,
      COUNT(*) AS total_reviews,
      COUNTIF(stars >= 4) AS positive_reviews,
      ROUND(SAFE_DIVIDE(COUNTIF(stars >= 4) * 100.0, COUNT(*)), 2) AS positive_rate_pct
    FROM {_table(BQ_REVIEWS)}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """

    satisfaction_trend   = run_query(satisfaction_sql)
    feedback_summary     = run_query(feedback_sql)
    conversion_trend     = run_query(conversion_sql)
    top_clicked          = run_query(top_clicked_sql)
    satisfaction_summary = run_query(satisfaction_summary_sql)

    return {
        "period_days": days,
        "satisfaction_summary": satisfaction_summary[0] if satisfaction_summary else {},
        "feedback_summary": feedback_summary[0] if feedback_summary else {},
        "satisfaction_trend": satisfaction_trend,
        "conversion_trend": conversion_trend,
        "top_clicked_products": top_clicked,
    }
