from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.config import BootstrapSettings, Settings
from app.models.config import (
    APP_CONFIG_SCHEMA_VERSION,
    AppConfig,
    DataSourceKind,
    EmbeddingProfile,
    LLMProfile,
    Neo4jProfile,
    RuntimeConfig,
    SearchApiConfig,
    SearchPermissionSource,
)
from app.services.local_data import LocalDataStore
from app.services.search_api import normalize_permission_source_ids

_CONFIG_PATH = ("config", "app_config.json")


class AppConfigService:
    def __init__(self, bootstrap: BootstrapSettings, store: LocalDataStore) -> None:
        self._bootstrap = bootstrap
        self._store = store
        self._cached_config: AppConfig | None = None

    def get_config(self) -> AppConfig:
        if self._cached_config is None:
            self._cached_config = self._load_or_initialize_config()
        return self._cached_config.model_copy(deep=True)

    def save_config(self, config: AppConfig) -> AppConfig:
        validated = AppConfig.model_validate(config)
        self._persist(validated)
        self._cached_config = validated
        return validated.model_copy(deep=True)

    def list_profiles(self, kind: DataSourceKind) -> list[Neo4jProfile | LLMProfile | EmbeddingProfile]:
        config = self.get_config()
        return deepcopy(_get_profiles(config, kind))

    def create_profile(
        self,
        kind: DataSourceKind,
        profile: Neo4jProfile | LLMProfile | EmbeddingProfile,
    ) -> AppConfig:
        config = self.get_config()
        profiles = _get_profiles(config, kind)
        if any(item.id == profile.id for item in profiles):
            raise ValueError(f"{kind.value} profile '{profile.id}' already exists")
        profiles.append(profile)
        if _get_active_profile_id(config, kind) is None:
            setattr(config, _active_field_name(kind), profile.id)
        return self.save_config(config)

    def update_profile(
        self,
        kind: DataSourceKind,
        profile_id: str,
        profile: Neo4jProfile | LLMProfile | EmbeddingProfile,
    ) -> AppConfig:
        config = self.get_config()
        profiles = _get_profiles(config, kind)
        for index, current in enumerate(profiles):
            if current.id != profile_id:
                continue
            if profile.id != profile_id and any(item.id == profile.id for item in profiles):
                raise ValueError(f"{kind.value} profile '{profile.id}' already exists")
            profiles[index] = profile
            _repoint_active_profile(config, kind, profile_id, profile.id)
            return self.save_config(config)
        raise KeyError(profile_id)

    def delete_profile(self, kind: DataSourceKind, profile_id: str) -> AppConfig:
        config = self.get_config()
        profiles = _get_profiles(config, kind)
        active_profile_id = _get_active_profile_id(config, kind)
        if profile_id == active_profile_id:
            raise ValueError(f"Cannot delete active {kind.value} profile '{profile_id}'")
        updated_profiles = [profile for profile in profiles if profile.id != profile_id]
        if len(updated_profiles) == len(profiles):
            raise KeyError(profile_id)
        setattr(config, _profile_field_name(kind), updated_profiles)
        if not updated_profiles:
            setattr(config, _active_field_name(kind), None)
        return self.save_config(config)

    def set_active_profile(self, kind: DataSourceKind, profile_id: str | None) -> AppConfig:
        config = self.get_config()
        profiles = _get_profiles(config, kind)
        if profile_id is not None and not any(profile.id == profile_id for profile in profiles):
            raise KeyError(profile_id)
        setattr(config, _active_field_name(kind), profile_id)
        return self.save_config(config)

    def get_runtime_settings(self) -> Settings:
        return Settings.from_sources(self._bootstrap, self.get_config())

    def get_summary(self) -> dict[str, Any]:
        config = self.get_config()
        return {
            "schema_version": config.schema_version,
            "data_root": str(self._store.root),
            "active_profiles": {
                "neo4j": config.active_neo4j_profile_id,
                "llm": config.active_llm_profile_id,
                "embedding": config.active_embedding_profile_id,
            },
            "knowledge_theme": config.get_active_knowledge_theme(),
            "allowed_domains": config.runtime.allowed_domains,
            "search_api_enabled": config.search_api.enabled,
            "search_api_validation_enabled": config.search_api.validation_enabled,
        }

    def update_search_api_settings(
        self,
        *,
        enabled: bool,
        validation_enabled: bool,
    ) -> AppConfig:
        config = self.get_config()
        config.search_api.enabled = enabled
        config.search_api.validation_enabled = validation_enabled
        return self.save_config(config)

    def create_search_permission_source(
        self,
        source: SearchPermissionSource,
    ) -> AppConfig:
        config = self.get_config()
        config.search_api.permission_sources = list(
            normalize_permission_source_ids(config.search_api.permission_sources)
        )
        if any(item.id == source.id for item in config.search_api.permission_sources):
            raise ValueError(f"search_api permission source '{source.id}' already exists")
        config.search_api.permission_sources.append(source)
        return self.save_config(config)

    def update_search_permission_source(
        self,
        source_id: str,
        source: SearchPermissionSource,
    ) -> AppConfig:
        config = self.get_config()
        sources = list(normalize_permission_source_ids(config.search_api.permission_sources))
        config.search_api.permission_sources = sources
        for index, current in enumerate(sources):
            if current.id != source_id:
                continue
            if source.id != source_id and any(item.id == source.id for item in sources):
                raise ValueError(f"search_api permission source '{source.id}' already exists")
            sources[index] = source
            return self.save_config(config)
        raise KeyError(source_id)

    def delete_search_permission_source(self, source_id: str) -> AppConfig:
        config = self.get_config()
        updated_sources = [
            source for source in config.search_api.permission_sources if source.id != source_id
        ]
        if len(updated_sources) == len(config.search_api.permission_sources):
            raise KeyError(source_id)
        config.search_api.permission_sources = updated_sources
        return self.save_config(config)

    def _load_or_initialize_config(self) -> AppConfig:
        payload = self._store.read_json(*_CONFIG_PATH)
        if payload is None:
            config = build_default_app_config(self._bootstrap)
            self._persist(config)
            return config
        migrated = migrate_app_config(payload, self._bootstrap)
        self._persist(migrated)
        return migrated

    def _persist(self, config: AppConfig) -> None:
        self._store.write_json(*_CONFIG_PATH, payload=config.model_dump(mode="json"))


