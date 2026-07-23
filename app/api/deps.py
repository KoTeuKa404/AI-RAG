from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_workspace_id
from app.db.session import get_db
from app.services.rate_limit import RateLimiter

WorkspaceId = Annotated[str, Depends(get_workspace_id)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


ChatRateLimiter = Annotated[RateLimiter, Depends(get_rate_limiter)]
