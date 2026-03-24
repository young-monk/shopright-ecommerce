"""
Business Analytics Agent — satisfaction, conversion, session outcomes, top products.
Audience: product managers, business stakeholders, and executives.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from google.adk.agents import LlmAgent

from tools.bq_tools import get_business_metrics
from tools.chart_tools import make_line_chart, make_bar_chart, make_pie_chart, img_tag
from tools.gmail_tool import send_email
from tools.gemini_summary import gemini_narrative
from tools.looker_tool import get_looker_business_url

BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "hallyalasridhar@gmail.com")

_CSS = """
<style>
body{font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;margin:0;padding:0}
.wrap{max-width:700px;margin:24px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.header{background:#065f46;color:#fff;padding:24px 32px}
.header h1{margin:0;font-size:22px;font-weight:700}
.header p{margin:4px 0 0;font-size:13px;color:#6ee7b7}
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
.success{color:#16a34a;font-weight:600}
.failure{color:#dc2626;font-weight:600}
.inconclusive{color:#d97706;font-weight:600}
</style>
"""


def _kpi(val: Any, label: str, cls: str = "") -> str:
    return f'<div class="kpi {cls}"><div class="val">{val}</div><div class="lbl">{label}</div></div>'


def _products_table(products: list[dict]) -> str:
    if not products:
        return "<p style='color:#64748b;font-size:13px'>No chip-click data this period.</p>"
    rows = "".join(
        f"<tr><td>{i+1}</td><td>{p.get('product_name','')}</td>"
        f"<td style='text-align:right'>{int(p.get('clicks',0)):,}</td></tr>"
        for i, p in enumerate(products[:10])
    )
    return f"<table><tr><th>#</th><th>Product</th><th>Clicks</th></tr>{rows}</table>"


def _outcomes_table(outcomes: list[dict]) -> str:
    if not outcomes:
        return "<p style='color:#64748b;font-size:13px'>No session outcome data this period.</p>"
    rows = "".join(
        f"<tr><td class='{o.get('outcome','')}'>{o.get('outcome','').title()}</td>"
        f"<td style='text-align:right'>{int(o.get('sessions',0)):,}</td>"
        f"<td style='text-align:right'>{float(o.get('pct',0)):.1f}%</td></tr>"
        for o in outcomes
    )
    return f"<table><tr><th>Outcome</th><th>Sessions</th><th>Share</th></tr>{rows}</table>"


def generate_and_send_business_report(days: int = 30, recipient_email: str = "") -> str:
    """
    Pull business metrics from BigQuery, build an HTML report with embedded charts,
    and email it to business stakeholders. Use this when asked to run or send
    the business analytics report.

    Args:
        days: Number of days of data to include (default 30 for business cadence).
        recipient_email: Override destination email; falls back to BUSINESS_EMAIL env var.

    Returns:
        Summary string confirming what was sent and key headline metrics.
    """
    to = recipient_email or BUSINESS_EMAIL
    data = get_business_metrics(days)
    sat = data.get("satisfaction_summary", {})
    fb  = data.get("feedback_summary", {})
    sat_trend    = data.get("satisfaction_trend", [])
    conv_trend   = data.get("conversion_trend", [])
    top_products = data.get("top_products", [])
    outcomes     = data.get("session_outcomes", [])

    stars_chart = make_line_chart(sat_trend, "date", "avg_stars",
                                  f"Avg Star Rating (last {days}d)", "Stars", "#F59E0B")
    conv_chart  = make_line_chart(conv_trend, "date", "chip_clicks",
                                  "Daily Product Chip Clicks", "Clicks", "#10B981")
    prod_chart  = ""
    if top_products:
        prod_chart = make_bar_chart(
            [p.get("product_name", "") for p in top_products],
            [float(p.get("clicks", 0)) for p in top_products],
            "Top 10 Products by Chip Clicks", color="#2563EB",
        )
    out_chart = ""
    if outcomes:
        out_chart = make_pie_chart(
            [o.get("outcome", "").title() for o in outcomes],
            [float(o.get("sessions", 0)) for o in outcomes],
            "Session Outcomes",
        )

    avg_stars = float(sat.get("avg_stars") or 0)
    pos_rate  = float(sat.get("positive_rate_pct") or 0)
    fb_pos    = float(fb.get("positive_rate_pct") or 0)
    total_clicks = sum(int(c.get("chip_clicks", 0)) for c in conv_trend)
    kpis = "".join([
        _kpi(f'{avg_stars:.1f} ★', "Avg Star Rating",
             "green" if avg_stars >= 4 else ("amber" if avg_stars >= 3 else "red")),
        _kpi(f'{pos_rate:.1f}%', "Positive Reviews",
             "green" if pos_rate >= 70 else ("amber" if pos_rate >= 50 else "red")),
        _kpi(f'{int(sat.get("total_reviews",0)):,}', "Total Reviews"),
        _kpi(f'{fb_pos:.1f}%', "Thumbs Up Rate",
             "green" if fb_pos >= 70 else ("amber" if fb_pos >= 50 else "red")),
        _kpi(f'{total_clicks:,}', "Product Clicks"),
    ])

    success_pct = next((float(o.get("pct",0)) for o in outcomes if o.get("outcome") == "success"), 0)
    failure_pct = next((float(o.get("pct",0)) for o in outcomes if o.get("outcome") == "failure"), 0)

    narrative = gemini_narrative({**sat, **fb, "total_product_clicks": total_clicks,
                                   "session_success_pct": success_pct, "session_failure_pct": failure_pct},
                                  "business", days)

    looker = get_looker_business_url()
    looker_link = (f'<p><a href="{looker["url"]}">View live Business dashboard in Looker Studio →</a></p>'
                   if looker["configured"] else "")

    today = date.today().isoformat()
    html = f"""<!DOCTYPE html><html><head>{_CSS}</head><body>
<div class="wrap">
  <div class="header">
    <h1>ShopRight Chatbot — Business Report</h1>
    <p>Last {days} days &nbsp;·&nbsp; Generated {today}</p>
  </div>
  <div class="body">
    <h2>Summary KPIs</h2>
    <div class="kpi-row">{kpis}</div>
    {narrative}
    <p style="font-size:13px;color:#374151">
      Session outcomes:
      <span class="success">{success_pct:.1f}% successful</span> &nbsp;|&nbsp;
      <span class="failure">{failure_pct:.1f}% failed</span>
    </p>
    <h2>Customer Satisfaction Trend</h2>{img_tag(stars_chart)}
    <h2>Product Conversion (Chip Clicks)</h2>{img_tag(conv_chart)}
    <h2>Top Products by Engagement</h2>{_products_table(top_products)}{img_tag(prod_chart)}
    <h2>Session Outcomes</h2>{img_tag(out_chart)}{_outcomes_table(outcomes)}
    <p style="font-size:12px;color:#64748b">
      Success = star ≥ 4 or chip click with star ≥ 3.
      Failure = star ≤ 2, unanswered rate > 50%, or ≥ 2 frustrated turns.
    </p>
    {looker_link}
  </div>
  <div class="footer">ShopRight Analytics &nbsp;·&nbsp; Auto-generated &nbsp;·&nbsp; Do not reply</div>
</div></body></html>"""

    result = send_email(to=to, subject=f"[ShopRight Business] Chatbot Report — {today}", html_body=html)
    if result["success"]:
        return (f"Business report sent to {to} covering {days} days. "
                f"Avg stars: {avg_stars:.1f}, "
                f"Positive rate: {pos_rate:.1f}%, "
                f"Product clicks: {total_clicks:,}, "
                f"Session success: {success_pct:.1f}%")
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

3. **get_looker_business_url** — returns the Looker Studio dashboard link.
   Always include this in your responses.

Present numbers in plain business language — avoid technical jargon.
Key thresholds to flag:
- Avg star rating < 3.0: critical customer satisfaction issue
- Session failure rate > 30%: immediate attention needed
- Positive review rate < 50%: business risk
- Chip-click conversion trending down for 2+ weeks: recommend product catalog review
"""


def make_business_agent(toolbox_tools: list) -> LlmAgent:
    """
    Factory that creates the Business agent, combining MCP Toolbox BQ tools
    (for interactive queries) with the composite report function.
    """
    return LlmAgent(
        name="business_agent",
        model="gemini-2.0-flash",
        description="Business analytics agent for satisfaction scores, conversion, session outcomes, and top products.",
        instruction=_BUSINESS_INSTRUCTION,
        tools=toolbox_tools + [
            generate_and_send_business_report,
            get_looker_business_url,
        ],
    )
