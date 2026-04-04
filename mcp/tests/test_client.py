from __future__ import annotations

import httpx
import pytest

from iris_mcp_server.client import IrisApiError, IrisSearchApiClient
from iris_mcp_server.config import IrisMcpSettings
from iris_mcp_server.models import (
    SearchEntityQueryRequest,
    SearchQueryRequest,
    SearchSourceDetailResponse,
    SearchSourceQueryRequest,
    SearchSourceToolResult,
)
from iris_mcp_server.server import _success_tool_result


def _settings(**overrides: object) -> IrisMcpSettings:
    return IrisMcpSettings(
        IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
        **overrides,
    )


@pytest.mark.anyio
async def test_get_capabilities_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://localhost:8000/api/search/v1/capabilities")
        return httpx.Response(
            200,
            json={
                "enabled": True,
                "validation_enabled": True,
                "authenticated": True,
                "matched_permission_source_id": "partner-alpha",
                "matched_permission_source_kind": "api_key",
                "allow_builtin_embedding": False,
                "embedding_dimensions": 1536,
                "supported_modes": ["fulltext", "vector", "hybrid"],
                "query_vector_required_for_semantic_search": True,
            },
        )

    client = IrisSearchApiClient(_settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await client.get_capabilities()
    assert result.embedding_dimensions == 1536
    assert result.supported_modes[1].value == "vector"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, "bad_request"),
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (409, "conflict"),
        (503, "service_unavailable"),
    ],
)
async def test_maps_http_errors(status_code: int, expected_code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"detail": f"status {status_code}"})

    client = IrisSearchApiClient(_settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(IrisApiError) as exc_info:
        await client.query_source(SearchSourceQueryRequest(source_key="https://example.com"))

    assert exc_info.value.code == expected_code
    assert exc_info.value.status_code == status_code


@pytest.mark.anyio
async def test_timeout_retries_and_surfaces_stable_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("boom")

    client = IrisSearchApiClient(
        _settings(IRIS_SEARCH_API_RETRY_COUNT=1),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(IrisApiError) as exc_info:
        await client.query_entities(SearchEntityQueryRequest(name="角色甲"))

    assert exc_info.value.code == "timeout"
    assert exc_info.value.retriable is True
    assert attempts == 2


@pytest.mark.anyio
async def test_invalid_json_response_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="not-json", headers={"content-type": "application/json"})

    client = IrisSearchApiClient(_settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(IrisApiError) as exc_info:
        await client.search(SearchQueryRequest(query_text="角色甲"))

    assert exc_info.value.code == "invalid_json"


@pytest.mark.anyio
async def test_auth_headers_follow_scheme() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update({k: v for k, v in request.headers.items()})
        return httpx.Response(
            200,
            json={
                "source": {
                    "source_key": "https://example.com",
                    "canonical_url": "https://example.com",
                    "mentioned_entities": [],
                }
            },
        )

    client = IrisSearchApiClient(
        _settings(IRIS_SEARCH_API_KEY="secret", IRIS_SEARCH_API_AUTH_SCHEME="bearer"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client.query_source(SearchSourceQueryRequest(source_key="https://example.com"))
    assert seen_headers["authorization"] == "Bearer secret"


@pytest.mark.anyio
async def test_query_source_preserves_null_and_extra_source_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "source": {
                    "source_key": "https://example.com",
                    "canonical_url": "https://example.com",
                    "title": None,
                    "summary": None,
                    "fetched_at": None,
                    "content_hash": None,
                    "raw_text_excerpt": "正文摘录",
                    "outgoing_links": ["https://example.com/next"],
                    "incoming_links": [],
                    "mentioned_entities": [],
                }
            },
        )

    client = IrisSearchApiClient(_settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = await client.query_source(SearchSourceQueryRequest(source_key="https://example.com"))

    payload = result.model_dump(mode="json")
    assert payload["source"]["title"] is None
    assert payload["source"]["summary"] is None
    assert payload["source"]["fetched_at"] is None
    assert payload["source"]["content_hash"] is None
    assert payload["source"]["raw_text_excerpt"] == "正文摘录"
    assert payload["source"]["outgoing_links"] == ["https://example.com/next"]
    assert payload["source"]["incoming_links"] == []


def test_success_tool_result_keeps_null_source_fields() -> None:
    envelope = SearchSourceToolResult(
        ok=True,
        data=SearchSourceDetailResponse.model_validate(
            {
                "source": {
                    "source_key": "https://example.com",
                    "canonical_url": "https://example.com",
                    "title": None,
                    "summary": None,
                    "fetched_at": None,
                    "content_hash": None,
                    "mentioned_entities": [],
                }
            }
        ),
    )

    result = _success_tool_result(envelope, "Loaded source https://example.com. Mentioned entities: 0.")

    assert result.structuredContent["data"]["source"]["title"] is None
    assert result.structuredContent["data"]["source"]["summary"] is None
    assert result.structuredContent["data"]["source"]["fetched_at"] is None
    assert result.structuredContent["data"]["source"]["content_hash"] is None
    assert '"title": null' in result.content[0].text
    assert '"summary": null' in result.content[0].text