"""Intent classification and recommendation-gap detection."""
from __future__ import annotations

import logging

from config import _genai_client

logger = logging.getLogger(__name__)

_INTENT_LABELS = (
    "product_lookup",
    "project_advice",
    "compatibility",
    "pricing_availability",
    "troubleshooting",
    "general_chat",
)
_INTENT_PROMPT = (
    "Classify the following customer message into exactly one of these intent labels:\n"
    + ", ".join(_INTENT_LABELS)
    + "\n\nRespond with only the label — no explanation.\n\nMessage: "
)
_TARGET_PROMPT = (
    "Extract the specific product, material, or topic the customer is asking about in 1-5 words. "
    "Examples: 'cordless drill', 'deck lumber', 'garbage disposal', 'bathroom tile', 'paint primer'. "
    "If the message is general or a greeting, respond with 'general'. "
    "Respond with only the extracted term — no explanation.\n\nMessage: "
)


async def classify_intent(message: str) -> tuple[str, int, int]:
    """Returns (label, tokens_in, tokens_out)."""
    if not _genai_client:
        return "unknown", 0, 0
    try:
        resp = await _genai_client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=_INTENT_PROMPT + message[:500],
        )
        label = resp.text.strip().lower().split()[0].rstrip(".,")
        usage = resp.usage_metadata
        tokens_in  = getattr(usage, "prompt_token_count", 0) or 0
        tokens_out = getattr(usage, "candidates_token_count", 0) or 0
        return (label if label in _INTENT_LABELS else "unknown"), tokens_in, tokens_out
    except Exception as e:
        logger.warning(f"Intent classification failed: {e}")
        return "unknown", 0, 0


async def extract_intent_target(message: str) -> tuple[str, int, int]:
    """Returns (target, tokens_in, tokens_out)."""
    if not _genai_client:
        return "", 0, 0
    try:
        resp = await _genai_client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=_TARGET_PROMPT + message[:500],
        )
        usage = resp.usage_metadata
        tokens_in  = getattr(usage, "prompt_token_count", 0) or 0
        tokens_out = getattr(usage, "candidates_token_count", 0) or 0
        return resp.text.strip()[:100], tokens_in, tokens_out
    except Exception as e:
        logger.warning(f"Intent target extraction failed: {e}")
        return "", 0, 0


def compute_rec_gap(user_intent_target: str, sources: list, is_unanswered: bool) -> bool:
    """True when the bot surfaced products but none matched what the user wanted."""
    if not user_intent_target or user_intent_target.lower() in ("general", ""):
        return False
    if is_unanswered:
        return True
    if not sources:
        return False
    target_words = set(user_intent_target.lower().split())
    for s in sources:
        name = (s.get("name", "") if isinstance(s, dict) else getattr(s, "name", "")).lower()
        if any(w in name for w in target_words):
            return False
    return True
