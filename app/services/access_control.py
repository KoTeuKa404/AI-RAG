from __future__ import annotations

from sqlalchemy import or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.core.auth import Principal
from app.db.models import Document


def document_access_clause(principal: Principal) -> ColumnElement[bool]:
    """SQL predicate that never crosses a workspace and enforces document ACLs."""
    if principal.is_admin or "*" in principal.groups:
        return true()
    if principal.groups:
        return or_(
            Document.visibility == "workspace",
            Document.allowed_groups.overlap(sorted(principal.groups)),
        )
    return Document.visibility == "workspace"


def can_access_document_values(
    principal: Principal,
    visibility: str,
    allowed_groups: list[str] | None,
) -> bool:
    if principal.is_admin or "*" in principal.groups:
        return True
    if visibility == "workspace":
        return True
    return bool(principal.groups.intersection(allowed_groups or []))
