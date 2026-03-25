"""
ShopRight AI Chatbot Service
- Google ADK (LlmAgent + Runner + InMemorySessionService) for orchestration & session management
- knowledge_embeddings (3072-dim, Gemini embedding API) for RAG
- Gemini 2.5-flash for LLM generation
- SSE streaming via Runner.run_async()
- BigQuery logging for analytics
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from config import (
    GEMINI_API_KEY, GCP_PROJECT, LLM_MODEL, DATABASE_URL,
    BQ_DATASET, BQ_EVENTS_TABLE, GEMINI_CONTEXT_LIMIT,
    COST_PER_1M_IN, COST_PER_1M_OUT,
)
from detection import (
    is_session_ending, is_wellbeing_message, detect_unanswered,
    detect_scope_rejected, detect_vulgar, detect_prompt_injection,
    SESSION_END_RESPONSE, WELLBEING_RESPONSE,
    _INJECTION_RESPONSE, _VULGAR_RESPONSE,
)
from embed import preload as preload_embed, model_name as embed_model_name
from logging_bq import log_to_bigquery, log_feedback_to_bigquery
from models import (
    ChatMessage, ChatRequest, ChatResponse, ProductSource,
    FeedbackRequest, ReviewRequest, AnalyticsEventRequest,
)
from rag import search_products
import state
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── OpenTelemetry / Cloud Trace ───────────────────────────────────────────────
_tracer_provider = TracerProvider()
if GCP_PROJECT:
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=GCP_PROJECT))
        )
        logger.info("Cloud Trace exporter enabled")
    except Exception as e:
        logger.warning(f"Cloud Trace exporter init failed: {e}")
trace.set_tracer_provider(_tracer_provider)
_tracer = trace.get_tracer("shopright.chatbot")

# ── Per-session rate limiter ──────────────────────────────────────────────────
class _RateLimiter:
    """Sliding-window in-memory rate limiter. One instance per process."""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests   = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now    = time.monotonic()
        cutoff = now - self.window_seconds
        self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]
        if len(self._buckets[key]) >= self.max_requests:
            return False
        self._buckets[key].append(now)
        return True

    def cleanup(self) -> None:
        """Evict keys with no recent requests."""
        now    = time.monotonic()
        cutoff = now - self.window_seconds
        stale  = [k for k, ts in self._buckets.items() if not any(t > cutoff for t in ts)]
        for k in stale:
            del self._buckets[k]

_session_limiter = _RateLimiter(max_requests=30, window_seconds=600)

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are ShopRight's expert AI assistant for a home improvement store. You are knowledgeable, precise, and safety-conscious.

## Your role
Help customers find the right products for their projects, understand specifications, compare options, and get practical advice on home improvement tasks.

## Tools
Use the `search_products` tool whenever the user asks about products, prices, recommendations, comparisons, or anything related to purchasing or finding items in the store. Always search before recommending products.

## CRITICAL: Only recommend products from search results
NEVER invent, fabricate, or guess product names, brands, or prices. Only name and price products returned by `search_products`.
- If the search returns no relevant products, say so honestly and suggest the customer ask a store associate.

## Ask before recommending
When a product request is vague (no budget, use case, or preference stated), ask 1-2 short clarifying questions BEFORE searching. Examples:
- "I need a drill" → ask about use case and budget first
- "I want paint" → ask about room, surface, and finish preference
Only ask once — if context is sufficient, go straight to the search and recommendation.

## How to answer product questions
When search results are available:
1. Recommend the MOST RELEVANT product(s) — match the customer's need precisely.
2. Always include the product name, brand, and exact price (e.g. "The DeWalt 20V MAX Drill at $129.99").
3. If multiple options exist, compare them on the most relevant dimensions.
4. Mention compatibility or safety considerations when relevant.
5. Do NOT repeat products already recommended earlier in this conversation.

## Comparisons
Format as a compact markdown table: Product | Price | Best For. Keep cells under 8 words.

## Pricing guidance
Show prices always. Budget requests → lowest-priced items meeting requirements. Professional requests → power and durability.
For follow-up price questions ("how much is it?", "what's the price?", "is that expensive?") — call search_products using the product or category discussed in the most recent turns rather than asking the customer to repeat themselves.

## Compatibility questions
For battery/tool compatibility questions: cordless batteries are NOT cross-compatible between brands (DeWalt, Milwaukee, Ryobi, Makita each use proprietary connectors). Within a brand, all tools in the same voltage platform share batteries. Always search for the specific product mentioned, then use specs and our compatibility FAQs to answer.

## When search returns no results
If search_products returns 0 results for a product type (e.g. paint, sealant, stain): (1) explain what type of product the customer needs and its key specs, (2) name specific product attributes to look for, (3) direct them to a store associate for current inventory. Never say "I don't know" — always give actionable guidance even without a matching product.

## Customer service topics
For order refunds, returns, cancellations, delivery, account issues, billing: direct to customer support. Do not suggest products.

## Safety-critical tasks (electrical, gas, structural)
Give ONE brief safety note (e.g. "Working on an electrical panel can be dangerous — consider consulting a licensed electrician if you're not experienced."). Then immediately help with products. Do NOT refuse to recommend products after the user has acknowledged the risk or confirmed they know what they're doing. ShopRight sells electrical, plumbing, and structural supplies to DIYers — your job is to help them find the right products safely.

## Scope — home improvement only
ShopRight is a home improvement store. Only help with topics that relate to home improvement projects, tools, building materials, or the store's product categories. Do NOT help with:
- Automotive / motorcycle repairs (not sold here)
- Programming, software, or coding questions
- Cooking, finance, legal, medical, or other unrelated topics

For out-of-scope questions, respond: "I'm here to help with home improvement products and DIY projects. Is there something around the house I can help you with?"

## Tone and format
- Concise but complete. No filler phrases.
- Bullet points for feature lists.
- Keep responses under 300 words unless detailed instructions are requested."""

