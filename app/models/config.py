from __future__ import annotations

from enum import Enum
from typing import TypeVar

from pydantic import BaseModel, Field, model_validator

APP_CONFIG_SCHEMA_VERSION = 1


class DataSourceKind(str, Enum):
    neo4j = "neo4j"
    llm = "llm"
    embedding = "embedding"


class BaseProfile(BaseModel):
    id: str
    description: str | None = None


class Neo4jProfile(BaseProfile):
    uri: str = ""
    username: str = ""
    password: str = ""


class LLMProfile(BaseProfile):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class EmbeddingProfile(BaseProfile):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class RuntimeConfig(BaseModel):
    knowledge_theme: str = ""
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

    @model_validator(mode="after")
    def _validate_active_profiles(self) -> "AppConfig":
        _require_profiles("neo4j_profiles", self.neo4j_profiles, self.active_neo4j_profile_id)
        _require_profiles("llm_profiles", self.llm_profiles, self.active_llm_profile_id)
        _require_profiles("embedding_profiles", self.embedding_profiles, self.active_embedding_profile_id)
        return self

    def get_active_neo4j_profile(self) -> Neo4jProfile | None:
        return _get_active_profile(self.neo4j_profiles, self.active_neo4j_profile_id)

    def get_active_llm_profile(self) -> LLMProfile | None:
        return _get_active_profile(self.llm_profiles, self.active_llm_profile_id)

    def get_active_embedding_profile(self) -> EmbeddingProfile | None:
        return _get_active_profile(self.embedding_profiles, self.active_embedding_profile_id)


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
