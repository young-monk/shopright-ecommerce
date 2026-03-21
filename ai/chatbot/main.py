"""
ShopRight AI Chatbot Service
- Uses Google Gemini REST API directly
- Uses pgvector for RAG (product catalog embedded with text-embedding-004)
- Logs all conversations to BigQuery for analytics
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
import uuid
import json
import logging
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
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-1.5-flash")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://shopright:shopright_dev@localhost:5432/shopright")
BQ_DATASET = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE = os.getenv("BIGQUERY_TABLE", "chat_logs")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

app = FastAPI(title="ShopRight Chatbot", version="1.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ── Request/Response Models ───────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = []

class ChatResponse(BaseModel):
    response: str
    session_id: str
    sources: List[str] = []
    message_id: str

# ── Gemini REST helpers ───────────────────────────────────────────────────────
async def gemini_embed(text: str) -> list[float] | None:
    if not GEMINI_API_KEY:
        return None
    url = f"{GEMINI_BASE}/models/{EMBED_MODEL}:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": f"models/{EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": "RETRIEVAL_QUERY",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            return resp.json()["embedding"]["values"]
        logger.warning(f"Embed error {resp.status_code}: {resp.text[:200]}")
        return None

async def gemini_generate(contents: list, system_prompt: str) -> str:
    if not GEMINI_API_KEY:
        return "[Chatbot not configured] Please set GEMINI_API_KEY."
    url = f"{GEMINI_BASE}/models/{LLM_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
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

async def generate_response(message: str, history: List[ChatMessage], context: str) -> str:
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
async def log_to_bigquery(session_id, message_id, user_message, assistant_response, sources):
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
            }],
        )
        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
    except Exception as e:
        logger.error(f"Failed to log to BigQuery: {e}")


# ── API Endpoints ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "chatbot"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    context, sources = await get_relevant_context(request.message)
    response_text = await generate_response(request.message, request.history or [], context)

    asyncio.create_task(
        log_to_bigquery(session_id, message_id, request.message, response_text, sources)
    )

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        sources=sources,
        message_id=message_id,
    )

@app.post("/embeddings/ingest")
async def ingest_products():
    """Ingest product catalog into vector store for RAG."""
    if not GEMINI_API_KEY:
        return {"message": "GEMINI_API_KEY not configured, skipping ingestion"}

    conn = await asyncpg.connect(DATABASE_URL)
    products = await conn.fetch(
        "SELECT id, name, description, category, brand, price, specifications FROM products"
    )

    ingested = 0
    for product in products:
        text = f"{product['name']} {product['description']} {product['category']} {product['brand']}"
        url = f"{GEMINI_BASE}/models/{EMBED_MODEL}:embedContent?key={GEMINI_API_KEY}"
        payload = {
            "model": f"models/{EMBED_MODEL}",
            "content": {"parts": [{"text": text}]},
            "taskType": "RETRIEVAL_DOCUMENT",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error(f"Embed failed for {product['name']}: {resp.text[:200]}")
                continue
            vector = resp.json()["embedding"]["values"]

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
