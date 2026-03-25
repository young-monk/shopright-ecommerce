"""RAG pipeline: vector search, Vertex AI reranking, and the ADK search_products tool."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import asyncpg
from opentelemetry import trace

from config import GCP_PROJECT, DATABASE_URL
from detection import detect_category, extract_price_limit, CATEGORY_KEYWORDS
from embed import embed as gemini_embed, model_name as embed_model_name
import state

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("shopright.chatbot.rag")

# ── Vertex AI Ranking API client (lazy init) ──────────────────────────────────
_rank_client = None


def _get_rank_client():
    global _rank_client
    if _rank_client is None:
        from google.cloud import discoveryengine_v1 as de
        _rank_client = de.RankServiceClient()
    return _rank_client


def _rerank_sync(query: str, rows: list, top_n: int) -> list:
    """Call Vertex AI Ranking API synchronously. Returns rows in ranked order."""
    from google.cloud import discoveryengine_v1 as de
    ranking_config = (
        f"projects/{GCP_PROJECT}/locations/global"
        f"/rankingConfigs/default_ranking_config"
    )
    records = [
        de.RankingRecord(id=str(i), content=r["content"][:512])
        for i, r in enumerate(rows)
    ]
    resp = _get_rank_client().rank(de.RankRequest(
        ranking_config=ranking_config,
        query=query,
        records=records,
        top_n=top_n,
    ))
    return [rows[int(r.id)] for r in resp.records]


async def get_relevant_context(query: str, top_k: int = 10) -> tuple[str, list, dict]:
    """Search knowledge_embeddings with hybrid ANN + Vertex AI Ranking API rerank."""
    with _tracer.start_as_current_span("embed_query") as span:
        span.set_attribute("query_length", len(query))
        vector, embed_ms = await gemini_embed(query, task_type="RETRIEVAL_QUERY")
        span.set_attribute("embed_ms", embed_ms or 0)
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
        conn = await (state._db_pool.acquire() if state._db_pool else asyncpg.connect(DATABASE_URL))

        price_clause = f"AND (metadata->>'price')::numeric <= {price_limit:.2f}" if price_limit is not None else ""
        cat_clause = f"AND metadata->>'category' ILIKE '%{detected_category}%'" if detected_category else ""

        keyword_bonus = "0"
        if keywords:
            kw_regex = "|".join(re.escape(k) for k in keywords)
            keyword_bonus = f"CASE WHEN LOWER(content) ~ '{kw_regex}' THEN 0.15 ELSE 0 END"

        # Fetch more candidates when Vertex AI rerank is available (50), else use top_k directly
        ann_limit = 50 if GCP_PROJECT else top_k

        with _tracer.start_as_current_span("vector_search") as span:
            span.set_attribute("ann_limit", ann_limit)
            span.set_attribute("price_filter", price_limit is not None)
            span.set_attribute("category_filter", detected_category or "")
            t_db = time.monotonic()
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
            span.set_attribute("candidates_returned", len(rows))
            span.set_attribute("db_ms", db_ms)

        if state._db_pool:
            await state._db_pool.release(conn)
        else:
            await conn.close()

        ann_candidates_count = len(rows) if rows else 0
        rag_meta = {
            "price_filter_used": price_limit is not None,
            "price_filter_value": price_limit,
            "detected_category": detected_category,
            "embed_ms": embed_ms,
            "db_ms": db_ms,
            "ann_candidates_count": ann_candidates_count,
        }

        if not rows:
            rag_meta.update({"rag_confidence": None, "rag_empty": True})
            return "", [], rag_meta

        # ── Rerank via Vertex AI Ranking API ──────────────────────────────────
        rerank_used = False
        if GCP_PROJECT and rows:
            with _tracer.start_as_current_span("vertex_rerank") as span:
                top_n = min(16, len(rows))
                span.set_attribute("candidates_in", len(rows))
                span.set_attribute("top_n", top_n)
                try:
                    reranked_rows = await asyncio.to_thread(_rerank_sync, query, rows, top_n)
                    rerank_used = True
                    span.set_attribute("rerank_used", True)
                except Exception as e:
                    logger.warning(f"Vertex AI rerank failed, falling back to hybrid score: {e}")
                    reranked_rows = sorted(rows, key=lambda r: float(r["vec_dist"]) - float(r["keyword_bonus"]))
                    span.set_attribute("rerank_used", False)
                    span.set_attribute("error", str(e))
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

        vec_distances = [float(r["vec_dist"]) for r in ranked]
        avg_dist = sum(vec_distances) / len(vec_distances)
        min_vec_distance = round(min(vec_distances), 4)
        low_confidence = avg_dist > 0.6
        product_rows = [r for r in ranked if r["doc_type"] == "product"]
        rag_meta.update({
            "rag_confidence": round(avg_dist, 4),
            "min_vec_distance": min_vec_distance,
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
                        "price_filter_value": None, "detected_category": None, "rerank_used": False}


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
    mid = state._cv_message_id.get("")
    if mid:
        state._sources_store[mid] = sources
        state._rag_meta_store[mid] = rag_meta
    return context if context else "No matching products found in our catalog for that query."
