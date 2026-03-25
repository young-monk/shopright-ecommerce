"""
Business Analytics Agent — satisfaction, conversion, session outcomes, top products.
Audience: product managers, business stakeholders, and executives.
"""
from __future__ import annotations

import os
from datetime import date

from google.adk.agents import LlmAgent

from tools.bq_tools import get_business_metrics
from tools.gmail_tool import send_email
from tools.gemini_summary import gemini_narrative
from tools.dashboard_tool import get_dashboard_business_url

BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "hallyalasridhar@gmail.com")

_CSS = """<style>
body{font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;margin:0;padding:0}
.wrap{max-width:680px;margin:24px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.header{background:#065f46;color:#fff;padding:24px 32px}
.header h1{margin:0;font-size:20px;font-weight:700}
.header p{margin:6px 0 0;font-size:13px;color:#6ee7b7}
.body{padding:24px 32px;font-size:14px;color:#374151;line-height:1.7}
.dashboard{background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:12px 16px;margin-bottom:20px}
.body h2{font-size:15px;color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:5px;margin-top:24px}
.body ul{padding-left:20px;margin:8px 0}
.body li{margin-bottom:6px}
.body ol{padding-left:20px;margin:8px 0}
.footer{background:#f8fafc;padding:14px 32px;font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0}
a{color:#065f46}
</style>"""


def generate_and_send_business_report(days: int = 30, recipient_email: str = "") -> str:
    """
    Pull business metrics from BigQuery, generate an AI-written analysis,
    and email it with the Streamlit dashboard link.

    Args:
        days: Number of days of data to include (default 30 for business cadence).
        recipient_email: Override destination email; falls back to BUSINESS_EMAIL env var.

    Returns:
        Summary string confirming what was sent and key headline metrics.
    """
    to = recipient_email or BUSINESS_EMAIL
    data = get_business_metrics(days)
    sat = data.get("satisfaction_summary", {})

    narrative = gemini_narrative(data, "business", days)

    dash = get_dashboard_business_url()
    if dash["configured"]:
        dashboard = (
            f'<div class="dashboard">'
            f'&#128202; <a href="{dash["url"]}"><strong>View live Business dashboard &rarr;</strong></a>'
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
    <h1>ShopRight Chatbot &mdash; Business Report</h1>
    <p>Last {days} days &nbsp;&middot;&nbsp; Generated {today}</p>
  </div>
  <div class="body">
    {dashboard}
    {narrative}
  </div>
  <div class="footer">ShopRight Analytics &nbsp;&middot;&nbsp; Auto-generated &nbsp;&middot;&nbsp; Do not reply</div>
</div></body></html>"""

    result = send_email(to=to, subject=f"[ShopRight Business] Chatbot Report — {today}", html_body=html)
    avg_stars = float(sat.get("avg_stars") or 0)
    pos_rate = float(sat.get("positive_rate_pct") or 0)
    if result["success"]:
        return (f"Business report sent to {to} covering {days} days. "
                f"Avg stars: {avg_stars:.1f}, "
                f"Positive rate: {pos_rate:.1f}%")
    return f"Business report failed to send: {result.get('error')}"


_BUSINESS_INSTRUCTION = """You are the Business Analytics Agent for the ShopRight chatbot platform.
Your audience is product managers and executives who need business performance data in plain language.

You have two types of tools:

1. **Report tool** — generate_and_send_business_report(days, recipient_email)
   Use this when the user asks to "run", "send", or "generate" a business report.
   Default to 30 days for business reporting cadence.

2. **BigQuery query tools** (via MCP Toolbox) — named queries like get_business_satisfaction_daily,
   get_business_top_products, get_business_session_outcomes, get_business_conversion_funnel, etc.
   Use these for ad-hoc questions like "which products had the most clicks this month?" or
   "what was our session success rate last week?".

3. **get_dashboard_business_url** — returns the Streamlit dashboard link.
   Always include this in your responses.

Present numbers in plain business language — avoid technical jargon.
Key thresholds to flag:
- Avg star rating < 3.0: critical customer satisfaction issue
- Session failure rate > 30%: immediate attention needed
- Positive review rate (stars ≥ 4 sessions) < 50%: business risk
- Thumbs-up rate (thumbs_up_rate_pct) < 60%: per-message response quality concern — distinct from star ratings
- Chip-click conversion_rate_pct (% of sessions where user clicked a product) < 10%: low product engagement
- Chip-click conversion_rate_pct declining for 2+ weeks: recommend product catalog review
"""


def make_business_agent(toolbox_tools: list) -> LlmAgent:
    """Factory that creates the Business agent."""
    return LlmAgent(
        name="business_agent",
        model="gemini-3.1-pro-preview",
        description="Business analytics agent for satisfaction scores, conversion, session outcomes, and top products.",
        instruction=_BUSINESS_INSTRUCTION,
        tools=toolbox_tools + [
            generate_and_send_business_report,
            get_dashboard_business_url,
        ],
    )
