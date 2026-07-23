from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import ApiPrincipalConfig, Role, get_settings


@dataclass(frozen=True, slots=True)
class Principal:
    workspace_id: str
    subject: str
    role: Role
    groups: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return self.role in {"owner", "admin"}

    @property
    def can_edit(self) -> bool:
        return self.role in {"owner", "admin", "editor"}


def _to_principal(config: ApiPrincipalConfig) -> Principal:
    return Principal(
        workspace_id=config.workspace_id,
        subject=config.subject,
        role=config.role,
        groups=frozenset(config.groups),
    )


def authenticate_api_key(api_key: str) -> Principal:
    settings = get_settings()
    for configured_key, principal_config in settings.api_keys_json.items():
        if hmac.compare_digest(api_key, configured_key):
            return _to_principal(principal_config)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def get_principal(
    x_api_key: Annotated[str, Header(alias="X-API-Key")],
) -> Principal:
    return authenticate_api_key(x_api_key)


def get_workspace_id(
    x_api_key: Annotated[str, Header(alias="X-API-Key")],
) -> str:
    """Backward-compatible dependency for integrations that only need workspace ID."""
    return authenticate_api_key(x_api_key).workspace_id


def require_roles(principal: Principal, *allowed_roles: Role) -> None:
    if principal.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key does not have permission for this operation",
        )
