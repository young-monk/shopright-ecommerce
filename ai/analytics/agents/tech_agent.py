"""
Technical Analytics Agent — RAG quality, embeddings, token cost, intent/frustration.
Audience: ML engineers and technical stakeholders.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from google.adk.agents import LlmAgent

from tools.bq_tools import get_tech_metrics
from tools.chart_tools import (make_line_chart, make_dual_line_chart,
                                make_bar_chart, make_pie_chart, img_tag)
from tools.gmail_tool import send_email
from tools.gemini_summary import gemini_narrative
from tools.looker_tool import get_looker_tech_url

TECH_EMAIL = os.getenv("TECH_EMAIL", "hallyalasridhar@gmail.com")

_CSS = """
<style>
body{font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;margin:0;padding:0}
.wrap{max-width:700px;margin:24px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.header{background:#1e3a5f;color:#fff;padding:24px 32px}
.header h1{margin:0;font-size:22px;font-weight:700}
.header p{margin:4px 0 0;font-size:13px;color:#93c5fd}
.body{padding:24px 32px}
.kpi-row{display:flex;gap:12px;margin:16px 0;flex-wrap:wrap}
.kpi{flex:1;min-width:120px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;text-align:center}
.kpi .val{font-size:24px;font-weight:700;color:#1e293b}
.kpi .lbl{font-size:11px;color:#64748b;margin-top:4px}
.kpi.red .val{color:#dc2626} .kpi.green .val{color:#16a34a} .kpi.amber .val{color:#d97706}
h2{font-size:16px;color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin-top:28px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
th{background:#f1f5f9;padding:8px 10px;text-align:left;color:#475569;font-weight:600}
td{padding:7px 10px;border-bottom:1px solid #f1f5f9;color:#374151}
tr:hover td{background:#f8fafc}
.footer{background:#f8fafc;padding:16px 32px;font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0}
a{color:#2563eb}
</style>
"""


def _kpi(val: Any, label: str, cls: str = "") -> str:
    return f'<div class="kpi {cls}"><div class="val">{val}</div><div class="lbl">{label}</div></div>'


def _gaps_table(gaps: list[dict]) -> str:
    if not gaps:
        return "<p style='color:#64748b;font-size:13px'>No unanswered queries this period.</p>"
    rows = "".join(
        f"<tr><td>{g.get('user_message','')[:80]}</td>"
        f"<td>{g.get('category','')}</td>"
        f"<td style='text-align:right'>{g.get('frequency',0)}</td></tr>"
        for g in gaps[:10]
    )
    return f"<table><tr><th>Query</th><th>Category</th><th>Count</th></tr>{rows}</table>"


def generate_and_send_tech_report(days: int = 7, recipient_email: str = "") -> str:
    """
    Pull technical/ML metrics from BigQuery, build an HTML report with embedded charts,
    and email it to the technical stakeholders. Use this when asked to run or send
    the technical analytics report.

    Args:
        days: Number of days of data to include (default 7).
        recipient_email: Override destination email; falls back to TECH_EMAIL env var.

    Returns:
        Summary string confirming what was sent and key headline metrics.
    """
    to = recipient_email or TECH_EMAIL
    data = get_tech_metrics(days)
    s = data.get("summary", {})
    daily = data.get("daily", [])
    intent = data.get("intent_distribution", [])
    gaps = data.get("catalog_gaps", [])

    rag_chart      = make_line_chart(daily, "date", "avg_rag_confidence",
                                     f"Avg RAG Confidence (last {days}d)", "Score", "#10B981")
    embed_chart    = make_line_chart(daily, "date", "avg_min_vec_distance",
                                     "Avg Min Vector Distance (lower = better)", "Distance", "#8B5CF6")
    cost_chart     = make_line_chart(daily, "date", "cost_usd",
                                     "Daily LLM Cost (USD)", "USD", "#F59E0B")
    token_chart    = make_dual_line_chart(daily, "date",
                                          value_keys=["avg_tokens_in", "avg_tokens_out"],
                                          labels=["tokens_in", "tokens_out"],
                                          title="Avg Tokens per Turn",
                                          colors=["#2563EB", "#DC2626"])
    frust_chart    = make_line_chart(daily, "date", "frustration_rate_pct",
                                     "Frustration Rate % per Day", "%", "#EF4444")
    intent_chart   = ""
    if intent:
        intent_chart = make_pie_chart(
            [r.get("intent", "unknown") for r in intent],
            [float(r.get("count", 0)) for r in intent],
            "Intent Distribution",
        )

    rag_conf   = float(s.get("avg_rag_confidence") or 0)
    frust_rate = float(s.get("frustration_rate_pct") or 0)
    kpis = "".join([
        _kpi(f'{rag_conf:.3f}', "Avg RAG Confidence",
             "green" if rag_conf > 0.7 else ("amber" if rag_conf > 0.5 else "red")),
        _kpi(f'{float(s.get("avg_min_vec_distance") or 0):.4f}', "Avg Vec Distance"),
        _kpi(f'${float(s.get("total_cost_usd") or 0):.4f}', "Total Cost (USD)"),
        _kpi(f'${float(s.get("cost_per_session_usd") or 0):.6f}', "Cost / Session"),
        _kpi(f'{frust_rate:.1f}%', "Frustration Rate",
             "red" if frust_rate > 15 else ("amber" if frust_rate > 8 else "")),
        _kpi(f'{float(s.get("hallucination_rate_pct") or 0):.1f}%', "Hallucination Rate",
             "red" if float(s.get("hallucination_rate_pct") or 0) > 5 else ""),
        _kpi(f'{float(s.get("rec_gap_rate_pct") or 0):.1f}%', "Rec Gap Rate"),
    ])

    narrative = gemini_narrative(s, "tech", days)

    looker = get_looker_tech_url()
    looker_link = (f'<p><a href="{looker["url"]}">View live Technical dashboard in Looker Studio →</a></p>'
                   if looker["configured"] else "")

    today = date.today().isoformat()
    html = f"""<!DOCTYPE html><html><head>{_CSS}</head><body>
<div class="wrap">
  <div class="header">
    <h1>ShopRight Chatbot — Technical Report</h1>
    <p>Last {days} days &nbsp;·&nbsp; Generated {today}</p>
  </div>
  <div class="body">
    <h2>Summary KPIs</h2>
    <div class="kpi-row">{kpis}</div>
    {narrative}
    <h2>RAG Confidence Score</h2>{img_tag(rag_chart)}
    <h2>Embedding Quality — Min Vector Distance</h2>{img_tag(embed_chart)}
    <p style="font-size:12px;color:#64748b">Lower distance = better retrieval. Rising trend = embedding drift.</p>
    <h2>LLM Cost Trend</h2>{img_tag(cost_chart)}
    <p style="font-size:12px;color:#64748b">
      Total: ${float(s.get("total_cost_usd",0)):.4f} &nbsp;|&nbsp;
      Per session: ${float(s.get("cost_per_session_usd",0)):.6f} &nbsp;|&nbsp;
      Tokens in: {int(s.get("total_tokens_in",0)):,} &nbsp;|&nbsp;
      Tokens out: {int(s.get("total_tokens_out",0)):,}
    </p>
    <h2>Token Usage per Turn</h2>{img_tag(token_chart)}
    <h2>Frustration Rate</h2>{img_tag(frust_chart)}
    <h2>Intent Distribution</h2>{img_tag(intent_chart)}
    <h2>Top Catalog Gaps (Unanswered Queries)</h2>{_gaps_table(gaps)}
    {looker_link}
  </div>
  <div class="footer">ShopRight Analytics &nbsp;·&nbsp; Auto-generated &nbsp;·&nbsp; Do not reply</div>
</div></body></html>"""

    result = send_email(to=to, subject=f"[ShopRight Tech] Chatbot Report — {today}", html_body=html)
    if result["success"]:
        return (f"Technical report sent to {to} covering {days} days. "
                f"RAG confidence: {rag_conf:.3f}, "
                f"Cost: ${float(s.get('total_cost_usd',0)):.4f}, "
                f"Frustration rate: {frust_rate:.1f}%")
    return f"Technical report failed to send: {result.get('error')}"


_TECH_INSTRUCTION = """You are the Technical Analytics Agent for the ShopRight chatbot platform.
Your audience is ML engineers and data scientists who need deep technical performance data.

You have two types of tools:

1. **Report tool** — generate_and_send_tech_report(days, recipient_email)
   Use this when the user asks to "run", "send", or "generate" a technical report.
   It queries BigQuery, makes charts, and emails the full HTML report.

2. **BigQuery query tools** (via MCP Toolbox) — named queries like get_tech_rag_daily,
   get_tech_cost_summary, get_tech_intent_distribution, get_tech_catalog_gaps, etc.
   Use these for ad-hoc questions like "what is our RAG confidence this week?" or
   "show me which categories have the worst retrieval quality".

3. **get_looker_tech_url** — returns the Looker Studio dashboard link.
   Include this link in any detailed metric response.

Key thresholds to flag:
- RAG confidence < 0.5: poor retrieval — check embedding model or catalog quality
- Min vector distance trending up: embedding drift — consider re-embedding
- Cost per session > $0.01: high — check context window usage or token budget
- Frustration rate > 15%: critical UX signal
- Hallucination rate > 5%: model quality issue
- Context pct p95 > 0.85: risk of context truncation
"""


def make_tech_agent(toolbox_tools: list) -> LlmAgent:
    """
    Factory that creates the Tech agent, combining MCP Toolbox BQ tools
    (for interactive queries) with the composite report function.
    """
    return LlmAgent(
        name="tech_agent",
        model="gemini-2.5-flash",
        description="Technical ML analytics agent covering RAG quality, embeddings, token cost, and intent analysis.",
        instruction=_TECH_INSTRUCTION,
        tools=toolbox_tools + [
            generate_and_send_tech_report,
            get_looker_tech_url,
        ],
    )
