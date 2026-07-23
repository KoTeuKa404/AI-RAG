from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Chunk, Document
from app.services.chunking import chunk_sections
from app.services.embeddings import embed_texts
from app.services.text_extractors import TextExtractionError, extract_text

logger = logging.getLogger(__name__)


class DocumentIndexingError(RuntimeError):
    pass


async def mark_document_failed(
    session: AsyncSession,
    document_id: uuid.UUID,
    workspace_id: str,
    message: str,
) -> None:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    if document is None:
        return
    document.status = "failed"
    document.error_message = message[:500]
    document.chunk_count = 0
    await session.commit()


async def index_document_from_bytes(
    session: AsyncSession,
    document_id: uuid.UUID,
    workspace_id: str,
    data: bytes,
    media_type: str,
) -> Document:
    settings = get_settings()
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    if document is None:
        raise DocumentIndexingError("Document not found")

    try:
        document.status = "processing"
        document.error_message = None
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        await session.flush()

        sections = extract_text(data, media_type, settings.max_extracted_characters)
        text_chunks = chunk_sections(sections, settings.chunk_size, settings.chunk_overlap)
        if not text_chunks:
            raise TextExtractionError("No chunks were created from the document")

        vectors = await embed_texts([item.content for item in text_chunks])
        for item, vector in zip(text_chunks, vectors, strict=True):
            session.add(
                Chunk(
                    document_id=document.id,
                    workspace_id=workspace_id,
                    page_number=item.page_number,
                    chunk_index=item.chunk_index,
                    content=item.content,
                    embedding=vector,
                )
            )

        document.status = "ready"
        document.chunk_count = len(text_chunks)
        document.error_message = None
        await session.commit()
        await session.refresh(document)
        return document
    except Exception as exc:
        logger.exception("Document indexing failed for document %s", document_id)
        await session.rollback()
        await mark_document_failed(session, document_id, workspace_id, str(exc) or "Indexing failed")
        raise
