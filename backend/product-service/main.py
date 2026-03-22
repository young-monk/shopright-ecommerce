from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, Boolean, Text, SmallInteger, Date, select, and_, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from pydantic import BaseModel, field_serializer
from typing import Optional, List
from uuid import UUID
from datetime import date
import os, uuid

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://shopright:shopright_dev@localhost:5432/shopright")

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Product(Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String)
    brand: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    original_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    specifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string

class ProductReview(Base):
    __tablename__ = "product_reviews"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    stars: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    review_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewResponse(BaseModel):
    id: UUID
    product_id: Optional[UUID]
    sku: str
    stars: int
    title: Optional[str]
    body: Optional[str]
    author: Optional[str]
    review_date: Optional[date]
    verified: bool

    model_config = {"from_attributes": True}

    @field_serializer("id", "product_id")
    def serialize_uuid(self, v) -> Optional[str]:
        return str(v) if v else None


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str
    category: str
    brand: str
    price: float
    original_price: Optional[float] = None
    stock: int = 0
    image_url: Optional[str] = None
    is_featured: bool = False
    specifications: Optional[str] = None

class ProductResponse(BaseModel):
    id: UUID | str
    sku: str
    name: str
    description: str
    category: str
    brand: str
    price: float
    original_price: Optional[float]
    stock: int
    rating: float
    review_count: int
    image_url: Optional[str]
    is_featured: bool
    specifications: Optional[str]

    model_config = {"from_attributes": True}

    @field_serializer("id")
    def serialize_id(self, v) -> str:
        return str(v)

app = FastAPI(title="Product Service", version="1.0.0")

# No CORS needed — this service is internal, only called by the API gateway

async def get_db():
    async with async_session() as session:
        yield session

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "product-service"}

@app.get("/products")
async def list_products(
    category: Optional[str] = None,
    featured: Optional[bool] = None,
    search: Optional[str] = None,
    min_price: float = 0,
    max_price: float = 999999,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    conditions = [Product.price >= min_price, Product.price <= max_price]
    if category:
        conditions.append(Product.category.ilike(f"%{category}%"))
    if featured is not None:
        conditions.append(Product.is_featured == featured)
    if search:
        conditions.append(
            (Product.name.ilike(f"%{search}%")) | (Product.description.ilike(f"%{search}%"))
        )

    count_result = await db.execute(select(func.count()).select_from(Product).where(and_(*conditions)))
    total = count_result.scalar_one()

    result = await db.execute(
        select(Product).where(and_(*conditions)).offset(offset).limit(limit)
    )
    products = result.scalars().all()
    return {
        "products": [ProductResponse.model_validate(p) for p in products],
        "total": total,
        "limit": limit,
        "offset": offset,
        "pages": -(-total // limit),  # ceiling division
    }

@app.get("/products/{product_id}")
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse.model_validate(product)

@app.post("/products", status_code=201)
async def create_product(data: ProductCreate, db: AsyncSession = Depends(get_db)):
    product = Product(**data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return ProductResponse.model_validate(product)

@app.put("/products/{product_id}")
async def update_product(product_id: str, data: ProductCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, value in data.model_dump().items():
        setattr(product, key, value)
    await db.commit()
    await db.refresh(product)
    return ProductResponse.model_validate(product)

@app.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.delete(product)
    await db.commit()


@app.get("/products/{product_id}/reviews")
async def get_product_reviews(
    product_id: str,
    limit: int = Query(default=10, le=50),
    offset: int = 0,
    sort: str = Query(default="recent", pattern="^(recent|highest|lowest)$"),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated reviews for a product."""
    # Verify product exists
    prod_result = await db.execute(select(Product).where(Product.id == product_id))
    if not prod_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    order_col = {
        "recent":  ProductReview.review_date.desc().nulls_last(),
        "highest": ProductReview.stars.desc(),
        "lowest":  ProductReview.stars.asc(),
    }[sort]

    count_result = await db.execute(
        select(func.count()).select_from(ProductReview).where(ProductReview.product_id == product_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(ProductReview)
        .where(ProductReview.product_id == product_id)
        .order_by(order_col)
        .offset(offset)
        .limit(limit)
    )
    reviews = result.scalars().all()

    # Compute star distribution
    dist_result = await db.execute(
        select(ProductReview.stars, func.count().label("cnt"))
        .where(ProductReview.product_id == product_id)
        .group_by(ProductReview.stars)
    )
    distribution = {row.stars: row.cnt for row in dist_result}

    return {
        "reviews": [ReviewResponse.model_validate(r) for r in reviews],
        "total": total,
        "limit": limit,
        "offset": offset,
        "pages": -(-total // limit) if total else 0,
        "star_distribution": {str(i): distribution.get(i, 0) for i in range(1, 6)},
    }
