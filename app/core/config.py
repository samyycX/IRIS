from functools import lru_cache
from typing import Literal

from pydantic import Field, Json
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="I.R.I.S.", alias="APP_NAME")
    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        alias="APP_ENV",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_embedding_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_EMBEDDING_BASE_URL",
    )
    openai_embedding_api_key: str = Field(default="", alias="OPENAI_EMBEDDING_API_KEY")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )
    prompt_profile: str = Field(default="wuwa", alias="PROMPT_PROFILE")
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS", ge=1)
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE", ge=1)
    embedding_text_max_chars: int = Field(default=4000, alias="EMBEDDING_TEXT_MAX_CHARS", ge=1)
    embedding_version: str = Field(default="v1", alias="EMBEDDING_VERSION")
    embedding_similarity_function: str = Field(
        default="cosine",
        alias="EMBEDDING_SIMILARITY_FUNCTION",
    )

    neo4j_uri: str = Field(default="neo4j://localhost:7687", alias="NEO4J_URI")
    neo4j_username: str = Field(default="neo4j", alias="NEO4J_USERNAME")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")

    visited_url_ttl_days: int = Field(default=10, alias="VISITED_URL_TTL_DAYS")

    allowed_domains: Json[list[str]] = Field(
        default_factory=list,
        alias="ALLOWED_DOMAINS",
    )
    max_crawl_depth: int = Field(default=2, alias="MAX_CRAWL_DEPTH")
    max_pages_per_job: int = Field(default=20, alias="MAX_PAGES_PER_JOB")
    crawl_concurrency: int = Field(default=1, alias="CRAWL_CONCURRENCY", ge=1)
    request_timeout_seconds: int = Field(default=20, alias="REQUEST_TIMEOUT_SECONDS")
    llm_timeout_seconds: int = Field(default=90, alias="LLM_TIMEOUT_SECONDS")
    user_agent: str = Field(default="IRISKGCrawler/0.1", alias="USER_AGENT")
    skip_history_seen_urls: bool = Field(default=True, alias="SKIP_HISTORY_SEEN_URLS")
    enable_playwright: bool = Field(default=False, alias="ENABLE_PLAYWRIGHT")
    browser_headless: bool = Field(default=True, alias="BROWSER_HEADLESS")
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

@lru_cache
def get_settings() -> Settings:
    return Settings()
