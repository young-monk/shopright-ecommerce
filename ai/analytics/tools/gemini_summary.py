"""Generate an in-depth written analysis of analytics metrics using Gemini."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_AUDIENCE_CONTEXT = {
    "devops": (
        "You are a senior SRE writing an infrastructure health analysis for engineers and on-call staff. "
        "The audience understands technical terms like p95 latency, error rate, TTFT, and prompt injection. "
        "Focus on what needs attention, what looks healthy, and what trends warrant investigation."
    ),
    "tech": (
        "You are an ML engineer writing a technical performance analysis for ML engineers and data scientists. "
        "The audience cares deeply about RAG confidence, embedding quality, vector distance, token cost, "
        "frustration rate, hallucination rate, and catalog gaps. Be precise about thresholds and what they imply."
    ),
    "business": (
        "You are a product analyst writing a business performance summary for product managers and executives. "
        "Use plain language — no jargon. Focus on customer satisfaction, conversion trends, session outcomes, "
        "and what these numbers mean for the product. Highlight risks and bright spots."
    ),
}

_THRESHOLDS = {
    "devops": """Key thresholds:
- Error rate > 2%: critical | > 0.5%: elevated | ≤ 0.5%: healthy
- p95 latency > 8000ms: slow | > 4000ms: moderate
- Unanswered rate > 25%: high (catalog gaps likely) | > 10%: moderate
- Avg TTFT > 3000ms: elevated (cold starts or quota pressure)
- Any prompt injection or vulgar blocks: flag and explain the risk""",
    "tech": """Key thresholds:
- RAG confidence is COSINE DISTANCE (lower = better match, higher = worse):
  > 0.6: poor retrieval — check embedding model or catalog quality
  0.4–0.6: moderate retrieval quality
  < 0.4: good retrieval (do NOT flag low values as bad)
- Min vector distance trending UP over time: embedding drift — recommend re-embedding
- Rerank used pct < 80%: Cohere rerank may be down — check API key/quota
- Cost per session > $0.01: high — check context window usage
- Frustration rate > 15%: critical | > 8%: elevated
- Citation gap rate (hallucination_flag) > 5%: response may not cite retrieved products — investigate; note this is a heuristic proxy, not a true hallucination detector
- Rec gap rate > 10%: significant catalog coverage problem""",
    "business": """Key thresholds:
- Avg star rating < 3.0: critical | < 4.0: needs improvement
- Session failure rate > 30%: immediate attention needed
- Positive review rate (stars ≥ 4) < 50%: business risk
- Thumbs-up rate (thumbs_up_rate_pct, per-message 👍 clicks) < 60%: response quality concern — note this is a SEPARATE metric from star ratings
- Chip-click conversion_rate_pct (sessions that clicked a product chip / total sessions) < 10%: low product engagement — review catalog relevance
- Chip-click conversion_rate_pct declining for 2+ weeks: recommend product catalog review
- Unanswered rate includes both truly unanswered AND out-of-scope rejections""",
}


def gemini_narrative(metrics: dict, audience: str, days: int) -> str:
    """
    Call Gemini to produce an in-depth HTML analysis of the given metrics.

    Returns HTML with Executive Summary, Key Findings, Trends, and Actions.
    Falls back to a plain metric list on any error.
    """
    try:
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key) if api_key else genai.Client()

        ctx = _AUDIENCE_CONTEXT.get(audience, "")
        thresholds = _THRESHOLDS.get(audience, "")
        prompt = (
            f"{ctx}\n\n"
            f"{thresholds}\n\n"
            f"Metrics for the last {days} days (JSON):\n"
            f"{json.dumps(metrics, default=str, indent=2)}\n\n"
            "Write a thorough analysis in HTML with these four sections:\n"
            "1. <h2>Executive Summary</h2> — 2-3 sentences on overall health.\n"
            "2. <h2>Key Findings</h2> — 4-8 <li> bullets. Each must include the actual number, "
            "compare it to the threshold, and state the action needed. "
            "Use <strong style='color:#dc2626'>⚠ Critical:</strong>, "
            "<strong style='color:#d97706'>↑ Elevated:</strong>, or "
            "<strong style='color:#16a34a'>✓ Healthy:</strong> as the label.\n"
            "3. <h2>Trends &amp; Patterns</h2> — 2-4 sentences on what the daily data shows over time.\n"
            "4. <h2>Recommended Actions</h2> — numbered list of concrete next steps only for items "
            "that need attention. Omit this section entirely if everything is healthy.\n\n"
            "Return ONLY the HTML (no <html>/<body> tags). Use inline styles for colours. "
            "Be specific — always cite the actual numbers."
        )

        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
        )
        return response.text.strip()

    except Exception as exc:
        logger.warning("gemini_narrative failed (%s) — using metric fallback", exc)
        lines = [
            f"<li><strong>{k}:</strong> {v}</li>"
            for k, v in metrics.items()
            if not isinstance(v, (list, dict))
        ]
        return (
            "<h2>Metrics</h2>"
            f"<ul style='font-size:13px;line-height:1.8'>{''.join(lines)}</ul>"
            f"<p style='color:#94a3b8;font-size:12px'>AI analysis unavailable: {exc}</p>"
        )
