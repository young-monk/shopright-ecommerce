"""Shared mutable state accessed by multiple chatbot modules."""
from __future__ import annotations

import contextvars

import asyncpg

# asyncpg connection pool — initialised at startup, None until then
_db_pool: asyncpg.Pool | None = None

# In-memory metrics ring buffer (last 1000 requests)
_req_metrics: list[dict] = []

# Pass tool results from ADK search_products back to the SSE generator.
# ContextVar writes inside child tasks (how ADK calls tools) don't propagate
# back to the parent task. Fix: use a module-level dict keyed by message_id;
# store the ID in a ContextVar (reads are safe across task boundaries).
_cv_message_id: contextvars.ContextVar[str] = contextvars.ContextVar("message_id", default="")
_sources_store:  dict[str, list] = {}
_rag_meta_store: dict[str, dict] = {}
