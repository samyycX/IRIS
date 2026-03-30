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
)
from app.services.local_data import LocalDataStore

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
            "knowledge_theme": config.runtime.knowledge_theme,
            "allowed_domains": config.runtime.allowed_domains,
        }

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
    )


def migrate_app_config(payload: dict[str, Any], bootstrap: BootstrapSettings) -> AppConfig:
    version = int(payload.get("schema_version") or 0)
    data: dict[str, Any] = deepcopy(payload)
    while version < APP_CONFIG_SCHEMA_VERSION:
        if version == 0:
            data = _migrate_v0_to_v1(data, bootstrap)
            version = 1
            continue
        raise ValueError(f"Unsupported app config schema version: {version}")
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
