"""Pydantic request/response models for the ShopRight chatbot API."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = []   # used for seeding on pod restart
    session_started_at: Optional[str] = None


class ProductSource(BaseModel):
    id: str
    name: str
    price: float
    category: str = ""


class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
    sources: List[ProductSource] = []
    is_unanswered: bool = False
    session_ending: bool = False


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    rating: int
    user_message: Optional[str] = None
    assistant_response: Optional[str] = None


class ReviewRequest(BaseModel):
    session_id: str
    stars: int
    turn_count: Optional[int] = None
    unanswered_count: Optional[int] = None


class AnalyticsEventRequest(BaseModel):
    event_type: str
    session_id: str
    message_id: Optional[str] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    product_price: Optional[float] = None
    product_category: Optional[str] = None
