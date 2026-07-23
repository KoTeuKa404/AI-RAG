from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = "postgresql+asyncpg://rag:replace-with-a-database-password@postgres:5432/rag"
    redis_url: str = "redis://redis:6379/0"

    api_keys_json: dict[str, str] = Field(
        default_factory=lambda: {"replace-with-a-long-random-key": "demo-workspace"}
    )

    llm_base_url: str = "http://host.docker.internal:8080/v1"
    llm_api_key: str = "local-not-secret"
    llm_model: str = "deepseek"
    llm_timeout_seconds: float = 90.0
    llm_max_output_tokens: int = 700
    llm_temperature: float = 0.1

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
    def parse_api_keys(cls, value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("API_KEYS_JSON must be a JSON object")
            return {str(k): str(v) for k, v in parsed.items()}
        raise ValueError("API_KEYS_JSON must be a JSON object")

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
            raise ValueError(
                "ALLOWED_TELEGRAM_USER_IDS must be comma-separated integers"
            ) from exc

    @field_validator("chunk_overlap")
    @classmethod
    def validate_overlap(cls, value: int, info: Any) -> int:
        chunk_size = info.data.get("chunk_size", 900)
        if value < 0 or value >= chunk_size:
            raise ValueError("CHUNK_OVERLAP must be >= 0 and smaller than CHUNK_SIZE")
        return value

    @field_validator("api_keys_json")
    @classmethod
    def validate_api_keys(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("At least one API key must be configured")
        for key, workspace in value.items():
            if len(key) < 20:
                raise ValueError("Each API key must contain at least 20 characters")
            if not workspace.strip():
                raise ValueError("Workspace IDs must not be empty")
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
