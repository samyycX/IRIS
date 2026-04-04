from __future__ import annotations

import pytest
from mcp import Client

from iris_mcp_server.client import IrisApiError
from iris_mcp_server.config import IrisMcpSettings
from iris_mcp_server.models import (
    SearchApiCapabilities,
    SearchEntityQueryResponse,
    SearchEntityRecord,
    SearchMentionedSourceRecord,
    SearchMode,
    SearchQueryResponse,
    SearchSourceDetailResponse,
    SearchSourceRecord,
)
from iris_mcp_server.server import create_server


class StubClient:
    def __init__(self) -> None:
        self.fail_entities = False
        self.last_search_payload = None
        self.allow_builtin_embedding = False
        self.embedding_dimensions = 1536

    async def get_capabilities(self) -> SearchApiCapabilities:
        return SearchApiCapabilities(
            enabled=True,
            validation_enabled=True,
            authenticated=True,
            matched_permission_source_id="partner-alpha",
            matched_permission_source_kind="api_key",
            allow_builtin_embedding=self.allow_builtin_embedding,
            embedding_dimensions=self.embedding_dimensions,
            supported_modes=[SearchMode.fulltext, SearchMode.vector, SearchMode.hybrid],
            query_vector_required_for_semantic_search=not self.allow_builtin_embedding,
        )

    async def query_entities(self, payload):
        if self.fail_entities:
            raise IrisApiError(message="Entity not found", code="not_found", status_code=404)
        return SearchEntityQueryResponse(
            items=[
                SearchEntityRecord(
                    entity_id="role-alpha",
                    name="角色甲",
                    aliases=["Role Alpha"],
                    mentioned_in_sources=[
                        SearchMentionedSourceRecord(
                            id="https://example.com/role-alpha",
                            title="角色甲词条",
                            relevance=0.98,
                        )
                    ],
                )
            ]
        )

    async def query_source(self, payload):
        return SearchSourceDetailResponse(
            source=SearchSourceRecord(
                source_key=payload.source_key,
                canonical_url=payload.source_key,
                title="角色甲词条",
                mentioned_entities=[],
            )
        )

    async def search(self, payload):
        self.last_search_payload = payload
        return SearchQueryResponse(
            query_text=payload.query_text,
            mode=payload.mode,
            query_vector_provided=payload.query_vector is not None,
            capabilities=await self.get_capabilities(),
            entities=[],
            sources=[],
            relations=[],
            neighborhoods=[],
        )


class StubEmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls: list[str] = []

    async def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.vector


@pytest.fixture
def settings() -> IrisMcpSettings:
    return IrisMcpSettings(IRIS_SEARCH_API_BASE_URL="http://localhost:8000")


@pytest.mark.anyio
async def test_tools_are_exposed(settings: IrisMcpSettings) -> None:
    server = create_server(settings, StubClient())

    async with Client(server) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools.tools} == {
        "search_capabilities",
        "search_entities_query",
        "search_source_query",
        "search_query",
    }


@pytest.mark.anyio
async def test_search_entities_query_returns_structured_success(settings: IrisMcpSettings) -> None:
    server = create_server(settings, StubClient())

    async with Client(server) as client:
        result = await client.call_tool("search_entities_query", {"name": "角色甲"})

    assert result.isError is False
    assert result.structuredContent == {
        "ok": True,
        "data": {
            "items": [
                {
                    "entity_id": "role-alpha",
                    "name": "角色甲",
                    "aliases": ["Role Alpha"],
                    "mentioned_in_sources": [
                        {
                            "id": "https://example.com/role-alpha",
                            "title": "角色甲词条",
                            "relevance": 0.98,
                        }
                    ],
                    "outgoing_relations": [],
                    "incoming_relations": [],
                }
            ]
        },
    }


@pytest.mark.anyio
async def test_search_entities_query_returns_structured_error(settings: IrisMcpSettings) -> None:
    stub = StubClient()
    stub.fail_entities = True
    server = create_server(settings, stub)

    async with Client(server) as client:
        result = await client.call_tool("search_entities_query", {"name": "missing"})

    assert result.isError is True
    assert result.structuredContent == {
        "ok": False,
        "error": {
            "status_code": 404,
            "code": "not_found",
            "message": "Entity not found",
            "retriable": False,
        },
    }


@pytest.mark.anyio
async def test_search_query_accepts_mode_enum(settings: IrisMcpSettings) -> None:
    server = create_server(settings, StubClient())

    async with Client(server) as client:
        result = await client.call_tool(
            "search_query",
            {"query_text": "角色甲", "mode": "hybrid", "entity_limit": 2},
        )

    assert result.isError is False
    assert result.structuredContent == {
        "ok": True,
        "embedding_fallback_used": False,
        "data": {
            "query_text": "角色甲",
            "mode": "hybrid",
            "query_vector_provided": False,
            "capabilities": {
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
            "entities": [],
            "sources": [],
            "relations": [],
            "neighborhoods": [],
        },
    }


@pytest.mark.anyio
async def test_search_query_can_generate_query_vector_with_client_fallback() -> None:
    settings = IrisMcpSettings(
        IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
        IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=True,
        IRIS_OPENAI_API_KEY="sk-test",
        IRIS_OPENAI_EMBEDDING_MODEL="text-embedding-3-small",
    )
    stub = StubClient()
    embedding_client = StubEmbeddingClient([0.1] * 1536)
    server = create_server(settings, stub, embedding_client)

    async with Client(server) as client:
        result = await client.call_tool(
            "search_query",
            {"query_text": "角色甲", "mode": "hybrid", "entity_limit": 2},
        )

    assert result.isError is False
    assert embedding_client.calls == ["角色甲"]
    assert stub.last_search_payload is not None
    assert stub.last_search_payload.query_vector == [0.1] * 1536
    assert result.structuredContent["embedding_fallback_used"] is True
    assert result.structuredContent["embedding_model"] == "text-embedding-3-small"
    assert result.structuredContent["data"]["query_vector_provided"] is True


@pytest.mark.anyio
async def test_search_query_rejects_dimension_mismatch() -> None:
    settings = IrisMcpSettings(
        IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
        IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=True,
        IRIS_OPENAI_API_KEY="sk-test",
        IRIS_OPENAI_EMBEDDING_MODEL="text-embedding-3-small",
    )
    stub = StubClient()
    embedding_client = StubEmbeddingClient([0.1, 0.2])
    server = create_server(settings, stub, embedding_client)

    async with Client(server) as client:
        result = await client.call_tool(
            "search_query",
            {"query_text": "角色甲", "mode": "hybrid"},
        )

    assert result.isError is True
    assert result.structuredContent == {
        "ok": False,
        "embedding_fallback_used": False,
        "error": {
            "code": "embedding_dimension_mismatch",
            "message": (
                "Client-side embedding vector dimension does not match IRIS search API expectations: "
                "got 2, expected 1536"
            ),
            "retriable": False,
        },
    }