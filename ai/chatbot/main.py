"""
ShopRight AI Chatbot Service
- Uses Google Gemini REST API directly (gemini-2.5-flash for speed)
- Uses pgvector for RAG with hybrid vector + keyword search
- Query rewriting for follow-up questions using conversation history
- Streaming responses via SSE
- Logs all conversations to BigQuery for analytics
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
from datetime import datetime, timezone

import re
import statistics
from collections import defaultdict
import httpx
from google.cloud import bigquery
import asyncpg
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from embed import embed as local_embed, preload as preload_embed, model_name as embed_model_name

# ── Config ───────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GCP_PROJECT    = os.getenv("GCP_PROJECT_ID", "")
LLM_MODEL      = os.getenv("LLM_MODEL", "gemini-2.5-flash")
EMBED_MODEL    = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
DATABASE_URL   = os.getenv("DATABASE_URL", "postgresql://shopright:shopright_dev@localhost:5432/shopright")
BQ_DATASET     = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE       = os.getenv("BIGQUERY_TABLE", "chat_logs")
BQ_FEEDBACK_TABLE = os.getenv("BIGQUERY_FEEDBACK_TABLE", "feedback")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Gemini-2.5-flash pricing (per 1M tokens, as of 2026)
_COST_PER_1M_IN  = 0.075
_COST_PER_1M_OUT = 0.30

GEMINI_CONTEXT_LIMIT = 1_000_000  # Gemini 2.5-flash context window (tokens)
BQ_EVENTS_TABLE = os.getenv("BIGQUERY_EVENTS_TABLE", "chat_events")

# In-memory metrics buffer (last 1000 requests) — used for /metrics/summary
# In production, all metrics also flow to BigQuery
_req_metrics: list[dict] = []

SESSION_END_PHRASES = [
    "thanks", "thank you", "that's all", "that's it", "i'm done", "im done",
    "goodbye", "bye", "see you", "see ya", "all set", "got it", "perfect",
    "great thanks", "no more questions", "nothing else", "that's everything",
    "i'm good", "im good", "i'm all good", "that'll do", "no thanks",
]

# Short ambiguous words that mean "done" only when the bot was already wrapping up
_AMBIGUOUS_ENDINGS = {"ok", "okay", "k", "sure", "yep", "nope", "nah", "alright", "cool", "noted"}

# Signals that the bot was wrapping up / offering further help
_BOT_WRAP_UP_SIGNALS = [
    "anything else", "let me know", "here if you need", "feel free to ask",
    "happy to help", "have a great day", "come back", "is there anything",
    "can i help", "hope that helps", "if you need anything",
]

SESSION_END_RESPONSE = (
    "You're welcome! Before you go — how would you rate your experience today? "
    "Your feedback helps us improve. ⭐"
)

def is_session_ending(message: str, history: List) -> bool:
    """Return True if the user is wrapping up the conversation."""
    msg = message.lower().strip()
    if len(msg.split()) > 6:
        return False
    if any(phrase in msg for phrase in SESSION_END_PHRASES):
        return True
    # Ambiguous one-word replies (ok/sure/nope) only close the session if the
    # bot's last message was already wrapping up / offering further help
    if msg in _AMBIGUOUS_ENDINGS and history:
        last_bot = next((m.content.lower() for m in reversed(history) if m.role == "assistant"), "")
        if any(signal in last_bot for signal in _BOT_WRAP_UP_SIGNALS):
            return True
    return False

UNCERTAINTY_PHRASES = [
    "i don't have", "i don't know", "i'm not sure", "i cannot find",
    "not available in", "no information", "outside my knowledge",
    "can't help with that", "unable to find", "not in our catalog",
]

# Keys must match the actual category values stored in the products DB (used in ILIKE filter)
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

app = FastAPI(title="ShopRight Chatbot", version="2.0.0")


@app.on_event("startup")
async def startup():
    """Preload the embedding model so the first request isn't slow."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, preload_embed)


app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ── Models ────────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = []

class ProductSource(BaseModel):
    id: str
    name: str
    price: float

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
    stars: int  # 1-5

class AnalyticsEventRequest(BaseModel):
    event_type: str  # "chip_click", "chatbot_open", etc.
    session_id: str
    message_id: Optional[str] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None

# ── Gemini helpers ────────────────────────────────────────────────────────────
async def gemini_embed(text: str, task_type: str = "RETRIEVAL_QUERY") -> list[float] | None:
    if not GEMINI_API_KEY:
        return None
    url = f"{GEMINI_BASE}/models/{EMBED_MODEL}:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": f"models/{EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        "outputDimensionality": 768,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            return resp.json()["embedding"]["values"]
        logger.warning(f"Embed error {resp.status_code}: {resp.text[:200]}")
        return None


