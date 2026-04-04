from __future__ import annotations

from enum import Enum
from ipaddress import ip_network
from typing import TypeVar

from pydantic import BaseModel, Field, model_validator

APP_CONFIG_SCHEMA_VERSION = 3


class DataSourceKind(str, Enum):
    neo4j = "neo4j"
    llm = "llm"
    embedding = "embedding"


class BaseProfile(BaseModel):
    id: str


class Neo4jProfile(BaseProfile):
    uri: str = ""
    username: str = ""
    password: str = ""
    knowledge_theme: str = ""


class LLMProfile(BaseProfile):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class EmbeddingProfile(BaseProfile):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class SearchPermissionSourceKind(str, Enum):
    api_key = "api_key"
    ip = "ip"


class SearchPermissionSource(BaseModel):
    id: str
    kind: SearchPermissionSourceKind
    description: str = ""
    enabled: bool = True
    allow_builtin_embedding: bool = False
    api_key_hash: str | None = None
    key_prefix: str | None = None
    ip_value: str | None = None

    @model_validator(mode="after")
    def _validate_source_payload(self) -> "SearchPermissionSource":
        self.id = self.id.strip()
        if not self.id:
            raise ValueError("Search API permission source id must not be empty")
        if self.kind == SearchPermissionSourceKind.api_key:
            if not self.api_key_hash:
                raise ValueError("API key permission source requires api_key_hash")
            return self

        if not self.ip_value:
            raise ValueError("IP permission source requires ip_value")
        ip_network(self.ip_value, strict=False)
        return self


class SearchApiConfig(BaseModel):
    enabled: bool = False
    validation_enabled: bool = True
    permission_sources: list[SearchPermissionSource] = Field(default_factory=list)


class RuntimeConfig(BaseModel):
    embedding_dimensions: int = Field(default=1536, ge=1)
    embedding_batch_size: int = Field(default=16, ge=1)
    embedding_text_max_chars: int = Field(default=4000, ge=1)
    embedding_version: str = "v1"
    visited_url_ttl_days: int = 10
    allowed_domains_enabled: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    max_crawl_depth: int = 2
    max_pages_per_job: int = 20
    crawl_concurrency: int = Field(default=1, ge=1)
    request_timeout_seconds: int = 20
    llm_timeout_seconds: int = 90
    user_agent: str = "IRISKGCrawler/0.1"
    skip_history_seen_urls: bool = True
    auto_backfill_indexes_after_crawl: bool = False
    browser_navigation_timeout_ms: int = 30000
    browser_post_load_wait_ms: int = 1500
    browser_scroll_pause_ms: int = 400
    browser_scroll_rounds: int = 6
    browser_locale: str = "zh-CN"
    browser_auto_accept_consent: bool = True


class AppConfig(BaseModel):
    schema_version: int = APP_CONFIG_SCHEMA_VERSION
    neo4j_profiles: list[Neo4jProfile] = Field(default_factory=list)
    active_neo4j_profile_id: str | None = None
    llm_profiles: list[LLMProfile] = Field(default_factory=list)
    active_llm_profile_id: str | None = None
    embedding_profiles: list[EmbeddingProfile] = Field(default_factory=list)
    active_embedding_profile_id: str | None = None
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    search_api: SearchApiConfig = Field(default_factory=SearchApiConfig)

    @model_validator(mode="after")
    def _validate_active_profiles(self) -> "AppConfig":
        _require_profiles("neo4j_profiles", self.neo4j_profiles, self.active_neo4j_profile_id)
        _require_profiles("llm_profiles", self.llm_profiles, self.active_llm_profile_id)
        _require_profiles("embedding_profiles", self.embedding_profiles, self.active_embedding_profile_id)
        permission_source_ids = [source.id for source in self.search_api.permission_sources]
        if len(permission_source_ids) != len(set(permission_source_ids)):
            raise ValueError("Search API permission source ids must be unique")
        return self

    def get_active_neo4j_profile(self) -> Neo4jProfile | None:
        return _get_active_profile(self.neo4j_profiles, self.active_neo4j_profile_id)

    def get_active_llm_profile(self) -> LLMProfile | None:
        return _get_active_profile(self.llm_profiles, self.active_llm_profile_id)

    def get_active_embedding_profile(self) -> EmbeddingProfile | None:
        return _get_active_profile(self.embedding_profiles, self.active_embedding_profile_id)

    def get_active_knowledge_theme(self) -> str:
        active_profile = self.get_active_neo4j_profile()
        if active_profile is None:
            return ""
        return active_profile.knowledge_theme


class ActiveProfilesResponse(BaseModel):
    neo4j: str | None
    llm: str | None
    embedding: str | None


class ConfigSummaryResponse(BaseModel):
    schema_version: int
    data_root: str
    active_profiles: ActiveProfilesResponse
    knowledge_theme: str
    allowed_domains: list[str]
    search_api_enabled: bool
    search_api_validation_enabled: bool


def _require_profiles(
    field_name: str,
    profiles: list[BaseProfile],
    active_profile_id: str | None,
) -> None:
    if not profiles:
        if active_profile_id is not None:
            raise ValueError(f"{field_name} is empty, active profile must be null")
        return
    ids = {profile.id for profile in profiles}
    if active_profile_id not in ids:
        raise ValueError(f"Active profile '{active_profile_id}' not found in {field_name}")


ProfileT = TypeVar("ProfileT", bound=BaseProfile)


def _get_active_profile(
    profiles: list[ProfileT],
    active_profile_id: str | None,
) -> ProfileT | None:
    if active_profile_id is None:
        return None
    for profile in profiles:
        if profile.id == active_profile_id:
            return profile
    raise ValueError(f"Active profile '{active_profile_id}' not found")
