from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def get_workspace_id(x_api_key: str = Header(alias="X-API-Key")) -> str:
    settings = get_settings()
    for configured_key, workspace_id in settings.api_keys_json.items():
        if hmac.compare_digest(x_api_key, configured_key):
            return workspace_id
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
