from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request, status

from app.core.config import Settings
from app.models import (
    SearchApiCapabilitiesResponse,
    SearchEntityHit,
    SearchEntityQueryRequest,
    SearchEntityQueryResponse,
    SearchEntityRecord,
    SearchMode,
    SearchPermissionSource,
    SearchPermissionSourceCreateRequest,
    SearchPermissionSourceKind,
    SearchPermissionSourceUpdateRequest,
    SearchQueryRequest,
    SearchQueryResponse,
    SearchRelationHit,
    SearchSourceByKeyRequest,
    SearchSourceDetailResponse,
    SearchSourceHit,
    SearchSourceRecord,
)
from app.models.config import SearchApiConfig
from app.repos.graph_repo import Neo4jGraphRepository, Neo4jUnavailableError
from app.services.llm.embedding_client import EmbeddingClient


@dataclass(frozen=True)
class SearchApiAccessContext:
    authenticated: bool
    validation_enabled: bool
    matched_permission_source_id: str | None
    matched_permission_source_kind: SearchPermissionSourceKind | None
    allow_builtin_embedding: bool


class SearchApiService:
    def __init__(
        self,
        *,
        settings: Settings,
        graph_repo: Neo4jGraphRepository,
        embedding_client: EmbeddingClient,
        config: SearchApiConfig,
    ) -> None:
        self._settings = settings
        self._graph_repo = graph_repo
        self._embedding_client = embedding_client
        self._config = config

    def replace_config(self, config: SearchApiConfig) -> None:
        self._config = config

    def require_enabled(self) -> None:
        if self._config.enabled:
            return
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Search API is disabled")

    async def authorize_request(self, request: Request) -> SearchApiAccessContext:
        self.require_enabled()
        if not self._config.validation_enabled:
            return SearchApiAccessContext(
                authenticated=True,
                validation_enabled=False,
                matched_permission_source_id=None,
                matched_permission_source_kind=None,
                allow_builtin_embedding=True,
            )

        enabled_sources = [source for source in self._config.permission_sources if source.enabled]
        if not enabled_sources:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Search API validation is enabled but no permission sources are configured",
            )

        api_key = _read_api_key(request)
        matched_api_key_source = self._match_api_key_source(enabled_sources, api_key)
        if matched_api_key_source is not None:
            return _build_access_context(matched_api_key_source)

        matched_ip_source = self._match_ip_source(enabled_sources, request.client.host if request.client else None)
        if matched_ip_source is not None:
            return _build_access_context(matched_ip_source)

        if api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP is not allowed")

    async def get_capabilities(self, request: Request) -> SearchApiCapabilitiesResponse:
        access = await self.authorize_request(request)
        return self.build_capabilities(access)

    def build_capabilities(
        self,
        access: SearchApiAccessContext,
        *,
        query_vector_required_for_semantic_search: bool = False,
    ) -> SearchApiCapabilitiesResponse:
        return SearchApiCapabilitiesResponse(
            enabled=self._config.enabled,
            validation_enabled=self._config.validation_enabled,
            authenticated=access.authenticated,
            matched_permission_source_id=access.matched_permission_source_id,
            matched_permission_source_kind=access.matched_permission_source_kind,
            allow_builtin_embedding=access.allow_builtin_embedding,
            embedding_dimensions=self._settings.embedding_dimensions,
            supported_modes=[SearchMode.fulltext, SearchMode.vector, SearchMode.hybrid],
            query_vector_required_for_semantic_search=query_vector_required_for_semantic_search,
        )

    async def query_entities(
        self,
        payload: SearchEntityQueryRequest,
    ) -> SearchEntityQueryResponse:
        await self._ensure_graph_available()
        entity_id = (payload.entity_id or "").strip()
        if entity_id:
            entity_payload = await self._graph_repo.get_entity_detail(
                entity_id,
                source_limit=payload.source_limit,
                relation_limit=payload.relation_limit,
            )
            if entity_payload is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
            return SearchEntityQueryResponse(
                items=[SearchEntityRecord.model_validate(entity_payload)]
            )

        normalized_name = (payload.name or "").strip() or None
        normalized_alias = (payload.alias or "").strip() or None
        entity_payload = await self._graph_repo.find_entities_exact(
            name=normalized_name,
            alias=normalized_alias,
            limit=payload.limit,
            source_limit=payload.source_limit,
            relation_limit=payload.relation_limit,
        )
        return SearchEntityQueryResponse(
            items=[SearchEntityRecord.model_validate(item) for item in entity_payload]
        )

    async def get_source_detail(self, payload: SearchSourceByKeyRequest) -> SearchSourceDetailResponse:
        await self._ensure_graph_available()
        source_payload = await self._graph_repo.get_source_detail(payload.source_key)
        if source_payload is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
        return SearchSourceDetailResponse(source=SearchSourceRecord.model_validate(source_payload))

    async def query(
        self,
        payload: SearchQueryRequest,
        access: SearchApiAccessContext,
    ) -> SearchQueryResponse:
        await self._ensure_graph_available()
        query_text = (payload.query_text or "").strip()
        query_vector = self._resolve_query_vector(payload, access, query_text=query_text)

        graphrag_payload = await self._graph_repo.query_graphrag_context(
            query=query_text,
            entity_limit=payload.entity_limit,
            source_limit=payload.source_limit,
            relation_limit=payload.relation_limit,
            neighborhood_limit=max(payload.entity_limit, payload.relation_limit),
            candidate_urls=[],
            mode=payload.mode.value,
            query_embedding=query_vector,
        )
        capability_payload = self.build_capabilities(
            access,
            query_vector_required_for_semantic_search=(
                payload.mode in {SearchMode.vector, SearchMode.hybrid}
                and not access.allow_builtin_embedding
            ),
        )
        source_hits = await self._hydrate_source_hits(graphrag_payload["sources"])
        return SearchQueryResponse(
            query_text=query_text or None,
            mode=payload.mode,
            query_vector_provided=query_vector is not None,
            capabilities=capability_payload,
            entities=[SearchEntityHit.model_validate(item) for item in graphrag_payload["entities"]],
            sources=[SearchSourceHit.model_validate(item) for item in source_hits],
            relations=[SearchRelationHit.model_validate(item) for item in graphrag_payload["relations"]],
            neighborhoods=graphrag_payload["neighborhoods"],
        )

    async def _hydrate_source_hits(self, source_hits: list[dict[str, object]]) -> list[dict[str, object]]:
        source_keys = [str(item.get("source_key") or "").strip() for item in source_hits]
        metadata_by_key = await self._graph_repo.get_source_metadata_map(source_keys)
        hydrated_hits: list[dict[str, object]] = []
        for item in source_hits:
            payload = dict(item)
            source_key = str(payload.get("source_key") or "").strip()
            metadata = metadata_by_key.get(source_key, {})
            if not str(payload.get("title") or "").strip():
                payload["title"] = metadata.get("title")
            if not str(payload.get("summary") or "").strip():
                payload["summary"] = metadata.get("summary")
            hydrated_hits.append(payload)
        return hydrated_hits

    async def _ensure_graph_available(self) -> None:
        try:
            await self._graph_repo.ensure_available()
        except Neo4jUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    def _resolve_query_vector(
        self,
        payload: SearchQueryRequest,
        access: SearchApiAccessContext,
        *,
        query_text: str,
    ) -> list[float] | None:
        if payload.mode == SearchMode.fulltext:
            if not query_text:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="query_text is required for fulltext search",
                )
            return None

        if payload.mode == SearchMode.hybrid and not query_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_text is required for hybrid search",
            )

        if payload.query_vector is not None:
            self._validate_query_vector_dimensions(payload.query_vector)
            return payload.query_vector

        if not access.allow_builtin_embedding:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This permission source cannot use built-in embedding; provide query_vector explicitly",
            )

        if not query_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_text is required when query_vector is omitted",
            )
        return None

    def _validate_query_vector_dimensions(self, query_vector: list[float]) -> None:
        if not query_vector:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_vector must not be empty",
            )
        if len(query_vector) != self._settings.embedding_dimensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"query_vector length must equal embedding_dimensions "
                    f"({self._settings.embedding_dimensions})"
                ),
            )

    def _match_api_key_source(
        self,
        enabled_sources: list[SearchPermissionSource],
        api_key: str | None,
    ) -> SearchPermissionSource | None:
        if not api_key:
            return None
        candidate_hash = hash_api_key(api_key)
        for source in enabled_sources:
            if source.kind != SearchPermissionSourceKind.api_key or not source.api_key_hash:
                continue
            if hmac.compare_digest(source.api_key_hash, candidate_hash):
                return source
        return None

    def _match_ip_source(
        self,
        enabled_sources: list[SearchPermissionSource],
        host: str | None,
    ) -> SearchPermissionSource | None:
        if not host:
            return None
        try:
            client_ip = ip_address(host)
        except ValueError:
            return None
        for source in enabled_sources:
            if source.kind != SearchPermissionSourceKind.ip or not source.ip_value:
                continue
            if client_ip in ip_network(source.ip_value, strict=False):
                return source
        return None


