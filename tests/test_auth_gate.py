from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.routes import router
from app.main import require_password_gate
from app.models import RuntimeStatusResponse
from app.models.config import SearchPermissionSourceKind
from app.services.auth import PasswordGateService


class _FakeRuntimeStatus:
    async def get_status(self) -> RuntimeStatusResponse:
        return RuntimeStatusResponse.model_validate(
            {
                "status": "healthy",
                "checked_at": "2026-03-31T00:00:00Z",
                "neo4j": {
                    "state": "healthy",
                    "configured": False,
                    "available": False,
                    "last_checked_at": None,
                    "last_error": None,
                    "details": {},
                },
                "llm": {
                    "state": "unconfigured",
                    "configured": False,
                    "available": False,
                    "last_checked_at": None,
                    "last_error": None,
                    "details": {},
                },
                "embedding": {
                    "state": "unconfigured",
                    "configured": False,
                    "available": False,
                    "last_checked_at": None,
                    "last_error": None,
                    "details": {},
                },
                "graph": {
                    "entity_count": 0,
                    "source_count": 0,
                    "relation_count": 0,
                    "stale": False,
                    "last_updated_at": None,
                },
            }
        )


class _FakeSearchApi:
    async def authorize_request(self, request: Request):
        del request
        return SimpleNamespace(
            authenticated=True,
            validation_enabled=False,
            matched_permission_source_id=None,
            matched_permission_source_kind=None,
            allow_builtin_embedding=True,
        )

    async def get_capabilities(self, request: Request):
        del request
        return {
            "enabled": True,
            "validation_enabled": False,
            "authenticated": True,
            "matched_permission_source_id": None,
            "matched_permission_source_kind": None,
            "allow_builtin_embedding": True,
            "embedding_dimensions": 1536,
            "supported_modes": ["fulltext", "vector", "hybrid"],
            "query_vector_required_for_semantic_search": False,
        }

    async def get_entity_detail(self, entity_id: str):
        return {
            "entity": {
                "entity_id": entity_id,
                "name": "角色甲",
                "normalized_name": "角色甲",
                "category": "character",
                "summary": "示例实体",
                "aliases": [],
                "mentioned_in_sources": [],
                "outgoing_relations": [],
                "incoming_relations": [],
            }
        }

    async def lookup_entities(self, *, name: str | None, alias: str | None, limit: int):
        del name, alias, limit
        return {"items": []}

    async def get_source_detail(self, canonical_url: str):
        return {
            "source": {
                "source_key": canonical_url,
                "canonical_url": canonical_url,
                "title": "Example",
                "summary": "Summary",
                "fetched_at": None,
                "content_hash": None,
                "outgoing_links": [],
                "incoming_links": [],
                "mentioned_entities": [],
            }
        }

    async def query(self, payload, access):
        del payload, access
        return {
            "query_text": "角色甲",
            "mode": "fulltext",
            "query_vector_provided": False,
            "capabilities": {
                "enabled": True,
                "validation_enabled": False,
                "authenticated": True,
                "matched_permission_source_id": None,
                "matched_permission_source_kind": None,
                "allow_builtin_embedding": True,
                "embedding_dimensions": 1536,
                "supported_modes": ["fulltext", "vector", "hybrid"],
                "query_vector_required_for_semantic_search": False,
            },
            "entities": [],
            "sources": [],
            "relations": [],
            "neighborhoods": [],
        }


def _build_app(*, password: str = "", bypass_enabled: bool = False) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(require_password_gate)
    app.state.container = SimpleNamespace(
        auth=PasswordGateService(password=password, bypass_enabled=bypass_enabled),
        runtime_status=_FakeRuntimeStatus(),
        search_api=_FakeSearchApi(),
    )
    app.include_router(router)

    @app.get("/api/status")
    async def status(request: Request):
        return await request.app.state.container.runtime_status.get_status()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


def test_auth_gate_rejects_protected_routes_until_login():
    client = TestClient(_build_app(password="secret"))

    assert client.get("/healthz").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/auth/status").json() == {
        "bypass_enabled": False,
        "authenticated": False,
    }


def test_auth_gate_login_unlocks_cookie_session():
    client = TestClient(_build_app(password="secret"))

    bad_login = client.post("/api/auth/login", json={"password": "wrong"})
    good_login = client.post("/api/auth/login", json={"password": "secret"})
    protected = client.get("/api/status")
    logout = client.post("/api/auth/logout")
    locked_again = client.get("/api/status")

    assert bad_login.status_code == 401
    assert good_login.status_code == 200
    assert protected.status_code == 200
    assert logout.status_code == 200
    assert locked_again.status_code == 401


def test_auth_gate_bypass_allows_direct_access():
    client = TestClient(_build_app(bypass_enabled=True))

    status_response = client.get("/api/auth/status")
    protected = client.get("/api/status")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "bypass_enabled": True,
        "authenticated": True,
    }
    assert protected.status_code == 200


def test_external_search_api_is_not_blocked_by_dashboard_cookie_gate():
    client = TestClient(_build_app(password="secret"))

    search_response = client.get("/api/search/v1/capabilities")
    protected_config = client.get("/api/config")

    assert search_response.status_code == 200
    assert protected_config.status_code == 401