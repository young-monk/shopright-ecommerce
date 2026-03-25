"""BigQuery logging for chat events, feedback, and analytics."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from google.cloud import bigquery

from config import GCP_PROJECT, BQ_DATASET, BQ_TABLE, BQ_FEEDBACK_TABLE, INTENT_COST_PER_1M_IN, INTENT_COST_PER_1M_OUT
from detection import detect_frustration, _session_prev_message
from intent import classify_intent, extract_intent_target, compute_rec_gap
import state

logger = logging.getLogger(__name__)


async def log_to_bigquery(
    session_id, message_id, user_message, assistant_response,
    sources, latency_ms, is_unanswered, extra: dict | None = None,
):
    if not GCP_PROJECT:
        return
    try:
        # Derive: previous turn unanswered (for frustration detection)
        prev_unanswered = next(
            (m.get("is_unanswered", False) for m in reversed(state._req_metrics)
             if m.get("session_id") == session_id and m.get("message_id") != message_id),
            False,
        )
        frustration_signal, frustration_reason = detect_frustration(user_message, session_id, prev_unanswered)

        # Batch the two Gemini classification calls
        (intent, intent_in, intent_out), (user_intent_target, target_in, target_out) = \
            await asyncio.gather(
                classify_intent(user_message),
                extract_intent_target(user_message),
            )

        rec_gap = compute_rec_gap(user_intent_target, sources, is_unanswered)

        # Update sliding prev-message window after classification
        _session_prev_message[session_id] = user_message

        row = {
            "session_id": session_id, "message_id": message_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_message": user_message, "assistant_response": assistant_response,
            "sources_used": json.dumps(sources if isinstance(sources[0], dict) else [s.model_dump() for s in sources]) if sources else "[]",
            "message_length": len(user_message), "response_length": len(assistant_response),
            "sources_count": len(sources), "latency_ms": latency_ms, "is_unanswered": is_unanswered,
            "intent": intent,
            "frustration_signal": frustration_signal,
            "frustration_reason": frustration_reason,
            "user_intent_target": user_intent_target,
            "rec_gap": rec_gap,
        }
        if extra:
            row.update(extra)
        intent_cost = (
            (intent_in + target_in)  / 1e6 * INTENT_COST_PER_1M_IN +
            (intent_out + target_out) / 1e6 * INTENT_COST_PER_1M_OUT
        )
        row["estimated_cost_usd"] = round((row.get("estimated_cost_usd") or 0) + intent_cost, 8)
        bq = bigquery.Client(project=GCP_PROJECT)
        errors = bq.insert_rows_json(f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}", [row])
        if errors:
            logger.error(f"BigQuery insert errors for {message_id}: {errors}")
    except Exception as e:
        logger.error(f"Failed to log to BigQuery: {e}")


async def log_feedback_to_bigquery(
    message_id, session_id, rating, user_message, assistant_response,
    turn_number=None, detected_category=None,
):
    if not GCP_PROJECT:
        return
    try:
        row = {
            "message_id": message_id, "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rating": rating, "user_message": user_message or "",
            "assistant_response": assistant_response or "",
        }
        if turn_number is not None:
            row["turn_number"] = turn_number
        if detected_category is not None:
            row["detected_category"] = detected_category
        bq = bigquery.Client(project=GCP_PROJECT)
        bq.insert_rows_json(f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_FEEDBACK_TABLE}", [row])
    except Exception as e:
        logger.error(f"Failed to log feedback to BigQuery: {e}")
