"""
Step 3 — Re-embed all products with the fine-tuned (or base) model.

Replaces all vectors in product_embeddings with vectors from the local model.
Run this after training a new model or when switching from Gemini embeddings.

Usage:
    DATABASE_URL=postgresql://... python reembed.py
    DATABASE_URL=postgresql://... python reembed.py --model ../models/shopright-embed
    DATABASE_URL=postgresql://... python reembed.py --dry-run   # preview only
"""
import argparse
import asyncio
import os
import sys

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]
DEFAULT_MODEL_DIR = "../models/shopright-embed"
BASE_MODEL = "multi-qa-mpnet-base-dot-v1"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",   default=DEFAULT_MODEL_DIR)
    parser.add_argument("--batch",   type=int, default=64)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load model
    from sentence_transformers import SentenceTransformer
    model_path = args.model if os.path.exists(args.model) else BASE_MODEL
    print(f"Loading model: {model_path}")
    model = SentenceTransformer(model_path)
    dim = model.get_sentence_embedding_dimension()
    print(f"Embedding dimension: {dim}")

    conn = await asyncpg.connect(DATABASE_URL)

    # Verify pgvector dimension matches
    rows = await conn.fetch(
        "SELECT product_id, name, description, category, brand, price, specifications "
        "FROM product_embeddings ORDER BY name"
    )
    print(f"Found {len(rows)} products to re-embed")

    if args.dry_run:
        print("Dry run — no DB writes. Remove --dry-run to apply.")
        await conn.close()
        return

    # Build document texts (same format as main.py context)
    def product_text(r) -> str:
        specs = r["specifications"] or "N/A"
        return (
            f"Product: {r['name']}\n"
            f"Category: {r['category']} | Brand: {r['brand']} | Price: ${float(r['price']):.2f}\n"
            f"Description: {r['description']}\n"
            f"Specifications: {specs}"
        )

    texts      = [product_text(r) for r in rows]
    product_ids = [r["product_id"] for r in rows]

    # Embed in batches
    print(f"Embedding {len(texts)} products (batch={args.batch})...")
    vectors = model.encode(
        texts,
        batch_size=args.batch,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    # Write to DB
    updated = 0
    async with conn.transaction():
        for pid, vec in zip(product_ids, vectors):
            await conn.execute(
                "UPDATE product_embeddings SET embedding = $1 WHERE product_id = $2",
                str(vec.tolist()), pid,
            )
            updated += 1

    await conn.close()
    print(f"\nDone. {updated} products re-embedded with {model_path}")
    print("Restart the chatbot service to use the new vectors.")


if __name__ == "__main__":
    asyncio.run(main())
