FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libgomp1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install torch CPU-only first to avoid pulling in the 2GB GPU build
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the base embedding model at build time so the first request
# isn't slow. When a fine-tuned model is available, mount it at
# /app/models/shopright-embed and set LOCAL_EMBED_MODEL=/app/models/shopright-embed.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('multi-qa-mpnet-base-dot-v1')"

COPY . .
EXPOSE 8004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
