from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis
else:
    Redis = Any

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.db.models import Document
else:
    Document = Any

INDEXING_QUEUE_KEY = "documents:index:queue"
RAW_DOCUMENT_KEY_PREFIX = "documents:index:raw"


@dataclass(frozen=True, slots=True)
class IndexingJob:
    document_id: uuid.UUID
    workspace_id: str
    media_type: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "document_id": str(self.document_id),
                "workspace_id": self.workspace_id,
                "media_type": self.media_type,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> IndexingJob:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        payload = json.loads(value)
        return cls(
            document_id=uuid.UUID(str(payload["document_id"])),
            workspace_id=str(payload["workspace_id"]),
            media_type=str(payload["media_type"]),
        )


def raw_document_key(document_id: uuid.UUID | str) -> str:
    return f"{RAW_DOCUMENT_KEY_PREFIX}:{document_id}"


async def enqueue_document_indexing(
    redis: Redis,
    document: Document,
    data: bytes,
) -> None:
    settings = get_settings()
    job = IndexingJob(
        document_id=document.id,
        workspace_id=document.workspace_id,
        media_type=document.media_type,
    )
    raw_key = raw_document_key(document.id)
    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.set(raw_key, data, ex=settings.document_raw_ttl_seconds)
        pipeline.lpush(INDEXING_QUEUE_KEY, job.to_json())
        await pipeline.execute()
