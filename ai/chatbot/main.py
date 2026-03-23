"""
ShopRight AI Chatbot Service
- Google ADK (LlmAgent + Runner + InMemorySessionService) for orchestration & session management
- knowledge_embeddings (3072-dim, Gemini embedding API) for RAG
- Gemini 2.5-flash for LLM generation
- SSE streaming via Runner.run_async()
- BigQuery logging for analytics
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import os
import uuid
import json
import logging
import time
import re
import contextvars
import asyncio
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from google.cloud import bigquery
import asyncpg

from google.adk.agents import LlmAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from embed import embed as gemini_embed, preload as preload_embed, model_name as embed_model_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GCP_PROJECT    = os.getenv("GCP_PROJECT_ID", "")
LLM_MODEL      = os.getenv("LLM_MODEL", "gemini-2.5-flash")
DATABASE_URL   = os.getenv("DATABASE_URL", "postgresql://shopright:shopright_dev@localhost:5432/shopright")
BQ_DATASET     = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE       = os.getenv("BIGQUERY_TABLE", "chat_logs")
BQ_FEEDBACK_TABLE = os.getenv("BIGQUERY_FEEDBACK_TABLE", "feedback")
BQ_EVENTS_TABLE   = os.getenv("BIGQUERY_EVENTS_TABLE", "chat_events")
COHERE_API_KEY    = os.getenv("COHERE_API_KEY", "")

# Cohere rerank client (optional — graceful fallback if key not set)
_co = None
if COHERE_API_KEY:
    try:
        import cohere as _cohere_lib
        _co = _cohere_lib.ClientV2(api_key=COHERE_API_KEY)
        logger.info("Cohere rerank enabled (rerank-v3.5)")
    except ImportError:
        logger.warning("cohere package not installed — rerank disabled")

GEMINI_CONTEXT_LIMIT = 1_000_000

# Gemini-2.5-flash pricing (per 1M tokens)
_COST_PER_1M_IN  = 0.075
_COST_PER_1M_OUT = 0.30

# In-memory metrics ring buffer (last 1000 requests)
_req_metrics: list[dict] = []

# Pass tool results from ADK search_products back to the SSE generator.
# ContextVar writes inside child tasks (how ADK calls tools) don't propagate back
# to the parent task. Fix: use a module-level dict keyed by message_id; store the
# ID in a ContextVar (reads are safe across task boundaries).
_cv_message_id: contextvars.ContextVar[str] = contextvars.ContextVar("message_id", default="")
_sources_store: dict[str, list] = {}
_rag_meta_store: dict[str, dict] = {}

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

_session_limiter = _RateLimiter(max_requests=30, window_seconds=600)  # 30 req / 10 min per session

# ── Session ending detection ──────────────────────────────────────────────────
SESSION_END_PHRASES = [
    "thanks", "thank you", "that's all", "that's it", "i'm done", "im done",
    "goodbye", "bye", "see you", "see ya", "all set", "got it", "perfect",
    "great thanks", "no more questions", "nothing else", "that's everything",
    "i'm good", "im good", "i'm all good", "that'll do", "no thanks",
]
_AMBIGUOUS_ENDINGS = {"ok", "okay", "k", "sure", "yep", "nope", "nah", "alright", "cool", "noted"}
_BOT_WRAP_UP_SIGNALS = [
    "anything else", "let me know", "here if you need", "feel free to ask",
    "happy to help", "have a great day", "come back", "is there anything",
    "can i help", "hope that helps", "if you need anything",
]

SESSION_END_RESPONSE = (
    "You're welcome! Before you go — how would you rate your experience today? "
    "Your feedback helps us improve. ⭐"
)

def is_session_ending(message: str, history: list) -> bool:
    msg = message.lower().strip()
    if len(msg.split()) > 6:
        return False
    if any(phrase in msg for phrase in SESSION_END_PHRASES):
        return True
    if msg in _AMBIGUOUS_ENDINGS and history:
        last_bot = next((m.content.lower() for m in reversed(history) if m.role == "assistant"), "")
        if any(signal in last_bot for signal in _BOT_WRAP_UP_SIGNALS):
            return True
    return False

# ── Wellbeing detection ───────────────────────────────────────────────────────
WELLBEING_PATTERNS = [
    "feeling low", "feeling sad", "feeling depressed", "feeling lonely",
    "i'm sad", "im sad", "i'm depressed", "im depressed",
    "i'm lonely", "im lonely", "i'm not okay", "im not okay",
    "not doing well", "talk to me", "need someone to talk",
    "having a hard time", "going through a tough time",
    "stressed", "anxious", "overwhelmed", "hopeless",
    "want to hurt", "hurting myself", "end my life", "suicide",
    "nobody cares", "no one cares", "feel worthless",
]

WELLBEING_RESPONSE = (
    "I'm really sorry to hear you're feeling this way. "
    "I'm a shopping assistant and not equipped to provide the support you deserve right now, "
    "but please know that help is available.\n\n"
    "If you're in crisis or need someone to talk to, please reach out to a crisis helpline — "
    "in the US you can call or text **988** (Suicide & Crisis Lifeline), available 24/7.\n\n"
    "Take care of yourself. When you're ready, I'm here to help with any home improvement needs. 💙"
)

def is_wellbeing_message(message: str) -> bool:
    msg = message.lower().strip()
    return any(pattern in msg for pattern in WELLBEING_PATTERNS)

UNCERTAINTY_PHRASES = [
    "i don't have", "i don't know", "i'm not sure", "i cannot find",
    "not available in", "no information", "outside my knowledge",
    "can't help with that", "unable to find", "not in our catalog",
]

def detect_unanswered(response: str, sources_count: int, history: list) -> bool:
    response_lower = response.lower()
    has_uncertainty = any(phrase in response_lower for phrase in UNCERTAINTY_PHRASES)
    return sources_count == 0 and has_uncertainty

_INJECTION_RESPONSE = "I'm ShopRight's home improvement assistant and I'm not able to help with that request. Is there something around the house I can help you with?"

_SCOPE_REJECTION_MARKER = "i'm here to help with home improvement"

def detect_scope_rejected(response: str) -> bool:
    return _SCOPE_REJECTION_MARKER in response.lower()

# ── Prompt injection detection ────────────────────────────────────────────────
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+)?previous\s+instructions?",                 "ignore_instructions"),
    (r"(disregard|forget)\s+(your\s+)?(previous\s+)?instructions?", "disregard_instructions"),
    (r"you\s+are\s+now\s+(a|an|the)\s+",                           "persona_override"),
    (r"act\s+as\s+(a|an|the)\s+(?!store|sales|product|shop)",      "act_as"),
    (r"pretend\s+(you\s+are|to\s+be)\s+",                          "pretend_as"),
    (r"\b(jailbreak|dan\s+mode|do\s+anything\s+now)\b",            "jailbreak"),
    (r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions?)",      "extract_prompt"),
    (r"what\s+(are|were)\s+your\s+(system\s+)?instructions?",       "extract_prompt"),
    (r"override\s+(your\s+)?(safety|guidelines?|instructions?)",    "safety_override"),
]
_INJECTION_MSG_MAX_LEN = 4000

def detect_prompt_injection(message: str) -> tuple[bool, str | None]:
    if len(message) > _INJECTION_MSG_MAX_LEN:
        return True, "message_too_long"
    msg_lower = message.lower()
    for pattern, label in _INJECTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return True, label
    return False, None

# ── Category keywords ─────────────────────────────────────────────────────────
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Power Tools":            ["drill", "saw", "grinder", "sander", "router", "jigsaw", "circular saw", "impact driver", "nail gun", "heat gun", "power tool"],
    "Hand Tools":             ["hammer", "screwdriver", "wrench", "pliers", "chisel", "hand tool", "tape measure", "level", "utility knife"],
    "Outdoor & Garden":       ["lawn", "mower", "garden", "grass", "trimmer", "edger", "fertilizer", "soil", "mulch", "seed", "weed", "sprinkler", "hose", "rake", "shovel", "chainsaw", "leaf blower", "pressure washer", "snow blower", "generator", "outdoor power"],
    "Plumbing":               ["pipe", "faucet", "toilet", "sink", "drain", "valve", "fitting", "plumbing", "water heater", "garbage disposal"],
    "Electrical":             ["wire", "cable", "outlet", "switch", "breaker", "circuit", "electrical", "conduit", "panel", "speaker wire", "in-wall wire", "audio cable"],
    "Flooring":               ["floor", "tile", "hardwood", "laminate", "vinyl", "carpet", "grout", "underlayment"],
    "Paint & Supplies":       ["paint", "primer", "stain", "brush", "roller", "spray", "coating", "varnish", "caulk", "sealant"],
    "Safety & Security":      ["safety", "glove", "helmet", "goggle", "respirator", "harness", "protective", "lock", "deadbolt", "camera", "alarm"],
    "Storage & Organization": ["shelf", "cabinet", "rack", "storage", "organizer", "bin", "drawer", "pegboard"],
    "Heating & Cooling":      ["hvac", "air conditioner", "heater", "furnace", "duct", "vent", "thermostat", "filter", "fan", "dehumidifier"],
    "Building Materials":     ["insulation", "soundproof", "sound dampening", "acoustic", "drywall", "home theatre", "home theater", "theatre room", "theater room", "sound barrier", "noise reduction", "framing", "lumber", "plywood", "concrete", "cement", "batt", "r-value"],
}

def detect_category(query: str) -> str | None:
    query_lower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return category
    return None

# ── Price extraction ───────────────────────────────────────────────────────────
_PRICE_PATTERNS = [
    r'under\s*\$?(\d+(?:\.\d+)?)',
    r'below\s*\$?(\d+(?:\.\d+)?)',
    r'less\s+than\s*\$?(\d+(?:\.\d+)?)',
    r'cheaper\s+than\s*\$?(\d+(?:\.\d+)?)',
    r'up\s+to\s*\$?(\d+(?:\.\d+)?)',
    r'within\s*\$?(\d+(?:\.\d+)?)',
    r'max(?:imum)?\s*\$?(\d+(?:\.\d+)?)',
    r'budget\s*(?:of\s*|around\s*|~\s*)?\$?(\d+(?:\.\d+)?)',
    r'\$?(\d+(?:\.\d+)?)\s*budget',
    r'around\s*\$(\d+(?:\.\d+)?)',
]

def extract_price_limit(query: str) -> float | None:
    for pattern in _PRICE_PATTERNS:
        m = re.search(pattern, query.lower())
        if m:
            return float(m.group(1))
    return None

# ── RAG: knowledge_embeddings hybrid search ───────────────────────────────────
async def get_relevant_context(query: str, top_k: int = 10) -> tuple[str, list, dict]:
    """Search knowledge_embeddings with hybrid ANN + optional Cohere rerank."""
    vector, embed_ms = await gemini_embed(query, task_type="RETRIEVAL_QUERY")
    if not vector:
        return "", [], {"rag_confidence": None, "rag_empty": True, "price_filter_used": False,
                        "price_filter_value": None, "detected_category": None, "embed_ms": None, "db_ms": None}

    detected_category = detect_category(query)
    price_limit = extract_price_limit(query)

    stop_words = {"what", "which", "that", "this", "with", "have", "from", "your", "best", "good",
                  "need", "want", "some", "for", "can", "how", "does", "show", "find", "give",
                  "tell", "about", "under", "over", "more", "less", "cheap", "cheaper", "those", "other"}
    keywords = [w for w in query.lower().split() if len(w) >= 4 and w not in stop_words]

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        t_db = time.monotonic()

        # Build optional filter clauses
        # Price filter: metadata->>'price' is text in JSONB; cast to numeric
        price_clause = f"AND (metadata->>'price')::numeric <= {price_limit:.2f}" if price_limit is not None else ""
        cat_clause = f"AND metadata->>'category' ILIKE '%{detected_category}%'" if detected_category else ""

        # Keyword pattern for hybrid scoring
        keyword_bonus = "0"
        if keywords:
            kw_regex = "|".join(re.escape(k) for k in keywords)
            keyword_bonus = f"CASE WHEN LOWER(content) ~ '{kw_regex}' THEN 0.15 ELSE 0 END"

        # Fetch more candidates when rerank is available (50), else use top_k directly
        ann_limit = 50 if _co else top_k

        # Query all three doc types — use halfvec cast to hit the HNSW index
        # (pgvector's vector(3072) exceeds the 2000-dim ANN limit; halfvec lifts it to 16000)
        rows = await conn.fetch(
            f"""
            SELECT doc_type, source_id, content, metadata,
                   (embedding::halfvec(3072) <=> $1::halfvec(3072)) AS vec_dist,
                   {keyword_bonus} AS keyword_bonus
            FROM knowledge_embeddings
            WHERE 1=1 {cat_clause} {price_clause}
            ORDER BY (embedding::halfvec(3072) <=> $1::halfvec(3072)) - {keyword_bonus}
            LIMIT $2
            """,
            str(vector), ann_limit,
        )

        db_ms = int((time.monotonic() - t_db) * 1000)
        await conn.close()

        rag_meta = {
            "price_filter_used": price_limit is not None,
            "price_filter_value": price_limit,
            "detected_category": detected_category,
            "embed_ms": embed_ms,
            "db_ms": db_ms,
        }

        if not rows:
            rag_meta.update({"rag_confidence": None, "rag_empty": True})
            return "", [], rag_meta

        # ── Rerank ────────────────────────────────────────────────────────────
        rerank_used = False
        if _co and rows:
            try:
                rr = _co.rerank(
                    query=query,
                    documents=[r["content"] for r in rows],
                    top_n=min(16, len(rows)),
                    model="rerank-v3.5",
                )
                reranked_rows = [rows[hit.index] for hit in rr.results]
                rerank_used = True
            except Exception as e:
                logger.warning(f"Cohere rerank failed, falling back to hybrid score: {e}")
                reranked_rows = sorted(rows, key=lambda r: float(r["vec_dist"]) - float(r["keyword_bonus"]))
        else:
            reranked_rows = sorted(rows, key=lambda r: float(r["vec_dist"]) - float(r["keyword_bonus"]))

        # Deduplicate product rows by name; keep all FAQs and review summaries
        seen_names: dict = {}
        deduped = []
        for row in reranked_rows:
            if row["doc_type"] == "product":
                meta = json.loads(row["metadata"])
                name = meta.get("name", "")
                if name not in seen_names:
                    seen_names[name] = row
                    deduped.append(row)
            else:
                deduped.append(row)
        dedup_removed = len(reranked_rows) - len(deduped)
        ranked = deduped[:8]

        avg_dist = sum(float(r["vec_dist"]) for r in ranked) / len(ranked)
        low_confidence = avg_dist > 0.6
        product_rows = [r for r in ranked if r["doc_type"] == "product"]
        rag_meta.update({
            "rag_confidence": round(avg_dist, 4),
            "rag_empty": False,
            "dedup_removed_count": dedup_removed,
            "unique_brands_count": len({json.loads(r["metadata"]).get("brand") for r in product_rows}),
            "unique_categories_count": len({json.loads(r["metadata"]).get("category") for r in product_rows}),
            "rerank_used": rerank_used,
        })

        context_parts = []
        sources = []
        for row in ranked:
            context_parts.append(row["content"])
            if row["doc_type"] == "product":
                meta = json.loads(row["metadata"])
                sources.append({"id": row["source_id"], "name": meta.get("name", ""), "price": float(meta.get("price", 0)), "category": meta.get("category", "")})

        context = "\n\n---\n\n".join(context_parts)
        if low_confidence:
            context += f"\n\n[Note: Low confidence match. Available categories: {', '.join(CATEGORY_KEYWORDS.keys())}]"

        return context, sources, rag_meta

    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return "", [], {"rag_confidence": None, "rag_empty": True, "price_filter_used": False,
                        "price_filter_value": None, "detected_category": None}

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

# ── ADK Tool: search_products ─────────────────────────────────────────────────
async def search_products(query: str) -> str:
    """Search the ShopRight knowledge base: products, FAQs, and customer reviews.

    Use this tool whenever the user asks about products, prices, brands, recommendations,
    comparisons, store policies (returns, shipping, warranty), or any question that
    ShopRight's catalog or FAQ data could answer.

    Args:
        query: Search query describing what the customer is looking for.

    Returns:
        Relevant product listings with names, prices, descriptions, and specifications,
        plus any FAQ answers and customer review summaries related to the query.
    """
    context, sources, rag_meta = await get_relevant_context(query)
    mid = _cv_message_id.get("")
    if mid:
        _sources_store[mid] = sources
        _rag_meta_store[mid] = rag_meta
    return context if context else "No matching products found in our catalog for that query."

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

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

@app.on_event("startup")
async def startup():
    preload_embed()
    logger.info(f"[startup] Embed model: {embed_model_name()}")

# ── Pydantic models ────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = []  # used for seeding on pod restart
    session_started_at: Optional[str] = None

class ProductSource(BaseModel):
    id: str
    name: str
    price: float
    category: str = ""

class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
    sources: List[ProductSource] = []
    is_unanswered: bool = False
    session_ending: bool = False

class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    rating: int
    user_message: Optional[str] = None
    assistant_response: Optional[str] = None

class ReviewRequest(BaseModel):
    session_id: str
    stars: int
    turn_count: Optional[int] = None
    unanswered_count: Optional[int] = None

class AnalyticsEventRequest(BaseModel):
    event_type: str
    session_id: str
    message_id: Optional[str] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    product_price: Optional[float] = None
    product_category: Optional[str] = None

# ── Intent classification ──────────────────────────────────────────────────────
_INTENT_LABELS = (
    "product_lookup",       # searching for a specific product
    "project_advice",       # how-to / DIY project guidance
    "compatibility",        # will X work with Y
    "pricing_availability", # price, cost, stock, availability
    "troubleshooting",      # diagnosing or fixing a problem
    "general_chat",         # greetings, thanks, off-topic
)
_INTENT_PROMPT = (
    "Classify the following customer message into exactly one of these intent labels:\n"
    + ", ".join(_INTENT_LABELS)
    + "\n\nRespond with only the label — no explanation.\n\nMessage: "
)

async def classify_intent(message: str) -> str:
    if not GEMINI_API_KEY:
        return "unknown"
    try:
        import google.genai as genai
        _cl = genai.Client(api_key=GEMINI_API_KEY)
        resp = await _cl.aio.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=_INTENT_PROMPT + message[:500],
        )
        label = resp.text.strip().lower().split()[0].rstrip(".,")
        return label if label in _INTENT_LABELS else "unknown"
    except Exception as e:
        logger.warning(f"Intent classification failed: {e}")
        return "unknown"

# ── BigQuery logging ───────────────────────────────────────────────────────────
async def log_to_bigquery(session_id, message_id, user_message, assistant_response, sources, latency_ms, is_unanswered, extra: dict | None = None):
    if not GCP_PROJECT:
        return
    try:
        intent = await classify_intent(user_message)
        row = {
            "session_id": session_id, "message_id": message_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_message": user_message, "assistant_response": assistant_response,
            "sources_used": json.dumps(sources if isinstance(sources[0], dict) else [s.model_dump() for s in sources]) if sources else "[]",
            "message_length": len(user_message), "response_length": len(assistant_response),
            "sources_count": len(sources), "latency_ms": latency_ms, "is_unanswered": is_unanswered,
            "intent": intent,
        }
        if extra:
            row.update(extra)
        bq = bigquery.Client(project=GCP_PROJECT)
        errors = bq.insert_rows_json(f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}", [row])
        if errors:
            logger.error(f"BigQuery insert errors for {message_id}: {errors}")
    except Exception as e:
        logger.error(f"Failed to log to BigQuery: {e}")

async def log_feedback_to_bigquery(message_id, session_id, rating, user_message, assistant_response, turn_number=None, detected_category=None):
    if not GCP_PROJECT:
        return
    try:
        row = {
            "message_id": message_id, "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rating": rating, "user_message": user_message or "",
            "assistant_response": assistant_response or "",
        }
        if turn_number is not None:
            row["turn_number"] = turn_number
        if detected_category is not None:
            row["detected_category"] = detected_category
        bq = bigquery.Client(project=GCP_PROJECT)
        bq.insert_rows_json(f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_FEEDBACK_TABLE}", [row])
    except Exception as e:
        logger.error(f"Failed to log feedback to BigQuery: {e}")

# ── Helper: ensure ADK session exists ────────────────────────────────────────
async def _ensure_session(session_id: str, history: list[ChatMessage]) -> None:
    """Create an ADK session if it doesn't exist. Seeds history into context on pod restart."""
    existing = await _session_service.get_session(
        app_name="shopright", user_id="anon", session_id=session_id
    )
    if existing is None:
        await _session_service.create_session(
            app_name="shopright", user_id="anon", session_id=session_id
        )
        # Replay recent history so ADK has conversation context after pod restart
        if history:
            for msg in history[-6:]:
                role = "user" if msg.role == "user" else "model"
                seed_content = Content(role=role, parts=[Part(text=msg.content)])
                await _session_service.append_event(
                    session=await _session_service.get_session(
                        app_name="shopright", user_id="anon", session_id=session_id
                    ),
                    event=Event(
                        author="user" if role == "user" else _agent.name,
                        content=seed_content,
                        actions=EventActions(),
                    ),
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

    checks["gemini_key"]     = "configured" if GEMINI_API_KEY else "missing"
    checks["cohere_rerank"]  = "enabled" if _co else "disabled"
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

    # Rate limit: 30 requests per 10 minutes per session
    if not _session_limiter.is_allowed(session_id):
        logger.warning(f"[rate_limit] session={session_id}")
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")

    # Prompt injection detection — hard-block before reaching the LLM
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

    async def generate():
        t0 = time.monotonic()
        history = request.history or []
        turn_number = len([m for m in history if m.role == "assistant"]) + 1

        # Short-circuit: wellbeing / emotional distress
        if is_wellbeing_message(request.message):
            yield f"data: {json.dumps({'token': WELLBEING_RESPONSE, 'done': False})}\n\n"
            latency_ms = int((time.monotonic() - t0) * 1000)
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': False})}\n\n"
            m = {"session_id": session_id, "message_id": message_id,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "latency_ms": latency_ms, "turn_number": turn_number,
                 "wellbeing_triggered": True, "is_unanswered": False, "llm_error": False}
            _req_metrics.append(m)
            if len(_req_metrics) > 1000: _req_metrics.pop(0)
            asyncio.create_task(log_to_bigquery(
                session_id, message_id, request.message, WELLBEING_RESPONSE, [], latency_ms, False,
                extra={"turn_number": turn_number, "wellbeing_triggered": True},
            ))
            return

        # Short-circuit: session ending
        if is_session_ending(request.message, history):
            for token in SESSION_END_RESPONSE.split(" "):
                yield f"data: {json.dumps({'token': token + ' ', 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': True})}\n\n"
            return

        # Ensure ADK session exists (creates or uses existing)
        try:
            await _ensure_session(session_id, history)
        except Exception as e:
            logger.warning(f"Session setup warning (non-fatal): {e}")
            # Fall back to simple session creation without history seeding
            try:
                await _session_service.create_session(
                    app_name="shopright", user_id="anon", session_id=session_id
                )
            except Exception:
                pass

        # Bind message_id into ContextVar so the ADK tool can write sources to the store
        _cv_message_id.set(message_id)
        _sources_store.pop(message_id, None)
        _rag_meta_store.pop(message_id, None)

        # Run ADK agent, streaming tokens
        full_response = ""
        t_llm = time.monotonic()
        rag_ms = None
        llm_error_type = None
        tokens_in = None
        tokens_out = None
        ttft_ms = None
        first_token = True

        try:
            new_message = Content(role="user", parts=[Part(text=request.message)])
            async for event in _runner.run_async(
                user_id="anon",
                session_id=session_id,
                new_message=new_message,
            ):
                if not event.content or not event.content.parts:
                    continue

                # Skip tool call / tool response events
                has_function = any(
                    hasattr(p, "function_call") and p.function_call
                    or hasattr(p, "function_response") and p.function_response
                    for p in event.content.parts
                )
                if has_function:
                    # Record when the tool ran (RAG timing)
                    if rag_ms is None:
                        rag_ms = int((time.monotonic() - t_llm) * 1000)
                    continue

                # Extract text parts from LLM response
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
            yield f"data: {json.dumps({'token': err_msg, 'done': False})}\n\n"

        llm_ms = int((time.monotonic() - t_llm) * 1000)
        latency_ms = int((time.monotonic() - t0) * 1000)

        # Retrieve sources written by search_products tool (via module-level store)
        raw_sources = _sources_store.pop(message_id, [])
        rag_meta    = _rag_meta_store.pop(message_id, {})

        # Filter to sources Gemini actually mentioned in the response
        mentioned = [s for s in raw_sources if s["name"].lower() in full_response.lower()]
        final_sources = mentioned  # only show chips for products the bot actually named

        is_unanswered = detect_unanswered(full_response, len(final_sources), history)

        yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': final_sources, 'is_unanswered': is_unanswered, 'session_ending': False})}\n\n"

        # Metrics
        cost = ((tokens_in or 0) / 1e6 * _COST_PER_1M_IN) + ((tokens_out or 0) / 1e6 * _COST_PER_1M_OUT)
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
            "hallucination_flag": (len(raw_sources) > 0 and not any(
                s["name"].lower() in full_response.lower() for s in raw_sources
            )) if raw_sources else None,
            "context_pct": round(tokens_in / GEMINI_CONTEXT_LIMIT * 100, 1) if tokens_in else None,
        }
        _req_metrics.append(m)
        if len(_req_metrics) > 1000:
            _req_metrics.pop(0)

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

    _cv_message_id.set(message_id)
    _sources_store.pop(message_id, None)

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

    raw_sources = _sources_store.pop(message_id, [])
    mentioned = [s for s in raw_sources if s["name"].lower() in full_response.lower()]
    final_sources = mentioned  # only show chips for products the bot actually named
    is_unanswered = detect_unanswered(full_response, len(final_sources), history)
    latency_ms = 0  # not tracked for non-streaming

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
    metric = next((m for m in _req_metrics if m.get("message_id") == request.message_id), {})
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
    if not _req_metrics:
        return {"message": "No requests yet — send some chat messages first"}

    n = len(_req_metrics)
    latencies       = sorted(m["latency_ms"] for m in _req_metrics)
    unanswered      = [m for m in _req_metrics if m["is_unanswered"]]
    errors          = [m for m in _req_metrics if m.get("llm_error")]
    price_filtered  = [m for m in _req_metrics if m.get("price_filter_used")]
    rag_empty       = [m for m in _req_metrics if m.get("rag_empty")]

    rag_times   = sorted(m["rag_ms"]   for m in _req_metrics if m.get("rag_ms"))
    llm_times   = sorted(m["llm_ms"]   for m in _req_metrics if m.get("llm_ms"))
    ttft_times  = sorted(m["ttft_ms"]  for m in _req_metrics if m.get("ttft_ms"))
    embed_times = sorted(m["embed_ms"] for m in _req_metrics if m.get("embed_ms"))
    db_times    = sorted(m["db_ms"]    for m in _req_metrics if m.get("db_ms"))

    error_types: dict = defaultdict(int)
    for m in _req_metrics:
        if m.get("llm_error_type"):
            error_types[m["llm_error_type"]] += 1

    tokens_in  = [m["tokens_in"]  for m in _req_metrics if m.get("tokens_in")]
    tokens_out = [m["tokens_out"] for m in _req_metrics if m.get("tokens_out")]
    costs      = [m["estimated_cost_usd"] for m in _req_metrics if m.get("estimated_cost_usd")]
    confs      = [m["rag_confidence"] for m in _req_metrics if m.get("rag_confidence")]
    turns      = [m["turn_number"] for m in _req_metrics]

    cat_stats: dict = defaultdict(lambda: {"requests": 0, "unanswered": 0})
    for m in _req_metrics:
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
            "wellbeing_rate": pct([m for m in _req_metrics if m.get("wellbeing_triggered")]),
            "hallucination_flag_rate": pct([m for m in _req_metrics if m.get("hallucination_flag")]),
        },
        "rag_quality": {
            "avg_dedup_removed": round(sum(m.get("dedup_removed_count", 0) for m in _req_metrics) / n, 2),
            "avg_unique_brands_per_response": round(sum(m.get("unique_brands_count", 0) for m in _req_metrics) / n, 2),
            "avg_unique_categories_per_response": round(sum(m.get("unique_categories_count", 0) for m in _req_metrics) / n, 2),
        },
        "context_saturation": {
            "avg_context_pct": round(sum(m.get("context_pct", 0) or 0 for m in _req_metrics) / n, 1),
            "max_context_pct": max((m.get("context_pct") or 0 for m in _req_metrics), default=0),
        },
    }
