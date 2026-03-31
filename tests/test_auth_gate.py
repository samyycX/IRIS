from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.routes import router
from app.main import require_password_gate
from app.models import RuntimeStatusResponse
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


def _build_app(*, password: str = "", bypass_enabled: bool = False) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(require_password_gate)
    app.state.container = SimpleNamespace(
        auth=PasswordGateService(password=password, bypass_enabled=bypass_enabled),
        runtime_status=_FakeRuntimeStatus(),
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