"""BigQuery query tools — called by ADK analytics agents."""
from __future__ import annotations

import os
from typing import Any

from google.cloud import bigquery

GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
BQ_DATASET = "chat_analytics"


def _client() -> bigquery.Client:
    return bigquery.Client(project=GCP_PROJECT)


def _q(sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in _client().query(sql).result()]


def _t(table: str) -> str:
    return f"`{GCP_PROJECT}.{BQ_DATASET}.{table}`"


# ── DevOps ────────────────────────────────────────────────────────────────────

def get_devops_metrics(days: int = 7) -> dict[str, Any]:
    """
    Get infrastructure/DevOps metrics for the last N days:
    daily request volume, error rate, p50/p95 latency, TTFT, unanswered rate,
    vulgar content blocks, and prompt injection blocks.
    """
    daily_sql = f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      COUNT(*)                                                                   AS requests,
      COUNT(DISTINCT session_id)                                                 AS sessions,
      COUNTIF(llm_error = TRUE)                                                  AS errors,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(AVG(COALESCE(ttft_ms,0)) AS INT64)                                   AS avg_ttft_ms,
      CAST(APPROX_QUANTILES(COALESCE(ttft_ms,0),100)[OFFSET(95)] AS INT64)     AS p95_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE)*100.0, COUNT(*)), 2)        AS unanswered_rate_pct,
      COUNTIF(vulgar_flag = TRUE)                                                AS vulgar_blocks,
      COUNTIF(prompt_injection_flag = TRUE)                                      AS injection_blocks
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    summary_sql = f"""
    SELECT
      COUNT(*)                                                                   AS total_requests,
      COUNT(DISTINCT session_id)                                                 AS total_sessions,
      COUNTIF(llm_error = TRUE)                                                  AS total_errors,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(AVG(latency_ms) AS INT64)                                             AS avg_latency_ms,
      CAST(AVG(COALESCE(ttft_ms,0)) AS INT64)                                   AS avg_ttft_ms,
      CAST(APPROX_QUANTILES(COALESCE(ttft_ms,0),100)[OFFSET(95)] AS INT64)     AS p95_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE)*100.0, COUNT(*)), 2)        AS unanswered_rate_pct,
      COUNTIF(vulgar_flag = TRUE)                                                AS total_vulgar_blocks,
      COUNTIF(prompt_injection_flag = TRUE)                                      AS total_injection_blocks
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    daily = _q(daily_sql)
    summary = _q(summary_sql)
    return {
        "period_days": days,
        "summary": summary[0] if summary else {},
        "daily": daily,
    }


# ── Technical ─────────────────────────────────────────────────────────────────

def get_tech_metrics(days: int = 7) -> dict[str, Any]:
    """
    Get technical/ML metrics for the last N days:
    RAG confidence, embedding quality (min_vec_distance), token usage,
    cost per session, intent distribution, frustration rate, and catalog gaps.
    """
    daily_sql = f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      ROUND(AVG(COALESCE(rag_confidence,0)), 4)                                 AS avg_rag_confidence,
      ROUND(AVG(COALESCE(min_vec_distance,0)), 4)                               AS avg_min_vec_distance,
      CAST(AVG(COALESCE(tokens_in,0)) AS INT64)                                 AS avg_tokens_in,
      CAST(AVG(COALESCE(tokens_out,0)) AS INT64)                                AS avg_tokens_out,
      ROUND(SUM(COALESCE(estimated_cost_usd,0)), 6)                             AS cost_usd,
      ROUND(SAFE_DIVIDE(COUNTIF(frustration_signal=TRUE)*100.0, COUNT(*)), 2)  AS frustration_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rerank_used=TRUE)*100.0, COUNT(*)), 2)         AS rerank_used_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rec_gap=TRUE)*100.0, COUNT(*)), 2)             AS rec_gap_rate_pct,
      CAST(AVG(COALESCE(ann_candidates_count,0)) AS INT64)                      AS avg_ann_candidates
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    summary_sql = f"""
    SELECT
      ROUND(AVG(COALESCE(rag_confidence,0)), 4)                                 AS avg_rag_confidence,
      ROUND(AVG(COALESCE(min_vec_distance,0)), 4)                               AS avg_min_vec_distance,
      CAST(SUM(COALESCE(tokens_in,0)) AS INT64)                                 AS total_tokens_in,
      CAST(SUM(COALESCE(tokens_out,0)) AS INT64)                                AS total_tokens_out,
      ROUND(SUM(COALESCE(estimated_cost_usd,0)), 4)                             AS total_cost_usd,
      ROUND(SAFE_DIVIDE(SUM(COALESCE(estimated_cost_usd,0)),
            COUNT(DISTINCT session_id)), 6)                                      AS cost_per_session_usd,
      ROUND(SAFE_DIVIDE(COUNTIF(frustration_signal=TRUE)*100.0, COUNT(*)), 2)  AS frustration_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rerank_used=TRUE)*100.0, COUNT(*)), 2)         AS rerank_used_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rec_gap=TRUE)*100.0, COUNT(*)), 2)             AS rec_gap_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(hallucination_flag=TRUE)*100.0, COUNT(*)), 2)  AS hallucination_rate_pct
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    intent_sql = f"""
    SELECT
      COALESCE(intent, 'unknown')     AS intent,
      COUNT(*)                         AS count,
      ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(), 2) AS pct
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY intent
    ORDER BY count DESC
    """
    gaps_sql = f"""
    SELECT
      user_message,
      COALESCE(detected_category, 'Unknown') AS category,
      COUNT(*) AS frequency
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND is_unanswered = TRUE
    GROUP BY user_message, category
    ORDER BY frequency DESC
    LIMIT 15
    """
    daily = _q(daily_sql)
    summary = _q(summary_sql)
    intent = _q(intent_sql)
    gaps = _q(gaps_sql)
    return {
        "period_days": days,
        "summary": summary[0] if summary else {},
        "daily": daily,
        "intent_distribution": intent,
        "catalog_gaps": gaps,
    }


