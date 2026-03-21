"""
ShopRight AI Chatbot Service
- Uses Vertex AI Gemini 1.5 Pro as LLM
- Uses pgvector for RAG (product catalog + FAQs embedded with text-embedding-004)
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

import vertexai
from vertexai.generative_models import GenerativeModel, Part, Content
from vertexai.language_models import TextEmbeddingModel
from google.cloud import bigquery

import asyncpg
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
VERTEX_LOCATION = os.getenv("VERTEX_AI_LOCATION", "us-central1")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-1.5-pro")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://shopright:shopright_dev@localhost:5432/shopright")
BQ_DATASET = os.getenv("BIGQUERY_DATASET", "chat_analytics")
BQ_TABLE = os.getenv("BIGQUERY_TABLE", "chat_logs")

# ── Startup ──────────────────────────────────────────────────────────────────
if GCP_PROJECT:
    vertexai.init(project=GCP_PROJECT, location=VERTEX_LOCATION)

app = FastAPI(title="ShopRight Chatbot", version="1.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ── Models ────────────────────────────────────────────────────────────────────
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

# ── RAG: Vector Search ────────────────────────────────────────────────────────
async def get_relevant_context(query: str, top_k: int = 5) -> tuple[str, list[str]]:
    """Embed query, find similar products/FAQs via pgvector, return context + source names."""
    try:
        embed_model = TextEmbeddingModel.from_pretrained(EMBED_MODEL)
        embeddings = embed_model.get_embeddings([query])
        query_vector = embeddings[0].values

        conn = await asyncpg.connect(DATABASE_URL)

        # Search product embeddings
        rows = await conn.fetch(
            """
            SELECT name, description, category, brand, price, specifications
            FROM product_embeddings
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            str(query_vector),
            top_k,
        )
        await conn.close()

        if not rows:
            return "", []

        context_parts = []
        sources = []
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
        logger.warning(f"RAG retrieval failed (using LLM without context): {e}")
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
    """Generate LLM response using Vertex AI Gemini."""
    if not GCP_PROJECT:
        # Fallback for local dev without GCP
        return f"[Dev mode - GCP not configured] I received your message: '{message}'. In production, I would search our product catalog and provide relevant recommendations."

    model = GenerativeModel(LLM_MODEL, system_instruction=SYSTEM_PROMPT)

    # Build conversation history
    contents = []
    for msg in history[-6:]:  # Last 6 messages for context window
        role = "user" if msg.role == "user" else "model"
        contents.append(Content(role=role, parts=[Part.from_text(msg.content)]))

    # Add current message with RAG context
    user_message = message
    if context:
        user_message = f"""Relevant products from our catalog:
{context}

Customer question: {message}

Please answer using the product information above where relevant."""

    contents.append(Content(role="user", parts=[Part.from_text(user_message)]))

    response = model.generate_content(contents)
    return response.text


# ── BigQuery Logging ──────────────────────────────────────────────────────────
async def log_to_bigquery(session_id: str, message_id: str, user_message: str, assistant_response: str, sources: list[str]):
    """Log chat interaction to BigQuery for analytics."""
    if not GCP_PROJECT:
        return
    try:
        client = bigquery.Client(project=GCP_PROJECT)
        table_id = f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

        rows = [{
            "session_id": session_id,
            "message_id": message_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_message": user_message,
            "assistant_response": assistant_response,
            "sources_used": json.dumps(sources),
            "message_length": len(user_message),
            "response_length": len(assistant_response),
            "sources_count": len(sources),
        }]

        errors = client.insert_rows_json(table_id, rows)
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

    # RAG: Get relevant product context
    context, sources = await get_relevant_context(request.message)

    # Generate LLM response
    response_text = await generate_response(request.message, request.history or [], context)

    # Async log to BigQuery (don't await - fire and forget)
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
    if not GCP_PROJECT:
        return {"message": "GCP not configured, skipping ingestion"}

    conn = await asyncpg.connect(DATABASE_URL)
    embed_model = TextEmbeddingModel.from_pretrained(EMBED_MODEL)

    # Fetch all products
    products = await conn.fetch("SELECT id, name, description, category, brand, price, specifications FROM products")

    ingested = 0
    for product in products:
        text = f"{product['name']} {product['description']} {product['category']} {product['brand']}"
        embeddings = embed_model.get_embeddings([text])
        vector = embeddings[0].values

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
