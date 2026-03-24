"""
DevOps Analytics Agent — infrastructure health, error rates, latency, security events.
Audience: engineers and on-call SREs.

Two modes:
  • /analyze/run  → call generate_and_send_devops_report() for a formatted HTML email
  • /analyze/chat → use MCP Toolbox BQ tools for ad-hoc natural language queries
"""
import os
from datetime import date
from typing import Any

from google.adk.agents import LlmAgent

from tools.bq_tools import get_devops_metrics
from tools.chart_tools import make_line_chart, make_dual_line_chart, make_bar_chart, img_tag
from tools.gmail_tool import send_email
from tools.gemini_summary import gemini_narrative
from tools.looker_tool import get_looker_devops_url

DEVOPS_EMAIL = os.getenv("DEVOPS_EMAIL", "hallyalasridhar@gmail.com")

_CSS = """
<style>
body{font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;margin:0;padding:0}
.wrap{max-width:700px;margin:24px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.header{background:#1e293b;color:#fff;padding:24px 32px}
.header h1{margin:0;font-size:22px;font-weight:700}
.header p{margin:4px 0 0;font-size:13px;color:#94a3b8}
.body{padding:24px 32px}
.kpi-row{display:flex;gap:12px;margin:16px 0;flex-wrap:wrap}
.kpi{flex:1;min-width:120px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;text-align:center}
.kpi .val{font-size:24px;font-weight:700;color:#1e293b}
.kpi .lbl{font-size:11px;color:#64748b;margin-top:4px}
.kpi.red .val{color:#dc2626} .kpi.green .val{color:#16a34a} .kpi.amber .val{color:#d97706}
h2{font-size:16px;color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin-top:28px}
.footer{background:#f8fafc;padding:16px 32px;font-size:11px;color:#94a3b8;border-top:1px solid #e2e8f0}
a{color:#2563eb}
</style>
"""


def _kpi(val: Any, label: str, cls: str = "") -> str:
    return f'<div class="kpi {cls}"><div class="val">{val}</div><div class="lbl">{label}</div></div>'


def _color_error(pct: float) -> str:
    if pct > 2:   return "red"
    if pct > 0.5: return "amber"
    return "green"


