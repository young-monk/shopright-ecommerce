from fastapi import FastAPI, Depends, HTTPException, status, Response, Cookie, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Boolean, DateTime, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
import os, uuid

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://shopright:shopright_dev@localhost:5432/shopright")
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required and not set")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24  # 24 hours

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="User Service", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# No CORS needed — this service is internal, only called by the API gateway

async def get_db():
    async with async_session() as session:
        yield session

def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _decode_token(token: str) -> User | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    auth_token: str | None = Cookie(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
):
    # Accept token from httpOnly cookie (preferred) or Authorization header (API clients)
    raw_token = auth_token or (credentials.credentials if credentials else None)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _decode_token(raw_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "user-service"}

_SECURE_COOKIE = os.getenv("ENVIRONMENT", "development") == "production"

def _set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIE,      # HTTPS-only in prod
        samesite="lax",
        max_age=JWT_EXPIRE_MINUTES * 60,
        path="/",
    )

@app.post("/users/register", status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, data: UserCreate, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=pwd_context.hash(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_token(str(user.id), user.email)
    _set_auth_cookie(response, token)
    return {"user_id": str(user.id), "email": user.email}

@app.post("/users/login")
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(str(user.id), user.email)
    _set_auth_cookie(response, token)
    return {"user_id": str(user.id), "email": user.email, "full_name": user.full_name}

@app.post("/users/logout")
async def logout(response: Response):
    response.delete_cookie(key="auth_token", path="/")
    return {"status": "logged out"}

@app.get("/users/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"id": str(current_user.id), "email": current_user.email, "full_name": current_user.full_name, "is_admin": current_user.is_admin}
