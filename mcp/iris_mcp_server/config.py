"""Configuration for the IRIS MCP server package."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AuthScheme = Literal["x-api-key", "bearer", "none"]

_SEARCH_API_SUFFIX = "/api/search/v1"


class IrisMcpSettings(BaseSettings):
    """Environment-backed settings for the standalone MCP package."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    iris_search_api_base_url: str = Field(alias="IRIS_SEARCH_API_BASE_URL")
    iris_search_api_key: str | None = Field(default=None, alias="IRIS_SEARCH_API_KEY")
    iris_search_api_auth_scheme: AuthScheme | None = Field(
        default=None,
        alias="IRIS_SEARCH_API_AUTH_SCHEME",
    )
    iris_search_api_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        alias="IRIS_SEARCH_API_TIMEOUT_SECONDS",
    )
    iris_search_api_retry_count: int = Field(
        default=2,
        ge=0,
        le=5,
        alias="IRIS_SEARCH_API_RETRY_COUNT",
    )
    iris_search_api_default_limit: int = Field(
        default=5,
        ge=1,
        le=50,
        alias="IRIS_SEARCH_API_DEFAULT_LIMIT",
    )
    iris_mcp_allow_client_embedding_fallback: bool = Field(
        default=False,
        alias="IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK",
    )
    iris_mcp_log_level: str = Field(default="INFO", alias="IRIS_MCP_LOG_LEVEL")
    iris_mcp_host: str = Field(default="127.0.0.1", alias="IRIS_MCP_HOST")
    iris_mcp_port: int = Field(default=8000, ge=1, le=65535, alias="IRIS_MCP_PORT")
    iris_mcp_streamable_http_path: str = Field(
        default="/mcp",
        alias="IRIS_MCP_STREAMABLE_HTTP_PATH",
    )
    iris_mcp_json_response: bool = Field(default=True, alias="IRIS_MCP_JSON_RESPONSE")
    iris_mcp_stateless_http: bool = Field(default=True, alias="IRIS_MCP_STATELESS_HTTP")
    iris_openai_api_key: str | None = Field(default=None, alias="IRIS_OPENAI_API_KEY")
    iris_openai_base_url: str | None = Field(default=None, alias="IRIS_OPENAI_BASE_URL")
    iris_openai_embedding_model: str | None = Field(default=None, alias="IRIS_OPENAI_EMBEDDING_MODEL")
    iris_openai_embedding_dimensions: int | None = Field(
        default=None,
        ge=1,
        alias="IRIS_OPENAI_EMBEDDING_DIMENSIONS",
    )
    iris_openai_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        alias="IRIS_OPENAI_TIMEOUT_SECONDS",
    )

    @field_validator("iris_search_api_base_url")
    @classmethod
    def _normalize_search_api_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("IRIS_SEARCH_API_BASE_URL is required")
        if normalized.endswith(_SEARCH_API_SUFFIX):
            return normalized
        return f"{normalized}{_SEARCH_API_SUFFIX}"

    @field_validator("iris_mcp_log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"IRIS_MCP_LOG_LEVEL must be one of {sorted(allowed)}")
        return normalized

    @field_validator("iris_mcp_streamable_http_path")
    @classmethod
    def _normalize_streamable_http_path(cls, value: str) -> str:
        normalized = value.strip() or "/mcp"
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    @model_validator(mode="after")
    def _resolve_auth_scheme(self) -> "IrisMcpSettings":
        if self.iris_search_api_auth_scheme is None:
            self.iris_search_api_auth_scheme = "x-api-key" if self.iris_search_api_key else "none"
        if self.iris_search_api_auth_scheme != "none" and not (self.iris_search_api_key or "").strip():
            raise ValueError(
                "IRIS_SEARCH_API_KEY is required when IRIS_SEARCH_API_AUTH_SCHEME is not 'none'"
            )
        if self.iris_mcp_allow_client_embedding_fallback:
            if not (self.iris_openai_api_key or "").strip():
                raise ValueError(
                    "IRIS_OPENAI_API_KEY is required when IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK is true"
                )
            if not (self.iris_openai_embedding_model or "").strip():
                raise ValueError(
                    "IRIS_OPENAI_EMBEDDING_MODEL is required when IRIS_MCP_ALLOW_CLIENT_EMBEDDING_FALLBACK is true"
                )
        return self

    @property
    def search_api_base_url(self) -> str:
        return self.iris_search_api_base_url

    @property
    def auth_scheme(self) -> AuthScheme:
        assert self.iris_search_api_auth_scheme is not None
        return self.iris_search_api_auth_scheme

    @property
    def client_embedding_enabled(self) -> bool:
        return self.iris_mcp_allow_client_embedding_fallback


@lru_cache(maxsize=1)
def get_settings() -> IrisMcpSettings:
    """Return cached settings for process entrypoints."""

    return IrisMcpSettings()