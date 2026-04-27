from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.config import AppConfig, UiLanguage


class _SettingsFields(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    ui_language: UiLanguage = Field(default=UiLanguage.zh, alias="UI_LANGUAGE")

    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="", alias="OPENAI_MODEL")
    openai_embedding_base_url: str = Field(
        default="",
        alias="OPENAI_EMBEDDING_BASE_URL",
    )
    openai_embedding_api_key: str = Field(default="", alias="OPENAI_EMBEDDING_API_KEY")
    openai_embedding_model: str = Field(
        default="",
        alias="OPENAI_EMBEDDING_MODEL",
    )
    knowledge_theme: str = ""
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS", ge=1)
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE", ge=1)
    embedding_text_max_chars: int = Field(default=4000, alias="EMBEDDING_TEXT_MAX_CHARS", ge=1)
    embedding_version: str = Field(default="v1", alias="EMBEDDING_VERSION")

    neo4j_uri: str = Field(default="", alias="NEO4J_URI")
    neo4j_username: str = Field(default="", alias="NEO4J_USERNAME")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")

    visited_url_ttl_days: int = Field(default=10, alias="VISITED_URL_TTL_DAYS")
    allowed_domains_enabled: bool = Field(default=False, alias="ALLOWED_DOMAINS_ENABLED")
    allowed_domains: list[str] = Field(default_factory=list, alias="ALLOWED_DOMAINS")
    max_crawl_depth: int = Field(default=2, alias="MAX_CRAWL_DEPTH")
    max_pages_per_job: int = Field(default=20, alias="MAX_PAGES_PER_JOB")
    crawl_concurrency: int = Field(default=1, alias="CRAWL_CONCURRENCY", ge=1)
    request_timeout_seconds: int = Field(default=20, alias="REQUEST_TIMEOUT_SECONDS")
    llm_timeout_seconds: int = Field(default=90, alias="LLM_TIMEOUT_SECONDS")
    user_agent: str = Field(default="IRISKGCrawler/0.1", alias="USER_AGENT")
    skip_history_seen_urls: bool = Field(default=True, alias="SKIP_HISTORY_SEEN_URLS")
    auto_backfill_indexes_after_crawl: bool = Field(
        default=False,
        alias="AUTO_BACKFILL_INDEXES_AFTER_CRAWL",
    )
    browser_navigation_timeout_ms: int = Field(
        default=30000,
        alias="BROWSER_NAVIGATION_TIMEOUT_MS",
    )
    browser_post_load_wait_ms: int = Field(default=1500, alias="BROWSER_POST_LOAD_WAIT_MS")
    browser_scroll_pause_ms: int = Field(default=400, alias="BROWSER_SCROLL_PAUSE_MS")
    browser_scroll_rounds: int = Field(default=6, alias="BROWSER_SCROLL_ROUNDS")
    browser_locale: str = Field(default="zh-CN", alias="BROWSER_LOCALE")
    browser_auto_accept_consent: bool = Field(
        default=True,
        alias="BROWSER_AUTO_ACCEPT_CONSENT",
    )
class Settings(_SettingsFields):
    data_root: str = ""

    @classmethod
    def from_sources(cls, bootstrap: "BootstrapSettings", app_config: AppConfig) -> "Settings":
        neo4j = app_config.get_active_neo4j_profile()
        llm = app_config.get_active_llm_profile()
        embedding = app_config.get_active_embedding_profile()
        runtime = app_config.runtime
        return cls(
            log_level=bootstrap.log_level,
            ui_language=runtime.ui_language,
            data_root=str(bootstrap.data_root),
            openai_base_url=llm.base_url if llm else "",
            openai_api_key=llm.api_key if llm else "",
            openai_model=llm.model if llm else "",
            openai_embedding_base_url=embedding.base_url if embedding else "",
            openai_embedding_api_key=embedding.api_key if embedding else "",
            openai_embedding_model=embedding.model if embedding else "",
            knowledge_theme=neo4j.knowledge_theme if neo4j else "",
            embedding_dimensions=runtime.embedding_dimensions,
            embedding_batch_size=runtime.embedding_batch_size,
            embedding_text_max_chars=runtime.embedding_text_max_chars,
            embedding_version=runtime.embedding_version,
            neo4j_uri=neo4j.uri if neo4j else "",
            neo4j_username=neo4j.username if neo4j else "",
            neo4j_password=neo4j.password if neo4j else "",
            visited_url_ttl_days=runtime.visited_url_ttl_days,
            allowed_domains_enabled=runtime.allowed_domains_enabled,
            allowed_domains=(
                runtime.allowed_domains if runtime.allowed_domains_enabled else []
            ),
            max_crawl_depth=runtime.max_crawl_depth,
            max_pages_per_job=runtime.max_pages_per_job,
            crawl_concurrency=runtime.crawl_concurrency,
            request_timeout_seconds=runtime.request_timeout_seconds,
            llm_timeout_seconds=runtime.llm_timeout_seconds,
            user_agent=runtime.user_agent,
            skip_history_seen_urls=runtime.skip_history_seen_urls,
            auto_backfill_indexes_after_crawl=runtime.auto_backfill_indexes_after_crawl,
            browser_navigation_timeout_ms=runtime.browser_navigation_timeout_ms,
            browser_post_load_wait_ms=runtime.browser_post_load_wait_ms,
            browser_scroll_pause_ms=runtime.browser_scroll_pause_ms,
            browser_scroll_rounds=runtime.browser_scroll_rounds,
            browser_locale=runtime.browser_locale,
            browser_auto_accept_consent=runtime.browser_auto_accept_consent,
        )


class BootstrapSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    iris_docker_env: bool = Field(default=False, alias="IRIS_DOCKER_ENV")
    iris_data_root: str | None = Field(default=None, alias="IRIS_DATA_ROOT")
    iris_password: str = Field(default="", alias="IRIS_PASSWORD")
    iris_password_bypass: bool = Field(default=False, alias="IRIS_PASSWORD_BYPASS")

    @model_validator(mode="after")
    def validate_password_gate(self) -> "BootstrapSettings":
        if self.iris_password_bypass:
            return self
        if self.iris_password:
            return self
        raise ValueError("IRIS_PASSWORD OR IRIS_PASSWORD_BYPASS not set")

    @computed_field
    @property
    def data_root(self) -> Path:
        if self.iris_data_root:
            return Path(self.iris_data_root).expanduser()
        if self.iris_docker_env:
            return Path("/data")
        return (Path.cwd() / "data").resolve()


@lru_cache
def get_settings() -> BootstrapSettings:
    return BootstrapSettings()
