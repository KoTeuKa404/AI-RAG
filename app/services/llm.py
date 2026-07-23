from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _chat_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


# The local inference server should handle one expensive generation at a time.
# This prevents Telegram and Swagger requests from overloading the same model.
_LLM_REQUEST_LOCK = asyncio.Lock()


async def generate_answer(system_prompt: str, user_prompt: str) -> str:
    settings = get_settings()
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_output_tokens,
        "reasoning_effort": "low",
        "stream": False,
    }

    timeout = httpx.Timeout(
        connect=15.0,
        read=settings.llm_timeout_seconds,
        write=60.0,
        pool=15.0,
    )

    try:
        async with _LLM_REQUEST_LOCK:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(
                    _chat_url(settings.llm_base_url),
                    headers=headers,
                    json=payload,
                )
    except httpx.TimeoutException:
        logger.exception(
            "Local LLM timed out after %.1f seconds",
            settings.llm_timeout_seconds,
        )
        raise
    except httpx.RequestError:
        logger.exception("Local LLM API is unavailable")
        raise
    except httpx.HTTPError as exc:
        raise LLMError("The LLM request failed") from exc

    if response.status_code >= 400:
        logger.error("LLM returned HTTP %s: %s", response.status_code, response.text[:500])
        raise LLMError(f"LLM returned HTTP {response.status_code}")

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM returned an unexpected response format") from exc

    if not isinstance(content, str) or not content.strip():
        raise LLMError("LLM returned an empty answer")
    return content.strip()
