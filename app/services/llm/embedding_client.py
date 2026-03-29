from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_embedding_api_key or "missing-key",
            base_url=settings.openai_embedding_base_url,
        )
        self.enabled = bool(settings.openai_embedding_api_key)

    async def embed_text(self, text: str) -> list[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.enabled:
            raise RuntimeError("Embedding client is not configured.")

        payload: dict[str, Any] = {
            "model": self._settings.openai_embedding_model,
            "input": texts,
        }
        if self._settings.embedding_dimensions > 0:
            payload["dimensions"] = self._settings.embedding_dimensions

        logger.info(
            "embedding_request_start",
            model=self._settings.openai_embedding_model,
            base_url=self._settings.openai_embedding_base_url,
            batch_size=len(texts),
        )
        response = await self._client.embeddings.create(**payload)
        vectors = [list(item.embedding) for item in response.data]
        logger.info(
            "embedding_request_complete",
            model=self._settings.openai_embedding_model,
            batch_size=len(texts),
            vector_count=len(vectors),
        )
        return vectors
