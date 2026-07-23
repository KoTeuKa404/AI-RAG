from __future__ import annotations

from fastapi import APIRouter, Request
from redis.exceptions import RedisError
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, session: DbSession) -> dict[str, str]:
    database = "ok"
    redis = "ok"

    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        database = "error"

    try:
        await request.app.state.redis.ping()
    except RedisError:
        redis = "error"

    overall = "ok" if database == "ok" and redis == "ok" else "degraded"
    return {"status": overall, "database": database, "redis": redis}
