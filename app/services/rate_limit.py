from __future__ import annotations

import logging

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.settings = get_settings()

    async def enforce_chat_limit(self, workspace_id: str) -> None:
        limit = self.settings.chat_rate_limit_per_minute
        if limit <= 0:
            return

        key = f"rate:chat:{workspace_id}"
        try:
            async with self.redis.pipeline(transaction=True) as pipeline:
                pipeline.incr(key)
                pipeline.ttl(key)
                count, ttl = await pipeline.execute()
            if ttl == -1:
                await self.redis.expire(key, 60)
            if int(count) > limit:
                retry_after = max(int(ttl), 1) if int(ttl) > 0 else 60
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except RedisError as exc:
            logger.exception("Redis rate limiting failed")
            if not self.settings.rate_limit_fail_open:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Rate limiter is temporarily unavailable",
                ) from exc
