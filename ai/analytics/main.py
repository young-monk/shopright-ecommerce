"""
Chat Log Analytics Service
Queries BigQuery to surface insights from chat interactions:
- Top questions/topics
- Unanswered/poorly answered queries
- Product mention frequency
- Session metrics
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

GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
BQ_DATASET = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE = os.getenv("BIGQUERY_TABLE", "chat_logs")

app = FastAPI(title="Chat Analytics Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

def get_bq_client():
    return bigquery.Client(project=GCP_PROJECT)

def run_query(sql: str) -> List[Dict[str, Any]]:
    client = get_bq_client()
    return [dict(row) for row in client.query(sql).result()]

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "analytics"}

@app.get("/analytics/overview")
async def get_overview(days: int = 7):
    """High-level chat metrics for the last N days."""
    if not GCP_PROJECT:
        return {"error": "GCP not configured"}

    table = f"`{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`"
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    sql = f"""
    SELECT
      COUNT(*) AS total_messages,
      COUNT(DISTINCT session_id) AS unique_sessions,
      AVG(message_length) AS avg_message_length,
      AVG(response_length) AS avg_response_length,
      AVG(sources_count) AS avg_sources_per_response,
      COUNTIF(sources_count = 0) AS messages_without_rag,
      COUNTIF(sources_count > 0) AS messages_with_rag
    FROM {table}
    WHERE timestamp >= '{cutoff}'
    """
    results = run_query(sql)
    return results[0] if results else {}

@app.get("/analytics/top-questions")
async def get_top_questions(days: int = 7, limit: int = 20):
    """Most common user questions by keyword clustering."""
    if not GCP_PROJECT:
        return {"error": "GCP not configured"}

    table = f"`{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`"
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    sql = f"""
    SELECT
      user_message,
      COUNT(*) AS frequency,
      AVG(sources_count) AS avg_rag_sources
    FROM {table}
    WHERE timestamp >= '{cutoff}'
    GROUP BY user_message
    ORDER BY frequency DESC
    LIMIT {limit}
    """
    return {"questions": run_query(sql)}

@app.get("/analytics/daily-volume")
async def get_daily_volume(days: int = 30):
    """Daily message volume trend."""
    if not GCP_PROJECT:
        return {"error": "GCP not configured"}

    table = f"`{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`"

    sql = f"""
    SELECT
      DATE(timestamp) AS date,
      COUNT(*) AS messages,
      COUNT(DISTINCT session_id) AS sessions
    FROM {table}
    WHERE timestamp >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date DESC
    """
    return {"daily_volume": run_query(sql)}

@app.get("/analytics/rag-performance")
async def get_rag_performance(days: int = 7):
    """How well RAG is performing - source retrieval rates."""
    if not GCP_PROJECT:
        return {"error": "GCP not configured"}

    table = f"`{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`"
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    sql = f"""
    SELECT
      sources_count,
      COUNT(*) AS message_count,
      ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS percentage
    FROM {table}
    WHERE timestamp >= '{cutoff}'
    GROUP BY sources_count
    ORDER BY sources_count
    """
    return {"rag_distribution": run_query(sql)}

@app.get("/analytics/top-products-mentioned")
async def get_top_products(days: int = 7, limit: int = 10):
    """Which products are mentioned most in chat sources."""
    if not GCP_PROJECT:
        return {"error": "GCP not configured"}

    table = f"`{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`"
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    sql = f"""
    SELECT
      source_item AS product,
      COUNT(*) AS mention_count
    FROM {table},
    UNNEST(JSON_VALUE_ARRAY(sources_used)) AS source_item
    WHERE timestamp >= '{cutoff}'
    GROUP BY source_item
    ORDER BY mention_count DESC
    LIMIT {limit}
    """
    return {"top_products": run_query(sql)}

@app.get("/analytics/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """Full conversation log for a specific session."""
    if not GCP_PROJECT:
        return {"error": "GCP not configured"}

    table = f"`{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`"

    sql = f"""
    SELECT
      message_id,
      timestamp,
      user_message,
      assistant_response,
      sources_used,
      sources_count
    FROM {table}
    WHERE session_id = '{session_id}'
    ORDER BY timestamp ASC
    """
    messages = run_query(sql)
    return {"session_id": session_id, "messages": messages}
