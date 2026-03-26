"""
Single source of truth for all BigQuery SQL used by the analytics service.

Both app.py (Streamlit dashboard) and main.py (REST endpoints) import from here.
Every function returns a SQL string — execution stays in the caller.

Usage:
    from queries import devops_summary_sql
    sql = devops_summary_sql(project, dataset, days)
"""
from __future__ import annotations


def _t(project: str, dataset: str, table: str) -> str:
    return f"`{project}.{dataset}.{table}`"


# ── DevOps ─────────────────────────────────────────────────────────────────────

def devops_summary_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      COUNT(*)                                                                   AS total_requests,
      COUNT(DISTINCT session_id)                                                 AS total_sessions,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(AVG(COALESCE(ttft_ms,0)) AS INT64)                                   AS avg_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE)*100.0, COUNT(*)), 2)        AS unanswered_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(scope_rejected=TRUE)*100.0, COUNT(*)), 2)       AS scope_rejected_rate_pct,
      COUNTIF(vulgar_flag = TRUE)                                                AS vulgar_blocks,
      COUNTIF(prompt_injection_flag = TRUE)                                      AS injection_blocks
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def devops_daily_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      COUNT(*)                                                                   AS requests,
      COUNT(DISTINCT session_id)                                                 AS sessions,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(AVG(COALESCE(ttft_ms,0)) AS INT64)                                   AS avg_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE)*100.0, COUNT(*)), 2)        AS unanswered_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(scope_rejected=TRUE)*100.0, COUNT(*)), 2)       AS scope_rejected_rate_pct
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """


def devops_error_types_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      COALESCE(llm_error_type, 'unknown')                                        AS error_type,
      COUNT(*)                                                                   AS count
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND llm_error = TRUE
    GROUP BY error_type ORDER BY count DESC
    """


def devops_infra_daily_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      COUNT(*)                                                                   AS requests,
      COUNT(DISTINCT session_id)                                                 AS sessions,
      COUNTIF(llm_error = TRUE)                                                  AS errors,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(AVG(latency_ms) AS INT64)                                             AS avg_latency_ms
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """


def devops_infra_summary_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      COUNT(*)                                                                   AS total_requests,
      COUNT(DISTINCT session_id)                                                 AS total_sessions,
      COUNTIF(llm_error = TRUE)                                                  AS total_errors,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(AVG(latency_ms) AS INT64)                                             AS avg_latency_ms
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


# ── Technical / ML ─────────────────────────────────────────────────────────────

def tech_summary_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      ROUND(AVG(COALESCE(rag_confidence,0)), 4)                                 AS avg_rag_confidence,
      ROUND(SAFE_DIVIDE(COUNTIF(frustration_signal=TRUE)*100.0, COUNT(*)), 2)  AS frustration_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rec_gap=TRUE)*100.0, COUNT(*)), 2)             AS rec_gap_rate_pct,
      ROUND(SUM(COALESCE(estimated_cost_usd,0)), 4)                             AS total_cost_usd,
      ROUND(SAFE_DIVIDE(SUM(COALESCE(estimated_cost_usd,0)),
            COUNT(DISTINCT session_id)), 6)                                      AS cost_per_session_usd,
      ROUND(SAFE_DIVIDE(COUNTIF(hallucination_flag=TRUE)*100.0, COUNT(*)), 2)  AS citation_gap_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rerank_used=TRUE)*100.0, COUNT(*)), 2)         AS rerank_used_pct,
      ROUND(AVG(COALESCE(turn_number, 1)), 1)                                   AS avg_turn_number,
      ROUND(AVG(COALESCE(sources_count, 0)), 1)                                 AS avg_sources_count,
      ROUND(SAFE_DIVIDE(COUNTIF(query_rewritten=TRUE)*100.0, COUNT(*)), 2)     AS query_rewritten_rate_pct,
      COUNTIF(wellbeing_triggered=TRUE)                                          AS wellbeing_triggered_count,
      CAST(AVG(COALESCE(tokens_in, 0)) AS INT64)                                AS avg_tokens_in,
      CAST(AVG(COALESCE(tokens_out, 0)) AS INT64)                               AS avg_tokens_out,
      ROUND(AVG(COALESCE(context_pct, 0)), 2)                                   AS avg_context_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rag_empty=TRUE)*100.0, COUNT(*)), 2)           AS rag_empty_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(price_filter_used=TRUE)*100.0, COUNT(*)), 2)   AS price_filter_rate_pct,
      CAST(AVG(COALESCE(ann_candidates_count, 0)) AS INT64)                     AS avg_ann_candidates,
      ROUND(AVG(COALESCE(unique_brands_count, 0)), 1)                           AS avg_unique_brands
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def tech_daily_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      ROUND(AVG(COALESCE(rag_confidence,0)), 4)                                 AS avg_rag_confidence,
      ROUND(SAFE_DIVIDE(COUNTIF(frustration_signal=TRUE)*100.0, COUNT(*)), 2)  AS frustration_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rec_gap=TRUE)*100.0, COUNT(*)), 2)             AS rec_gap_rate_pct,
      ROUND(SUM(COALESCE(estimated_cost_usd,0)), 6)                             AS cost_usd
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """


