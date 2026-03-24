"""Generate a concise written summary of analytics metrics using Gemini."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_AUDIENCE_CONTEXT = {
    "devops": (
        "You are summarising a DevOps / SRE infrastructure report for engineers. "
        "Audience cares about error rates, latency, unanswered queries, and security events."
    ),
    "tech": (
        "You are summarising a Technical / ML analytics report for ML engineers and data scientists. "
        "Audience cares about RAG confidence, embedding quality, LLM cost, frustration rate, "
        "and hallucination rate."
    ),
    "business": (
        "You are summarising a Business analytics report for product managers and executives. "
        "Audience cares about customer satisfaction scores, session outcomes, top products, "
        "and conversion trends. Use plain, non-technical language."
    ),
}


def gemini_narrative(metrics: dict, audience: str, days: int) -> str:
    """
    Call Gemini to produce a short HTML <ul> narrative for the given metrics dict.

    Args:
        metrics: Summary/KPI dict from get_*_metrics().
        audience: One of "devops", "tech", "business".
        days: Time window for context.

    Returns:
        HTML string: <h2>Analysis</h2><ul>…</ul>
        Falls back to empty string on any error.
    """
    try:
        from google import genai  # type: ignore  # google-genai package
        from google.genai import types as genai_types

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key) if api_key else genai.Client()

        ctx = _AUDIENCE_CONTEXT.get(audience, "")
        prompt = (
            f"{ctx}\n\n"
            f"Here are the key metrics for the last {days} days (JSON):\n"
            f"{json.dumps(metrics, default=str, indent=2)}\n\n"
            "Write 4-6 bullet points of plain-English analysis. Each bullet should either: "
            "flag something that needs attention with a threshold reason, "
            "or confirm something is healthy. Be specific — include the actual numbers. "
            "Return ONLY the bullet points as HTML <li> elements (no wrapping <ul> tag). "
            "Use <strong> for status labels like '✓ Healthy', '⚠ Critical', '↑ Elevated'."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        bullets = response.text.strip()
        # Ensure bullets are wrapped correctly
        if not bullets.startswith("<li"):
            bullets = f"<li>{bullets}</li>"
        return (
            '<h2>Analysis</h2>'
            '<ul style="padding-left:18px;line-height:1.8;font-size:13px;color:#374151">'
            f'{bullets}'
            '</ul>'
        )
    except Exception as exc:
        logger.warning("gemini_narrative failed (%s) — skipping summary block", exc)
        return ""