async def gemini_generate(contents: list, system_prompt: str) -> tuple[str, int]:
    """Non-streaming generate. Returns (text, latency_ms)."""
    if not GEMINI_API_KEY:
        return "[Chatbot not configured] Please set GEMINI_API_KEY.", 0
    url = f"{GEMINI_BASE}/models/{LLM_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)
    latency_ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code == 200:
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"], latency_ms
    logger.error(f"Gemini generate error {resp.status_code}: {resp.text[:400]}")
    raise HTTPException(status_code=502, detail=f"LLM error: {resp.status_code}")


async def gemini_stream(contents: list, system_prompt: str, metrics_ctx: dict | None = None):
    """Async generator that yields text chunks from Gemini streaming API.
    Populates metrics_ctx with token counts and per-step timings.
    On error, sets metrics_ctx['llm_error_type'] and yields an error message
    instead of raising (so the SSE stream closes cleanly)."""
    if not GEMINI_API_KEY:
        yield "[Chatbot not configured] Please set GEMINI_API_KEY."
        return
    url = f"{GEMINI_BASE}/models/{LLM_MODEL}:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error(f"Gemini stream error {response.status_code}: {body[:200]}")
                    if metrics_ctx is not None:
                        metrics_ctx["llm_error_type"] = str(response.status_code)
                    yield "Sorry, I encountered an error. Please try again."
                    return
                first_token = True
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line[6:])
                            # Capture token usage from final chunk
                            if metrics_ctx is not None and "usageMetadata" in chunk:
                                usage = chunk["usageMetadata"]
                                metrics_ctx["tokens_in"]  = usage.get("promptTokenCount", 0)
                                metrics_ctx["tokens_out"] = usage.get("candidatesTokenCount", 0)
                            parts = chunk["candidates"][0]["content"]["parts"]
                            text = next((p.get("text", "") for p in parts if "text" in p), "")
                            if text:
                                if first_token and metrics_ctx is not None:
                                    t_start = metrics_ctx.get("_t_llm_start")
                                    if t_start is not None:
                                        metrics_ctx["ttft_ms"] = int((time.monotonic() - t_start) * 1000)
                                    first_token = False
                                yield text
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
    except httpx.TimeoutException:
        logger.error("Gemini stream timeout")
        if metrics_ctx is not None:
            metrics_ctx["llm_error_type"] = "timeout"
        yield "Sorry, the request timed out. Please try again."

# ── Query rewriting for follow-ups ───────────────────────────────────────────
# Multi-word signals are safe as substring checks.
# Single short words ("it", "them", "any") must be whole-word matched to avoid
# false substring hits (e.g. "it" inside "capital", "them" inside "theme").
_FOLLOWUP_SIGNALS = [
    "cheaper", "more expensive", "similar", "another", "else", "instead",
    "that one", "this one", "those", "these", "show me more",
    "what about", "how about", "any other", "alternatives",
    # Price filter follow-ups
    "below", "under", "less than", "cheaper than", "above", "over", "more than",
    "within", "budget", "price range", "affordable",
    # Vague references that need context
    "anything", "something", "do you have", "got any", "show me",
]
# Short whole-word-only follow-up signals (checked separately with word boundary)
_FOLLOWUP_SIGNALS_WORD = {"it", "them", "any"}

async def rewrite_query(message: str, history: List[ChatMessage]) -> tuple[str, bool]:
    """
    Rewrite a follow-up query into a standalone product search query.
    Returns (query, was_rewritten).
    """
    if not history or not GEMINI_API_KEY:
        return message, False

    msg_lower = message.lower()
    msg_words = set(re.findall(r'\b\w+\b', msg_lower))
    is_followup = (
        len(message.split()) <= 12 and
        (any(sig in msg_lower for sig in _FOLLOWUP_SIGNALS) or
         bool(msg_words & _FOLLOWUP_SIGNALS_WORD))
    )
    if not is_followup:
        return message, False

    recent = history[-4:]
    context = " | ".join(f"{m.role}: {m.content[:120]}" for m in recent)
    prompt = (
        f"Conversation so far: {context}\n\n"
        f'Rewrite this follow-up as a standalone product search query (max 10 words, no explanation):\n"{message}"\n\nRewritten:'
    )
    url = f"{GEMINI_BASE}/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 100, "thinkingConfig": {"thinkingBudget": 0}},
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                parts = resp.json()["candidates"][0]["content"]["parts"]
                text = next((p["text"] for p in parts if "text" in p), None)
                if not text:
                    return message, False
                rewritten = text.strip().strip('"')
                logger.info(f"Query rewrite: '{message}' → '{rewritten}'")
                return rewritten, True
    except Exception as e:
        logger.warning(f"Query rewrite failed: {e}")
    return message, False