def tech_latency_breakdown_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      CAST(AVG(COALESCE(embed_ms, 0)) AS INT64)                                 AS avg_embed_ms,
      CAST(AVG(COALESCE(db_ms, 0)) AS INT64)                                    AS avg_db_ms,
      CAST(AVG(COALESCE(llm_ms, 0)) AS INT64)                                   AS avg_llm_ms
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """


def tech_intents_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT COALESCE(intent, 'unknown') AS intent, COUNT(*) AS count
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY intent ORDER BY count DESC
    """


def tech_gaps_sql(project: str, dataset: str, days: int, limit: int = 15) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT user_message, COALESCE(detected_category, 'Unknown') AS category, COUNT(*) AS frequency
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND is_unanswered = TRUE
    GROUP BY user_message, category
    ORDER BY frequency DESC LIMIT {limit}
    """


def tech_model_daily_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      ROUND(SUM(COALESCE(estimated_cost_usd, 0)), 6)                            AS cost_usd,
      CAST(AVG(COALESCE(ttft_ms, 0)) AS INT64)                                  AS avg_ttft_ms,
      CAST(AVG(COALESCE(llm_ms, 0)) AS INT64)                                   AS avg_llm_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE OR scope_rejected=TRUE)*100.0,
            COUNT(*)), 2)                                                         AS unanswered_rate_pct,
      ROUND(AVG(COALESCE(rag_confidence, 0)), 4)                                 AS avg_rag_confidence,
      CAST(AVG(COALESCE(tokens_in, 0)) AS INT64)                                 AS avg_tokens_in,
      CAST(AVG(COALESCE(tokens_out, 0)) AS INT64)                                AS avg_tokens_out
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """


def tech_model_summary_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      ROUND(SUM(COALESCE(estimated_cost_usd, 0)), 4)                            AS total_cost_usd,
      ROUND(AVG(COALESCE(estimated_cost_usd, 0)) * 1000, 4)                     AS cost_per_1k_requests_usd,
      CAST(APPROX_QUANTILES(ttft_ms, 100)[OFFSET(95)] AS INT64)                 AS p95_ttft_ms,
      CAST(AVG(COALESCE(ttft_ms, 0)) AS INT64)                                  AS avg_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE OR scope_rejected=TRUE)*100.0,
            COUNT(*)), 2)                                                         AS unanswered_rate_pct,
      ROUND(AVG(COALESCE(rag_confidence, 0)), 4)                                 AS avg_rag_confidence,
      ROUND(SAFE_DIVIDE(COUNTIF(hallucination_flag=TRUE)*100.0, COUNT(*)), 2)   AS citation_gap_rate_pct,
      CAST(AVG(COALESCE(tokens_in, 0)) AS INT64)                                 AS avg_tokens_in,
      CAST(AVG(COALESCE(tokens_out, 0)) AS INT64)                                AS avg_tokens_out
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def tech_category_performance_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      COALESCE(detected_category, 'General')                                    AS category,
      COUNT(*)                                                                   AS requests,
      COUNTIF(is_unanswered = TRUE)                                              AS unanswered,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE)*100.0, COUNT(*)), 2)        AS unanswered_rate_pct,
      ROUND(AVG(COALESCE(rag_confidence, 0)), 4)                                 AS avg_rag_confidence
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY category ORDER BY requests DESC
    """


# ── Business ───────────────────────────────────────────────────────────────────

def biz_sat_summary_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "session_reviews")
    return f"""
    SELECT
      ROUND(AVG(stars), 2)                                                       AS avg_stars,
      COUNT(*)                                                                   AS total_reviews,
      ROUND(SAFE_DIVIDE(COUNTIF(stars>=4)*100.0, COUNT(*)), 2)                  AS positive_rate_pct
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def biz_sat_daily_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "session_reviews")
    return f"""
    SELECT DATE(timestamp) AS date, ROUND(AVG(stars), 2) AS avg_stars
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """


