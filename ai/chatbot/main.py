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

import httpx
from google.cloud import bigquery
import asyncpg
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

SESSION_END_PHRASES = [
    "thanks", "thank you", "that's all", "that's it", "i'm done", "im done",
    "goodbye", "bye", "see you", "see ya", "all set", "got it", "perfect",
    "great thanks", "no more questions", "nothing else", "that's everything",
    "i'm good", "im good", "i'm all good", "that'll do", "no thanks",
]

SESSION_END_RESPONSE = (
    "You're welcome! Before you go — how would you rate your experience today? "
    "Your feedback helps us improve. ⭐"
)

def is_session_ending(message: str, history: List) -> bool:
    """Return True if the user is wrapping up the conversation."""
    msg = message.lower().strip()
    # Must be a short, closing message
    if len(msg.split()) > 6:
        return False
    return any(phrase in msg for phrase in SESSION_END_PHRASES)

UNCERTAINTY_PHRASES = [
    "i don't have", "i don't know", "i'm not sure", "i cannot find",
    "not available in", "no information", "outside my knowledge",
    "can't help with that", "unable to find", "not in our catalog",
]

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Power Tools":            ["drill", "saw", "grinder", "sander", "router", "jigsaw", "circular saw", "impact driver", "nail gun", "heat gun", "power tool"],
    "Hand Tools":             ["hammer", "screwdriver", "wrench", "pliers", "chisel", "hand tool", "tape measure", "level", "utility knife"],
    "Lawn & Garden":          ["lawn", "mower", "garden", "grass", "trimmer", "edger", "fertilizer", "soil", "mulch", "seed", "weed", "sprinkler", "hose", "rake", "shovel"],
    "Outdoor Power Equipment":["chainsaw", "leaf blower", "pressure washer", "snow blower", "generator", "outdoor power"],
    "Plumbing":               ["pipe", "faucet", "toilet", "sink", "drain", "valve", "fitting", "plumbing", "water heater"],
    "Electrical":             ["wire", "cable", "outlet", "switch", "breaker", "circuit", "electrical", "conduit", "panel"],
    "Flooring":               ["floor", "tile", "hardwood", "laminate", "vinyl", "carpet", "grout", "underlayment"],
    "Paint":                  ["paint", "primer", "stain", "brush", "roller", "spray", "coating", "varnish"],
    "Hardware":               ["bolt", "screw", "nut", "anchor", "hinge", "lock", "latch", "fastener", "hardware"],
    "Safety":                 ["safety", "glove", "helmet", "goggle", "respirator", "harness", "protective"],
    "Storage":                ["shelf", "cabinet", "rack", "storage", "organizer", "bin", "drawer"],
    "HVAC":                   ["hvac", "air conditioner", "heater", "furnace", "duct", "vent", "thermostat", "filter"],
}

app = FastAPI(title="ShopRight Chatbot", version="2.0.0")
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


async def gemini_stream(contents: list, system_prompt: str):
    """Async generator that yields text chunks from Gemini streaming API."""
    if not GEMINI_API_KEY:
        yield "[Chatbot not configured] Please set GEMINI_API_KEY."
        return
    url = f"{GEMINI_BASE}/models/{LLM_MODEL}:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                logger.error(f"Gemini stream error {response.status_code}: {body[:200]}")
                raise HTTPException(status_code=502, detail=f"LLM error: {response.status_code}")
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        parts = chunk["candidates"][0]["content"]["parts"]
                        text = next((p.get("text", "") for p in parts if "text" in p), "")
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

# ── Query rewriting for follow-ups ───────────────────────────────────────────
_FOLLOWUP_SIGNALS = [
    "cheaper", "more expensive", "similar", "another", "else", "instead",
    "that one", "this one", "those", "these", "it", "them", "show me more",
    "what about", "how about", "any other", "alternatives",
]

