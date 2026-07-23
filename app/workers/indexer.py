from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.document_indexer import mark_document_failed, index_document_from_bytes
from app.services.indexing_queue import INDEXING_QUEUE_KEY, IndexingJob, raw_document_key

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


async def _handle_job(redis: Redis, raw_job: str | bytes) -> None:
    job = IndexingJob.from_json(raw_job)
    raw_key = raw_document_key(job.document_id)
    data = await redis.get(raw_key)
    if data is None:
        async with SessionLocal() as session:
            await mark_document_failed(
                session,
                job.document_id,
                job.workspace_id,
                "Temporary raw upload data expired before indexing",
            )
        return
    if isinstance(data, str):
        data = data.encode("utf-8")

    try:
        async with SessionLocal() as session:
            await index_document_from_bytes(
                session,
                document_id=job.document_id,
                workspace_id=job.workspace_id,
                data=data,
                media_type=job.media_type,
            )
    finally:
        await redis.delete(raw_key)


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    logger.info("Document indexing worker started; queue=%s", INDEXING_QUEUE_KEY)
    try:
        while True:
            try:
                item = await redis.brpop(INDEXING_QUEUE_KEY, timeout=5)
                if item is None:
                    continue
                _, raw_job = item
                await _handle_job(redis, raw_job)
            except (RedisError, OSError):
                logger.exception("Indexing worker Redis error; retrying")
                await asyncio.sleep(5)
            except Exception:
                logger.exception("Indexing worker failed to process a job")
                await asyncio.sleep(1)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
