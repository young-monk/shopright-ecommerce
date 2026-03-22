"""
Local embedding module — replaces Gemini embedding API calls.

Uses sentence-transformers with multi-qa-mpnet-base-dot-v1 as the base model
(768 dims, pre-trained on QA pairs, matches existing pgvector index).

After fine-tuning with finetune/train.py, set LOCAL_EMBED_MODEL env var to
point at the fine-tuned model directory and it will be loaded automatically.

Inference: ~10-20ms on CPU vs ~150ms for the Gemini API call.
"""
import os
import asyncio
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Fine-tuned model takes priority; falls back to the base model.
_MODEL_DIR = os.getenv("LOCAL_EMBED_MODEL", "./models/shopright-embed")
_BASE_MODEL = "multi-qa-mpnet-base-dot-v1"

_model = None


def _load():
    global _model
    if _model is not None:
        return
    from sentence_transformers import SentenceTransformer
    if os.path.exists(_MODEL_DIR):
        logger.info(f"[embed] Loading fine-tuned model from {_MODEL_DIR}")
        _model = SentenceTransformer(_MODEL_DIR)
    else:
        logger.info(f"[embed] Fine-tuned model not found at {_MODEL_DIR}, using base: {_BASE_MODEL}")
        _model = SentenceTransformer(_BASE_MODEL)
    logger.info(f"[embed] Model ready — dim={_model.get_sentence_embedding_dimension()}")


def embed_sync(text: str) -> list[float]:
    """Synchronous embed — call via run_in_executor from async code."""
    _load()
    vec = _model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    return vec.tolist()


async def embed(text: str) -> list[float]:
    """Async embed — runs inference in a thread so it doesn't block the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, embed_sync, text)


def preload():
    """Call once at startup to load the model before the first request."""
    _load()
