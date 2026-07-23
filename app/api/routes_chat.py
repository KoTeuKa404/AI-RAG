from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import ChatRateLimiter, DbSession, PrincipalContext
from app.db.models import ChatLog, Document
from app.schemas.chat import (
    ChatFeedbackRequest,
    ChatFeedbackResponse,
    ChatRequest,
    ChatResponse,
    SourceItem,
)
from app.services.access_control import document_access_clause
from app.services.llm import LLMError
from app.services.rag import answer_question

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    session: DbSession,
    principal: PrincipalContext,
    limiter: ChatRateLimiter,
) -> ChatResponse:
    await limiter.enforce_chat_limit(principal.workspace_id)

    if payload.document_id is not None:
        document = await session.scalar(
            select(Document).where(
                Document.id == payload.document_id,
                Document.workspace_id == principal.workspace_id,
                document_access_clause(principal),
            )
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found or access is denied",
            )
        if document.status != "ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Document is not ready (status: {document.status})",
            )

    try:
        chat_id, answer, chunks = await answer_question(
            session,
            principal,
            payload.question.strip(),
            document_id=payload.document_id,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Локальна LLM не встигла сформувати відповідь.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Локальний LLM API недоступний.",
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return ChatResponse(
        chat_id=chat_id,
        answer=answer,
        sources=[
            SourceItem(
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                similarity=round(chunk.similarity, 4),
                excerpt=chunk.content[:300],
            )
            for chunk in chunks
        ],
    )


@router.put("/{chat_id}/feedback", response_model=ChatFeedbackResponse)
async def save_chat_feedback(
    chat_id: uuid.UUID,
    payload: ChatFeedbackRequest,
    session: DbSession,
    principal: PrincipalContext,
) -> ChatFeedbackResponse:
    chat_log = await session.scalar(
        select(ChatLog).where(
            ChatLog.id == chat_id,
            ChatLog.workspace_id == principal.workspace_id,
        )
    )
    if chat_log is None or (
        not principal.is_admin and chat_log.actor_id != principal.subject
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat entry not found")

    comment = payload.comment.strip() if payload.comment else None
    chat_log.feedback_rating = payload.rating
    chat_log.feedback_comment = comment or None
    await session.commit()
    return ChatFeedbackResponse(
        chat_id=chat_log.id,
        rating=chat_log.feedback_rating,
        comment=chat_log.feedback_comment,
    )
