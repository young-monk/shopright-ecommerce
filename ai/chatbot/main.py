"""
ShopRight AI Chatbot Service
- Uses Google Gemini REST API directly
- Uses pgvector for RAG (product catalog embedded with gemini-embedding-001)
- Logs all conversations to BigQuery for analytics
- Tracks: latency, user ratings, unanswered question detection
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

# ── Config ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://shopright:shopright_dev@localhost:5432/shopright")
BQ_DATASET = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE = os.getenv("BIGQUERY_TABLE", "chat_logs")
BQ_FEEDBACK_TABLE = os.getenv("BIGQUERY_FEEDBACK_TABLE", "feedback")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Phrases that indicate the bot couldn't answer
UNCERTAINTY_PHRASES = [
    "i don't have", "i don't know", "i'm not sure", "i cannot find",
    "not available in", "no information", "outside my knowledge",
    "can't help with that", "unable to find", "not in our catalog",
]

app = FastAPI(title="ShopRight Chatbot", version="1.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ── Request/Response Models ───────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = []

class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
    sources: List[str] = []
    is_unanswered: bool = False

class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    rating: int  # 1 = thumbs up, -1 = thumbs down
    user_message: Optional[str] = None
    assistant_response: Optional[str] = None

# ── Gemini REST helpers ───────────────────────────────────────────────────────
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
    """Returns (response_text, latency_ms)."""
    if not GEMINI_API_KEY:
        return "[Chatbot not configured] Please set GEMINI_API_KEY.", 0
    url = f"{GEMINI_BASE}/models/{LLM_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
    latency_ms = int((time.monotonic() - t0) * 1000)

    if resp.status_code == 200:
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"], latency_ms
    logger.error(f"Gemini generate error {resp.status_code}: {resp.text[:400]}")
    raise HTTPException(status_code=502, detail=f"LLM error: {resp.status_code}")

# ── RAG: Vector Search ────────────────────────────────────────────────────────
async def get_relevant_context(query: str, top_k: int = 5) -> tuple[str, list[str]]:
    vector = await gemini_embed(query)
    if not vector:
        return "", []
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch(
            """
            SELECT name, description, category, brand, price, specifications
            FROM product_embeddings
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            str(vector),
            top_k,
        )
        await conn.close()

        if not rows:
            return "", []

        context_parts, sources = [], []
        for row in rows:
            context_parts.append(
                f"Product: {row['name']}\n"
                f"Category: {row['category']} | Brand: {row['brand']} | Price: ${row['price']:.2f}\n"
                f"Description: {row['description']}\n"
                f"Specifications: {row['specifications'] or 'N/A'}\n"
            )
            sources.append(f"{row['name']} (${row['price']:.2f})")

        return "\n---\n".join(context_parts), sources

    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")
        return "", []

# ── Unanswered detection ──────────────────────────────────────────────────────
def detect_unanswered(response: str, sources_count: int, history: List[ChatMessage]) -> bool:
    """
    A message is flagged as unanswered if:
    - No RAG sources were found AND the response contains uncertainty phrases, OR
    - The user appears to be rephrasing a recent question (same session, no sources again)
    """
    response_lower = response.lower()
    has_uncertainty = any(phrase in response_lower for phrase in UNCERTAINTY_PHRASES)
    no_sources = sources_count == 0

    if no_sources and has_uncertainty:
        return True

    # Detect rephrase: last 2+ user messages with no sources in between
    if no_sources and len(history) >= 2:
        recent_user_msgs = [m for m in history[-4:] if m.role == "user"]
        if len(recent_user_msgs) >= 2:
            return True

    return False

# ── LLM Response ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are ShopRight's helpful AI assistant for a home improvement store.
You help customers:
- Find the right products for their projects
- Understand product specifications and compatibility
- Get advice on home improvement projects
- Compare products and brands
- Understand installation and usage

When you have product context from the store catalog, use it to give specific recommendations.
Always be helpful, accurate, and safety-conscious. If unsure, say so and suggest consulting a professional.
Keep responses concise but complete. Format lists clearly when helpful."""

async def generate_response(message: str, history: List[ChatMessage], context: str) -> tuple[str, int]:
    contents = []
    for msg in history[-6:]:
        role = "user" if msg.role == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg.content}]})

    user_message = message
    if context:
        user_message = (
            f"Relevant products from our catalog:\n{context}\n\n"
            f"Customer question: {message}\n\n"
            f"Please answer using the product information above where relevant."
        )
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    return await gemini_generate(contents, SYSTEM_PROMPT)

# ── BigQuery Logging ──────────────────────────────────────────────────────────
async def log_to_bigquery(
    session_id: str,
    message_id: str,
    user_message: str,
    assistant_response: str,
    sources: list[str],
    latency_ms: int,
    is_unanswered: bool,
):
    if not GCP_PROJECT:
        return
    try:
        bq = bigquery.Client(project=GCP_PROJECT)
        errors = bq.insert_rows_json(
            f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}",
            [{
                "session_id": session_id,
                "message_id": message_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_message": user_message,
                "assistant_response": assistant_response,
                "sources_used": json.dumps(sources),
                "message_length": len(user_message),
                "response_length": len(assistant_response),
                "sources_count": len(sources),
                "latency_ms": latency_ms,
                "is_unanswered": is_unanswered,
            }],
        )
        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
    except Exception as e:
        logger.error(f"Failed to log to BigQuery: {e}")

async def log_feedback_to_bigquery(
    message_id: str,
    session_id: str,
    rating: int,
    user_message: str,
    assistant_response: str,
):
    if not GCP_PROJECT:
        return
    try:
        bq = bigquery.Client(project=GCP_PROJECT)
        errors = bq.insert_rows_json(
            f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_FEEDBACK_TABLE}",
            [{
                "message_id": message_id,
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rating": rating,
                "user_message": user_message or "",
                "assistant_response": assistant_response or "",
            }],
        )
        if errors:
            logger.error(f"BigQuery feedback insert errors: {errors}")
    except Exception as e:
        logger.error(f"Failed to log feedback to BigQuery: {e}")

# ── API Endpoints ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "chatbot"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    context, sources = await get_relevant_context(request.message)
    response_text, latency_ms = await generate_response(request.message, request.history or [], context)
    is_unanswered = detect_unanswered(response_text, len(sources), request.history or [])

    asyncio.create_task(log_to_bigquery(
        session_id, message_id, request.message, response_text,
        sources, latency_ms, is_unanswered,
    ))

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        message_id=message_id,
        sources=sources,
        is_unanswered=is_unanswered,
    )

@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    if request.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 (up) or -1 (down)")
    asyncio.create_task(log_feedback_to_bigquery(
        request.message_id, request.session_id, request.rating,
        request.user_message or "", request.assistant_response or "",
    ))
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
        text = f"{product['name']} {product['description']} {product['category']} {product['brand']}"
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
