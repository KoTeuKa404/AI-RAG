from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Role = Literal["owner", "admin", "editor", "viewer"]


class ApiPrincipalConfig(BaseModel):
    """Identity and permissions associated with one API key."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=120)
    role: Role = "viewer"
    groups: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("workspace_id", "subject")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value must not be empty")
        return cleaned

    @field_validator("groups", mode="before")
    @classmethod
    def parse_groups(cls, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("groups must be a list or comma-separated string")
        groups: list[str] = []
        seen: set[str] = set()
        for raw_group in value:
            group = str(raw_group).strip()
            if group and group not in seen:
                seen.add(group)
                groups.append(group)
        return groups


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AI Knowledge Assistant"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+asyncpg://rag:replace-with-a-database-password@postgres:5432/rag"
    )
    redis_url: str = "redis://redis:6379/0"

    api_keys_json: dict[str, ApiPrincipalConfig] = Field(
        default_factory=lambda: {
            "replace-with-a-long-random-key": ApiPrincipalConfig(
                workspace_id="demo-workspace",
                subject="local-admin",
                role="owner",
                groups=["*"],
            )
        }
    )

    llm_base_url: str = "http://host.docker.internal:8080/v1"
    llm_api_key: str = "local-not-secret"
    llm_model: str = "deepseek"
    llm_timeout_seconds: float = 90.0
    llm_max_output_tokens: int = 700
    llm_temperature: float = 0.1
    llm_reasoning_effort: str = ""

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384
    embedding_device: str = "cpu"

    max_upload_bytes: int = 15 * 1024 * 1024
    max_extracted_characters: int = 2_000_000
    chunk_size: int = 900
    chunk_overlap: int = 150

    document_indexing_mode: Literal["async", "sync"] = "async"
    document_raw_ttl_seconds: int = 3600

    rag_top_k: int = 5
    rag_min_similarity: float = 0.15
    rag_hybrid_search: bool = True
    rag_keyword_weight: float = 0.25
    rag_candidate_multiplier: int = 4

    chat_rate_limit_per_minute: int = 30
    rate_limit_fail_open: bool = False
    cors_origins: list[str] = Field(default_factory=list)

    telegram_bot_token: str = ""
    backend_url: str = "http://api:8000"
    backend_api_key: str = "replace-with-a-long-random-key"
    allowed_telegram_user_ids: str = ""

    @field_validator("api_keys_json", mode="before")
    @classmethod
    def parse_api_keys(cls, value: Any) -> dict[str, dict[str, Any]]:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("API_KEYS_JSON must be a JSON object")

        normalized: dict[str, dict[str, Any]] = {}
        for raw_key, raw_principal in value.items():
            key = str(raw_key)
            if isinstance(raw_principal, str):
                workspace_id = raw_principal.strip()
                normalized[key] = {
                    "workspace_id": workspace_id,
                    "subject": f"legacy:{workspace_id}",
                    "role": "owner",
                    "groups": ["*"],
                }
                continue
            if isinstance(raw_principal, ApiPrincipalConfig):
                normalized[key] = raw_principal.model_dump()
                continue
            if not isinstance(raw_principal, dict):
                raise ValueError("Each API key value must be a workspace string or an object")
            principal = dict(raw_principal)
            workspace_id = str(principal.get("workspace_id", "")).strip()
            principal.setdefault("subject", f"api:{workspace_id}" if workspace_id else "api-key")
            principal.setdefault("role", "viewer")
            principal.setdefault("groups", [])
            normalized[key] = principal
        return normalized

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS must be a JSON array")
            return [str(item) for item in parsed]
        raise ValueError("CORS_ORIGINS must be a JSON array")

    @property
    def allowed_telegram_users(self) -> set[int]:
        try:
            return {
                int(item.strip())
                for item in self.allowed_telegram_user_ids.split(",")
                if item.strip()
            }
        except ValueError as exc:
            raise ValueError("ALLOWED_TELEGRAM_USER_IDS must be comma-separated integers") from exc

    @field_validator("chunk_overlap")
    @classmethod
    def validate_overlap(cls, value: int, info: Any) -> int:
        chunk_size = info.data.get("chunk_size", 900)
        if value < 0 or value >= chunk_size:
            raise ValueError("CHUNK_OVERLAP must be >= 0 and smaller than CHUNK_SIZE")
        return value

    @field_validator("api_keys_json")
    @classmethod
    def validate_api_keys(
        cls, value: dict[str, ApiPrincipalConfig]
    ) -> dict[str, ApiPrincipalConfig]:
        if not value:
            raise ValueError("At least one API key must be configured")
        for key in value:
            if len(key) < 20:
                raise ValueError("Each API key must contain at least 20 characters")
        return value

    @field_validator("document_raw_ttl_seconds")
    @classmethod
    def validate_document_raw_ttl(cls, value: int) -> int:
        if value < 60:
            raise ValueError("DOCUMENT_RAW_TTL_SECONDS must be at least 60 seconds")
        return value

    @field_validator("rag_candidate_multiplier")
    @classmethod
    def validate_candidate_multiplier(cls, value: int) -> int:
        if value < 1:
            raise ValueError("RAG_CANDIDATE_MULTIPLIER must be at least 1")
        return value

    @field_validator("rag_keyword_weight")
    @classmethod
    def validate_keyword_weight(cls, value: float) -> float:
        if value < 0:
            raise ValueError("RAG_KEYWORD_WEIGHT must not be negative")
        return value

    @model_validator(mode="after")
    def reject_placeholder_secrets_in_production(self) -> Settings:
        if self.app_env.lower() != "production":
            return self
        insecure_api_key = any(key.startswith("replace-with-") for key in self.api_keys_json)
        if insecure_api_key or "replace-with-a-database-password" in self.database_url:
            raise ValueError("Production configuration still contains placeholder secrets")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