def biz_sat_full_summary_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "session_reviews")
    return f"""
    SELECT
      ROUND(AVG(stars), 2)                                                       AS avg_stars,
      COUNT(*)                                                                   AS total_reviews,
      COUNTIF(stars >= 4)                                                        AS positive_reviews,
      ROUND(SAFE_DIVIDE(COUNTIF(stars>=4)*100.0, COUNT(*)), 2)                  AS positive_rate_pct
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def biz_feedback_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "feedback")
    return f"""
    SELECT ROUND(SAFE_DIVIDE(COUNTIF(rating=1)*100.0, COUNT(*)), 2) AS thumbs_up_rate_pct
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def biz_feedback_full_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "feedback")
    return f"""
    SELECT
      COUNTIF(rating = 1)                                                        AS thumbs_up,
      COUNTIF(rating = -1)                                                       AS thumbs_down,
      COUNT(*)                                                                   AS total_feedback,
      ROUND(SAFE_DIVIDE(COUNTIF(rating=1)*100.0, COUNT(*)), 2)                  AS positive_rate_pct
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def biz_conversion_sql(project: str, dataset: str, days: int) -> str:
    te = _t(project, dataset, "chat_events")
    tl = _t(project, dataset, "chat_logs")
    return f"""
    SELECT e.date,
           ROUND(SAFE_DIVIDE(e.sessions_with_clicks*100.0, t.total_sessions), 2) AS conversion_rate_pct
    FROM (
      SELECT DATE(timestamp) AS date, COUNT(DISTINCT session_id) AS sessions_with_clicks
      FROM {te}
      WHERE event_type = 'chip_click'
        AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      GROUP BY date
    ) e
    LEFT JOIN (
      SELECT DATE(timestamp) AS date, COUNT(DISTINCT session_id) AS total_sessions
      FROM {tl}
      WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      GROUP BY date
    ) t ON e.date = t.date
    ORDER BY e.date
    """


def biz_conversion_raw_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_events")
    return f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      COUNT(*)                                                                   AS chip_clicks,
      COUNT(DISTINCT session_id)                                                 AS sessions_with_clicks
    FROM {t}
    WHERE event_type = 'chip_click'
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """


def biz_top_products_sql(project: str, dataset: str, days: int, limit: int = 10) -> str:
    t = _t(project, dataset, "chat_events")
    return f"""
    SELECT product_name, COUNT(*) AS clicks
    FROM {t}
    WHERE event_type = 'chip_click'
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND product_name IS NOT NULL
    GROUP BY product_name ORDER BY clicks DESC LIMIT {limit}
    """


def biz_category_demand_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      COALESCE(detected_category, 'Unknown')                                    AS category,
      COUNT(*)                                                                   AS requests,
      ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER (), 1)                            AS pct
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND detected_category IS NOT NULL
    GROUP BY category ORDER BY requests DESC LIMIT 12
    """


def biz_outcomes_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "session_outcomes")
    return f"""
    SELECT outcome, COUNT(*) AS sessions,
           ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(), 2) AS pct
    FROM {t}
    WHERE session_end_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY outcome ORDER BY sessions DESC
    """


# ── General ────────────────────────────────────────────────────────────────────

def overview_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      COUNT(*)                                                                   AS total_messages,
      COUNT(DISTINCT session_id)                                                 AS unique_sessions,
      AVG(message_length)                                                        AS avg_message_length,
      AVG(response_length)                                                       AS avg_response_length,
      AVG(sources_count)                                                         AS avg_sources_per_response,
      COUNTIF(sources_count = 0)                                                 AS messages_without_rag,
      COUNTIF(sources_count > 0)                                                 AS messages_with_rag
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """


def top_questions_sql(project: str, dataset: str, days: int, limit: int = 20) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      user_message,
      COUNT(*)                                                                   AS frequency,
      AVG(sources_count)                                                         AS avg_rag_sources
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY user_message
    ORDER BY frequency DESC
    LIMIT {limit}
    """


def daily_volume_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      COUNT(*)                                                                   AS messages,
      COUNT(DISTINCT session_id)                                                 AS sessions
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date DESC
    """


def rag_performance_sql(project: str, dataset: str, days: int) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      sources_count,
      COUNT(*)                                                                   AS message_count,
      ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER (), 2)                            AS percentage
    FROM {t}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY sources_count ORDER BY sources_count
    """


def top_products_mentioned_sql(project: str, dataset: str, days: int, limit: int = 10) -> str:
    t = _t(project, dataset, "chat_logs")
    return f"""
    SELECT
      JSON_EXTRACT_SCALAR(src, '$.name')  AS product_name,
      JSON_EXTRACT_SCALAR(src, '$.price') AS price,
      COUNT(*)                            AS mentions
    FROM {t},
    UNNEST(JSON_EXTRACT_ARRAY(sources_used)) AS src
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND sources_used IS NOT NULL
    GROUP BY product_name, price
    ORDER BY mentions DESC
    LIMIT {limit}
    """
