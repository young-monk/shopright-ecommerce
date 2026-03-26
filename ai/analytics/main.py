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

from queries import (
    overview_sql, top_questions_sql, daily_volume_sql, rag_performance_sql,
    top_products_mentioned_sql, devops_infra_daily_sql, devops_infra_summary_sql,
    tech_model_daily_sql, tech_model_summary_sql, tech_gaps_sql,
    tech_category_performance_sql, biz_sat_daily_sql, biz_sat_full_summary_sql,
    biz_feedback_full_sql, biz_conversion_raw_sql, biz_top_products_sql,
)

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
    results = run_query(overview_sql(GCP_PROJECT, BQ_DATASET, days))
    return results[0] if results else {}


@app.get("/analytics/top-questions")
async def get_top_questions(days: int = 7, limit: int = 20):
    """Most common user questions by keyword clustering."""
    if not GCP_PROJECT:
        return _no_gcp()
    return {"questions": run_query(top_questions_sql(GCP_PROJECT, BQ_DATASET, days, limit))}


@app.get("/analytics/daily-volume")
async def get_daily_volume(days: int = 30):
    """Daily message volume trend."""
    if not GCP_PROJECT:
        return _no_gcp()
    return {"daily_volume": run_query(daily_volume_sql(GCP_PROJECT, BQ_DATASET, days))}


@app.get("/analytics/rag-performance")
async def get_rag_performance(days: int = 7):
    """How well RAG is performing - source retrieval rates."""
    if not GCP_PROJECT:
        return _no_gcp()
    return {"rag_distribution": run_query(rag_performance_sql(GCP_PROJECT, BQ_DATASET, days))}


@app.get("/analytics/top-products-mentioned")
async def get_top_products(days: int = 7, limit: int = 10):
    """Which products are mentioned most in chat sources."""
    if not GCP_PROJECT:
        return _no_gcp()
    return {"top_products": run_query(top_products_mentioned_sql(GCP_PROJECT, BQ_DATASET, days, limit))}


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
    daily   = run_query(devops_infra_daily_sql(GCP_PROJECT, BQ_DATASET, days))
    summary = run_query(devops_infra_summary_sql(GCP_PROJECT, BQ_DATASET, days))
    return {"period_days": days, "summary": summary[0] if summary else {}, "daily": daily}


@app.get("/analytics/model")
async def get_model_metrics(days: int = 14):
    """Model metrics: cost trends, RAG quality, TTFT, catalog gaps."""
    if not GCP_PROJECT:
        return _no_gcp()
    daily      = run_query(tech_model_daily_sql(GCP_PROJECT, BQ_DATASET, days))
    summary    = run_query(tech_model_summary_sql(GCP_PROJECT, BQ_DATASET, days))
    gaps       = run_query(tech_gaps_sql(GCP_PROJECT, BQ_DATASET, days))
    categories = run_query(tech_category_performance_sql(GCP_PROJECT, BQ_DATASET, days))
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
    return {
        "period_days": days,
        "satisfaction_summary": (run_query(biz_sat_full_summary_sql(GCP_PROJECT, BQ_DATASET, days)) or [{}])[0],
        "feedback_summary":     (run_query(biz_feedback_full_sql(GCP_PROJECT, BQ_DATASET, days)) or [{}])[0],
        "satisfaction_trend":   run_query(biz_sat_daily_sql(GCP_PROJECT, BQ_DATASET, days)),
        "conversion_trend":     run_query(biz_conversion_raw_sql(GCP_PROJECT, BQ_DATASET, days)),
        "top_clicked_products": run_query(biz_top_products_sql(GCP_PROJECT, BQ_DATASET, days)),
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
