"""ShopRight Analytics Dashboard — Streamlit app.

Three sections (DevOps / Technical / Business) covering the same metrics
as the ADK analytics agents. Supports ?section=devops|tech|business deep links.
"""
from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery

GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
BQ_DATASET = "chat_analytics"


# ── BigQuery helpers ───────────────────────────────────────────────────────────

def _client() -> bigquery.Client:
    return bigquery.Client(project=GCP_PROJECT or None)


def _t(table: str) -> str:
    return f"`{GCP_PROJECT}.{BQ_DATASET}.{table}`"


@st.cache_data(ttl=300, show_spinner=False)
def _q(sql: str) -> pd.DataFrame:
    try:
        return _client().query(sql).to_dataframe()
    except Exception as exc:
        st.error(f"BigQuery error: {exc}")
        return pd.DataFrame()


def _scalar(df: pd.DataFrame, col: str, default=0):
    if df.empty or col not in df.columns:
        return default
    val = df[col].iloc[0]
    return default if pd.isna(val) else val


# ── Queries ───────────────────────────────────────────────────────────────────

def _devops_summary(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT
      COUNT(*)                                                                   AS total_requests,
      COUNT(DISTINCT session_id)                                                 AS total_sessions,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(AVG(COALESCE(ttft_ms,0)) AS INT64)                                   AS avg_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE OR scope_rejected=TRUE)*100.0, COUNT(*)), 2)
                                                                                 AS unanswered_rate_pct,
      COUNTIF(vulgar_flag = TRUE)                                                AS vulgar_blocks,
      COUNTIF(prompt_injection_flag = TRUE)                                      AS injection_blocks
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """)


def _devops_daily(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      COUNT(*)                                                                   AS requests,
      COUNT(DISTINCT session_id)                                                 AS sessions,
      ROUND(SAFE_DIVIDE(COUNTIF(llm_error=TRUE)*100.0, COUNT(*)), 2)            AS error_rate_pct,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(50)] AS INT64)               AS p50_latency_ms,
      CAST(APPROX_QUANTILES(latency_ms,100)[OFFSET(95)] AS INT64)               AS p95_latency_ms,
      CAST(AVG(COALESCE(ttft_ms,0)) AS INT64)                                   AS avg_ttft_ms,
      ROUND(SAFE_DIVIDE(COUNTIF(is_unanswered=TRUE OR scope_rejected=TRUE)*100.0, COUNT(*)), 2)
                                                                                 AS unanswered_rate_pct
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """)


def _tech_summary(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT
      ROUND(AVG(COALESCE(rag_confidence,0)), 4)                                 AS avg_rag_confidence,
      ROUND(SAFE_DIVIDE(COUNTIF(frustration_signal=TRUE)*100.0, COUNT(*)), 2)  AS frustration_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rec_gap=TRUE)*100.0, COUNT(*)), 2)             AS rec_gap_rate_pct,
      ROUND(SUM(COALESCE(estimated_cost_usd,0)), 4)                             AS total_cost_usd,
      ROUND(SAFE_DIVIDE(SUM(COALESCE(estimated_cost_usd,0)),
            COUNT(DISTINCT session_id)), 6)                                      AS cost_per_session_usd,
      ROUND(SAFE_DIVIDE(COUNTIF(hallucination_flag=TRUE)*100.0, COUNT(*)), 2)  AS citation_gap_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rerank_used=TRUE)*100.0, COUNT(*)), 2)         AS rerank_used_pct
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """)


def _tech_daily(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT
      DATE(timestamp)                                                            AS date,
      ROUND(AVG(COALESCE(rag_confidence,0)), 4)                                 AS avg_rag_confidence,
      ROUND(SAFE_DIVIDE(COUNTIF(frustration_signal=TRUE)*100.0, COUNT(*)), 2)  AS frustration_rate_pct,
      ROUND(SAFE_DIVIDE(COUNTIF(rec_gap=TRUE)*100.0, COUNT(*)), 2)             AS rec_gap_rate_pct,
      ROUND(SUM(COALESCE(estimated_cost_usd,0)), 6)                             AS cost_usd
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """)


def _tech_intents(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT COALESCE(intent, 'unknown') AS intent, COUNT(*) AS count
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY intent ORDER BY count DESC
    """)


def _tech_gaps(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT user_message, COALESCE(detected_category, 'Unknown') AS category, COUNT(*) AS frequency
    FROM {_t("chat_logs")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND is_unanswered = TRUE
    GROUP BY user_message, category
    ORDER BY frequency DESC LIMIT 15
    """)


