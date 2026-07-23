from __future__ import annotations

import hashlib
import logging
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, WorkspaceId
from app.core.config import get_settings
from app.db.models import Document
from app.schemas.documents import DocumentListResponse, DocumentResponse
from app.services.document_indexer import index_document_from_bytes
from app.services.file_validation import FileValidationError, validate_uploaded_file
from app.services.indexing_queue import enqueue_document_indexing
from app.services.text_extractors import TextExtractionError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = await upload.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Uploaded file is too large",
            )
        chunks.append(block)
    return b"".join(chunks)


async def _get_workspace_document(
    session: DbSession,
    workspace_id: str,
    document_id: uuid.UUID,
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    session: DbSession,
    workspace_id: WorkspaceId,
    file: UploadFile = File(...),
) -> DocumentResponse:
    settings = get_settings()
    raw = await _read_limited(file, settings.max_upload_bytes)

    try:
        validated = validate_uploaded_file(
            filename=file.filename or "",
            data=raw,
            max_bytes=settings.max_upload_bytes,
        )
    except FileValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    digest = hashlib.sha256(validated.data).hexdigest()
    existing = await session.scalar(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.sha256 == digest,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This file already exists with document id {existing.id}",
        )

    document = Document(
        workspace_id=workspace_id,
        filename=validated.filename,
        media_type=validated.media_type,
        sha256=digest,
        status="processing",
    )
    session.add(document)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This file already exists",
        ) from exc
    await session.refresh(document)

    if settings.document_indexing_mode == "sync":
        try:
            document = await index_document_from_bytes(
                session,
                document.id,
                workspace_id,
                validated.data,
                validated.media_type,
            )
        except TextExtractionError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            logger.exception("Synchronous indexing failed for document %s", document.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document indexing failed",
            ) from exc
        return DocumentResponse.model_validate(document)

    try:
        await enqueue_document_indexing(request.app.state.redis, document, validated.data)
    except RedisError as exc:
        logger.exception("Could not enqueue document indexing job")
        document.status = "failed"
        document.error_message = "Could not enqueue indexing job"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Indexing queue is temporarily unavailable",
        ) from exc

    return DocumentResponse.model_validate(document)


@router.get("", response_model=DocumentListResponse)
async def list_documents(session: DbSession, workspace_id: WorkspaceId) -> DocumentListResponse:
    statement = (
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
        .limit(200)
    )
    documents = list((await session.scalars(statement)).all())
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(document) for document in documents]
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    session: DbSession,
    workspace_id: WorkspaceId,
) -> DocumentResponse:
    document = await _get_workspace_document(session, workspace_id, document_id)
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    session: DbSession,
    workspace_id: WorkspaceId,
) -> None:
    result = await session.execute(
        delete(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    if result.rowcount == 0:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await session.commit()