# ── Intent detection ──────────────────────────────────────────────────────────
PRODUCT_INTENT_KEYWORDS = [
    "buy", "purchase", "find", "show", "recommend", "suggest", "need", "want",
    "looking for", "best", "cheap", "affordable", "price", "cost", "how much",
    "do you have", "do you sell", "in stock", "available",
    "difference between", "compare", "vs", "versus", "which one", "what type",
    "brand", "model", "size", "weight", "color", "compatible", "fit", "work with",
    "install", "fix", "repair", "replace", "build", "paint", "drill", "cut",
    "project", "renovation", "upgrade",
]

CONVERSATIONAL_PHRASES = [
    "hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye",
    "how are you", "what are you", "who are you", "what can you do",
    "help me", "good morning", "good afternoon", "good evening",
    "ok", "okay", "great", "awesome", "cool", "nice", "perfect",
    "yes", "no", "sure", "alright",
]

NON_PRODUCT_PATTERNS = [
    # SQL
    "select ", "insert ", "update ", "delete ", "drop ", "create table",
    "from ", "where ", "join ", "group by", "order by", "* from", "SELECT *",
    # Programming
    "def ", "class ", "import ", "function ", "console.log", "print(",
    "java ", "python ", "javascript ", "typescript ", "c++ ", "c# ", "ruby ",
    "write code", "write a function", "write a program", "write a script",
    "code for ", "algorithm for", "implement a", "how to code",
    # Math / general knowledge
    "what is the formula", "what is the equation", "solve for",
    "calculate the ", "how many calories", "convert ", "translate ",
    "what year", "who is ", "who was ", "tell me a joke", "write a poem",
    "what does", "define ", "synonym ", "antonym ", "spell ",
]

# Arithmetic expression — digits with operators, no product keywords
_MATH_EXPR = re.compile(r'^\s*[\d\s\+\-\*\/\^\(\)\.%]+\s*[=\?]?\s*$')

# Customer service queries — don't run RAG, bot will direct to support
CUSTOMER_SERVICE_PATTERNS = [
    "refund", "return my order", "cancel my order", "order status",
    "track my order", "where is my order", "my order",
    "complaint", "customer service", "customer support",
    "shipping", "delivery date", "when will it arrive",
    "my account", "reset password", "forgot password",
    "billing", "invoice", "receipt", "charge on my card",
    "warranty claim", "damaged item", "wrong item",
]

# Emotional / wellbeing signals — respond with empathy, skip RAG
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

def is_product_query(query: str) -> bool:
    query_lower = query.lower().strip()

    # Hard exclusions — never run RAG for these
    if _MATH_EXPR.match(query_lower):
        return False
    if any(p.lower() in query_lower for p in NON_PRODUCT_PATTERNS):
        return False
    if any(p in query_lower for p in CUSTOMER_SERVICE_PATTERNS):
        return False
    if is_wellbeing_message(query):
        return False

    # Short conversational phrases
    if len(query_lower.split()) <= 3:
        if any(phrase in query_lower for phrase in CONVERSATIONAL_PHRASES):
            return False

    # Positive signals — only return True if there's actual product/home-improvement intent
    if any(kw in query_lower for kw in PRODUCT_INTENT_KEYWORDS):
        return True
    if detect_category(query) is not None:
        return True
    # "how do i / how to" only counts when paired with a home-improvement word
    _HOME_CONTEXT = ["fix", "install", "repair", "replace", "build", "paint",
                     "drill", "cut", "wire", "plumb", "tile", "floor", "seal"]
    if any(p in query_lower for p in ["how do i", "how to", "can i use"]):
        if any(w in query_lower for w in _HOME_CONTEXT):
            return True
    # "which / what are" only if a category keyword is also present
    if any(p in query_lower for p in ["which", "what are"]):
        if detect_category(query) is not None:
            return True
    # Follow-up signals (cheaper, under $X, show me more)
    if any(sig in query_lower for sig in _FOLLOWUP_SIGNALS):
        return True
    # Short whole-word signals ("it", "them", "any") — word boundary check
    words = set(re.findall(r'\b\w+\b', query_lower))
    if words & _FOLLOWUP_SIGNALS_WORD:
        return True

    # Default: don't run RAG — let the LLM handle it as general conversation
    return False

# ── Category detection ────────────────────────────────────────────────────────
def detect_category(query: str) -> str | None:
    query_lower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return category
    return None

# ── Price extraction ──────────────────────────────────────────────────────────
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

