from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    media_type: str
    status: str
    error_message: str | None
    chunk_count: int
    visibility: Literal["workspace", "restricted"]
    allowed_groups: list[str]
    created_by: str | None
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]


class DocumentAccessUpdate(BaseModel):
    visibility: Literal["workspace", "restricted"]
    allowed_groups: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("allowed_groups")
    @classmethod
    def normalize_groups(cls, groups: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw_group in groups:
            group = raw_group.strip()
            if group and group not in seen:
                if len(group) > 120:
                    raise ValueError("Group names must not exceed 120 characters")
                seen.add(group)
                result.append(group)
        return result

    @model_validator(mode="after")
    def validate_restricted_groups(self) -> DocumentAccessUpdate:
        if self.visibility == "restricted" and not self.allowed_groups:
            raise ValueError("Restricted documents require at least one allowed group")
        if self.visibility == "workspace":
            self.allowed_groups = []
        return self
