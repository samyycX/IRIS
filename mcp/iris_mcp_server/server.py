"""MCP server composition for IRIS search tools."""

from __future__ import annotations

import json
from typing import Annotated, TypeVar

from mcp.types import CallToolResult, TextContent
from mcp.server import FastMCP

from iris_mcp_server.client import IrisApiError, IrisSearchApiClient
from iris_mcp_server.config import IrisMcpSettings
from iris_mcp_server.embedding_client import EmbeddingProviderError, OpenAIEmbeddingClient
from iris_mcp_server.models import (
    SearchApiCapabilities,
    SearchCapabilitiesToolResult,
    SearchEntitiesToolResult,
    SearchEntityQueryRequest,
    SearchEntityQueryResponse,
    SearchMode,
    SearchQueryRequest,
    SearchQueryResponse,
    SearchQueryToolResult,
    SearchSourceDetailResponse,
    SearchSourceQueryRequest,
    SearchSourceToolResult,
    ToolError,
)

TEnvelope = TypeVar(
    "TEnvelope",
    SearchCapabilitiesToolResult,
    SearchEntitiesToolResult,
    SearchSourceToolResult,
    SearchQueryToolResult,
)


def create_server(
    settings: IrisMcpSettings,
    client: IrisSearchApiClient,
    embedding_client: OpenAIEmbeddingClient | None = None,
    **kwargs,
) -> FastMCP:
    """Build the MCP server with the four IRIS search tools."""

    mcp = FastMCP("iris-mcp-server", **kwargs)

    @mcp.tool(
        name="search_capabilities",
        description=(
            "Read the current IRIS search API capabilities, including authentication state, "
            "supported search modes, and whether query vectors are required. Returns the full payload "
            "in both structuredContent and text."
        ),
    )
    async def search_capabilities() -> Annotated[CallToolResult, SearchCapabilitiesToolResult]:
        try:
            data = await client.get_capabilities()
        except IrisApiError as exc:
            return _error_tool_result(
                SearchCapabilitiesToolResult,
                exc,
                "Failed to read IRIS search capabilities.",
            )

        summary = _summarize_capabilities(data)
        payload = SearchCapabilitiesToolResult(ok=True, data=data)
        return _success_tool_result(payload, summary)

    @mcp.tool(
        name="search_entities_query",
        description=(
            "Query IRIS entities by entity_id, exact name, or exact alias. "
            "Provide at least one of entity_id, name, or alias. limit, source_limit, and relation_limit "
            "should be integers. Returns full entity details, mentioned sources, and relation neighborhoods."
        ),
    )
    async def search_entities_query(
        entity_id: str | None = None,
        name: str | None = None,
        alias: str | None = None,
        limit: int | None = None,
        source_limit: int | None = None,
        relation_limit: int | None = None,
    ) -> Annotated[CallToolResult, SearchEntitiesToolResult]:
        try:
            request = SearchEntityQueryRequest(
                entity_id=entity_id,
                name=name,
                alias=alias,
                limit=limit or settings.iris_search_api_default_limit,
                source_limit=source_limit or settings.iris_search_api_default_limit,
                relation_limit=relation_limit or settings.iris_search_api_default_limit,
            )
            data = await client.query_entities(request)
        except (ValueError, IrisApiError) as exc:
            return _exception_to_entities_result(exc)

        summary = _summarize_entities(data)
        payload = SearchEntitiesToolResult(ok=True, data=data)
        return _success_tool_result(payload, summary)

    @mcp.tool(
        name="search_source_query",
        description=(
            "Fetch one IRIS source by source_key and include the entities mentioned in it. "
            "Returns the full source payload in text and structuredContent."
        ),
    )
    async def search_source_query(
        source_key: str,
    ) -> Annotated[CallToolResult, SearchSourceToolResult]:
        try:
            request = SearchSourceQueryRequest(source_key=source_key)
            data = await client.query_source(request)
        except (ValueError, IrisApiError) as exc:
            return _exception_to_source_result(exc)

        summary = _summarize_source(data)
        payload = SearchSourceToolResult(ok=True, data=data)
        return _success_tool_result(payload, summary)

    @mcp.tool(
        name="search_query",
        description=(
            "Run the unified IRIS search endpoint in fulltext, vector, or hybrid mode over "
            "entities, sources, relations, and graph neighborhoods. mode must be one of fulltext, vector, hybrid. "
            "entity_limit, source_limit, and relation_limit should be integers. Returns the complete search payload."
        ),
    )
    async def search_query(
        query_text: str | None = None,
        mode: SearchMode = SearchMode.hybrid,
        query_vector: list[float] | None = None,
        entity_limit: int | None = None,
        source_limit: int | None = None,
        relation_limit: int | None = None,
    ) -> Annotated[CallToolResult, SearchQueryToolResult]:
        embedding_fallback_used = False
        try:
            request = SearchQueryRequest(
                query_text=query_text,
                mode=mode,
                query_vector=query_vector,
                entity_limit=entity_limit or settings.iris_search_api_default_limit,
                source_limit=source_limit or settings.iris_search_api_default_limit,
                relation_limit=relation_limit or settings.iris_search_api_default_limit,
            )
            request, embedding_fallback_used = await _maybe_apply_embedding_fallback(
                request,
                client,
                embedding_client,
                settings,
            )
            data = await client.search(request)
        except (ValueError, IrisApiError, EmbeddingProviderError) as exc:
            return _exception_to_query_result(exc)

        summary = _summarize_query(data)
        payload = SearchQueryToolResult(
            ok=True,
            data=data,
            embedding_fallback_used=embedding_fallback_used,
            embedding_model=(settings.iris_openai_embedding_model if embedding_fallback_used else None),
        )
        return _success_tool_result(payload, summary)

    return mcp


