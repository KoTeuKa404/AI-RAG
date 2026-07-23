from __future__ import annotations

import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import get_settings


class EmbeddingDimensionError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    settings = get_settings()
    return SentenceTransformer(
        settings.embedding_model,
        device=settings.embedding_device,
        trust_remote_code=False,
    )


def _encode_sync(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    model = _load_model()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
        batch_size=32,
    )
    if vectors.ndim != 2 or vectors.shape[1] != settings.embedding_dimension:
        raise EmbeddingDimensionError(
            f"Embedding model returned dimension {vectors.shape[1] if vectors.ndim == 2 else 'unknown'}, "
            f"expected {settings.embedding_dimension}"
        )
    return vectors.astype(float).tolist()


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await asyncio.to_thread(_encode_sync, texts)


async def embed_query(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]