def build_permission_source_from_create_request(
    payload: SearchPermissionSourceCreateRequest,
) -> tuple[SearchPermissionSource, str | None]:
    source_id = _normalize_or_generate_permission_source_id(
        payload.id,
        kind=payload.kind,
        description=payload.description,
        ip_value=payload.ip_value,
    )
    if payload.kind == SearchPermissionSourceKind.api_key:
        generated_api_key = generate_api_key_secret()
        return (
            SearchPermissionSource(
                id=source_id,
                kind=payload.kind,
                description=payload.description,
                enabled=payload.enabled,
                allow_builtin_embedding=payload.allow_builtin_embedding,
                api_key_hash=hash_api_key(generated_api_key),
                key_prefix=generated_api_key[:12],
            ),
            generated_api_key,
        )

    return (
        SearchPermissionSource(
            id=source_id,
            kind=payload.kind,
            description=payload.description,
            enabled=payload.enabled,
            allow_builtin_embedding=payload.allow_builtin_embedding,
            ip_value=payload.ip_value,
        ),
        None,
    )


def build_permission_source_from_update_request(
    existing: SearchPermissionSource,
    payload: SearchPermissionSourceUpdateRequest,
) -> SearchPermissionSource:
    if existing.kind == SearchPermissionSourceKind.api_key:
        return SearchPermissionSource(
            id=existing.id,
            kind=existing.kind,
            description=payload.description,
            enabled=payload.enabled,
            allow_builtin_embedding=payload.allow_builtin_embedding,
            api_key_hash=existing.api_key_hash,
            key_prefix=existing.key_prefix,
        )

    return SearchPermissionSource(
        id=existing.id,
        kind=existing.kind,
        description=payload.description,
        enabled=payload.enabled,
        allow_builtin_embedding=payload.allow_builtin_embedding,
        ip_value=payload.ip_value or existing.ip_value,
    )