def _summarize_capabilities(data: SearchApiCapabilities) -> str:
    source_summary = "none"
    if data.matched_permission_source_id and data.matched_permission_source_kind:
        source_summary = f"{data.matched_permission_source_id} ({data.matched_permission_source_kind.value})"
    modes = ", ".join(mode.value for mode in data.supported_modes)
    return (
        f"IRIS search enabled: {data.enabled}. Validation enabled: {data.validation_enabled}. "
        f"Authenticated: {data.authenticated}. Permission source: {source_summary}. "
        f"Built-in embedding allowed: {data.allow_builtin_embedding}. Supported modes: {modes}. "
        f"Semantic search requires query_vector: {data.query_vector_required_for_semantic_search}."
    )


def _summarize_entities(data: SearchEntityQueryResponse) -> str:
    count = len(data.items)
    if not data.items:
        return "Entity query completed with 0 results."
    first = data.items[0]
    name = first.name or first.normalized_name or first.entity_id
    return f"Entity query returned {count} result(s). First result: {name} ({first.entity_id})."


def _summarize_source(data: SearchSourceDetailResponse) -> str:
    source = data.source
    entity_count = len(source.mentioned_entities)
    title = source.title or source.source_key
    return f"Loaded source {title}. Mentioned entities: {entity_count}."


def _summarize_query(data: SearchQueryResponse) -> str:
    return (
        f"Search mode: {data.mode.value}. Entities: {len(data.entities)}. Sources: {len(data.sources)}. "
        f"Relations: {len(data.relations)}. Neighborhoods: {len(data.neighborhoods)}. "
        f"query_vector_provided: {data.query_vector_provided}."
    )


async def _maybe_apply_embedding_fallback(
    request: SearchQueryRequest,
    client: IrisSearchApiClient,
    embedding_client: OpenAIEmbeddingClient | None,
    settings: IrisMcpSettings,
) -> tuple[SearchQueryRequest, bool]:
    if not settings.client_embedding_enabled:
        return request, False
    if request.mode == SearchMode.fulltext:
        return request, False
    if request.query_vector is not None:
        return request, False

    query_text = (request.query_text or "").strip()
    if not query_text:
        return request, False

    capabilities = await client.get_capabilities()
    if capabilities.allow_builtin_embedding and not capabilities.query_vector_required_for_semantic_search:
        return request, False
    if embedding_client is None:
        raise EmbeddingProviderError(
            "Client-side embedding fallback is enabled but no embedding client is configured",
            code="embedding_not_configured",
        )

    vector = await embedding_client.embed_text(query_text)
    if capabilities.embedding_dimensions > 0 and len(vector) != capabilities.embedding_dimensions:
        raise EmbeddingProviderError(
            (
                "Client-side embedding vector dimension does not match IRIS search API expectations: "
                f"got {len(vector)}, expected {capabilities.embedding_dimensions}"
            ),
            code="embedding_dimension_mismatch",
        )

    return request.model_copy(update={"query_vector": vector}), True


def _success_tool_result(envelope: TEnvelope, summary: str) -> CallToolResult:
    payload = envelope.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=_format_text_result(summary, payload))],
        structuredContent=payload,
    )


def _error_tool_result(
    result_model: type[TEnvelope],
    exc: IrisApiError,
    prefix: str,
) -> CallToolResult:
    error = ToolError(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        retriable=exc.retriable,
    )
    envelope = result_model(ok=False, error=error)
    payload = envelope.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=_format_text_result(f"{prefix} {exc.message}", payload))],
        structuredContent=payload,
        isError=True,
    )


def _validation_error_result(result_model: type[TEnvelope], message: str) -> CallToolResult:
    error = ToolError(code="validation_error", message=message, retriable=False)
    envelope = result_model(ok=False, error=error)
    payload = envelope.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=_format_text_result(message, payload))],
        structuredContent=payload,
        isError=True,
    )


def _exception_to_entities_result(exc: Exception) -> CallToolResult:
    if isinstance(exc, IrisApiError):
        return _error_tool_result(SearchEntitiesToolResult, exc, "Entity query failed.")
    return _validation_error_result(SearchEntitiesToolResult, str(exc))


def _exception_to_source_result(exc: Exception) -> CallToolResult:
    if isinstance(exc, IrisApiError):
        return _error_tool_result(SearchSourceToolResult, exc, "Source query failed.")
    return _validation_error_result(SearchSourceToolResult, str(exc))


def _exception_to_query_result(exc: Exception) -> CallToolResult:
    if isinstance(exc, IrisApiError):
        return _error_tool_result(SearchQueryToolResult, exc, "Unified search failed.")
    if isinstance(exc, EmbeddingProviderError):
        return _embedding_error_tool_result(SearchQueryToolResult, exc, "Unified search failed.")
    return _validation_error_result(SearchQueryToolResult, str(exc))


def _embedding_error_tool_result(
    result_model: type[TEnvelope],
    exc: EmbeddingProviderError,
    prefix: str,
) -> CallToolResult:
    error = ToolError(
        code=exc.code,
        message=exc.message,
        retriable=exc.retriable,
    )
    envelope = result_model(ok=False, error=error)
    payload = envelope.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=_format_text_result(f"{prefix} {exc.message}", payload))],
        structuredContent=payload,
        isError=True,
    )


def _format_text_result(summary: str, payload: dict[str, object]) -> str:
    return f"{summary}\n\nFull result:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"