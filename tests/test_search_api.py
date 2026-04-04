from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.routes import router
from app.core.config import Settings
from app.models import (
    AppConfig,
    SearchApiConfig,
    SearchMode,
    SearchPermissionSource,
    SearchPermissionSourceCreateRequest,
    SearchPermissionSourceKind,
    SearchApiSettingsUpdateRequest,
    SearchEntityQueryRequest,
    SearchPermissionSourceUpdateRequest,
    SearchQueryRequest,
    SearchSourceByKeyRequest,
)
from app.services.search_api import SearchApiService, build_permission_source_from_create_request


class _FakeNeo4jDateTime:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def to_native(self) -> datetime:
        return self._value


class _FakeEmbeddingClient:
    enabled = True


class _FakeGraphRepo:
    def __init__(self) -> None:
        self.last_query_embedding = None
        self.last_query_text = None

    async def ensure_available(self) -> None:
        return None

    async def get_entity_detail(
        self,
        entity_id: str,
        *,
        source_limit: int = 10,
        relation_limit: int = 10,
    ):
        if entity_id != "entity-1":
            return None
        return {
            "entity_id": entity_id,
            "name": "角色甲",
            "normalized_name": "角色甲",
            "category": "character",
            "summary": "角色甲摘要",
            "aliases": ["Role Alpha"],
            "mentioned_in_sources": [
                {
                    "id": f"https://example.com/role-alpha-{index}",
                    "title": f"角色甲词条 {index}",
                    "summary": f"来源摘要 {index}",
                    "relevance": 0.9 - (index * 0.1),
                }
                for index in range(source_limit)
            ],
            "outgoing_relations": [
                {
                    "relation_type": "RELATED_TO",
                    "entity_id": f"target-{index}",
                    "name": f"Target {index}",
                    "evidence": None,
                }
                for index in range(relation_limit)
            ],
            "incoming_relations": [
                {
                    "relation_type": "RELATED_TO",
                    "entity_id": f"source-{index}",
                    "name": f"Source {index}",
                    "evidence": None,
                }
                for index in range(relation_limit)
            ],
        }

    async def find_entities_exact(
        self,
        *,
        name: str | None,
        alias: str | None,
        limit: int,
        source_limit: int,
        relation_limit: int,
    ):
        del limit
        if name == "角色甲" or alias == "Role Alpha":
            return [
                {
                    "entity_id": "entity-1",
                    "name": "角色甲",
                    "normalized_name": "角色甲",
                    "category": "character",
                    "summary": "角色甲摘要",
                    "aliases": ["Role Alpha"],
                    "mentioned_in_sources": [
                        {
                            "id": f"https://example.com/role-alpha-{index}",
                            "title": f"角色甲词条 {index}",
                            "summary": f"来源摘要 {index}",
                            "relevance": 0.9 - (index * 0.1),
                        }
                        for index in range(source_limit)
                    ],
                    "outgoing_relations": [
                        {
                            "relation_type": "RELATED_TO",
                            "entity_id": f"target-{index}",
                            "name": f"Target {index}",
                            "evidence": None,
                        }
                        for index in range(relation_limit)
                    ],
                    "incoming_relations": [
                        {
                            "relation_type": "RELATED_TO",
                            "entity_id": f"source-{index}",
                            "name": f"Source {index}",
                            "evidence": None,
                        }
                        for index in range(relation_limit)
                    ],
                }
            ]
        return []

    async def get_source_detail(self, canonical_url: str):
        if canonical_url != "https://example.com/role-alpha":
            return None
        return {
            "source_key": canonical_url,
            "canonical_url": canonical_url,
            "title": "角色甲词条",
            "summary": "来源摘要",
            "fetched_at": None,
            "content_hash": "hash-1",
            "mentioned_entities": [{"entity_id": "entity-1", "name": "角色甲"}],
        }

    async def get_source_metadata_map(self, source_keys: list[str]):
        return {
            source_key: {
                "source_key": source_key,
                "title": "角色甲词条",
                "summary": "来源摘要",
            }
            for source_key in source_keys
        }

    async def query_graphrag_context(
        self,
        *,
        query: str,
        entity_limit: int,
        source_limit: int,
        relation_limit: int,
        neighborhood_limit: int,
        candidate_urls: list[str] | None = None,
        mode: str = "hybrid",
        query_embedding: list[float] | None = None,
        neighborhood_hops: int = 2,
    ):
        del entity_limit, source_limit, relation_limit, neighborhood_limit, candidate_urls, mode, neighborhood_hops
        self.last_query_embedding = query_embedding
        self.last_query_text = query
        return {
            "query": query,
            "entities": [
                {
                    "entity_id": "entity-1",
                    "name": "角色甲",
                    "category": "character",
                    "summary": "角色甲摘要",
                    "aliases": ["Role Alpha"],
                    "fulltext_score": 1.0,
                    "vector_score": 0.8,
                    "hybrid_score": 1.8,
                }
            ],
            "sources": [
                {
                    "source_key": "https://example.com/role-alpha",
                    "title": None,
                    "summary": None,
                    "fulltext_score": 0.9,
                    "vector_score": 0.7,
                    "hybrid_score": 1.6,
                }
            ],
            "relations": [
                {
                    "source_key": "entity-1::entity-2",
                    "left_entity_id": "entity-1",
                    "right_entity_id": "entity-2",
                    "left_entity_name": "角色甲",
                    "right_entity_name": "地区乙",
                    "aggregated_text": "角色甲与地区乙有关联",
                    "fulltext_score": 0.6,
                    "vector_score": 0.5,
                    "hybrid_score": 1.1,
                }
            ],
            "neighborhoods": [{"seed_entity_id": "entity-1", "neighbors": []}],
        }


