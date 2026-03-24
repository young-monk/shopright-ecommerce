"""
Technical Analytics Agent — RAG quality, embeddings, token cost, intent/frustration.
Audience: ML engineers and technical stakeholders.
"""
from __future__ import annotations

import os
from datetime import date

from google.adk.agents import LlmAgent

from tools.bq_tools import get_tech_metrics
from tools.gmail_tool import send_email
from tools.gemini_summary import gemini_narrative
from tools.looker_tool import get_looker_tech_url

TECH_EMAIL = os.getenv("TECH_EMAIL", "hallyalasridhar@gmail.com")

_CSS = """<style>
body{font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;margin:0;padding:0}
.wrap{max-width:680px;margin:24px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.header{background:#1e3a5f;color:#fff;padding:24px 32px}
.header h1{margin:0;font-size:20px;font-weight:700}
.header p{margin:6px 0 0;font-size:13px;color:#93c5fd}
.body{padding:24px 32px;font-size:14px;color:#374151;line-height:1.7}
.dashboard{background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:12px 16px;margin-bottom:20px}
.body h2{font-size:15px;color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:5px;margin-top:24px}
.body ul{padding-left:20px;margin:8px 0}
.body li{margin-bottom:6px}
.body ol{padding-left:20px;margin:8px 0}
.footer{background:#f8fafc;padding:14px 32px;font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0}
a{color:#2563eb}
</style>"""


def generate_and_send_tech_report(days: int = 7, recipient_email: str = "") -> str:
    """
    Pull technical/ML metrics from BigQuery, generate an AI-written analysis,
    and email it with the Looker Studio dashboard link.

    Args:
        days: Number of days of data to include (default 7).
        recipient_email: Override destination email; falls back to TECH_EMAIL env var.

    Returns:
        Summary string confirming what was sent and key headline metrics.
    """
    to = recipient_email or TECH_EMAIL
    data = get_tech_metrics(days)
    s = data.get("summary", {})

    narrative = gemini_narrative(data, "tech", days)

    looker = get_looker_tech_url()
    if looker["configured"]:
        dashboard = (
            f'<div class="dashboard">'
            f'&#128202; <a href="{looker["url"]}"><strong>View live Technical dashboard in Looker Studio &rarr;</strong></a>'
            f'</div>'
        )
    else:
        dashboard = (
            '<div class="dashboard" style="background:#fafafa;border-color:#e2e8f0">'
            '&#128202; <span style="color:#94a3b8">Looker Studio dashboard not yet configured &mdash; '
            'set <code>LOOKER_STUDIO_TECH_URL</code> to enable.</span>'
            '</div>'
        )

    today = date.today().isoformat()
    html = f"""<!DOCTYPE html><html><head>{_CSS}</head><body>
<div class="wrap">
  <div class="header">
    <h1>ShopRight Chatbot &mdash; Technical Report</h1>
    <p>Last {days} days &nbsp;&middot;&nbsp; Generated {today}</p>
  </div>
  <div class="body">
    {dashboard}
    {narrative}
  </div>
  <div class="footer">ShopRight Analytics &nbsp;&middot;&nbsp; Auto-generated &nbsp;&middot;&nbsp; Do not reply</div>
</div></body></html>"""

    result = send_email(to=to, subject=f"[ShopRight Tech] Chatbot Report — {today}", html_body=html)
    rag_conf = float(s.get("avg_rag_confidence") or 0)
    if result["success"]:
        return (f"Technical report sent to {to} covering {days} days. "
                f"RAG confidence: {rag_conf:.3f}, "
                f"Cost: ${float(s.get('total_cost_usd', 0)):.4f}, "
                f"Frustration rate: {float(s.get('frustration_rate_pct', 0)):.1f}%")
    return f"Technical report failed to send: {result.get('error')}"


_TECH_INSTRUCTION = """You are the Technical Analytics Agent for the ShopRight chatbot platform.
Your audience is ML engineers and data scientists who need deep technical performance data.

You have two types of tools:

1. **Report tool** — generate_and_send_tech_report(days, recipient_email)
   Use this when the user asks to "run", "send", or "generate" a technical report.
   It queries BigQuery, generates an AI analysis, and emails it with the Looker dashboard link.

2. **BigQuery query tools** (via MCP Toolbox) — named queries like get_tech_rag_daily,
   get_tech_cost_summary, get_tech_intent_distribution, get_tech_catalog_gaps, etc.
   Use these for ad-hoc questions like "what is our RAG confidence this week?" or
   "show me which categories have the worst retrieval quality".

3. **get_looker_tech_url** — returns the Looker Studio dashboard link.
   Include this link in any detailed metric response.

Key thresholds to flag:
- RAG confidence is COSINE DISTANCE — lower is better, not higher:
  > 0.6: poor retrieval — check embedding model or catalog quality
  0.4–0.6: moderate
  < 0.4: good (do NOT flag low values as a problem)
- Min vector distance trending UP week-over-week: embedding drift — consider re-embedding
- Rerank used pct < 80%: Cohere rerank may be failing — check API key/quota
- Cost per session > $0.01: high — check context window usage or token budget
- Frustration rate > 15%: critical UX signal
- Citation gap rate (hallucination_flag) > 5%: bot not citing retrieved products — heuristic proxy, not true hallucination detection
- Context pct p95 > 0.85: risk of context truncation
"""


def make_tech_agent(toolbox_tools: list) -> LlmAgent:
    """Factory that creates the Tech agent."""
    return LlmAgent(
        name="tech_agent",
        model="gemini-3.1-pro-preview",
        description="Technical ML analytics agent covering RAG quality, embeddings, token cost, and intent analysis.",
        instruction=_TECH_INSTRUCTION,
        tools=toolbox_tools + [
            generate_and_send_tech_report,
            get_looker_tech_url,
        ],
    )
