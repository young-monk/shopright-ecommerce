"""
ShopRight Knowledge Base Ingest
================================
Embeds and upserts 3 doc types into knowledge_embeddings:
  - 'product'        : one doc per product (from DB)
  - 'faq'            : one doc per FAQ (from data/faqs.json)
  - 'review_summary' : one review-summary per product (from data/reviews.json)

Also inserts individual reviews into product_reviews table.

Run once (or whenever catalog/FAQs/reviews change):
  python ingest.py

Requires: GEMINI_API_KEY and DATABASE_URL env vars.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DATABASE_URL   = os.getenv("DATABASE_URL", "postgresql://shopright:shopright_dev@localhost:5432/shopright")

_EMBED_MODEL  = "gemini-embedding-001"
_GEMINI_BASE  = "https://generativelanguage.googleapis.com/v1beta"
_BATCH_PAUSE  = 0.2   # seconds between embed API calls to avoid rate-limit

DATA_DIR = Path(__file__).parent / "data"


# ── Embedding ──────────────────────────────────────────────────────────────────

async def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """Call Gemini embedding API, return 3072-dim vector."""
    url = f"{_GEMINI_BASE}/models/{_EMBED_MODEL}:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": f"models/{_EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(3):
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return resp.json()["embedding"]["values"]
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Rate limited — waiting {wait}s")
                await asyncio.sleep(wait)
                continue
            raise RuntimeError(f"Embed error {resp.status_code}: {resp.text[:200]}")
    raise RuntimeError("Embed failed after 3 retries")


# ── Products ───────────────────────────────────────────────────────────────────

async def ingest_products(conn: asyncpg.Connection) -> int:
    rows = await conn.fetch(
        "SELECT id, sku, name, description, category, brand, price, specifications FROM products ORDER BY sku"
    )
    logger.info(f"Ingesting {len(rows)} products …")
    count = 0
    for row in rows:
        specs_raw = row["specifications"] or ""
        # Parse JSON specs into readable key: value pairs
        try:
            specs_dict = json.loads(specs_raw) if specs_raw else {}
            specs_text = " | ".join(f"{k}: {v}" for k, v in specs_dict.items())
        except Exception:
            specs_text = specs_raw

        content = (
            f"Product: {row['name']}\n"
            f"SKU: {row['sku']}\n"
            f"Category: {row['category']} | Brand: {row['brand']} | Price: ${row['price']:.2f}\n"
            f"Description: {row['description']}\n"
            f"Specifications: {specs_text}"
        )
        metadata = {
            "sku": row["sku"],
            "name": row["name"],
            "price": float(row["price"]),
            "category": row["category"],
            "brand": row["brand"],
        }
        vec = await embed_text(content)
        await conn.execute(
            """
            INSERT INTO knowledge_embeddings (doc_type, source_id, content, metadata, embedding)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (doc_type, source_id) DO UPDATE
                SET content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
            """,
            "product", str(row["id"]), content, json.dumps(metadata), str(vec),
        )
        count += 1
        if count % 50 == 0:
            logger.info(f"  products: {count}/{len(rows)}")
        await asyncio.sleep(_BATCH_PAUSE)
    logger.info(f"Upserted {count} product embeddings")
    return count


# ── FAQs ───────────────────────────────────────────────────────────────────────

async def ingest_faqs(conn: asyncpg.Connection) -> int:
    faq_path = DATA_DIR / "faqs.json"
    faqs = json.loads(faq_path.read_text())
    logger.info(f"Ingesting {len(faqs)} FAQs …")
    count = 0
    for i, faq in enumerate(faqs):
        source_id = f"faq-{i:04d}"
        content = f"Q: {faq['question']}\nA: {faq['answer']}"
        metadata = {"category": faq.get("category", "General"), "source_id": source_id}
        vec = await embed_text(content)
        await conn.execute(
            """
            INSERT INTO knowledge_embeddings (doc_type, source_id, content, metadata, embedding)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (doc_type, source_id) DO UPDATE
                SET content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
            """,
            "faq", source_id, content, json.dumps(metadata), str(vec),
        )
        count += 1
        await asyncio.sleep(_BATCH_PAUSE)
    logger.info(f"Upserted {count} FAQ embeddings")
    return count


# ── Reviews ────────────────────────────────────────────────────────────────────

async def ingest_reviews(conn: asyncpg.Connection) -> tuple[int, int]:
    """
    1. Insert individual reviews into product_reviews (skips dupes via unique index).
    2. Build one review_summary per product and upsert into knowledge_embeddings.
    Returns (reviews_inserted, summaries_upserted).
    """
    reviews_path = DATA_DIR / "reviews.json"
    all_entries = json.loads(reviews_path.read_text())
    logger.info(f"Ingesting reviews for {len(all_entries)} products …")

    # Build sku → product_id map from DB
    product_rows = await conn.fetch("SELECT id, sku FROM products")
    sku_to_id = {r["sku"]: r["id"] for r in product_rows}

    reviews_inserted = 0
    summaries_upserted = 0

    for entry in all_entries:
        sku = entry["sku"]
        product_id = sku_to_id.get(sku)
        if not product_id:
            logger.warning(f"  SKU {sku} not found in products table — skipping")
            continue

        reviews = entry.get("reviews", [])

        # ── Insert individual reviews ─────────────────────────────────────────
        for rev in reviews:
            try:
                review_date_raw = rev.get("date")
                review_date = None
                if review_date_raw:
                    try:
                        review_date = date.fromisoformat(review_date_raw)
                    except ValueError:
                        pass

                await conn.execute(
                    """
                    INSERT INTO product_reviews
                        (product_id, sku, stars, title, body, author, review_date, verified)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT DO NOTHING
                    """,
                    product_id,
                    sku,
                    int(rev.get("stars", 3)),
                    rev.get("title"),
                    rev.get("body"),
                    rev.get("author"),
                    review_date,
                    bool(rev.get("verified", False)),
                )
                reviews_inserted += 1
            except Exception as e:
                logger.warning(f"  Review insert error for {sku}: {e}")

        # ── Build review summary for RAG ──────────────────────────────────────
        if reviews:
            avg_stars = sum(r.get("stars", 3) for r in reviews) / len(reviews)
            sample = reviews[:5]  # top 5 reviews in summary
            summary_lines = [
                f"Customer reviews for {entry['name']} ({sku}):",
                f"Average rating: {avg_stars:.1f}/5 based on {len(reviews)} reviews.",
            ]
            for r in sample:
                summary_lines.append(f'- {r.get("stars")}★ "{r.get("title", "")}" — {r.get("body", "")[:200]}')

            summary_content = "\n".join(summary_lines)
            metadata = {
                "sku": sku,
                "name": entry["name"],
                "price": float(entry.get("price", 0)),
                "category": entry.get("category", ""),
                "brand": entry.get("brand", ""),
                "avg_rating": round(avg_stars, 2),
                "review_count": len(reviews),
            }
            vec = await embed_text(summary_content)
            await conn.execute(
                """
                INSERT INTO knowledge_embeddings (doc_type, source_id, content, metadata, embedding)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (doc_type, source_id) DO UPDATE
                    SET content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                """,
                "review_summary", sku, summary_content, json.dumps(metadata), str(vec),
            )
            summaries_upserted += 1
            await asyncio.sleep(_BATCH_PAUSE)

    logger.info(f"Inserted {reviews_inserted} reviews | Upserted {summaries_upserted} review summaries")
    return reviews_inserted, summaries_upserted


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    if not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is required")

    t0 = time.monotonic()
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        products  = await ingest_products(conn)
        faqs      = await ingest_faqs(conn)
        reviews, summaries = await ingest_reviews(conn)
    finally:
        await conn.close()

    elapsed = int(time.monotonic() - t0)
    logger.info(
        f"Ingest complete in {elapsed}s — "
        f"{products} products | {faqs} FAQs | {reviews} reviews | {summaries} review summaries"
    )


if __name__ == "__main__":
    asyncio.run(main())