def generate_api_key_secret() -> str:
    return f"iris_sk_{secrets.token_urlsafe(24)}"


def hash_api_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _read_api_key(request: Request) -> str | None:
    explicit = request.headers.get("x-api-key")
    if explicit:
        return explicit.strip()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def _build_access_context(source: SearchPermissionSource) -> SearchApiAccessContext:
    return SearchApiAccessContext(
        authenticated=True,
        validation_enabled=True,
        matched_permission_source_id=source.id,
        matched_permission_source_kind=source.kind,
        allow_builtin_embedding=source.allow_builtin_embedding,
    )


def normalize_permission_source_ids(
    permission_sources: list[dict[str, object]] | list[SearchPermissionSource],
) -> list[dict[str, object]] | list[SearchPermissionSource]:
    seen_ids: set[str] = set()
    normalized_sources: list[dict[str, object]] | list[SearchPermissionSource] = []
    for source in permission_sources:
        if isinstance(source, SearchPermissionSource):
            candidate_id = _normalize_or_generate_permission_source_id(
                source.id,
                kind=source.kind,
                description=source.description,
                ip_value=source.ip_value,
            )
            while candidate_id in seen_ids:
                candidate_id = _normalize_or_generate_permission_source_id(
                    None,
                    kind=source.kind,
                    description=source.description,
                    ip_value=source.ip_value,
                )
            seen_ids.add(candidate_id)
            normalized_sources.append(source.model_copy(update={"id": candidate_id}))
            continue

        if not isinstance(source, dict):
            normalized_sources.append(source)
            continue

        kind = SearchPermissionSourceKind(str(source.get("kind") or SearchPermissionSourceKind.api_key.value))
        description = str(source.get("description") or "")
        ip_value = str(source.get("ip_value") or "") or None
        candidate_id = _normalize_or_generate_permission_source_id(
            source.get("id"),
            kind=kind,
            description=description,
            ip_value=ip_value,
        )
        while candidate_id in seen_ids:
            candidate_id = _normalize_or_generate_permission_source_id(
                None,
                kind=kind,
                description=description,
                ip_value=ip_value,
            )
        seen_ids.add(candidate_id)
        normalized_source = dict(source)
        normalized_source["id"] = candidate_id
        normalized_sources.append(normalized_source)

    return normalized_sources


def _normalize_or_generate_permission_source_id(
    raw_id: object,
    *,
    kind: SearchPermissionSourceKind,
    description: str,
    ip_value: str | None,
) -> str:
    normalized_id = str(raw_id or "").strip().lower()
    if normalized_id:
        return normalized_id

    parts = [kind.value.replace("_", "-")]
    if description.strip():
        parts.append(description.strip())
    elif kind == SearchPermissionSourceKind.ip and ip_value:
        parts.append(ip_value)
    slug = re.sub(r"[^a-z0-9]+", "-", "-".join(parts).lower()).strip("-")
    if not slug:
        slug = kind.value.replace("_", "-")
    return f"{slug}-{secrets.token_hex(4)}"