# ── RAG: Hybrid Vector + Keyword Search ──────────────────────────────────────
async def get_relevant_context(query: str, top_k: int = 15) -> tuple[str, list[ProductSource], dict]:
    # Embed the query locally — no API call, ~10-20ms on CPU
    vector, embed_ms = await local_embed(query)
    if not vector:
        return "", [], {"rag_confidence": None, "rag_empty": True, "price_filter_used": False, "price_filter_value": None, "detected_category": None, "embed_ms": None, "db_ms": None}

    detected_category = detect_category(query)
    price_limit = extract_price_limit(query)
    price_clause = f"AND price <= {price_limit:.2f}" if price_limit is not None else ""

    stop_words = {"what", "which", "that", "this", "with", "have", "from", "your", "best", "good",
                  "need", "want", "some", "for", "can", "how", "does", "show", "find", "give",
                  "tell", "about", "under", "over", "more", "less", "cheap", "cheaper", "those", "other"}
    keywords = [w for w in query.lower().split() if len(w) >= 4 and w not in stop_words]

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        t_db = time.monotonic()

        if detected_category and keywords:
            keyword_pattern = "%(" + "|".join(keywords) + ")%"
            rows = await conn.fetch(
                f"""
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist,
                       CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END AS keyword_bonus
                FROM product_embeddings
                WHERE category ILIKE $4 {price_clause}
                ORDER BY (embedding <=> $1::vector) - (CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END)
                LIMIT $2
                """,
                str(vector), top_k, keyword_pattern, f"%{detected_category}%",
            )
            if not rows:
                rows = await conn.fetch(
                    f"""
                    SELECT product_id, name, description, category, brand, price, specifications,
                           (embedding <=> $1::vector) AS vec_dist,
                           CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END AS keyword_bonus
                    FROM product_embeddings
                    WHERE 1=1 {price_clause}
                    ORDER BY (embedding <=> $1::vector) - (CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END)
                    LIMIT $2
                    """,
                    str(vector), top_k, keyword_pattern,
                )
        elif detected_category:
            rows = await conn.fetch(
                f"""
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist, 0 AS keyword_bonus
                FROM product_embeddings
                WHERE category ILIKE $3 {price_clause}
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                str(vector), top_k, f"%{detected_category}%",
            )
            if not rows:
                rows = await conn.fetch(
                    f"""
                    SELECT product_id, name, description, category, brand, price, specifications,
                           (embedding <=> $1::vector) AS vec_dist, 0 AS keyword_bonus
                    FROM product_embeddings WHERE 1=1 {price_clause} ORDER BY embedding <=> $1::vector LIMIT $2
                    """,
                    str(vector), top_k,
                )
        elif keywords:
            keyword_pattern = "%(" + "|".join(keywords) + ")%"
            rows = await conn.fetch(
                f"""
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist,
                       CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END AS keyword_bonus
                FROM product_embeddings
                WHERE 1=1 {price_clause}
                ORDER BY (embedding <=> $1::vector) - (CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END)
                LIMIT $2
                """,
                str(vector), top_k, keyword_pattern,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist, 0 AS keyword_bonus
                FROM product_embeddings WHERE 1=1 {price_clause} ORDER BY embedding <=> $1::vector LIMIT $2
                """,
                str(vector), top_k,
            )

        db_ms = int((time.monotonic() - t_db) * 1000)
        await conn.close()

        rag_meta = {"price_filter_used": price_limit is not None, "price_filter_value": price_limit,
                    "detected_category": detected_category, "embed_ms": embed_ms, "db_ms": db_ms}

        if not rows:
            rag_meta.update({"rag_confidence": None, "rag_empty": True})
            return "", [], rag_meta

        # Re-rank: sort by combined score (vec_dist - keyword_bonus)
        ranked_all = sorted(rows, key=lambda r: float(r['vec_dist']) - float(r['keyword_bonus']))

        # Deduplicate: keep best-scored row per unique product name
        seen_names: dict = {}
        for row in ranked_all:
            name = row['name']
            if name not in seen_names:
                seen_names[name] = row
        ranked = list(seen_names.values())[:5]
        dedup_removed = len(ranked_all) - len(seen_names)

        avg_dist = sum(float(r['vec_dist']) for r in ranked) / len(ranked)
        low_confidence = avg_dist > 0.6
        rag_meta.update({
            "rag_confidence": round(avg_dist, 4), "rag_empty": False,
            "dedup_removed_count": dedup_removed,
            "unique_brands_count": len({row['brand'] for row in ranked}),
            "unique_categories_count": len({row['category'] for row in ranked}),
        })

        context_parts, sources = [], []
        for row in ranked:
            context_parts.append(
                f"Product: {row['name']}\n"
                f"Category: {row['category']} | Brand: {row['brand']} | Price: ${row['price']:.2f}\n"
                f"Description: {row['description']}\n"
                f"Specifications: {row['specifications'] or 'N/A'}\n"
            )
            sources.append(ProductSource(id=str(row['product_id']), name=row['name'], price=row['price']))

        context = "\n---\n".join(context_parts)
        if low_confidence:
            available_cats = list(CATEGORY_KEYWORDS.keys())
            context += f"\n\n[Note: Low confidence match. Available categories: {', '.join(available_cats)}]"

        return context, sources, rag_meta

    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return "", [], {"rag_confidence": None, "rag_empty": True, "price_filter_used": False, "price_filter_value": None, "detected_category": None}