def _build_request(*, headers: dict[str, str] | None = None, client_host: str = "127.0.0.1") -> Request:
    encoded_headers = []
    for key, value in (headers or {}).items():
        encoded_headers.append((key.lower().encode("utf-8"), value.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/search/v1/capabilities",
            "headers": encoded_headers,
            "query_string": b"",
            "client": (client_host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def _build_service(config: SearchApiConfig) -> tuple[SearchApiService, _FakeGraphRepo]:
    graph_repo = _FakeGraphRepo()
    service = SearchApiService(
        settings=Settings(data_root="", embedding_dimensions=3),
        graph_repo=graph_repo,
        embedding_client=_FakeEmbeddingClient(),
        config=config,
    )
    return service, graph_repo


class _FakeConfigService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def get_config(self) -> AppConfig:
        return self._config.model_copy(deep=True)

    def update_search_api_settings(self, *, enabled: bool, validation_enabled: bool) -> AppConfig:
        self._config.search_api.enabled = enabled
        self._config.search_api.validation_enabled = validation_enabled
        return self.get_config()

    def create_search_permission_source(self, source: SearchPermissionSource) -> AppConfig:
        self._config.search_api.permission_sources.append(source)
        return self.get_config()

    def update_search_permission_source(
        self,
        source_id: str,
        source: SearchPermissionSource,
    ) -> AppConfig:
        for index, current in enumerate(self._config.search_api.permission_sources):
            if current.id != source_id:
                continue
            self._config.search_api.permission_sources[index] = source
            return self.get_config()
        raise KeyError(source_id)

    def delete_search_permission_source(self, source_id: str) -> AppConfig:
        for index, current in enumerate(self._config.search_api.permission_sources):
            if current.id != source_id:
                continue
            del self._config.search_api.permission_sources[index]
            return self.get_config()
        raise KeyError(source_id)


class _RouteTestContainer:
    def __init__(self, config: AppConfig, search_api: SearchApiService) -> None:
        self.config_service = _FakeConfigService(config)
        self.search_api = search_api
        self.reload_runtime_calls = 0
        self.reload_search_api_config_calls = 0

    async def reload_runtime(self) -> None:
        self.reload_runtime_calls += 1

    async def reload_search_api_config(self) -> None:
        self.reload_search_api_config_calls += 1
        self.search_api.replace_config(self.config_service.get_config().search_api)


async def test_search_api_service_authorizes_matching_api_key_source():
    permission_source, generated_api_key = build_permission_source_from_create_request(
        SearchPermissionSourceCreateRequest(
            kind=SearchPermissionSourceKind.api_key,
            description="Partner Alpha",
            allow_builtin_embedding=False,
        )
    )
    service, _graph_repo = _build_service(
        SearchApiConfig(enabled=True, validation_enabled=True, permission_sources=[permission_source])
    )

    access = await service.authorize_request(
        _build_request(headers={"x-api-key": generated_api_key or ""})
    )

    assert access.matched_permission_source_id.startswith("api-key-partner-alpha-")
    assert access.allow_builtin_embedding is False


def test_search_permission_source_create_request_generates_id_when_omitted():
    permission_source, generated_api_key = build_permission_source_from_create_request(
        SearchPermissionSourceCreateRequest(
            kind=SearchPermissionSourceKind.api_key,
            description="Partner Alpha",
        )
    )

    assert generated_api_key is not None
    assert permission_source.id.startswith("api-key-partner-alpha-")
    assert permission_source.key_prefix == generated_api_key[:12]


async def test_search_api_service_matches_ip_permission_source():
    service, _graph_repo = _build_service(
        SearchApiConfig(
            enabled=True,
            validation_enabled=True,
            permission_sources=[
                SearchPermissionSource(
                    id="local-ip",
                    kind=SearchPermissionSourceKind.ip,
                    ip_value="127.0.0.1/32",
                    allow_builtin_embedding=True,
                )
            ],
        )
    )

    access = await service.authorize_request(_build_request())

    assert access.matched_permission_source_id == "local-ip"
    assert access.allow_builtin_embedding is True


async def test_search_api_service_requires_manual_vector_when_builtin_embedding_is_disallowed():
    permission_source, generated_api_key = build_permission_source_from_create_request(
        SearchPermissionSourceCreateRequest(
            id="partner-alpha",
            kind=SearchPermissionSourceKind.api_key,
            allow_builtin_embedding=False,
        )
    )
    service, _graph_repo = _build_service(
        SearchApiConfig(enabled=True, validation_enabled=True, permission_sources=[permission_source])
    )
    access = await service.authorize_request(
        _build_request(headers={"x-api-key": generated_api_key or ""})
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.query(
            SearchQueryRequest(query_text="角色甲", mode=SearchMode.vector),
            access,
        )

    assert exc_info.value.status_code == 403
    assert "query_vector" in str(exc_info.value.detail)


async def test_search_api_service_accepts_manual_vector_payload():
    permission_source, generated_api_key = build_permission_source_from_create_request(
        SearchPermissionSourceCreateRequest(
            id="partner-alpha",
            kind=SearchPermissionSourceKind.api_key,
            allow_builtin_embedding=False,
        )
    )
    service, graph_repo = _build_service(
        SearchApiConfig(enabled=True, validation_enabled=True, permission_sources=[permission_source])
    )
    access = await service.authorize_request(
        _build_request(headers={"x-api-key": generated_api_key or ""})
    )

    response = await service.query(
        SearchQueryRequest(mode=SearchMode.vector, query_vector=[0.1, 0.2, 0.3]),
        access,
    )

    assert response.query_vector_provided is True
    assert graph_repo.last_query_embedding == [0.1, 0.2, 0.3]


async def test_search_api_service_unified_entity_query_accepts_entity_id():
    service, _graph_repo = _build_service(SearchApiConfig(enabled=True, validation_enabled=False))

    response = await service.query_entities(
        SearchEntityQueryRequest(entity_id="entity-1", source_limit=1, relation_limit=1)
    )

    assert len(response.items) == 1
    assert response.items[0].entity_id == "entity-1"


async def test_search_api_service_unified_entity_query_accepts_alias():
    service, _graph_repo = _build_service(SearchApiConfig(enabled=True, validation_enabled=False))

    response = await service.query_entities(
        SearchEntityQueryRequest(alias="Role Alpha", source_limit=1, relation_limit=1)
    )

    assert len(response.items) == 1
    assert response.items[0].name == "角色甲"


async def test_search_api_service_source_detail_accepts_neo4j_datetime_like_value():
    service, graph_repo = _build_service(SearchApiConfig(enabled=True, validation_enabled=False))

    async def _fake_get_source_detail(canonical_url: str):
        return {
            "source_key": canonical_url,
            "canonical_url": canonical_url,
            "title": "角色甲词条",
            "summary": "来源摘要",
            "fetched_at": _FakeNeo4jDateTime(datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)),
            "content_hash": "hash-1",
            "mentioned_entities": [{"entity_id": "entity-1", "name": "角色甲"}],
        }

    graph_repo.get_source_detail = _fake_get_source_detail

    response = await service.get_source_detail(
        SearchSourceByKeyRequest(source_key="https://example.com/role-alpha")
    )

    assert response.source.fetched_at == datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)


def test_search_api_routes_return_expected_payloads():
    service, _graph_repo = _build_service(SearchApiConfig(enabled=True, validation_enabled=False))
    app = FastAPI()
    app.state.container = SimpleNamespace(search_api=service)
    app.include_router(router)
    client = TestClient(app)

    capabilities = client.get("/api/search/v1/capabilities")
    entity = client.post(
        "/api/search/v1/entities/query",
        json=SearchEntityQueryRequest(entity_id="entity-1", source_limit=1, relation_limit=1).model_dump(mode="json"),
    )
    lookup = client.post(
        "/api/search/v1/entities/query",
        json=SearchEntityQueryRequest(name="角色甲", source_limit=1, relation_limit=1).model_dump(mode="json"),
    )
    source = client.post(
        "/api/search/v1/sources/query",
        json=SearchSourceByKeyRequest(source_key="https://example.com/role-alpha").model_dump(mode="json"),
    )
    query = client.post(
        "/api/search/v1/search",
        json={"query_text": "角色甲", "mode": "hybrid", "entity_limit": 5, "source_limit": 5, "relation_limit": 5},
    )

    assert capabilities.status_code == 200
    assert capabilities.json()["authenticated"] is True
    assert entity.status_code == 200
    assert entity.json()["items"][0]["entity_id"] == "entity-1"
    assert entity.json()["items"][0]["mentioned_in_sources"][0]["id"] == "https://example.com/role-alpha-0"
    assert len(entity.json()["items"][0]["outgoing_relations"]) == 1
    assert lookup.status_code == 200
    assert lookup.json()["items"][0]["mentioned_in_sources"][0]["title"] == "角色甲词条 0"
    assert source.status_code == 200
    assert source.json()["source"]["source_key"] == "https://example.com/role-alpha"
    assert "outgoing_links" not in source.json()["source"]
    assert "incoming_links" not in source.json()["source"]
    assert query.status_code == 200
    assert query.json()["entities"][0]["entity_id"] == "entity-1"
    assert query.json()["sources"][0]["title"] == "角色甲词条"
    assert query.json()["sources"][0]["summary"] == "来源摘要"


def test_removed_legacy_entity_routes_return_404():
    service, _graph_repo = _build_service(SearchApiConfig(enabled=True, validation_enabled=False))
    app = FastAPI()
    app.state.container = SimpleNamespace(search_api=service)
    app.include_router(router)
    client = TestClient(app)

    by_id = client.post(
        "/api/search/v1/entities/by-id",
        json={"entity_id": "entity-1"},
    )
    lookup = client.post(
        "/api/search/v1/entities/lookup",
        json={"name": "角色甲"},
    )

    assert by_id.status_code == 404
    assert lookup.status_code == 404


def test_search_api_config_routes_do_not_trigger_full_runtime_reload():
    config = AppConfig(
        search_api=SearchApiConfig(enabled=False, validation_enabled=True),
    )
    service, _graph_repo = _build_service(config.search_api)
    container = _RouteTestContainer(config.model_copy(deep=True), service)

    app = FastAPI()
    app.state.container = container
    app.include_router(router)
    client = TestClient(app)

    settings_response = client.put(
        "/api/config/search-api/settings",
        json=SearchApiSettingsUpdateRequest(enabled=True, validation_enabled=False).model_dump(mode="json"),
    )

    assert settings_response.status_code == 200
    assert container.reload_search_api_config_calls == 1
    assert container.reload_runtime_calls == 0

    create_response = client.post(
        "/api/config/search-api/permissions",
        json=SearchPermissionSourceCreateRequest(
            kind=SearchPermissionSourceKind.ip,
            description="Office network",
            ip_value="127.0.0.1/32",
        ).model_dump(mode="json"),
    )

    assert create_response.status_code == 200
    assert container.reload_search_api_config_calls == 2
    assert container.reload_runtime_calls == 0

    created_source_id = create_response.json()["permission_source"]["id"]
    update_response = client.put(
        f"/api/config/search-api/permissions/{created_source_id}",
        json=SearchPermissionSourceUpdateRequest(
            description="HQ network",
            enabled=True,
            allow_builtin_embedding=True,
            ip_value="127.0.0.1/32",
        ).model_dump(mode="json"),
    )

    assert update_response.status_code == 200
    assert container.reload_search_api_config_calls == 3
    assert container.reload_runtime_calls == 0

    delete_response = client.delete(f"/api/config/search-api/permissions/{created_source_id}")

    assert delete_response.status_code == 200
    assert container.reload_search_api_config_calls == 4
    assert container.reload_runtime_calls == 0
    assert container.search_api._config.enabled is True
    assert container.search_api._config.validation_enabled is False