async def rewrite_query(message: str, history: List[ChatMessage]) -> str:
    """
    Rewrite a follow-up query into a standalone product search query
    by injecting context from the conversation history.
    Only rewrites when the message is ambiguous/short and references prior context.
    """
    if not history or not GEMINI_API_KEY:
        return message

    msg_lower = message.lower()
    is_followup = (
        len(message.split()) <= 8 and
        any(sig in msg_lower for sig in _FOLLOWUP_SIGNALS)
    )
    if not is_followup:
        return message

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
                    return message
                rewritten = text.strip().strip('"')
                logger.info(f"Query rewrite: '{message}' → '{rewritten}'")
                return rewritten
    except Exception as e:
        logger.warning(f"Query rewrite failed: {e}")
    return message

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
    "select ", "insert ", "update ", "delete ", "drop ", "create table",
    "from ", "where ", "join ", "group by", "order by",
    "def ", "class ", "import ", "function ", "console.log", "print(",
    "* from", "SELECT *",
]

def is_product_query(query: str) -> bool:
    query_lower = query.lower().strip()
    if any(p.lower() in query_lower for p in NON_PRODUCT_PATTERNS):
        return False
    if len(query_lower.split()) <= 3:
        if any(phrase in query_lower for phrase in CONVERSATIONAL_PHRASES):
            return False
    if any(kw in query_lower for kw in PRODUCT_INTENT_KEYWORDS):
        return True
    if detect_category(query) is not None:
        return True
    if any(p in query_lower for p in ["what is", "what are", "which", "how do i", "how to", "can i use"]):
        return True
    # Also treat follow-up signals as product queries if there's history
    if any(sig in query_lower for sig in _FOLLOWUP_SIGNALS):
        return True
    return len(query_lower.split()) > 4

# ── Category detection ────────────────────────────────────────────────────────
def detect_category(query: str) -> str | None:
    query_lower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return category
    return None

# ── RAG: Hybrid Vector + Keyword Search ──────────────────────────────────────
async def get_relevant_context(query: str, top_k: int = 10) -> tuple[str, list[ProductSource]]:
    vector = await gemini_embed(query)
    if not vector:
        return "", []

    detected_category = detect_category(query)
    stop_words = {"what", "which", "that", "this", "with", "have", "from", "your", "best", "good",
                  "need", "want", "some", "for", "can", "how", "does", "show", "find", "give",
                  "tell", "about", "under", "over", "more", "less", "cheap", "cheaper", "those", "other"}
    keywords = [w for w in query.lower().split() if len(w) >= 4 and w not in stop_words]

    try:
        conn = await asyncpg.connect(DATABASE_URL)

        if detected_category and keywords:
            keyword_pattern = "%(" + "|".join(keywords) + ")%"
            rows = await conn.fetch(
                """
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist,
                       CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END AS keyword_bonus
                FROM product_embeddings
                WHERE category ILIKE $4
                ORDER BY (embedding <=> $1::vector) - (CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END)
                LIMIT $2
                """,
                str(vector), top_k, keyword_pattern, f"%{detected_category}%",
            )
            if not rows:
                rows = await conn.fetch(
                    """
                    SELECT product_id, name, description, category, brand, price, specifications,
                           (embedding <=> $1::vector) AS vec_dist,
                           CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END AS keyword_bonus
                    FROM product_embeddings
                    ORDER BY (embedding <=> $1::vector) - (CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END)
                    LIMIT $2
                    """,
                    str(vector), top_k, keyword_pattern,
                )
        elif detected_category:
            rows = await conn.fetch(
                """
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist, 0 AS keyword_bonus
                FROM product_embeddings
                WHERE category ILIKE $3
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                str(vector), top_k, f"%{detected_category}%",
            )
            if not rows:
                rows = await conn.fetch(
                    """
                    SELECT product_id, name, description, category, brand, price, specifications,
                           (embedding <=> $1::vector) AS vec_dist, 0 AS keyword_bonus
                    FROM product_embeddings ORDER BY embedding <=> $1::vector LIMIT $2
                    """,
                    str(vector), top_k,
                )
        elif keywords:
            keyword_pattern = "%(" + "|".join(keywords) + ")%"
            rows = await conn.fetch(
                """
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist,
                       CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END AS keyword_bonus
                FROM product_embeddings
                ORDER BY (embedding <=> $1::vector) - (CASE WHEN LOWER(name || ' ' || description) ~ $3 THEN 0.15 ELSE 0 END)
                LIMIT $2
                """,
                str(vector), top_k, keyword_pattern,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT product_id, name, description, category, brand, price, specifications,
                       (embedding <=> $1::vector) AS vec_dist, 0 AS keyword_bonus
                FROM product_embeddings ORDER BY embedding <=> $1::vector LIMIT $2
                """,
                str(vector), top_k,
            )

        await conn.close()

        if not rows:
            return "", []

        # Re-rank: sort by combined score (vec_dist - keyword_bonus), take top 5 for context
        ranked = sorted(rows, key=lambda r: float(r['vec_dist']) - float(r['keyword_bonus']))[:5]

        # "Did you mean?" — check if confidence is low (all results have high vec_dist)
        avg_dist = sum(float(r['vec_dist']) for r in ranked) / len(ranked)
        low_confidence = avg_dist > 0.6

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

        return context, sources

    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return "", []