# ── Unanswered detection ──────────────────────────────────────────────────────
def detect_unanswered(response: str, sources_count: int, history: List[ChatMessage]) -> bool:
    response_lower = response.lower()
    has_uncertainty = any(phrase in response_lower for phrase in UNCERTAINTY_PHRASES)
    return sources_count == 0 and has_uncertainty

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are ShopRight's expert AI assistant for a home improvement store. You are knowledgeable, precise, and safety-conscious.

## Your role
Help customers find the right products for their projects, understand specifications, compare options, and get practical advice on home improvement tasks.

## CRITICAL: Only recommend products from the provided catalog context
NEVER invent, fabricate, or guess product names, brands, or prices. You may ONLY name and price products that appear verbatim in the "Relevant products from our catalog" section provided with the user's message.
- If the catalog context doesn't contain a relevant product, say so honestly and suggest the customer ask a store associate — do not make up a product.
- If catalog context is not provided at all, do not recommend specific products.

## Ask before recommending
When a product request is vague (no budget, use case, or preference stated), ask 1-2 short clarifying questions BEFORE recommending. Examples:
- "I need a drill" → "What will you mainly use it for — light home tasks or heavy-duty work? And do you have a budget in mind?"
- "I want paint" → "Which room and surface? Do you have a finish preference (matte, eggshell, gloss)?"
- "Show me lawn mowers" → "How large is your lawn, and do you prefer cordless or gas-powered?"
Only ask once — if the user has already given enough context, go straight to recommendations.

## How to answer product questions
When product catalog context is provided:
1. Recommend the MOST RELEVANT product(s) from the catalog — match the customer's stated need precisely.
2. Always include the product name, brand, and exact price from the catalog (e.g. "The DeWalt 20V MAX Drill at $129.99").
3. If multiple options exist, compare them on the most relevant dimensions (power, price, weight, battery).
4. Mention compatibility or safety considerations when relevant.
5. If you already recommended products earlier in this conversation, do NOT repeat the same ones — offer different options or explain why the previous ones are still the best fit.

## Product links
When a user asks for product links or where to find a product:
- Tell them: "You can click the product cards shown below my messages to go directly to each product page."
- Do NOT say you cannot provide links — the product cards in this chat are clickable links.

## Comparisons
When the user asks to compare products or uses "vs", "versus", "which is better", format your response as a compact markdown table with columns: Product | Price | Best For. Keep each cell under 8 words. Use short separators (e.g. |---|---|---|). Do not pad or align columns.

## Pricing guidance
- Always show prices when available.
- If asked for budget options, prioritize the lowest-priced items that meet the requirement.
- If asked for professional/heavy-duty options, prioritize power and durability over price.

## Low-confidence matches
If the catalog note says "[Note: Low confidence match]", be honest that you couldn't find an exact match and suggest the customer browse the listed categories or ask a store associate.

## When you cannot find a matching product
- If the user is asking how to fix or repair something (leaky faucet, broken tile, etc.), give practical DIY advice first, then mention any relevant tools, materials, or related products from the catalog that could help.
- If no related products exist at all, say: "I couldn't find an exact match in our current catalog for [item]. Please ask a store associate for help." Do NOT fabricate product names or prices.

## Referring back to previous recommendations
If the user refers to products mentioned earlier in the conversation (e.g. "those structural elements", "the products you mentioned", "the ones above"), recall those specific products from the conversation history and answer based on them — do not redirect to the current catalog context.

## Off-topic or nonsensical input
If the message is not related to home improvement, products, or shopping (e.g. SQL queries, code, random text), respond with:
"I'm here to help you find home improvement products and answer DIY questions. Could you tell me what you're working on or looking for?"

## Customer service topics
If the message is about order refunds, returns, cancellations, delivery, account issues, billing, or complaints, respond with:
"For help with [topic], please contact our customer support team directly. I'm here to help with product questions and home improvement advice."
Do not suggest products for customer service queries.