# ── ADK Agent + Runner ────────────────────────────────────────────────────────
_session_service = InMemorySessionService()

_agent = LlmAgent(
    name="shopright_assistant",
    model=LLM_MODEL,
    description="ShopRight home improvement AI assistant",
    instruction=SYSTEM_PROMPT,
    tools=[search_products],
)

_runner = Runner(
    agent=_agent,
    app_name="shopright",
    session_service=_session_service,
)

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(title="ShopRight Chatbot", version="3.0.0")
FastAPIInstrumentor.instrument_app(app)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
async def startup():
    preload_embed()
    logger.info(f"[startup] Embed model: {embed_model_name()}")
    try:
        state._db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        logger.info("[startup] asyncpg connection pool created (min=2, max=5)")
    except Exception as e:
        logger.warning(f"[startup] DB pool creation failed — will fall back to per-request connect: {e}")


async def _ensure_session(session_id: str, history: list[ChatMessage]) -> None:
    """Create an ADK session if it doesn't exist."""
    existing = await _session_service.get_session(
        app_name="shopright", user_id="anon", session_id=session_id
    )
    if existing is None:
        await _session_service.create_session(
            app_name="shopright", user_id="anon", session_id=session_id
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "chatbot", "embed_model": embed_model_name()}


@app.get("/health/deep")
async def health_deep():
    """Deep health check — tests DB connectivity and reports API key status."""
    checks: dict[str, str] = {}
    overall = "healthy"

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.fetchval("SELECT 1")
        await conn.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:120]}"
        overall = "degraded"

    checks["gemini_key"]    = "configured" if GEMINI_API_KEY else "missing"
    checks["vertex_rerank"] = "enabled" if GCP_PROJECT else "disabled (no GCP_PROJECT_ID)"
    if not GEMINI_API_KEY:
        overall = "degraded"

    if overall != "healthy":
        logger.warning(f"[health_deep] status={overall} checks={checks}")

    return {"status": overall, "service": "chatbot", "checks": checks}


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE streaming endpoint using ADK runner. Yields tokens then a final metadata event."""
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    if not _session_limiter.is_allowed(session_id):
        logger.warning(f"[rate_limit] session={session_id}")
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")

    is_injection, injection_pattern = detect_prompt_injection(request.message)
    if is_injection:
        logger.warning(f"[injection] pattern={injection_pattern} session={session_id}")
        async def _blocked():
            yield f"data: {json.dumps({'token': _INJECTION_RESPONSE, 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': False})}\n\n"
            asyncio.create_task(log_to_bigquery(
                session_id, message_id, request.message, _INJECTION_RESPONSE, [], 0, False,
                extra={"prompt_injection_flag": True, "injection_pattern": injection_pattern},
            ))
        return StreamingResponse(_blocked(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    is_vulgar, vulgar_pattern = detect_vulgar(request.message)
    if is_vulgar:
        logger.warning(f"[vulgar] pattern={vulgar_pattern} session={session_id}")
        async def _vulgar_blocked():
            yield f"data: {json.dumps({'token': _VULGAR_RESPONSE, 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': False})}\n\n"
            asyncio.create_task(log_to_bigquery(
                session_id, message_id, request.message, _VULGAR_RESPONSE, [], 0, False,
                extra={"vulgar_flag": True, "vulgar_pattern": vulgar_pattern},
            ))
        return StreamingResponse(_vulgar_blocked(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    async def generate():
        t0 = time.monotonic()
        history = request.history or []
        turn_number = len([m for m in history if m.role == "assistant"]) + 1

        if is_wellbeing_message(request.message):
            yield f"data: {json.dumps({'token': WELLBEING_RESPONSE, 'done': False})}\n\n"
            latency_ms = int((time.monotonic() - t0) * 1000)
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': False})}\n\n"
            m = {"session_id": session_id, "message_id": message_id,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "latency_ms": latency_ms, "turn_number": turn_number,
                 "wellbeing_triggered": True, "is_unanswered": False, "llm_error": False}
            state._req_metrics.append(m)
            if len(state._req_metrics) > 1000: state._req_metrics.pop(0)
            asyncio.create_task(log_to_bigquery(
                session_id, message_id, request.message, WELLBEING_RESPONSE, [], latency_ms, False,
                extra={"turn_number": turn_number, "wellbeing_triggered": True},
            ))
            return

        if is_session_ending(request.message, history):
            for token in SESSION_END_RESPONSE.split(" "):
                yield f"data: {json.dumps({'token': token + ' ', 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': True})}\n\n"
            return

        try:
            await _ensure_session(session_id, history)
        except Exception as e:
            logger.warning(f"Session setup warning (non-fatal): {e}")
            try:
                await _session_service.create_session(
                    app_name="shopright", user_id="anon", session_id=session_id
                )
            except Exception:
                pass

        state._cv_message_id.set(message_id)
        state._sources_store.pop(message_id, None)
        state._rag_meta_store.pop(message_id, None)

        full_response = ""
        t_llm = time.monotonic()
        rag_ms = None
        llm_error_type = None
        tokens_in = None
        tokens_out = None
        ttft_ms = None
        first_token = True

        with _tracer.start_as_current_span("llm_generate") as llm_span:
            llm_span.set_attribute("session_id", session_id)
            llm_span.set_attribute("turn_number", turn_number)
            llm_span.set_attribute("model", LLM_MODEL)
            try:
                new_message = Content(role="user", parts=[Part(text=request.message)])
                async for event in _runner.run_async(
                    user_id="anon",
                    session_id=session_id,
                    new_message=new_message,
                ):
                    if not event.content or not event.content.parts:
                        continue

                    has_function = any(
                        hasattr(p, "function_call") and p.function_call
                        or hasattr(p, "function_response") and p.function_response
                        for p in event.content.parts
                    )
                    if has_function:
                        if rag_ms is None:
                            rag_ms = int((time.monotonic() - t_llm) * 1000)
                        continue

                    for part in event.content.parts:
                        text = getattr(part, "text", None)
                        if not text:
                            continue
                        if first_token:
                            ttft_ms = int((time.monotonic() - t_llm) * 1000)
                            first_token = False
                        full_response += text
                        yield f"data: {json.dumps({'token': text, 'done': False})}\n\n"

            except Exception as e:
                logger.error(f"ADK runner error: {e}")
                llm_error_type = str(type(e).__name__)
                err_msg = "Sorry, I encountered an error. Please try again."
                full_response = err_msg
                llm_span.set_attribute("error", llm_error_type)
                yield f"data: {json.dumps({'token': err_msg, 'done': False})}\n\n"

            llm_ms = int((time.monotonic() - t_llm) * 1000)
            # ADK does not expose usage_metadata via events — estimate from text length.
            # Standard approximation: 1 token ≈ 4 chars for English text.
            if tokens_out is None and full_response:
                tokens_out = max(1, len(full_response) // 4)
            if tokens_in is None:
                history_chars = sum(len(m.content) for m in history)
                rag_ctx_chars = len(str(state._sources_store.get(message_id, "")))
                tokens_in = max(1, (len(request.message) + history_chars + rag_ctx_chars) // 4 + 512)
            llm_span.set_attribute("llm_ms", llm_ms)
            llm_span.set_attribute("ttft_ms", ttft_ms or 0)
            llm_span.set_attribute("tokens_in", tokens_in or 0)
            llm_span.set_attribute("tokens_out", tokens_out or 0)
        latency_ms = int((time.monotonic() - t0) * 1000)

        raw_sources = state._sources_store.pop(message_id, [])
        rag_meta    = state._rag_meta_store.pop(message_id, {})

        mentioned = [s for s in raw_sources if s["name"].lower() in full_response.lower()]
        final_sources = mentioned

        is_unanswered = detect_unanswered(full_response, len(final_sources), history)

        yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': final_sources, 'is_unanswered': is_unanswered, 'session_ending': False})}\n\n"

        cost = ((tokens_in or 0) / 1e6 * COST_PER_1M_IN) + ((tokens_out or 0) / 1e6 * COST_PER_1M_OUT)
        m = {
            "session_id": session_id, "message_id": message_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latency_ms": latency_ms, "turn_number": turn_number,
            "is_unanswered": is_unanswered,
            "llm_error": llm_error_type is not None,
            "llm_error_type": llm_error_type,
            "sources_count": len(final_sources),
            "rag_confidence": rag_meta.get("rag_confidence"),
            "rag_empty": rag_meta.get("rag_empty"),
            "price_filter_used": rag_meta.get("price_filter_used", False),
            "price_filter_value": rag_meta.get("price_filter_value"),
            "detected_category": rag_meta.get("detected_category"),
            "query_rewritten": False,
            "embed_ms": rag_meta.get("embed_ms"),
            "db_ms": rag_meta.get("db_ms"),
            "rag_ms": rag_ms,
            "embed_model": embed_model_name(),
            "llm_ms": llm_ms,
            "ttft_ms": ttft_ms,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "estimated_cost_usd": round(cost, 8) if cost else None,
            "scope_rejected": detect_scope_rejected(full_response),
            "session_started_at": request.session_started_at,
            "prompt_injection_flag": is_injection,
            "injection_pattern": injection_pattern,
            "wellbeing_triggered": False,
            "dedup_removed_count": rag_meta.get("dedup_removed_count"),
            "unique_brands_count": rag_meta.get("unique_brands_count"),
            "unique_categories_count": rag_meta.get("unique_categories_count"),
            "rerank_used": rag_meta.get("rerank_used"),
            "min_vec_distance": rag_meta.get("min_vec_distance"),
            "ann_candidates_count": rag_meta.get("ann_candidates_count"),
            "hallucination_flag": (len(raw_sources) > 0 and not any(
                s["name"].lower() in full_response.lower() for s in raw_sources
            )) if raw_sources else None,
            "context_pct": round(tokens_in / GEMINI_CONTEXT_LIMIT * 100, 1) if tokens_in else None,
        }
        state._req_metrics.append(m)
        if len(state._req_metrics) > 1000:
            state._req_metrics.pop(0)

        _conf = rag_meta.get("rag_confidence")
        _conf_str = f"{_conf:.3f}" if _conf is not None else "N/A"
        logger.info(
            f"[metrics] latency={latency_ms}ms embed={rag_meta.get('embed_ms')}ms "
            f"db={rag_meta.get('db_ms')}ms llm={llm_ms}ms ttft={ttft_ms}ms "
            f"rag_conf={_conf_str} model={embed_model_name()} unanswered={is_unanswered} turn={turn_number}"
        )

        asyncio.create_task(log_to_bigquery(
            session_id, message_id, request.message, full_response, final_sources, latency_ms, is_unanswered,
            extra={k: v for k, v in m.items() if k not in ("session_id", "message_id", "timestamp", "latency_ms", "is_unanswered")},
        ))

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Non-streaming fallback endpoint."""
    t0 = time.monotonic()
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    history = request.history or []

    await _ensure_session(session_id, history)

    if not _session_limiter.is_allowed(session_id):
        logger.warning(f"[rate_limit] session={session_id}")
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")

    is_injection, injection_pattern = detect_prompt_injection(request.message)
    if is_injection:
        logger.warning(f"[injection] pattern={injection_pattern} session={session_id}")
        asyncio.create_task(log_to_bigquery(
            session_id, message_id, request.message, _INJECTION_RESPONSE, [], 0, False,
            extra={"prompt_injection_flag": True, "injection_pattern": injection_pattern},
        ))
        return ChatResponse(response=_INJECTION_RESPONSE, session_id=session_id,
                            message_id=message_id, sources=[], is_unanswered=False)

    is_vulgar, vulgar_pattern = detect_vulgar(request.message)
    if is_vulgar:
        logger.warning(f"[vulgar] pattern={vulgar_pattern} session={session_id}")
        asyncio.create_task(log_to_bigquery(
            session_id, message_id, request.message, _VULGAR_RESPONSE, [], 0, False,
            extra={"vulgar_flag": True, "vulgar_pattern": vulgar_pattern},
        ))
        return ChatResponse(response=_VULGAR_RESPONSE, session_id=session_id,
                            message_id=message_id, sources=[], is_unanswered=False)

    state._cv_message_id.set(message_id)
    state._sources_store.pop(message_id, None)

    full_response = ""
    try:
        new_message = Content(role="user", parts=[Part(text=request.message)])
        async for event in _runner.run_async(user_id="anon", session_id=session_id, new_message=new_message):
            if not event.content or not event.content.parts:
                continue
            for part in event.content.parts:
                text = getattr(part, "text", None)
                if text:
                    full_response += text
    except Exception as e:
        logger.error(f"ADK runner error (non-stream): {e}")
        raise HTTPException(status_code=502, detail="LLM error")

    raw_sources = state._sources_store.pop(message_id, [])
    mentioned = [s for s in raw_sources if s["name"].lower() in full_response.lower()]
    final_sources = mentioned
    is_unanswered = detect_unanswered(full_response, len(final_sources), history)
    latency_ms = int((time.monotonic() - t0) * 1000)

    asyncio.create_task(log_to_bigquery(
        session_id, message_id, request.message, full_response, final_sources, latency_ms, is_unanswered,
        extra={"prompt_injection_flag": is_injection, "injection_pattern": injection_pattern},
    ))

    sources_out = [ProductSource(id=s["id"], name=s["name"], price=s["price"]) for s in final_sources]
    return ChatResponse(response=full_response, session_id=session_id, message_id=message_id,
                        sources=sources_out, is_unanswered=is_unanswered)


