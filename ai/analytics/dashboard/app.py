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

from queries import (
    devops_summary_sql, devops_daily_sql, devops_error_types_sql,
    tech_summary_sql, tech_daily_sql, tech_latency_breakdown_sql,
    tech_intents_sql, tech_gaps_sql,
    biz_sat_summary_sql, biz_sat_daily_sql, biz_feedback_sql,
    biz_conversion_sql, biz_top_products_sql, biz_category_demand_sql,
    biz_outcomes_sql,
)

GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
BQ_DATASET = "chat_analytics"


# ── BigQuery helpers ───────────────────────────────────────────────────────────

def _client() -> bigquery.Client:
    return bigquery.Client(project=GCP_PROJECT or None)


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


# ── Query wrappers (delegate SQL to queries.py) ────────────────────────────────

def _devops_summary(days: int) -> pd.DataFrame:
    return _q(devops_summary_sql(GCP_PROJECT, BQ_DATASET, days))

def _devops_daily(days: int) -> pd.DataFrame:
    return _q(devops_daily_sql(GCP_PROJECT, BQ_DATASET, days))

def _devops_error_types(days: int) -> pd.DataFrame:
    return _q(devops_error_types_sql(GCP_PROJECT, BQ_DATASET, days))

def _tech_summary(days: int) -> pd.DataFrame:
    return _q(tech_summary_sql(GCP_PROJECT, BQ_DATASET, days))

def _tech_daily(days: int) -> pd.DataFrame:
    return _q(tech_daily_sql(GCP_PROJECT, BQ_DATASET, days))

def _tech_latency_breakdown(days: int) -> pd.DataFrame:
    return _q(tech_latency_breakdown_sql(GCP_PROJECT, BQ_DATASET, days))

def _tech_intents(days: int) -> pd.DataFrame:
    return _q(tech_intents_sql(GCP_PROJECT, BQ_DATASET, days))

def _tech_gaps(days: int) -> pd.DataFrame:
    return _q(tech_gaps_sql(GCP_PROJECT, BQ_DATASET, days))

def _biz_sat_summary(days: int) -> pd.DataFrame:
    return _q(biz_sat_summary_sql(GCP_PROJECT, BQ_DATASET, days))

def _biz_sat_daily(days: int) -> pd.DataFrame:
    return _q(biz_sat_daily_sql(GCP_PROJECT, BQ_DATASET, days))

def _biz_feedback(days: int) -> pd.DataFrame:
    return _q(biz_feedback_sql(GCP_PROJECT, BQ_DATASET, days))

def _biz_conversion(days: int) -> pd.DataFrame:
    return _q(biz_conversion_sql(GCP_PROJECT, BQ_DATASET, days))

def _biz_top_products(days: int) -> pd.DataFrame:
    return _q(biz_top_products_sql(GCP_PROJECT, BQ_DATASET, days))

def _biz_category_demand(days: int) -> pd.DataFrame:
    return _q(biz_category_demand_sql(GCP_PROJECT, BQ_DATASET, days))