def generate_and_send_devops_report(days: int = 7, recipient_email: str = "") -> str:
    """
    Pull DevOps metrics from BigQuery, build an HTML report with embedded charts,
    and email it to the DevOps team. Use this when asked to run or send a DevOps report.

    Args:
        days: Number of days of data to include (default 7).
        recipient_email: Override destination email; falls back to DEVOPS_EMAIL env var.

    Returns:
        Summary string confirming what was sent and key headline metrics.
    """
    to = recipient_email or DEVOPS_EMAIL
    data = get_devops_metrics(days)
    s = data.get("summary", {})
    daily = data.get("daily", [])

    req_chart  = make_line_chart(daily, "date", "requests",
                                 f"Daily Request Volume (last {days}d)", "Requests", "#2563EB")
    err_chart  = make_line_chart(daily, "date", "error_rate_pct",
                                 "Error Rate % per Day", "Error %", "#DC2626")
    lat_chart  = make_dual_line_chart(daily, "date",
                                      value_keys=["p50_latency_ms", "p95_latency_ms"],
                                      labels=["p50", "p95"],
                                      title="Response Latency (ms)",
                                      colors=["#10B981", "#F59E0B"])
    ttft_chart = make_line_chart(daily, "date", "avg_ttft_ms",
                                 "Avg Time-to-First-Token (ms)", "ms", "#8B5CF6")
    unans_chart = make_line_chart(daily, "date", "unanswered_rate_pct",
                                  "Unanswered Rate % per Day", "%", "#F59E0B")
    sec_chart  = make_bar_chart(
        ["Prompt Injections", "Vulgar Blocks"],
        [float(s.get("total_injection_blocks", 0)), float(s.get("total_vulgar_blocks", 0))],
        "Security Events (period total)", horizontal=False, color="#DC2626"
    )

    err_pct = float(s.get("error_rate_pct") or 0)
    kpis = "".join([
        _kpi(f'{s.get("total_requests", 0):,}', "Total Requests"),
        _kpi(f'{s.get("total_sessions", 0):,}', "Unique Sessions"),
        _kpi(f'{err_pct:.2f}%', "Error Rate", _color_error(err_pct)),
        _kpi(f'{s.get("p95_latency_ms", 0):,}ms', "p95 Latency"),
        _kpi(f'{s.get("avg_ttft_ms", 0):,}ms', "Avg TTFT"),
        _kpi(f'{s.get("unanswered_rate_pct", 0):.1f}%', "Unanswered Rate",
             "red" if float(s.get("unanswered_rate_pct") or 0) > 20 else ""),
    ])

    narrative = gemini_narrative(s, "devops", days)

    looker = get_looker_devops_url()
    looker_link = (f'<p><a href="{looker["url"]}">View live DevOps dashboard in Looker Studio →</a></p>'
                   if looker["configured"] else "")

    today = date.today().isoformat()
    html = f"""<!DOCTYPE html><html><head>{_CSS}</head><body>
<div class="wrap">
  <div class="header">
    <h1>ShopRight Chatbot — DevOps Report</h1>
    <p>Last {days} days &nbsp;·&nbsp; Generated {today}</p>
  </div>
  <div class="body">
    <h2>Summary KPIs</h2>
    <div class="kpi-row">{kpis}</div>
    {narrative}
    <h2>Request Volume</h2>{img_tag(req_chart)}
    <h2>Error Rate</h2>{img_tag(err_chart)}
    <h2>Latency Breakdown</h2>{img_tag(lat_chart)}
    <h2>Time-to-First-Token</h2>{img_tag(ttft_chart)}
    <h2>Unanswered Rate</h2>{img_tag(unans_chart)}
    <h2>Security Events</h2>{img_tag(sec_chart)}
    <p style="font-size:12px;color:#64748b">
      Prompt injections: {int(s.get("total_injection_blocks", 0))} &nbsp;|&nbsp;
      Vulgar blocks: {int(s.get("total_vulgar_blocks", 0))}
    </p>
    {looker_link}
  </div>
  <div class="footer">ShopRight Analytics &nbsp;·&nbsp; Auto-generated &nbsp;·&nbsp; Do not reply</div>
</div></body></html>"""

    result = send_email(to=to, subject=f"[ShopRight DevOps] Chatbot Report — {today}", html_body=html)
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
   It queries BigQuery, makes charts, and emails the full HTML report.

2. **BigQuery query tools** (via MCP Toolbox) — named queries like get_devops_daily,
   get_devops_summary, get_devops_error_types, get_devops_security_events, etc.
   Use these for ad-hoc questions like "what was the error rate yesterday?" or
   "show me latency trends for the past 2 weeks".

3. **get_looker_devops_url** — returns the Looker Studio dashboard link.
   Include this link in any response that involves metrics.

Key metric thresholds to call out:
- Error rate > 2%: critical — investigate immediately
- p95 latency > 8000ms: slow — check Gemini API or Cloud Run scaling
- Unanswered rate > 25%: high — likely catalog gaps
- TTFT > 3000ms average: elevated — may indicate cold starts or LLM quota pressure
- Injection attempts spike: security incident — alert the team
"""


def make_devops_agent(toolbox_tools: list) -> LlmAgent:
    """
    Factory that creates the DevOps agent, combining MCP Toolbox BQ tools
    (for interactive queries) with the composite report function.
    Called once at app startup after the toolbox client is initialised.
    """
    return LlmAgent(
        name="devops_agent",
        model="gemini-2.5-flash",
        description="DevOps analytics agent for infrastructure health, error rates, latency and security events.",
        instruction=_DEVOPS_INSTRUCTION,
        tools=toolbox_tools + [
            generate_and_send_devops_report,
            get_looker_devops_url,
        ],
    )