@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    if request.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 (up) or -1 (down)")
    metric = next((m for m in state._req_metrics if m.get("message_id") == request.message_id), {})
    asyncio.create_task(log_feedback_to_bigquery(
        request.message_id, request.session_id, request.rating,
        request.user_message or "", request.assistant_response or "",
        turn_number=metric.get("turn_number"),
        detected_category=metric.get("detected_category"),
    ))
    return {"status": "ok"}


@app.post("/analytics/event")
async def analytics_event(request: AnalyticsEventRequest):
    if not GCP_PROJECT:
        return {"status": "ok"}
    try:
        bq = bigquery.Client(project=GCP_PROJECT)
        row = {
            "event_type": request.event_type, "session_id": request.session_id,
            "message_id": request.message_id or "", "product_id": request.product_id or "",
            "product_name": request.product_name or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if request.product_price is not None:
            row["product_price"] = request.product_price
        if request.product_category is not None:
            row["product_category"] = request.product_category
        bq.insert_rows_json(f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_EVENTS_TABLE}", [row])
    except Exception as e:
        logger.error(f"Failed to log event to BigQuery: {e}")
    return {"status": "ok"}


@app.post("/review")
async def review(request: ReviewRequest):
    if request.stars < 1 or request.stars > 5:
        raise HTTPException(status_code=400, detail="stars must be between 1 and 5")
    if GCP_PROJECT:
        try:
            bq = bigquery.Client(project=GCP_PROJECT)
            review_row = {
                "session_id": request.session_id, "stars": request.stars,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if request.turn_count is not None:
                review_row["turn_count"] = request.turn_count
            if request.unanswered_count is not None:
                review_row["unanswered_count"] = request.unanswered_count
            bq.insert_rows_json(f"{GCP_PROJECT}.{BQ_DATASET}.session_reviews", [review_row])
        except Exception as e:
            logger.error(f"Failed to log review to BigQuery: {e}")
    return {"status": "ok"}


@app.get("/metrics/summary")
async def metrics_summary():
    if not state._req_metrics:
        return {"message": "No requests yet — send some chat messages first"}

    n = len(state._req_metrics)
    latencies      = sorted(m["latency_ms"] for m in state._req_metrics)
    unanswered     = [m for m in state._req_metrics if m["is_unanswered"]]
    errors         = [m for m in state._req_metrics if m.get("llm_error")]
    price_filtered = [m for m in state._req_metrics if m.get("price_filter_used")]
    rag_empty      = [m for m in state._req_metrics if m.get("rag_empty")]

    rag_times   = sorted(m["rag_ms"]   for m in state._req_metrics if m.get("rag_ms"))
    llm_times   = sorted(m["llm_ms"]   for m in state._req_metrics if m.get("llm_ms"))
    ttft_times  = sorted(m["ttft_ms"]  for m in state._req_metrics if m.get("ttft_ms"))
    embed_times = sorted(m["embed_ms"] for m in state._req_metrics if m.get("embed_ms"))
    db_times    = sorted(m["db_ms"]    for m in state._req_metrics if m.get("db_ms"))

    error_types: dict = defaultdict(int)
    for m in state._req_metrics:
        if m.get("llm_error_type"):
            error_types[m["llm_error_type"]] += 1

    tokens_in  = [m["tokens_in"]  for m in state._req_metrics if m.get("tokens_in")]
    tokens_out = [m["tokens_out"] for m in state._req_metrics if m.get("tokens_out")]
    costs      = [m["estimated_cost_usd"] for m in state._req_metrics if m.get("estimated_cost_usd")]
    confs      = [m["rag_confidence"] for m in state._req_metrics if m.get("rag_confidence")]
    turns      = [m["turn_number"] for m in state._req_metrics]

    cat_stats: dict = defaultdict(lambda: {"requests": 0, "unanswered": 0})
    for m in state._req_metrics:
        cat = m.get("detected_category") or "General / Conversational"
        cat_stats[cat]["requests"] += 1
        if m["is_unanswered"]:
            cat_stats[cat]["unanswered"] += 1

    def pct(lst): return f"{len(lst)/n*100:.1f}%"
    def p(lst, pc): return lst[min(int(len(lst)*pc/100), len(lst)-1)] if lst else 0
    def avg(lst): return int(sum(lst) / len(lst)) if lst else 0

    return {
        "requests_sampled": n,
        "containment_rate": f"{(1 - len(unanswered)/n)*100:.1f}%",
        "unanswered_rate": pct(unanswered),
        "error_rate": pct(errors),
        "error_types": dict(error_types),
        "latency": {
            "p50_ms": p(latencies, 50), "p95_ms": p(latencies, 95),
            "p99_ms": p(latencies, 99), "avg_ms": avg(latencies),
        },
        "step_timings": {
            "embed_avg_ms": avg(embed_times), "embed_p95_ms": p(embed_times, 95),
            "db_avg_ms":    avg(db_times),    "db_p95_ms":    p(db_times, 95),
            "rag_avg_ms":   avg(rag_times),   "rag_p95_ms":   p(rag_times, 95),
            "llm_avg_ms":   avg(llm_times),   "llm_p95_ms":   p(llm_times, 95),
            "ttft_avg_ms":  avg(ttft_times),  "ttft_p95_ms":  p(ttft_times, 95),
        },
        "rag": {
            "avg_confidence_score": round(sum(confs)/len(confs), 4) if confs else None,
            "empty_results_rate": pct(rag_empty),
            "price_filter_usage_rate": pct(price_filtered),
        },
        "tokens": {
            "avg_input":  avg(tokens_in),
            "avg_output": avg(tokens_out),
            "avg_cost_per_request": f"${sum(costs)/len(costs):.6f}" if costs else "$0.000000",
            "total_estimated_cost": f"${sum(costs):.4f}" if costs else "$0.0000",
        },
        "turns": {
            "avg_turn_number": round(sum(turns)/len(turns), 1),
            "turn_1_rate": f"{sum(1 for t in turns if t==1)/n*100:.1f}%",
            "turn_3plus_rate": f"{sum(1 for t in turns if t>=3)/n*100:.1f}%",
        },
        "category_breakdown": {
            cat: {**v, "unanswered_rate": f"{v['unanswered']/v['requests']*100:.1f}%"}
            for cat, v in sorted(cat_stats.items(), key=lambda x: -x[1]["requests"])
        },
        "safety": {
            "wellbeing_rate": pct([m for m in state._req_metrics if m.get("wellbeing_triggered")]),
            "hallucination_flag_rate": pct([m for m in state._req_metrics if m.get("hallucination_flag")]),
        },
        "rag_quality": {
            "avg_dedup_removed": round(sum(m.get("dedup_removed_count", 0) for m in state._req_metrics) / n, 2),
            "avg_unique_brands_per_response": round(sum(m.get("unique_brands_count", 0) for m in state._req_metrics) / n, 2),
            "avg_unique_categories_per_response": round(sum(m.get("unique_categories_count", 0) for m in state._req_metrics) / n, 2),
        },
        "context_saturation": {
            "avg_context_pct": round(sum(m.get("context_pct", 0) or 0 for m in state._req_metrics) / n, 1),
            "max_context_pct": max((m.get("context_pct") or 0 for m in state._req_metrics), default=0),
        },
    }