def _biz_outcomes(days: int) -> pd.DataFrame:
    return _q(biz_outcomes_sql(GCP_PROJECT, BQ_DATASET, days))


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

    # ── Row 1: volume & reliability ──────────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Total Requests", f"{int(_scalar(s, 'total_requests')):,}",
                  help="Total chat messages sent by users in the selected period.")
    with c2:
        st.metric("Sessions", f"{int(_scalar(s, 'total_sessions')):,}",
                  help="Unique chat sessions (conversations) started in the period.")
    with c3:
        val = _scalar(s, "error_rate_pct")
        icon = "🔴" if val > 2 else "🟡" if val > 0.5 else "🟢"
        st.metric("Error Rate", f"{icon} {val:.2f}%",
                  help="% of requests where the LLM returned an error. 🟢 ≤ 0.5% · 🟡 ≤ 2% · 🔴 > 2%")
    with c4:
        val = int(_scalar(s, "p95_latency_ms"))
        icon = "🔴" if val > 8000 else "🟡" if val > 4000 else "🟢"
        st.metric("p95 Latency", f"{icon} {val:,} ms",
                  help="95th-percentile end-to-end response time. 🟢 < 4 s · 🟡 < 8 s · 🔴 ≥ 8 s")
    with c5:
        val = _scalar(s, "unanswered_rate_pct")
        icon = "🔴" if val > 20 else "🟡" if val > 10 else "🟢"
        st.metric("Unanswered Rate", f"{icon} {val:.1f}%",
                  help="% of messages the bot genuinely couldn't answer (no relevant products or knowledge). Excludes out-of-scope rejections. 🟢 ≤ 10% · 🟡 ≤ 20% · 🔴 > 20%")
    with c6:
        val = _scalar(s, "scope_rejected_rate_pct")
        icon = "🔴" if val > 15 else "🟡" if val > 5 else "🟢"
        st.metric("Scope Rejected Rate", f"{icon} {val:.1f}%",
                  help="% of messages the bot refused because they were outside its domain (e.g. asking for recipes, weather, or other non-home-improvement topics). High values may mean the scope prompt is too restrictive. 🟢 ≤ 5% · 🟡 ≤ 15% · 🔴 > 15%")

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

        st.subheader("Unanswered vs Scope-Rejected Rate (%)")
        fig4 = px.line(daily, x="date",
                       y=["unanswered_rate_pct", "scope_rejected_rate_pct"],
                       color_discrete_map={"unanswered_rate_pct": "#f59e0b",
                                           "scope_rejected_rate_pct": "#8b5cf6"},
                       labels={"value": "%", "variable": ""})
        fig4.for_each_trace(lambda t: t.update(
            name={"unanswered_rate_pct": "Unanswered",
                  "scope_rejected_rate_pct": "Scope Rejected"}[t.name]
        ))
        fig4.update_layout(height=260, margin=dict(t=10, b=10))
        st.plotly_chart(fig4, use_container_width=True)

    col_sec, col_err = st.columns(2)
    with col_sec:
        st.subheader("Security Events (period total)")
        sc1, sc2 = st.columns(2)
        with sc1:
            val = int(_scalar(s, "vulgar_blocks"))
            st.metric("Vulgar Content Blocks", val,
                      help="Messages blocked because they contained profanity or abusive language. Any non-zero value should be reviewed.")
        with sc2:
            val = int(_scalar(s, "injection_blocks"))
            st.metric("Prompt Injection Blocks", val,
                      help="Messages blocked because they attempted to override the bot's instructions (e.g. 'ignore all previous instructions'). Any non-zero value should be reviewed.")
    with col_err:
        error_types = _devops_error_types(days)
        if not error_types.empty:
            st.subheader("Error Type Breakdown")
            fig_err = px.bar(error_types, x="count", y="error_type", orientation="h",
                             color_discrete_sequence=["#f87171"])
            fig_err.update_layout(height=max(180, len(error_types) * 40),
                                  margin=dict(t=10, b=10),
                                  yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_err, use_container_width=True)


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
    latency_bd = _tech_latency_breakdown(days)

    # ── Row 1: Retrieval & answer quality ─────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        val = _scalar(s, "avg_rag_confidence")
        icon = "🔴" if val > 0.6 else "🟡" if val > 0.4 else "🟢"
        st.metric("RAG Confidence", f"{icon} {val:.3f}",
                  help="Cosine distance between query and retrieved docs — lower is better. 🟢 ≤ 0.4 · 🟡 ≤ 0.6 · 🔴 > 0.6")
    with c2:
        val = _scalar(s, "rag_empty_rate_pct")
        icon = "🔴" if val > 10 else "🟡" if val > 3 else "🟢"
        st.metric("RAG Empty Rate", f"{icon} {val:.1f}%",
                  help="% of queries where vector search returned zero results — harder gap than rec_gap (wrong products; this means no products at all). 🟢 ≤ 3% · 🟡 ≤ 10% · 🔴 > 10%")
    with c3:
        val = _scalar(s, "avg_unique_brands")
        icon = "🟢" if val >= 2 else "🟡"
        st.metric("Avg Brands / Query", f"{icon} {val:.1f}",
                  help="Average number of distinct brands in retrieved results per query. Low diversity may mean the catalog is brand-concentrated. 🟢 ≥ 2 · 🟡 < 2")
    with c4:
        val = _scalar(s, "citation_gap_rate_pct")
        icon = "🔴" if val > 5 else "🟢"
        st.metric("Citation Gap Rate", f"{icon} {val:.1f}%",
                  help="Heuristic: bot had RAG sources but product names didn't appear in its response — proxy for hallucination. 🟢 ≤ 5% · 🔴 > 5%")
    with c5:
        val = _scalar(s, "rec_gap_rate_pct")
        icon = "🔴" if val > 10 else "🟡" if val > 5 else "🟢"
        st.metric("Rec Gap Rate", f"{icon} {val:.1f}%",
                  help="% of messages where no product matched what the user asked for — proxy for catalog coverage gaps. 🟢 ≤ 5% · 🟡 ≤ 10% · 🔴 > 10%")

    # ── Row 2: Cost, tokens & engagement ──────────────────────────────────────
    t1, t2, t3, t4, t5 = st.columns(5)
    with t1:
        val = _scalar(s, "frustration_rate_pct")
        icon = "🔴" if val > 15 else "🟡" if val > 8 else "🟢"
        st.metric("Frustration Rate", f"{icon} {val:.1f}%",
                  help="% of messages where the user showed frustration signals (repeated rephrasing, negative sentiment). 🟢 ≤ 8% · 🟡 ≤ 15% · 🔴 > 15%")
    with t2:
        st.metric("Total LLM Cost", f"${_scalar(s, 'total_cost_usd'):.4f}",
                  help="Estimated Gemini API cost for the period, based on tokens in/out at published rates.")
    with t3:
        val = int(_scalar(s, "avg_tokens_in"))
        st.metric("Avg Tokens In", f"{val:,}",
                  help="Average input token count per message (user message + history + RAG context). Grows with conversation depth. Watch for spikes approaching the 1M context limit.")
    with t4:
        val = int(_scalar(s, "avg_tokens_out"))
        st.metric("Avg Tokens Out", f"{val:,}",
                  help="Average output token count per message. Higher values = longer bot responses. Directly drives LLM cost.")
    with t5:
        val = _scalar(s, "avg_turn_number")
        icon = "🟢" if val >= 3 else "🟡"
        st.metric("Avg Turn Depth", f"{icon} {val:.1f}",
                  help="Average turn number within a session — measures conversation engagement. Higher = more engaged users. 🟢 ≥ 3 turns · 🟡 < 3 turns")

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

    if not latency_bd.empty:
        st.subheader("Latency Breakdown by Component (avg ms per day)")
        fig_lb = px.area(
            latency_bd, x="date",
            y=["avg_embed_ms", "avg_db_ms", "avg_llm_ms"],
            color_discrete_map={
                "avg_embed_ms": "#60a5fa",
                "avg_db_ms":    "#34d399",
                "avg_llm_ms":   "#f59e0b",
            },
            labels={"value": "ms", "variable": "Component"},
        )
        fig_lb.for_each_trace(lambda t: t.update(
            name={"avg_embed_ms": "Embed", "avg_db_ms": "Vector DB", "avg_llm_ms": "LLM"}[t.name]
        ))
        fig_lb.update_layout(height=280, margin=dict(t=10, b=10))
        st.plotly_chart(fig_lb, use_container_width=True)

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
    tech = _tech_summary(days)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        val = _scalar(sat, "avg_stars")
        icon = "🔴" if val < 3.0 else "🟡" if val < 4.0 else "🟢"
        st.metric("Avg Star Rating", f"{icon} {val:.1f} ★",
                  help="Average star rating left by users at the end of a session (1–5 stars). 🟢 ≥ 4.0 · 🟡 ≥ 3.0 · 🔴 < 3.0")
    with c2:
        val = _scalar(sat, "positive_rate_pct")
        icon = "🔴" if val < 50 else "🟡" if val < 70 else "🟢"
        st.metric("Positive Reviews (≥4★)", f"{icon} {val:.1f}%",
                  help="% of session reviews with 4 or 5 stars. 🟢 ≥ 70% · 🟡 ≥ 50% · 🔴 < 50%")
    with c3:
        val = _scalar(feedback, "thumbs_up_rate_pct")
        icon = "🔴" if val < 60 else "🟡" if val < 75 else "🟢"
        st.metric("Thumbs-Up Rate", f"{icon} {val:.1f}%",
                  help="% of individual bot responses that received a 👍 reaction. Measures per-message quality, not overall session satisfaction — distinct from star ratings. 🟢 ≥ 75% · 🟡 ≥ 60% · 🔴 < 60%")
    with c4:
        conv_avg = conversion["conversion_rate_pct"].mean() if not conversion.empty else 0
        icon = "🔴" if conv_avg < 10 else "🟢"
        st.metric("Avg Chip Conversion", f"{icon} {conv_avg:.1f}%",
                  help="% of sessions where the user clicked at least one product chip (add-to-cart intent signal). Calculated as sessions-with-clicks ÷ total-sessions. 🟢 ≥ 10% · 🔴 < 10%")
    with c5:
        val = _scalar(tech, "cost_per_session_usd")
        icon = "🔴" if val > 0.01 else "🟡" if val > 0.005 else "🟢"
        st.metric("Cost / Session", f"{icon} ${val:.5f}",
                  help="Average Gemini API cost per unique session. Calculated as total token cost ÷ total sessions. 🟢 < $0.005 · 🟡 < $0.01 · 🔴 ≥ $0.01")

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

    products = _biz_top_products(days)
    if not products.empty:
        st.subheader("Top Clicked Products")
        fig4 = px.bar(products, x="clicks", y="product_name", orientation="h",
                      color_discrete_sequence=["#10b981"])
        fig4.update_layout(height=300, margin=dict(t=10, b=10),
                           yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig4, use_container_width=True)

    biz_col1, biz_col2 = st.columns(2)
    with biz_col1:
        intents = _tech_intents(days)
        if not intents.empty:
            _INTENT_LABELS = {
                "product_search": "Product Search",
                "DIY_advice": "DIY Advice",
                "price_comparison": "Price Comparison",
                "how_to_use": "How-To / Install",
                "complaint": "Complaint",
                "general_info": "General Info",
                "availability_check": "Availability Check",
                "troubleshooting": "Troubleshooting",
                "general_chat": "General Chat",
                "unknown": "Unknown",
            }
            intents["label"] = intents["intent"].map(lambda x: _INTENT_LABELS.get(x, x))
            st.subheader("What Are Customers Asking About?")
            fig5 = px.pie(intents, names="label", values="count",
                          color_discrete_sequence=px.colors.qualitative.Pastel)
            fig5.update_traces(textposition="inside", textinfo="percent+label")
            fig5.update_layout(height=360, margin=dict(t=10, b=10), showlegend=False)
            st.plotly_chart(fig5, use_container_width=True)

    with biz_col2:
        cat_demand = _biz_category_demand(days)
        if not cat_demand.empty:
            st.subheader("Top Categories by Demand")
            fig6 = px.bar(cat_demand, x="requests", y="category", orientation="h",
                          text="pct",
                          color_discrete_sequence=["#6366f1"])
            fig6.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig6.update_layout(height=max(280, len(cat_demand) * 30),
                               margin=dict(t=10, b=10, r=60),
                               yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig6, use_container_width=True)


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