# ── Business ──────────────────────────────────────────────────────────────────

def get_business_metrics(days: int = 30) -> dict[str, Any]:
    """
    Get business metrics for the last N days:
    satisfaction (stars), chip-click conversion, session outcomes,
    top products mentioned, recommendation gap, and intent trends.
    """
    satisfaction_sql = f"""
    SELECT
      DATE(timestamp)               AS date,
      ROUND(AVG(stars), 2)          AS avg_stars,
      COUNT(*)                       AS review_count,
      COUNTIF(stars >= 4)            AS positive_count,
      COUNTIF(stars <= 2)            AS negative_count
    FROM {_t("session_reviews")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    satisfaction_summary_sql = f"""
    SELECT
      ROUND(AVG(stars), 2)          AS avg_stars,
      COUNT(*)                       AS total_reviews,
      COUNTIF(stars >= 4)            AS positive_reviews,
      COUNTIF(stars <= 2)            AS negative_reviews,
      ROUND(SAFE_DIVIDE(COUNTIF(stars>=4)*100.0, COUNT(*)), 2) AS positive_rate_pct
    FROM {_t("session_reviews")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    conversion_sql = f"""
    SELECT
      DATE(timestamp)                       AS date,
      COUNT(*)                               AS chip_clicks,
      COUNT(DISTINCT session_id)             AS sessions_with_clicks
    FROM {_t("chat_events")}
    WHERE event_type = 'chip_click'
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date
    ORDER BY date
    """
    top_products_sql = f"""
    SELECT
      product_name,
      SUM(1) AS clicks
    FROM {_t("chat_events")}
    WHERE event_type = 'chip_click'
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND product_name IS NOT NULL
    GROUP BY product_name
    ORDER BY clicks DESC
    LIMIT 10
    """
    outcomes_sql = f"""
    SELECT
      outcome,
      COUNT(*) AS sessions,
      ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(), 2) AS pct
    FROM {_t("session_outcomes")}
    WHERE session_end_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY outcome
    ORDER BY sessions DESC
    """
    feedback_sql = f"""
    SELECT
      COUNTIF(rating=1)  AS thumbs_up,
      COUNTIF(rating=-1) AS thumbs_down,
      COUNT(*)            AS total_feedback,
      ROUND(SAFE_DIVIDE(COUNTIF(rating=1)*100.0, COUNT(*)), 2) AS positive_rate_pct
    FROM {_t("feedback")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """
    sat_trend = _q(satisfaction_sql)
    sat_summary = _q(satisfaction_summary_sql)
    conversion = _q(conversion_sql)
    top_products = _q(top_products_sql)
    outcomes = _q(outcomes_sql)
    feedback = _q(feedback_sql)
    return {
        "period_days": days,
        "satisfaction_summary": sat_summary[0] if sat_summary else {},
        "feedback_summary": feedback[0] if feedback else {},
        "satisfaction_trend": sat_trend,
        "conversion_trend": conversion,
        "top_products": top_products,
        "session_outcomes": outcomes,
    }
