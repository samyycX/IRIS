"""OpenAI embedding client for optional client-side query vector generation."""

from __future__ import annotations

from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI

from iris_mcp_server.config import IrisMcpSettings


class EmbeddingProviderError(Exception):
    """Stable error for client-side embedding failures."""

    def __init__(self, message: str, *, code: str = "embedding_error", retriable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retriable = retriable


class OpenAIEmbeddingClient:
    """Small wrapper around the OpenAI embeddings API."""

    def __init__(self, settings: IrisMcpSettings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.iris_openai_api_key,
            base_url=settings.iris_openai_base_url,
            timeout=settings.iris_openai_timeout_seconds,
        )

    async def embed_text(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingProviderError(
                "query_text is required for client-side embedding fallback",
                code="embedding_validation_error",
            )

        request: dict[str, Any] = {
            "model": self._settings.iris_openai_embedding_model,
            "input": text,
        }
        if self._settings.iris_openai_embedding_dimensions is not None:
            request["dimensions"] = self._settings.iris_openai_embedding_dimensions

        try:
            response = await self._client.embeddings.create(**request)
        except APITimeoutError as exc:
            raise EmbeddingProviderError(
                f"OpenAI embedding request timed out: {exc}",
                code="embedding_timeout",
                retriable=True,
            ) from exc
        except APIConnectionError as exc:
            raise EmbeddingProviderError(
                f"OpenAI embedding request failed to connect: {exc}",
                code="embedding_network_error",
                retriable=True,
            ) from exc
        except APIError as exc:
            raise EmbeddingProviderError(
                f"OpenAI embedding request failed: {exc}",
                code="embedding_api_error",
                retriable=getattr(exc, "status_code", None) in {429, 500, 502, 503, 504},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingProviderError(
                f"Unexpected embedding failure: {exc}",
                retriable=False,
            ) from exc

        if not response.data:
            raise EmbeddingProviderError("OpenAI embedding response was empty")
        vector = list(response.data[0].embedding)
        if not vector:
            raise EmbeddingProviderError("OpenAI embedding response did not contain a vector")
        return vector

    async def aclose(self) -> None:
        await self._client.close()