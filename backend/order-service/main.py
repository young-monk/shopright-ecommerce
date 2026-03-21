from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, Text, JSON, DateTime, select, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os, uuid, json

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://shopright:shopright_dev@localhost:5432/shopright")
engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, confirmed, shipped, delivered, cancelled
    items: Mapped[str] = mapped_column(Text)  # JSON list of {product_id, name, quantity, price}
    subtotal: Mapped[float] = mapped_column(Float)
    tax: Mapped[float] = mapped_column(Float)
    shipping: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)
    shipping_address: Mapped[str] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class OrderItem(BaseModel):
    product_id: str
    name: str
    quantity: int
    price: float

class ShippingAddress(BaseModel):
    full_name: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    zip_code: str
    country: str = "US"

class OrderCreate(BaseModel):
    user_id: str
    items: List[OrderItem]
    shipping_address: ShippingAddress

app = FastAPI(title="Order Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

async def get_db():
    async with async_session() as session:
        yield session

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "order-service"}

@app.post("/orders", status_code=201)
async def create_order(data: OrderCreate, db: AsyncSession = Depends(get_db)):
    subtotal = sum(item.price * item.quantity for item in data.items)
    tax = round(subtotal * 0.08, 2)
    shipping = 0 if subtotal >= 50 else 9.99
    total = round(subtotal + tax + shipping, 2)

    order = Order(
        user_id=data.user_id,
        items=json.dumps([item.model_dump() for item in data.items]),
        subtotal=subtotal,
        tax=tax,
        shipping=shipping,
        total=total,
        shipping_address=json.dumps(data.shipping_address.model_dump()),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return {"id": str(order.id), "status": order.status, "total": order.total}

@app.get("/orders/{order_id}")
async def get_order(order_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "id": order.id,
        "user_id": order.user_id,
        "status": order.status,
        "items": json.loads(order.items),
        "subtotal": order.subtotal,
        "tax": order.tax,
        "shipping": order.shipping,
        "total": order.total,
        "shipping_address": json.loads(order.shipping_address),
        "created_at": order.created_at.isoformat(),
    }

@app.get("/orders/user/{user_id}")
async def get_user_orders(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()))
    orders = result.scalars().all()
    return {"orders": [{"id": o.id, "status": o.status, "total": o.total, "created_at": o.created_at.isoformat()} for o in orders]}

@app.patch("/orders/{order_id}/status")
async def update_order_status(order_id: str, status: str, db: AsyncSession = Depends(get_db)):
    valid_statuses = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = status
    await db.commit()
    return {"id": order_id, "status": status}
