"""
Embedding module — uses Google Gemini embedding API (gemini-embedding-001).

Native 3072-dimensional output, no truncation needed.
Task types: RETRIEVAL_DOCUMENT (ingest) vs RETRIEVAL_QUERY (search).
"""
import os
import time
import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_EMBED_MODEL = "gemini-embedding-001"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def model_name() -> str:
    return _EMBED_MODEL


def embed_sync(text: str, task_type: str = "RETRIEVAL_QUERY") -> tuple[list[float], int]:
    """Synchronous embed via Gemini REST API. Returns (vector, embed_ms)."""
    t0 = time.monotonic()
    url = f"{_GEMINI_BASE}/models/{_EMBED_MODEL}:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": f"models/{_EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
    }
    with httpx.Client(timeout=15) as client:
        resp = client.post(url, json=payload)
    embed_ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code == 200:
        vec = resp.json()["embedding"]["values"]
        return vec, embed_ms
    logger.warning(f"[embed] Gemini embed error {resp.status_code}: {resp.text[:200]}")
    return [], embed_ms


async def embed(text: str, task_type: str = "RETRIEVAL_QUERY") -> tuple[list[float], int]:
    """Async embed — delegates to sync version in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, embed_sync, text, task_type)


def preload():
    """No-op: Gemini API has no warm-up cost. Kept for API compatibility."""
    logger.info(f"[embed] Using Gemini API model: {_EMBED_MODEL} (3072 dims)")
