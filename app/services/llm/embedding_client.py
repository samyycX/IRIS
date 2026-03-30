from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.enabled = bool(settings.openai_embedding_api_key)
        self._client = self._build_client() if self.enabled else None

    async def embed_text(self, text: str) -> list[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.enabled:
            raise RuntimeError("Embedding client is not configured.")

        logger.info(
            "embedding_request_start",
            model=self._settings.openai_embedding_model,
            base_url=self._settings.openai_embedding_base_url,
            batch_size=len(texts),
        )
        client = self._require_client()
        vectors = [list(item) for item in await client.aembed_documents(texts)]
        logger.info(
            "embedding_request_complete",
            model=self._settings.openai_embedding_model,
            batch_size=len(texts),
            vector_count=len(vectors),
        )
        return vectors

    def _build_client(self):
        from langchain_openai import OpenAIEmbeddings

        kwargs: dict[str, Any] = {
            "model": self._settings.openai_embedding_model,
            "api_key": self._settings.openai_embedding_api_key,
            "base_url": self._settings.openai_embedding_base_url,
        }
        if self._settings.embedding_dimensions > 0:
            kwargs["dimensions"] = self._settings.embedding_dimensions
        return OpenAIEmbeddings(**kwargs)

    def _require_client(self):
        if self._client is None:
            raise RuntimeError("Embedding client is not configured.")
        return self._client