def build_default_app_config(bootstrap: BootstrapSettings) -> AppConfig:
    del bootstrap
    return AppConfig(
        schema_version=APP_CONFIG_SCHEMA_VERSION,
        neo4j_profiles=[],
        active_neo4j_profile_id=None,
        llm_profiles=[],
        active_llm_profile_id=None,
        embedding_profiles=[],
        active_embedding_profile_id=None,
        runtime=RuntimeConfig(),
        search_api=SearchApiConfig(),
    )


def migrate_app_config(payload: dict[str, Any], bootstrap: BootstrapSettings) -> AppConfig:
    version = int(payload.get("schema_version") or 0)
    data: dict[str, Any] = deepcopy(payload)
    while version < APP_CONFIG_SCHEMA_VERSION:
        if version == 0:
            data = _migrate_v0_to_v1(data, bootstrap)
            version = 1
            continue
        if version == 1:
            data = _migrate_v1_to_v2(data)
            version = 2
            continue
        if version == 2:
            data = _migrate_v2_to_v3(data)
            version = 3
            continue
        raise ValueError(f"Unsupported app config schema version: {version}")
    data = _normalize_search_api_permission_source_ids(data)
    data["schema_version"] = APP_CONFIG_SCHEMA_VERSION
    return AppConfig.model_validate(data)


def _migrate_v0_to_v1(payload: dict[str, Any], bootstrap: BootstrapSettings) -> dict[str, Any]:
    default = build_default_app_config(bootstrap).model_dump(mode="json")
    migrated = deepcopy(default)
    migrated.update({key: value for key, value in payload.items() if key != "runtime"})
    runtime_payload = payload.get("runtime", {})
    if isinstance(runtime_payload, dict):
        migrated["runtime"].update(runtime_payload)
    return migrated


def _migrate_v1_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(payload)
    runtime_payload = migrated.get("runtime")
    knowledge_theme = ""
    if isinstance(runtime_payload, dict):
        knowledge_theme = str(runtime_payload.pop("knowledge_theme", "") or "")

    neo4j_profiles = migrated.get("neo4j_profiles")
    if isinstance(neo4j_profiles, list):
        for profile in neo4j_profiles:
            if not isinstance(profile, dict):
                continue
            profile.setdefault("knowledge_theme", knowledge_theme)

    return migrated


def _migrate_v2_to_v3(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(payload)
    search_api_payload = migrated.get("search_api")
    if not isinstance(search_api_payload, dict):
        migrated["search_api"] = SearchApiConfig().model_dump(mode="json")
    else:
        default_payload = SearchApiConfig().model_dump(mode="json")
        default_payload.update(search_api_payload)
        migrated["search_api"] = default_payload
    return migrated


def _normalize_search_api_permission_source_ids(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(payload)
    search_api_payload = migrated.get("search_api")
    if not isinstance(search_api_payload, dict):
        return migrated
    sources = search_api_payload.get("permission_sources")
    if not isinstance(sources, list):
        return migrated
    search_api_payload["permission_sources"] = normalize_permission_source_ids(sources)
    return migrated


def _profile_field_name(kind: DataSourceKind) -> str:
    return f"{kind.value}_profiles"


def _active_field_name(kind: DataSourceKind) -> str:
    return f"active_{kind.value}_profile_id"


def _get_profiles(
    config: AppConfig,
    kind: DataSourceKind,
) -> list[Neo4jProfile] | list[LLMProfile] | list[EmbeddingProfile]:
    return getattr(config, _profile_field_name(kind))


def _get_active_profile_id(config: AppConfig, kind: DataSourceKind) -> str | None:
    return getattr(config, _active_field_name(kind))


def _repoint_active_profile(
    config: AppConfig,
    kind: DataSourceKind,
    old_profile_id: str,
    new_profile_id: str,
) -> None:
    active_field = _active_field_name(kind)
    if getattr(config, active_field) == old_profile_id:
        setattr(config, active_field, new_profile_id)
