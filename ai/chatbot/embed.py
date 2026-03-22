"""
Local embedding module — replaces Gemini embedding API calls.

Uses sentence-transformers with multi-qa-mpnet-base-dot-v1 as the base model
(768 dims, pre-trained on QA pairs, matches existing pgvector index).

After fine-tuning with finetune/train.py, set LOCAL_EMBED_MODEL env var to
point at the fine-tuned model directory and it will be loaded automatically.

Inference: ~10-20ms on CPU vs ~150ms for the Gemini API call.
"""
import os
import time
import asyncio
import logging

logger = logging.getLogger(__name__)

# Fine-tuned model takes priority; falls back to the base model.
_MODEL_DIR = os.getenv("LOCAL_EMBED_MODEL", "./models/shopright-embed")
_BASE_MODEL = "multi-qa-mpnet-base-dot-v1"

_model = None
_model_name: str = ""  # set once on load, read by model_name()


def _load():
    global _model, _model_name
    if _model is not None:
        return
    from sentence_transformers import SentenceTransformer
    if os.path.exists(_MODEL_DIR):
        logger.info(f"[embed] Loading fine-tuned model from {_MODEL_DIR}")
        _model = SentenceTransformer(_MODEL_DIR)
        _model_name = os.path.basename(os.path.abspath(_MODEL_DIR))
    else:
        logger.info(f"[embed] Fine-tuned model not found at {_MODEL_DIR}, using base: {_BASE_MODEL}")
        _model = SentenceTransformer(_BASE_MODEL)
        _model_name = _BASE_MODEL
    logger.info(f"[embed] Model ready — name={_model_name} dim={_model.get_sentence_embedding_dimension()}")


def model_name() -> str:
    """Return the name of the currently loaded model."""
    _load()
    return _model_name


def embed_sync(text: str) -> tuple[list[float], int]:
    """Synchronous embed. Returns (vector, embed_ms)."""
    _load()
    t0 = time.monotonic()
    vec = _model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    embed_ms = int((time.monotonic() - t0) * 1000)
    return vec.tolist(), embed_ms


async def embed(text: str) -> tuple[list[float], int]:
    """Async embed — runs inference in a thread so it doesn't block the event loop.
    Returns (vector, embed_ms)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, embed_sync, text)


def preload():
    """Call once at startup to load the model before the first request."""
    _load()
