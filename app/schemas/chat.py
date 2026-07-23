from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    document_id: uuid.UUID | None = None


class SourceItem(BaseModel):
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    similarity: float
    excerpt: str


class ChatResponse(BaseModel):
    chat_id: uuid.UUID
    answer: str
    sources: list[SourceItem]


class ChatFeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ChatFeedbackResponse(BaseModel):
    chat_id: uuid.UUID
    rating: int
    comment: str | None
