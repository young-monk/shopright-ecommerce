"""Centralised config and shared clients for the ShopRight chatbot."""
from __future__ import annotations

import logging
import os

# ── Environment config ────────────────────────────────────────────────────────
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
GCP_PROJECT       = os.getenv("GCP_PROJECT_ID", "")
LLM_MODEL         = os.getenv("LLM_MODEL", "gemini-2.5-flash")
DATABASE_URL      = os.getenv("DATABASE_URL", "postgresql://shopright:shopright_dev@localhost:5432/shopright")
BQ_DATASET        = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE          = os.getenv("BIGQUERY_TABLE", "chat_logs")
BQ_FEEDBACK_TABLE = os.getenv("BIGQUERY_FEEDBACK_TABLE", "feedback")
BQ_EVENTS_TABLE   = os.getenv("BIGQUERY_EVENTS_TABLE", "chat_events")
GCP_REGION        = os.getenv("GCP_REGION", "us-central1")

# ── LLM cost constants (per 1M tokens) ───────────────────────────────────────
GEMINI_CONTEXT_LIMIT   = 1_000_000
COST_PER_1M_IN         = 0.30    # gemini-2.5-flash input
COST_PER_1M_OUT        = 2.50    # gemini-2.5-flash output
INTENT_COST_PER_1M_IN  = 0.075   # gemini-2.0-flash input (intent classification)
INTENT_COST_PER_1M_OUT = 0.30    # gemini-2.0-flash output (intent classification)

# ── Gemini client for lightweight classification calls ────────────────────────
_genai_client = None
if GEMINI_API_KEY:
    try:
        import google.genai as _genai_lib
        _genai_client = _genai_lib.Client(api_key=GEMINI_API_KEY)
    except Exception:
        pass

logging.basicConfig(level=logging.INFO)
