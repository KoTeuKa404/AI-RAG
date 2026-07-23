from typing import cast

from app.core.auth import Principal
from app.core.config import Role
from app.services.access_control import can_access_document_values


def _principal(role: str = "viewer", groups: set[str] | None = None) -> Principal:
    return Principal(
        workspace_id="workspace-a",
        subject="user-a",
        role=cast(Role, role),
        groups=frozenset(groups or set()),
    )


def test_workspace_document_is_visible_to_viewer() -> None:
    assert can_access_document_values(_principal(), "workspace", [])


def test_restricted_document_requires_matching_group() -> None:
    sales = _principal(groups={"sales"})
    support = _principal(groups={"support"})

    assert can_access_document_values(sales, "restricted", ["sales"])
    assert not can_access_document_values(support, "restricted", ["sales"])


def test_admin_can_access_restricted_document() -> None:
    assert can_access_document_values(_principal(role="admin"), "restricted", ["finance"])