# ── Unanswered detection ──────────────────────────────────────────────────────
def detect_unanswered(response: str, sources_count: int, history: List[ChatMessage]) -> bool:
    response_lower = response.lower()
    has_uncertainty = any(phrase in response_lower for phrase in UNCERTAINTY_PHRASES)
    no_sources = sources_count == 0
    if no_sources and has_uncertainty:
        return True
    if no_sources and len(history) >= 2:
        recent_user_msgs = [m for m in history[-4:] if m.role == "user"]
        if len(recent_user_msgs) >= 2:
            return True
    return False

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are ShopRight's expert AI assistant for a home improvement store. You are knowledgeable, precise, and safety-conscious.

## Your role
Help customers find the right products for their projects, understand specifications, compare options, and get practical advice on home improvement tasks.

## How to answer product questions
When product catalog context is provided:
1. Recommend the MOST RELEVANT product(s) from the catalog — match the customer's stated need precisely.
2. Always include the product name, brand, and exact price (e.g. "The DeWalt 20V MAX Drill at $129.99").
3. If multiple options exist, compare them on the most relevant dimensions (power, price, weight, battery).
4. Mention compatibility or safety considerations when relevant.

## Comparisons
When the user asks to compare products or uses "vs", "versus", "which is better", format your response as a markdown table with columns: Product | Price | Best For.

## Pricing guidance
- Always show prices when available.
- If asked for budget options, prioritize the lowest-priced items that meet the requirement.
- If asked for professional/heavy-duty options, prioritize power and durability over price.

## Low-confidence matches
If the catalog note says "[Note: Low confidence match]", be honest that you couldn't find an exact match and suggest the customer browse the listed categories or ask a store associate.

## When you cannot find a matching product
Say clearly: "I couldn't find an exact match in our current catalog for [item]. Please ask a store associate for help." Do NOT fabricate product names or prices.

