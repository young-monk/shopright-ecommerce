"""
Step 1 — Generate training data for fine-tuning the embedding model.

For each product in the catalog, asks Gemini to write 5 realistic customer
queries that would lead someone to buy that product. Each (query, product_text)
pair becomes a positive training example.

Usage:
    pip install -r requirements.txt
    DATABASE_URL=postgresql://... GEMINI_API_KEY=... python generate_training_data.py

Output:
    training_data.json — list of {"query": ..., "product": ...} dicts
"""
import asyncio
import json
import os
import sys
import httpx
import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
QUERIES_PER_PRODUCT = 5
OUTPUT_FILE = "training_data.json"


async def fetch_products(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT name, description, category, brand, price, specifications FROM product_embeddings"
    )
    return [dict(r) for r in rows]


def product_text(p: dict) -> str:
    """Build the document text the same way main.py builds context."""
    specs = p.get("specifications") or "N/A"
    return (
        f"Product: {p['name']}\n"
        f"Category: {p['category']} | Brand: {p['brand']} | Price: ${float(p['price']):.2f}\n"
        f"Description: {p['description']}\n"
        f"Specifications: {specs}"
    )


async def generate_queries(product: dict, client: httpx.AsyncClient) -> list[str]:
    text = product_text(product)
    prompt = (
        f"You are a home improvement store customer.\n"
        f"Given this product:\n{text}\n\n"
        f"Write exactly {QUERIES_PER_PRODUCT} different realistic customer search queries "
        f"that would lead someone to find and buy this product. "
        f"Vary the phrasing: some short keyword queries, some full questions, some with price constraints. "
        f"Output ONLY the queries, one per line, no numbering, no extra text."
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 200, "thinkingConfig": {"thinkingBudget": 0}},
    }
    url = f"{GEMINI_BASE}/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    try:
        resp = await client.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            parts = resp.json()["candidates"][0]["content"]["parts"]
            text_out = next((p["text"] for p in parts if "text" in p), "")
            queries = [q.strip() for q in text_out.strip().splitlines() if q.strip()]
            return queries[:QUERIES_PER_PRODUCT]
    except Exception as e:
        print(f"  ⚠ Gemini error for {product['name']}: {e}", file=sys.stderr)
    return []


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    products = await fetch_products(conn)
    await conn.close()

    print(f"Found {len(products)} products. Generating {QUERIES_PER_PRODUCT} queries each...")

    pairs = []
    async with httpx.AsyncClient() as client:
        for i, product in enumerate(products):
            queries = await generate_queries(product, client)
            doc = product_text(product)
            for q in queries:
                pairs.append({"query": q, "product": doc})
            print(f"  [{i+1}/{len(products)}] {product['name'][:60]} — {len(queries)} queries")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(pairs, f, indent=2)

    print(f"\nDone. {len(pairs)} training pairs written to {OUTPUT_FILE}")
    print(f"Next step: python train.py")


if __name__ == "__main__":
    asyncio.run(main())
