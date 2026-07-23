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
    answer: str
    sources: list[SourceItem]
