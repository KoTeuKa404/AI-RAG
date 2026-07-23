from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest


def test_chat_request_accepts_optional_document_id() -> None:
    document_id = uuid.uuid4()
    request = ChatRequest(question="What is this document about?", document_id=document_id)

    assert request.document_id == document_id


def test_chat_request_all_documents_by_default() -> None:
    request = ChatRequest(question="What is in the knowledge base?")

    assert request.document_id is None


def test_chat_request_rejects_invalid_document_id() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="What is this document about?", document_id="not-a-uuid")
