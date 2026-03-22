"""
Step 2 — Fine-tune the embedding model on ShopRight product queries.

Uses MultipleNegativesRankingLoss: for each (query, product) pair in a batch,
every other product in the batch acts as a hard negative. No manual negative
mining needed — the loss learns to pull query↔product together and push
query↔wrong-product apart.

Base model: multi-qa-mpnet-base-dot-v1
  - 768 dims (matches existing pgvector index — no schema changes needed)
  - Pre-trained on 200M+ QA pairs, excellent starting point for product search

Usage:
    pip install -r requirements.txt
    python train.py                          # uses training_data.json
    python train.py --data my_data.json      # custom data file
    python train.py --epochs 5 --batch 32   # override defaults

Output:
    ../models/shopright-embed/  — fine-tuned model directory
    Next step: python reembed.py
"""
import argparse
import json
import os
import math

from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader

BASE_MODEL = "multi-qa-mpnet-base-dot-v1"
OUTPUT_DIR = "../models/shopright-embed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data",   default="training_data.json")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch",  type=int, default=16)
    parser.add_argument("--lr",     type=float, default=2e-5)
    args = parser.parse_args()

    # Load training pairs
    with open(args.data) as f:
        pairs = json.load(f)
    print(f"Loaded {len(pairs)} training pairs from {args.data}")

    examples = [InputExample(texts=[p["query"], p["product"]]) for p in pairs]
    loader = DataLoader(examples, shuffle=True, batch_size=args.batch)

    # Load base model
    print(f"Loading base model: {BASE_MODEL}")
    model = SentenceTransformer(BASE_MODEL)

    # MultipleNegativesRankingLoss: in-batch negatives, no explicit negatives needed
    loss = losses.MultipleNegativesRankingLoss(model)

    warmup_steps = math.ceil(len(loader) * args.epochs * 0.1)
    print(f"Training: {args.epochs} epochs | batch={args.batch} | warmup={warmup_steps} steps")

    model.fit(
        train_objectives=[(loader, loss)],
        epochs=args.epochs,
        warmup_steps=warmup_steps,
        optimizer_params={"lr": args.lr},
        show_progress_bar=True,
        output_path=OUTPUT_DIR,
    )

    print(f"\nFine-tuned model saved to {OUTPUT_DIR}")
    print(f"Next step: DATABASE_URL=... python reembed.py")

    # Quick sanity check
    print("\nSanity check:")
    test_pairs = [
        ("best cordless drill for drywall", pairs[0]["product"]),
        ("cheap garden hose under $30",     pairs[min(5, len(pairs)-1)]["product"]),
    ]
    for query, doc in test_pairs:
        q_vec = model.encode(query, normalize_embeddings=True)
        d_vec = model.encode(doc,   normalize_embeddings=True)
        score = float(q_vec @ d_vec)
        print(f"  {query[:50]!r} → similarity={score:.3f}")


if __name__ == "__main__":
    main()