## Tone and format
- Be concise but complete. Avoid filler phrases.
- Use bullet points for feature lists.
- For safety-critical tasks (electrical, structural, gas), always recommend consulting a licensed professional.
- Keep responses under 300 words unless the customer asks for detailed instructions."""

def build_contents(message: str, history: List[ChatMessage], context: str) -> list:
    contents = []
    for msg in history[-6:]:
        contents.append({"role": "user" if msg.role == "user" else "model", "parts": [{"text": msg.content}]})
    user_message = message
    if context:
        user_message = (
            f"Relevant products from our catalog:\n{context}\n\n"
            f"Customer question: {message}\n\n"
            f"Please answer using the product information above where relevant."
        )
    contents.append({"role": "user", "parts": [{"text": user_message}]})
    return contents

# ── BigQuery logging ──────────────────────────────────────────────────────────
async def log_to_bigquery(session_id, message_id, user_message, assistant_response, sources, latency_ms, is_unanswered, extra: dict | None = None):
    if not GCP_PROJECT:
        return
    try:
        row = {
            "session_id": session_id, "message_id": message_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_message": user_message, "assistant_response": assistant_response,
            "sources_used": json.dumps([s.model_dump() for s in sources]),
            "message_length": len(user_message), "response_length": len(assistant_response),
            "sources_count": len(sources), "latency_ms": latency_ms, "is_unanswered": is_unanswered,
        }
        if extra:
            row.update(extra)
        bq = bigquery.Client(project=GCP_PROJECT)
        errors = bq.insert_rows_json(f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}", [row])
        if errors:
            logger.error(f"BigQuery insert errors for {message_id}: {errors}")
    except Exception as e:
        logger.error(f"Failed to log to BigQuery: {e}")

async def log_feedback_to_bigquery(message_id, session_id, rating, user_message, assistant_response):
    if not GCP_PROJECT:
        return
    try:
        bq = bigquery.Client(project=GCP_PROJECT)
        bq.insert_rows_json(
            f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_FEEDBACK_TABLE}",
            [{"message_id": message_id, "session_id": session_id,
              "timestamp": datetime.now(timezone.utc).isoformat(),
              "rating": rating, "user_message": user_message or "",
              "assistant_response": assistant_response or ""}],
        )
    except Exception as e:
        logger.error(f"Failed to log feedback to BigQuery: {e}")

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "chatbot"}


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE streaming endpoint. Yields tokens then a final metadata event."""
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    async def generate():
        t0 = time.monotonic()
        history = request.history or []
        turn_number = len([m for m in history if m.role == "assistant"]) + 1

        # Short-circuit: wellbeing / emotional distress — respond with empathy, no RAG
        if is_wellbeing_message(request.message):
            yield f"data: {json.dumps({'token': WELLBEING_RESPONSE, 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': False})}\n\n"
            _we_latency = int((time.monotonic() - t0) * 1000)
            _we = {"session_id": session_id, "message_id": message_id,
                   "timestamp": datetime.now(timezone.utc).isoformat(),
                   "latency_ms": _we_latency, "turn_number": turn_number,
                   "wellbeing_triggered": True, "is_unanswered": False, "llm_error": False}
            _req_metrics.append(_we)
            if len(_req_metrics) > 1000: _req_metrics.pop(0)
            asyncio.create_task(log_to_bigquery(
                session_id, message_id, request.message, WELLBEING_RESPONSE, [], _we_latency, False,
                extra={"turn_number": turn_number, "wellbeing_triggered": True},
            ))
            return

        # Short-circuit: session ending — skip RAG, stream canned farewell
        if is_session_ending(request.message, history):
            for token in SESSION_END_RESPONSE.split(" "):
                yield f"data: {json.dumps({'token': token + ' ', 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': True})}\n\n"
            return

        # Step 1: rewrite follow-ups, then embed + RAG
        metrics_ctx: dict = {}
        was_rewritten = False
        rag_meta: dict = {}
        rag_ms = None
        if is_product_query(request.message):
            search_query, was_rewritten = await rewrite_query(request.message, history)

            t_rag = time.monotonic()
            context, sources, rag_meta = await get_relevant_context(search_query)
            rag_ms = int((time.monotonic() - t_rag) * 1000)
        else:
            context, sources = "", []
            rag_meta = {"rag_confidence": None, "rag_empty": None, "price_filter_used": False,
                        "price_filter_value": None, "detected_category": None,
                        "dedup_removed_count": None, "unique_brands_count": None,
                        "unique_categories_count": None, "embed_ms": None, "db_ms": None}

        # Step 2: stream LLM tokens
        contents = build_contents(request.message, history, context)
        full_response = ""
        t_llm = time.monotonic()
        metrics_ctx["_t_llm_start"] = t_llm
        async for token in gemini_stream(contents, SYSTEM_PROMPT, metrics_ctx):
            full_response += token
            yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
        llm_ms = int((time.monotonic() - t_llm) * 1000)

        # Step 3: send final metadata event
        # Only show chips for products Gemini actually named — avoids irrelevant RAG noise
        mentioned = [s for s in sources if s.name.lower() in full_response.lower()]
        final_sources = mentioned if mentioned else sources
        latency_ms = int((time.monotonic() - t0) * 1000)
        is_unanswered = detect_unanswered(full_response, len(final_sources), history)
        yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [s.model_dump() for s in final_sources], 'is_unanswered': is_unanswered, 'session_ending': False})}\n\n"

        # Step 4: record metrics
        tokens_in  = metrics_ctx.get("tokens_in") or None
        tokens_out = metrics_ctx.get("tokens_out") or None
        cost = ((tokens_in or 0) / 1e6 * _COST_PER_1M_IN) + ((tokens_out or 0) / 1e6 * _COST_PER_1M_OUT)
        llm_error_type: str | None = metrics_ctx.get("llm_error_type")
        ttft_ms = metrics_ctx.get("ttft_ms") or None
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
            "query_rewritten": was_rewritten,
            "embed_ms": rag_meta.get("embed_ms"),
            "db_ms": rag_meta.get("db_ms"),
            "rag_ms": rag_ms,
            "embed_model": embed_model_name(),
            "llm_ms": llm_ms,
            "ttft_ms": ttft_ms,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "estimated_cost_usd": round(cost, 8) if cost else None,
            "wellbeing_triggered": False,
            "dedup_removed_count": rag_meta.get("dedup_removed_count"),
            "unique_brands_count": rag_meta.get("unique_brands_count"),
            "unique_categories_count": rag_meta.get("unique_categories_count"),
            "hallucination_flag": (len(sources) > 0 and not any(
                s.name.lower() in full_response.lower() for s in sources
            )) if sources else None,
            "context_pct": round(tokens_in / GEMINI_CONTEXT_LIMIT * 100, 1) if tokens_in else None,
        }
        _req_metrics.append(m)
        if len(_req_metrics) > 1000:
            _req_metrics.pop(0)
        _conf = rag_meta.get('rag_confidence')
        _conf_str = f"{_conf:.3f}" if _conf is not None else "N/A"
        logger.info(f"[metrics] latency={latency_ms}ms embed={rag_meta.get('embed_ms')}ms db={rag_meta.get('db_ms')}ms llm={llm_ms}ms ttft={ttft_ms}ms tokens={tokens_in}+{tokens_out} cost=${cost:.6f} rag_conf={_conf_str} model={embed_model_name()} unanswered={is_unanswered} rewritten={was_rewritten} turn={turn_number}")

        asyncio.create_task(log_to_bigquery(
            session_id, message_id, request.message, full_response, final_sources, latency_ms, is_unanswered,
            extra={k: v for k, v in m.items() if k not in ("session_id","message_id","timestamp","latency_ms","is_unanswered")},
        ))

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Non-streaming fallback endpoint."""
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    history = request.history or []

    if is_product_query(request.message):
        search_query, _ = await rewrite_query(request.message, history)
        context, sources, _ = await get_relevant_context(search_query)
    else:
        context, sources = "", []

    contents = build_contents(request.message, history, context)
    response_text, latency_ms = await gemini_generate(contents, SYSTEM_PROMPT)
    mentioned = [s for s in sources if s.name.lower() in response_text.lower()]
    final_sources = mentioned if mentioned else sources
    is_unanswered = detect_unanswered(response_text, len(final_sources), history)

    asyncio.create_task(log_to_bigquery(
        session_id, message_id, request.message, response_text, final_sources, latency_ms, is_unanswered
    ))
    return ChatResponse(response=response_text, session_id=session_id, message_id=message_id,
                        sources=final_sources, is_unanswered=is_unanswered)


@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    if request.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 (up) or -1 (down)")
    asyncio.create_task(log_feedback_to_bigquery(
        request.message_id, request.session_id, request.rating,
        request.user_message or "", request.assistant_response or "",
    ))
    return {"status": "ok"}


@app.get("/metrics/summary")
async def metrics_summary():
    """Live metrics summary from the in-memory buffer (last 1000 requests)."""
    if not _req_metrics:
        return {"message": "No requests yet — send some chat messages first"}

    n = len(_req_metrics)
    latencies = sorted(m["latency_ms"] for m in _req_metrics)
    unanswered = [m for m in _req_metrics if m["is_unanswered"]]
    errors     = [m for m in _req_metrics if m.get("llm_error")]
    rewritten  = [m for m in _req_metrics if m.get("query_rewritten")]
    price_filtered = [m for m in _req_metrics if m.get("price_filter_used")]
    rag_empty  = [m for m in _req_metrics if m.get("rag_empty")]

    # Per-step timing lists (only requests where the step ran)
    rag_times   = sorted(m["rag_ms"]    for m in _req_metrics if m.get("rag_ms"))
    llm_times   = sorted(m["llm_ms"]    for m in _req_metrics if m.get("llm_ms"))
    ttft_times  = sorted(m["ttft_ms"]   for m in _req_metrics if m.get("ttft_ms"))
    embed_times = sorted(m["embed_ms"]  for m in _req_metrics if m.get("embed_ms"))
    db_times    = sorted(m["db_ms"]     for m in _req_metrics if m.get("db_ms"))

    # Error type breakdown
    error_types: dict = defaultdict(int)
    for m in _req_metrics:
        if m.get("llm_error_type"):
            error_types[m["llm_error_type"]] += 1

    tokens_in  = [m["tokens_in"]  for m in _req_metrics if m.get("tokens_in")]
    tokens_out = [m["tokens_out"] for m in _req_metrics if m.get("tokens_out")]
    costs      = [m["estimated_cost_usd"] for m in _req_metrics if m.get("estimated_cost_usd")]

    confs = [m["rag_confidence"] for m in _req_metrics if m.get("rag_confidence")]

    # Category breakdown
    cat_stats: dict = defaultdict(lambda: {"requests": 0, "unanswered": 0})
    for m in _req_metrics:
        cat = m.get("detected_category") or "General / Conversational"
        cat_stats[cat]["requests"] += 1
        if m["is_unanswered"]:
            cat_stats[cat]["unanswered"] += 1

    # Turn distribution
    turns = [m["turn_number"] for m in _req_metrics]

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
            "p50_ms": p(latencies, 50),
            "p95_ms": p(latencies, 95),
            "p99_ms": p(latencies, 99),
            "avg_ms": int(sum(latencies) / n),
        },
        "step_timings": {
            "embed_avg_ms": avg(embed_times),
            "embed_p95_ms": p(embed_times, 95),
            "db_avg_ms":    avg(db_times),
            "db_p95_ms":    p(db_times, 95),
            "rag_avg_ms":   avg(rag_times),
            "rag_p95_ms":   p(rag_times, 95),
            "llm_avg_ms":   avg(llm_times),
            "llm_p95_ms":   p(llm_times, 95),
            "ttft_avg_ms":  avg(ttft_times),
            "ttft_p95_ms":  p(ttft_times, 95),
        },
        "rag": {
            "avg_confidence_score": round(sum(confs)/len(confs), 4) if confs else None,
            "empty_results_rate": pct(rag_empty),
            "price_filter_usage_rate": pct(price_filtered),
            "query_rewrite_rate": pct(rewritten),
        },
        "tokens": {
            "avg_input":  int(sum(tokens_in)/len(tokens_in))   if tokens_in  else 0,
            "avg_output": int(sum(tokens_out)/len(tokens_out)) if tokens_out else 0,
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
            "avg_context_pct": round(sum(m.get("context_pct", 0) for m in _req_metrics) / n, 1),
            "max_context_pct": max((m.get("context_pct", 0) for m in _req_metrics), default=0),
        },
    }


async def _log_event_to_bq(req: AnalyticsEventRequest):
    if not GCP_PROJECT:
        return
    try:
        bq = bigquery.Client(project=GCP_PROJECT)
        bq.insert_rows_json(
            f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_EVENTS_TABLE}",
            [{"event_type": req.event_type, "session_id": req.session_id,
              "message_id": req.message_id or "", "product_id": req.product_id or "",
              "product_name": req.product_name or "",
              "timestamp": datetime.now(timezone.utc).isoformat()}],
        )
    except Exception as e:
        logger.error(f"Failed to log event to BigQuery: {e}")


@app.post("/analytics/event")
async def analytics_event(request: AnalyticsEventRequest):
    """Log a frontend event (chip click, chatbot open, etc.) to BigQuery."""
    asyncio.create_task(_log_event_to_bq(request))
    return {"status": "ok"}


@app.post("/review")
async def review(request: ReviewRequest):
    if request.stars < 1 or request.stars > 5:
        raise HTTPException(status_code=400, detail="stars must be between 1 and 5")
    if GCP_PROJECT:
        try:
            bq = bigquery.Client(project=GCP_PROJECT)
            bq.insert_rows_json(
                f"{GCP_PROJECT}.{BQ_DATASET}.session_reviews",
                [{"session_id": request.session_id,
                  "stars": request.stars,
                  "timestamp": datetime.now(timezone.utc).isoformat()}],
            )
        except Exception as e:
            logger.error(f"Failed to log review to BigQuery: {e}")
    return {"status": "ok"}


@app.post("/embeddings/ingest")
async def ingest_products():
    conn = await asyncpg.connect(DATABASE_URL)
    products = await conn.fetch(
        "SELECT id, name, description, category, brand, price, specifications FROM products"
    )
    ingested = 0
    for product in products:
        specs = product['specifications'] or ""
        # Rich document text — written like a product description a customer would read,
        # matches the embedding model's training distribution
        text = (
            f"{product['name']} by {product['brand']}. "
            f"Category: {product['category']}. "
            f"Price: ${product['price']:.2f}. "
            f"{product['description']}. "
            f"Specifications and key features: {specs}."
        ).strip()
        vector, _ = await local_embed(text)
        await conn.execute(
            """
            INSERT INTO product_embeddings (product_id, name, description, category, brand, price, specifications, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            ON CONFLICT (product_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                brand = EXCLUDED.brand,
                price = EXCLUDED.price,
                specifications = EXCLUDED.specifications
            """,
            product['id'], product['name'], product['description'],
            product['category'], product['brand'], product['price'],
            product['specifications'], str(vector),
        )
        ingested += 1
    await conn.close()
    return {"message": f"Ingested {ingested} products using {embed_model_name()}"}