def _biz_sat_summary(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT
      ROUND(AVG(stars), 2)                                                       AS avg_stars,
      COUNT(*)                                                                   AS total_reviews,
      ROUND(SAFE_DIVIDE(COUNTIF(stars>=4)*100.0, COUNT(*)), 2)                  AS positive_rate_pct
    FROM {_t("session_reviews")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """)


def _biz_sat_daily(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT DATE(timestamp) AS date, ROUND(AVG(stars), 2) AS avg_stars
    FROM {_t("session_reviews")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY date ORDER BY date
    """)


def _biz_feedback(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT ROUND(SAFE_DIVIDE(COUNTIF(rating=1)*100.0, COUNT(*)), 2) AS thumbs_up_rate_pct
    FROM {_t("feedback")}
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    """)


def _biz_conversion(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT e.date,
           ROUND(SAFE_DIVIDE(e.sessions_with_clicks * 100.0, t.total_sessions), 2) AS conversion_rate_pct
    FROM (
      SELECT DATE(timestamp) AS date, COUNT(DISTINCT session_id) AS sessions_with_clicks
      FROM {_t("chat_events")}
      WHERE event_type = 'chip_click'
        AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      GROUP BY date
    ) e
    LEFT JOIN (
      SELECT DATE(timestamp) AS date, COUNT(DISTINCT session_id) AS total_sessions
      FROM {_t("chat_logs")}
      WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      GROUP BY date
    ) t ON e.date = t.date
    ORDER BY e.date
    """)


def _biz_top_products(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT product_name, COUNT(*) AS clicks
    FROM {_t("chat_events")}
    WHERE event_type = 'chip_click'
      AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND product_name IS NOT NULL
    GROUP BY product_name ORDER BY clicks DESC LIMIT 10
    """)


def _biz_outcomes(days: int) -> pd.DataFrame:
    return _q(f"""
    SELECT outcome, COUNT(*) AS sessions,
           ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(), 2) AS pct
    FROM {_t("session_outcomes")}
    WHERE session_end_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY outcome ORDER BY sessions DESC
    """)


# ── Pages ──────────────────────────────────────────────────────────────────────

def _refresh_bar() -> None:
    """Inline refresh button — clears cache and reruns the app."""
    col, _ = st.columns([1, 8])
    with col:
        if st.button("🔄 Refresh", key=f"refresh_{st.session_state.get('_page', 'x')}"):
            st.cache_data.clear()
            st.rerun()


def devops_page(days: int) -> None:
    st.session_state["_page"] = "devops"
    col1, col2 = st.columns([6, 1])
    with col1:
        st.header("DevOps & Infrastructure")
    with col2:
        st.write("")  # vertical alignment nudge
        if st.button("🔄 Refresh", key="refresh_devops"):
            st.cache_data.clear()
            st.rerun()

    s = _devops_summary(days)
    daily = _devops_daily(days)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Total Requests", f"{int(_scalar(s, 'total_requests')):,}")
    with c2:
        st.metric("Sessions", f"{int(_scalar(s, 'total_sessions')):,}")
    with c3:
        val = _scalar(s, "error_rate_pct")
        icon = "🔴" if val > 2 else "🟡" if val > 0.5 else "🟢"
        st.metric("Error Rate", f"{icon} {val:.2f}%")
    with c4:
        val = int(_scalar(s, "p95_latency_ms"))
        icon = "🔴" if val > 8000 else "🟡" if val > 4000 else "🟢"
        st.metric("p95 Latency", f"{icon} {val:,} ms")
    with c5:
        val = _scalar(s, "unanswered_rate_pct")
        icon = "🔴" if val > 25 else "🟡" if val > 10 else "🟢"
        st.metric("Unanswered Rate", f"{icon} {val:.1f}%")

    if not daily.empty:
        st.subheader("Daily Request Volume & Error Rate")
        fig = go.Figure()
        fig.add_bar(x=daily["date"], y=daily["requests"], name="Requests", marker_color="#93c5fd")
        fig.add_scatter(x=daily["date"], y=daily["error_rate_pct"], name="Error Rate %",
                        yaxis="y2", line=dict(color="#dc2626", width=2))
        fig.update_layout(
            yaxis=dict(title="Requests"),
            yaxis2=dict(title="Error Rate %", overlaying="y", side="right"),
            legend=dict(orientation="h"),
            height=300, margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Latency Trend (ms)")
        fig2 = px.line(daily, x="date", y=["p50_latency_ms", "p95_latency_ms"],
                       color_discrete_map={"p50_latency_ms": "#3b82f6", "p95_latency_ms": "#1e3a5f"},
                       labels={"value": "ms", "variable": ""})
        fig2.add_hline(y=8000, line_dash="dash", line_color="#dc2626",
                       annotation_text="p95 critical (8 s)")
        fig2.update_layout(height=280, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Avg Time-to-First-Token (ms)")
        fig3 = px.area(daily, x="date", y="avg_ttft_ms", color_discrete_sequence=["#60a5fa"])
        fig3.add_hline(y=3000, line_dash="dash", line_color="#d97706",
                       annotation_text="TTFT threshold (3 s)")
        fig3.update_layout(height=250, margin=dict(t=10, b=10))
        st.plotly_chart(fig3, use_container_width=True)

    st.subheader("Security Events (period total)")
    c1, c2 = st.columns(2)
    with c1:
        val = int(_scalar(s, "vulgar_blocks"))
        st.metric("Vulgar Content Blocks", val)
    with c2:
        val = int(_scalar(s, "injection_blocks"))
        st.metric("Prompt Injection Blocks", val)


def tech_page(days: int) -> None:
    st.session_state["_page"] = "tech"
    col1, col2 = st.columns([6, 1])
    with col1:
        st.header("Technical / ML Performance")
    with col2:
        st.write("")
        if st.button("🔄 Refresh", key="refresh_tech"):
            st.cache_data.clear()
            st.rerun()

    s = _tech_summary(days)
    daily = _tech_daily(days)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        val = _scalar(s, "avg_rag_confidence")
        icon = "🔴" if val > 0.6 else "🟡" if val > 0.4 else "🟢"
        st.metric("RAG Confidence", f"{icon} {val:.3f}",
                  help="Cosine distance — lower is better. > 0.6 = poor retrieval.")
    with c2:
        val = _scalar(s, "frustration_rate_pct")
        icon = "🔴" if val > 15 else "🟡" if val > 8 else "🟢"
        st.metric("Frustration Rate", f"{icon} {val:.1f}%")
    with c3:
        val = _scalar(s, "rec_gap_rate_pct")
        icon = "🔴" if val > 10 else "🟡" if val > 5 else "🟢"
        st.metric("Rec Gap Rate", f"{icon} {val:.1f}%")
    with c4:
        st.metric("Total LLM Cost", f"${_scalar(s, 'total_cost_usd'):.4f}")
    with c5:
        val = _scalar(s, "citation_gap_rate_pct")
        icon = "🔴" if val > 5 else "🟢"
        st.metric("Citation Gap Rate", f"{icon} {val:.1f}%",
                  help="Heuristic proxy — bot had sources but may not have cited products.")

    if not daily.empty:
        st.subheader("RAG Confidence Over Time (cosine distance — lower is better)")
        fig = px.line(daily, x="date", y="avg_rag_confidence", color_discrete_sequence=["#7c3aed"])
        fig.add_hline(y=0.6, line_dash="dash", line_color="#dc2626",
                      annotation_text="Poor retrieval (> 0.6)")
        fig.add_hline(y=0.4, line_dash="dash", line_color="#d97706",
                      annotation_text="Moderate (> 0.4)")
        fig.update_layout(height=280, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Frustration & Recommendation Gap Rate (%)")
        fig2 = px.line(daily, x="date", y=["frustration_rate_pct", "rec_gap_rate_pct"],
                       color_discrete_map={"frustration_rate_pct": "#dc2626",
                                           "rec_gap_rate_pct": "#d97706"},
                       labels={"value": "%", "variable": ""})
        fig2.add_hline(y=15, line_dash="dash", line_color="#dc2626",
                       annotation_text="Frustration critical (15%)")
        fig2.update_layout(height=280, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Daily LLM Cost (USD)")
        fig3 = px.bar(daily, x="date", y="cost_usd", color_discrete_sequence=["#a78bfa"])
        fig3.update_layout(height=240, margin=dict(t=10, b=10))
        st.plotly_chart(fig3, use_container_width=True)

    intents = _tech_intents(days)
    if not intents.empty:
        st.subheader("Intent Distribution")
        fig4 = px.bar(intents, x="count", y="intent", orientation="h",
                      color_discrete_sequence=["#8b5cf6"])
        fig4.update_layout(height=max(250, len(intents) * 32), margin=dict(t=10, b=10),
                            yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig4, use_container_width=True)

    gaps = _tech_gaps(days)
    if not gaps.empty:
        st.subheader("Top Unanswered Messages (Catalog Gaps)")
        st.dataframe(gaps, use_container_width=True, hide_index=True)


def business_page(days: int) -> None:
    st.session_state["_page"] = "business"
    col1, col2 = st.columns([6, 1])
    with col1:
        st.header("Business Performance")
    with col2:
        st.write("")
        if st.button("🔄 Refresh", key="refresh_business"):
            st.cache_data.clear()
            st.rerun()

    sat = _biz_sat_summary(days)
    feedback = _biz_feedback(days)
    sat_daily = _biz_sat_daily(days)
    conversion = _biz_conversion(days)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        val = _scalar(sat, "avg_stars")
        icon = "🔴" if val < 3.0 else "🟡" if val < 4.0 else "🟢"
        st.metric("Avg Star Rating", f"{icon} {val:.1f} ★")
    with c2:
        val = _scalar(sat, "positive_rate_pct")
        icon = "🔴" if val < 50 else "🟡" if val < 70 else "🟢"
        st.metric("Positive Reviews (≥4★)", f"{icon} {val:.1f}%")
    with c3:
        val = _scalar(feedback, "thumbs_up_rate_pct")
        icon = "🔴" if val < 60 else "🟡" if val < 75 else "🟢"
        st.metric("Thumbs-Up Rate", f"{icon} {val:.1f}%",
                  help="Per-message 👍 rate — separate from star ratings.")
    with c4:
        conv_avg = conversion["conversion_rate_pct"].mean() if not conversion.empty else 0
        icon = "🔴" if conv_avg < 10 else "🟢"
        st.metric("Avg Chip Conversion", f"{icon} {conv_avg:.1f}%",
                  help="% of sessions where user clicked a product chip.")

    if not sat_daily.empty:
        st.subheader("Star Rating Over Time")
        fig = px.line(sat_daily, x="date", y="avg_stars", color_discrete_sequence=["#059669"])
        fig.add_hline(y=3.0, line_dash="dash", line_color="#dc2626",
                      annotation_text="Critical (< 3★)")
        fig.add_hline(y=4.0, line_dash="dash", line_color="#d97706",
                      annotation_text="Target (4★)")
        fig.update_yaxes(range=[0, 5.2])
        fig.update_layout(height=280, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    if not conversion.empty:
        st.subheader("Chip-Click Conversion Rate (%)")
        fig2 = px.area(conversion, x="date", y="conversion_rate_pct",
                       color_discrete_sequence=["#34d399"])
        fig2.add_hline(y=10, line_dash="dash", line_color="#d97706",
                       annotation_text="Target (10%)")
        fig2.update_layout(height=260, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        outcomes = _biz_outcomes(days)
        if not outcomes.empty:
            st.subheader("Session Outcomes")
            fig3 = px.pie(outcomes, names="outcome", values="sessions",
                          color_discrete_sequence=px.colors.qualitative.Set2)
            fig3.update_layout(height=300, margin=dict(t=10, b=10))
            st.plotly_chart(fig3, use_container_width=True)

    with col2:
        products = _biz_top_products(days)
        if not products.empty:
            st.subheader("Top Clicked Products")
            fig4 = px.bar(products, x="clicks", y="product_name", orientation="h",
                          color_discrete_sequence=["#10b981"])
            fig4.update_layout(height=300, margin=dict(t=10, b=10),
                               yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig4, use_container_width=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="ShopRight Analytics",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.sidebar.title("📊 ShopRight Analytics")
    st.sidebar.markdown("---")

    # Support ?section=devops|tech|business deep links from email reports
    _section_map = {"devops": "DevOps", "tech": "Technical", "business": "Business"}
    default = _section_map.get(st.query_params.get("section", "devops"), "DevOps")

    section = st.sidebar.radio(
        "Dashboard",
        ["DevOps", "Technical", "Business"],
        index=["DevOps", "Technical", "Business"].index(default),
    )

    st.sidebar.markdown("---")
    days = st.sidebar.selectbox(
        "Time range",
        [7, 14, 30, 90],
        format_func=lambda d: f"Last {d} days",
    )

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Project: `{GCP_PROJECT or 'not configured'}`")
    if st.sidebar.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

    if section == "DevOps":
        devops_page(days)
    elif section == "Technical":
        tech_page(days)
    else:
        business_page(days)


if __name__ == "__main__":
    main()
