"""Async HTTP client for the IRIS search API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from json import JSONDecodeError
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from iris_mcp_server.config import IrisMcpSettings
from iris_mcp_server.models import (
    SearchApiCapabilities,
    SearchEntityQueryRequest,
    SearchEntityQueryResponse,
    SearchQueryRequest,
    SearchQueryResponse,
    SearchSourceDetailResponse,
    SearchSourceQueryRequest,
)

logger = logging.getLogger(__name__)


class IrisApiError(Exception):
    """Stable error type surfaced by the IRIS HTTP client."""

    def __init__(
        self,
        *,
        message: str,
        code: str,
        status_code: int | None = None,
        retriable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.retriable = retriable
        self.details = details or {}


class IrisSearchApiClient:
    """Typed client for the IRIS `/api/search/v1` endpoints."""

    def __init__(
        self,
        settings: IrisMcpSettings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.iris_search_api_timeout_seconds),
            headers={"accept": "application/json"},
        )
        self._owns_http_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def get_capabilities(self) -> SearchApiCapabilities:
        return await self._request(
            "GET",
            "/capabilities",
            response_model=SearchApiCapabilities,
        )

    async def query_entities(self, payload: SearchEntityQueryRequest) -> SearchEntityQueryResponse:
        return await self._request(
            "POST",
            "/entities/query",
            json_body=payload.model_dump(exclude_none=True),
            response_model=SearchEntityQueryResponse,
        )

    async def query_source(self, payload: SearchSourceQueryRequest) -> SearchSourceDetailResponse:
        return await self._request(
            "POST",
            "/sources/query",
            json_body=payload.model_dump(exclude_none=True),
            response_model=SearchSourceDetailResponse,
        )

    async def search(self, payload: SearchQueryRequest) -> SearchQueryResponse:
        return await self._request(
            "POST",
            "/search",
            json_body=payload.model_dump(exclude_none=True),
            response_model=SearchQueryResponse,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        response_model: type[BaseModel],
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        url = f"{self._settings.search_api_base_url}{path}"
        headers = self._build_auth_headers()
        last_error: IrisApiError | None = None

        for attempt in range(self._settings.iris_search_api_retry_count + 1):
            try:
                response = await self._http_client.request(method, url, headers=headers, json=json_body)
                return self._handle_response(response, response_model)
            except httpx.TimeoutException as exc:
                last_error = IrisApiError(
                    message=f"Timed out calling IRIS search API at {url}: {exc}",
                    code="timeout",
                    retriable=True,
                )
                logger.warning("Timeout talking to IRIS API", extra={"url": url, "attempt": attempt + 1})
            except httpx.RequestError as exc:
                last_error = IrisApiError(
                    message=f"Network error calling IRIS search API at {url}: {exc}",
                    code="network_error",
                    retriable=True,
                )
                logger.warning("Network error talking to IRIS API", extra={"url": url, "attempt": attempt + 1})
            except IrisApiError as exc:
                if not exc.retriable:
                    raise
                last_error = exc

            if attempt < self._settings.iris_search_api_retry_count:
                await asyncio.sleep(0.2 * (attempt + 1))

        assert last_error is not None
        raise last_error

    def _handle_response(self, response: httpx.Response, response_model: type[BaseModel]) -> Any:
        if response.status_code >= 400:
            raise self._build_http_error(response)

        try:
            payload = response.json()
        except JSONDecodeError as exc:
            raise IrisApiError(
                message="IRIS search API returned invalid JSON",
                code="invalid_json",
                status_code=response.status_code,
            ) from exc

        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            raise IrisApiError(
                message="IRIS search API response did not match the expected schema",
                code="invalid_response",
                status_code=response.status_code,
                details={"errors": exc.errors()},
            ) from exc

    def _build_http_error(self, response: httpx.Response) -> IrisApiError:
        detail = None
        body: dict[str, Any] | None = None
        try:
            body = response.json()
        except JSONDecodeError:
            body = None

        if isinstance(body, dict):
            detail = body.get("detail")
        message = str(detail or response.text or f"IRIS search API returned {response.status_code}")
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            503: "service_unavailable",
        }.get(response.status_code, "http_error")
        retriable = response.status_code in {503}
        return IrisApiError(
            message=message,
            code=code,
            status_code=response.status_code,
            retriable=retriable,
            details=body,
        )

    def _build_auth_headers(self) -> dict[str, str]:
        scheme = self._settings.auth_scheme
        api_key = (self._settings.iris_search_api_key or "").strip()
        if scheme == "none":
            return {}
        if scheme == "x-api-key":
            return {"X-API-Key": api_key}
        return {"Authorization": f"Bearer {api_key}"}