## Off-topic or nonsensical input
If the message is not related to home improvement, products, or shopping (e.g. SQL queries, code, random text), respond with:
"I'm here to help you find home improvement products and answer DIY questions. Could you tell me what you're working on or looking for?"

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
async def log_to_bigquery(session_id, message_id, user_message, assistant_response, sources, latency_ms, is_unanswered):
    if not GCP_PROJECT:
        return
    try:
        bq = bigquery.Client(project=GCP_PROJECT)
        bq.insert_rows_json(
            f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}",
            [{"session_id": session_id, "message_id": message_id,
              "timestamp": datetime.now(timezone.utc).isoformat(),
              "user_message": user_message, "assistant_response": assistant_response,
              "sources_used": json.dumps([s.model_dump() for s in sources]),
              "message_length": len(user_message), "response_length": len(assistant_response),
              "sources_count": len(sources), "latency_ms": latency_ms, "is_unanswered": is_unanswered}],
        )
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

        # Short-circuit: session ending — skip RAG, stream canned farewell
        if is_session_ending(request.message, history):
            for token in SESSION_END_RESPONSE.split(" "):
                yield f"data: {json.dumps({'token': token + ' ', 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [], 'is_unanswered': False, 'session_ending': True})}\n\n"
            return

        # Step 1: rewrite follow-ups, then RAG
        if is_product_query(request.message):
            search_query = await rewrite_query(request.message, history)
            context, sources = await get_relevant_context(search_query)
        else:
            context, sources = "", []

        # Step 2: stream LLM tokens
        contents = build_contents(request.message, history, context)
        full_response = ""
        try:
            async for token in gemini_stream(contents, SYSTEM_PROMPT):
                full_response += token
                yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
        except HTTPException:
            yield f"data: {json.dumps({'token': 'Sorry, I encountered an error. Please try again.', 'done': False})}\n\n"

        # Step 3: send final metadata event
        latency_ms = int((time.monotonic() - t0) * 1000)
        is_unanswered = detect_unanswered(full_response, len(sources), history)
        yield f"data: {json.dumps({'done': True, 'message_id': message_id, 'session_id': session_id, 'sources': [s.model_dump() for s in sources], 'is_unanswered': is_unanswered, 'session_ending': False})}\n\n"

        asyncio.create_task(log_to_bigquery(
            session_id, message_id, request.message, full_response, sources, latency_ms, is_unanswered
        ))

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Non-streaming fallback endpoint."""
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    history = request.history or []

    if is_product_query(request.message):
        search_query = await rewrite_query(request.message, history)
        context, sources = await get_relevant_context(search_query)
    else:
        context, sources = "", []

    contents = build_contents(request.message, history, context)
    response_text, latency_ms = await gemini_generate(contents, SYSTEM_PROMPT)
    is_unanswered = detect_unanswered(response_text, len(sources), history)

    asyncio.create_task(log_to_bigquery(
        session_id, message_id, request.message, response_text, sources, latency_ms, is_unanswered
    ))
    return ChatResponse(response=response_text, session_id=session_id, message_id=message_id,
                        sources=sources, is_unanswered=is_unanswered)


@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    if request.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 (up) or -1 (down)")
    asyncio.create_task(log_feedback_to_bigquery(
        request.message_id, request.session_id, request.rating,
        request.user_message or "", request.assistant_response or "",
    ))
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
    if not GEMINI_API_KEY:
        return {"message": "GEMINI_API_KEY not configured, skipping ingestion"}

    conn = await asyncpg.connect(DATABASE_URL)
    products = await conn.fetch(
        "SELECT id, name, description, category, brand, price, specifications FROM products"
    )
    ingested = 0
    for product in products:
        specs = product['specifications'] or ""
        text = (
            f"Category: {product['category']}. Product type: {product['name']}. "
            f"Brand: {product['brand']}. {product['description']}. Key features: {specs}"
        ).strip()
        vector = await gemini_embed(text, task_type="RETRIEVAL_DOCUMENT")
        if vector is None:
            logger.error(f"Embed failed for {product['name']}")
            continue
        await conn.execute(
            """
            INSERT INTO product_embeddings (product_id, name, description, category, brand, price, specifications, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            ON CONFLICT (product_id) DO UPDATE SET embedding = EXCLUDED.embedding
            """,
            product['id'], product['name'], product['description'],
            product['category'], product['brand'], product['price'],
            product['specifications'], str(vector),
        )
        ingested += 1
    await conn.close()
    return {"message": f"Ingested {ingested} products into vector store"}
