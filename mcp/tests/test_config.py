from __future__ import annotations

import pytest
from pydantic import ValidationError

from iris_mcp_server.config import IrisMcpSettings


def test_normalizes_service_root_to_search_prefix() -> None:
    settings = IrisMcpSettings(
        IRIS_SEARCH_API_BASE_URL="http://localhost:8000/",
    )
    assert settings.search_api_base_url == "http://localhost:8000/api/search/v1"
    assert settings.auth_scheme == "none"


def test_preserves_full_search_api_prefix() -> None:
    settings = IrisMcpSettings(
        IRIS_SEARCH_API_BASE_URL="http://localhost:8000/api/search/v1",
    )
    assert settings.search_api_base_url == "http://localhost:8000/api/search/v1"


def test_requires_api_key_for_authenticated_modes() -> None:
    with pytest.raises(ValidationError):
        IrisMcpSettings(
            IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
            IRIS_SEARCH_API_AUTH_SCHEME="bearer",
        )


def test_normalizes_http_path() -> None:
    settings = IrisMcpSettings(
        IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
        IRIS_MCP_STREAMABLE_HTTP_PATH="mcp",
    )
    assert settings.iris_mcp_streamable_http_path == "/mcp"


def test_rejects_invalid_log_level() -> None:
    with pytest.raises(ValidationError):
        IrisMcpSettings(
            IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
            IRIS_MCP_LOG_LEVEL="trace",
        )


def test_embedding_fallback_requires_openai_config() -> None:
    with pytest.raises(ValidationError):
        IrisMcpSettings(
            IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
            IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=True,
        )


def test_embedding_fallback_accepts_openai_config() -> None:
    settings = IrisMcpSettings(
        IRIS_SEARCH_API_BASE_URL="http://localhost:8000",
        IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK=True,
        IRIS_OPENAI_API_KEY="sk-test",
        IRIS_OPENAI_EMBEDDING_MODEL="text-embedding-3-small",
    )
    assert settings.client_embedding_enabled is True