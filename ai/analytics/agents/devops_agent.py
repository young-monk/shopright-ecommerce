"""
DevOps Analytics Agent — infrastructure health, error rates, latency, security events.
Audience: engineers and on-call SREs.
"""
from __future__ import annotations

import os
from datetime import date

from google.adk.agents import LlmAgent

from tools.bq_tools import get_devops_metrics
from tools.gmail_tool import send_email
from tools.gemini_summary import gemini_narrative
from tools.dashboard_tool import get_dashboard_devops_url

DEVOPS_EMAIL = os.getenv("DEVOPS_EMAIL", "hallyalasridhar@gmail.com")

_CSS = """<style>
body{font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;margin:0;padding:0}
.wrap{max-width:680px;margin:24px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.header{background:#1e293b;color:#fff;padding:24px 32px}
.header h1{margin:0;font-size:20px;font-weight:700}
.header p{margin:6px 0 0;font-size:13px;color:#94a3b8}
.body{padding:24px 32px;font-size:14px;color:#374151;line-height:1.7}
.dashboard{background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:12px 16px;margin-bottom:20px}
.body h2{font-size:15px;color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:5px;margin-top:24px}
.body ul{padding-left:20px;margin:8px 0}
.body li{margin-bottom:6px}
.body ol{padding-left:20px;margin:8px 0}
.footer{background:#f8fafc;padding:14px 32px;font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0}
a{color:#2563eb}
</style>"""


def generate_and_send_devops_report(days: int = 7, recipient_email: str = "") -> str:
    """
    Pull DevOps metrics from BigQuery, generate an AI-written analysis,
    and email it with the Streamlit dashboard link.

    Args:
        days: Number of days of data to include (default 7).
        recipient_email: Override destination email; falls back to DEVOPS_EMAIL env var.

    Returns:
        Summary string confirming what was sent and key headline metrics.
    """
    to = recipient_email or DEVOPS_EMAIL
    data = get_devops_metrics(days)
    s = data.get("summary", {})

    narrative = gemini_narrative(data, "devops", days)

    dash = get_dashboard_devops_url()
    if dash["configured"]:
        dashboard = (
            f'<div class="dashboard">'
            f'&#128202; <a href="{dash["url"]}"><strong>View live DevOps dashboard &rarr;</strong></a>'
            f'</div>'
        )
    else:
        dashboard = (
            '<div class="dashboard" style="background:#fafafa;border-color:#e2e8f0">'
            '&#128202; <span style="color:#94a3b8">Streamlit dashboard not yet configured &mdash; '
            'set <code>DASHBOARD_URL</code> to enable.</span>'
            '</div>'
        )

    today = date.today().isoformat()
    html = f"""<!DOCTYPE html><html><head>{_CSS}</head><body>
<div class="wrap">
  <div class="header">
    <h1>ShopRight Chatbot &mdash; DevOps Report</h1>
    <p>Last {days} days &nbsp;&middot;&nbsp; Generated {today}</p>
  </div>
  <div class="body">
    {dashboard}
    {narrative}
  </div>
  <div class="footer">ShopRight Analytics &nbsp;&middot;&nbsp; Auto-generated &nbsp;&middot;&nbsp; Do not reply</div>
</div></body></html>"""

    result = send_email(to=to, subject=f"[ShopRight DevOps] Chatbot Report — {today}", html_body=html)
    err_pct = float(s.get("error_rate_pct") or 0)
    if result["success"]:
        return (f"DevOps report sent to {to} covering {days} days. "
                f"Requests: {s.get('total_requests', 0):,}, "
                f"Error rate: {err_pct:.2f}%, "
                f"p95 latency: {s.get('p95_latency_ms', 0):,}ms")
    return f"DevOps report failed to send: {result.get('error')}"


_DEVOPS_INSTRUCTION = """You are the DevOps Analytics Agent for the ShopRight chatbot platform.
Your audience is engineers and on-call SREs who need infrastructure health information.

You have two types of tools:

1. **Report tool** — generate_and_send_devops_report(days, recipient_email)
   Use this when the user asks to "run", "send", or "generate" a report.
   It queries BigQuery, generates an AI analysis, and emails it with the Streamlit dashboard link.

2. **BigQuery query tools** (via MCP Toolbox) — named queries like get_devops_daily,
   get_devops_summary, get_devops_error_types, get_devops_security_events, etc.
   Use these for ad-hoc questions like "what was the error rate yesterday?" or
   "show me latency trends for the past 2 weeks".

3. **get_dashboard_devops_url** — returns the Streamlit dashboard link.
   Include this link in any response that involves metrics.

Key metric thresholds to call out:
- Error rate > 2%: critical — investigate immediately
- p95 latency > 8000ms: slow — check Gemini API or Cloud Run scaling
- Unanswered rate > 25%: high — likely catalog gaps
- TTFT > 3000ms average: elevated — may indicate cold starts or LLM quota pressure
- Injection attempts spike: security incident — alert the team
"""


def make_devops_agent(toolbox_tools: list) -> LlmAgent:
    """Factory that creates the DevOps agent."""
    return LlmAgent(
        name="devops_agent",
        model="gemini-3.1-pro-preview",
        description="DevOps analytics agent for infrastructure health, error rates, latency and security events.",
        instruction=_DEVOPS_INSTRUCTION,
        tools=toolbox_tools + [
            generate_and_send_devops_report,
            get_dashboard_devops_url,
        ],
    )
