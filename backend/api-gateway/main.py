from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ShopRight API Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVICES = {
    "products": os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8001"),
    "orders": os.getenv("ORDER_SERVICE_URL", "http://localhost:8002"),
    "users": os.getenv("USER_SERVICE_URL", "http://localhost:8003"),
}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "api-gateway"}

@app.api_route("/products{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_products(path: str, request: Request):
    return await proxy(f"{SERVICES['products']}/products{path}", request)

@app.api_route("/orders{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_orders(path: str, request: Request):
    return await proxy(f"{SERVICES['orders']}/orders{path}", request)

@app.api_route("/users{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_users(path: str, request: Request):
    return await proxy(f"{SERVICES['users']}/users{path}", request)

async def proxy(url: str, request: Request):
    body = await request.body()
    params = dict(request.query_params)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=url,
                params=params,
                content=body,
                headers=headers,
            )
            from fastapi.responses import Response
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Service unavailable")
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            raise HTTPException(status_code=500, detail="Internal gateway error")
