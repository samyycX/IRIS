import pytest
from pydantic import ValidationError

from app.core.config import BootstrapSettings, Settings
from app.models import AppConfig, LLMProfile, Neo4jProfile, RuntimeConfig, UiLanguage
from app.services.app_config import migrate_app_config


def test_profiles_only_require_id():
    config = AppConfig(
        llm_profiles=[LLMProfile(id="llm-main", model="gpt-4.1")],
        active_llm_profile_id="llm-main",
    )

    assert config.llm_profiles[0].model_dump() == {
        "id": "llm-main",
        "base_url": "",
        "api_key": "",
        "model": "gpt-4.1",
    }


def test_neo4j_profile_has_only_id_and_connection_fields():
    profile = Neo4jProfile(
        id="local",
        uri="neo4j://127.0.0.1:7687",
        username="neo4j",
        password="x",
    )
    dumped = profile.model_dump()
    assert dumped == {
        "id": "local",
        "uri": "neo4j://127.0.0.1:7687",
        "username": "neo4j",
        "password": "x",
        "knowledge_theme": "",
    }


def test_settings_disable_allowed_domains_when_whitelist_is_off():
    settings = Settings.from_sources(
        BootstrapSettings(iris_password_bypass=True),
        AppConfig(
            runtime=RuntimeConfig(
                allowed_domains_enabled=False,
                allowed_domains=["wiki.example.com"],
            )
        ),
    )

    assert settings.allowed_domains_enabled is False
    assert settings.allowed_domains == []


def test_settings_keep_allowed_domains_when_whitelist_is_on():
    settings = Settings.from_sources(
        BootstrapSettings(iris_password_bypass=True),
        AppConfig(
            runtime=RuntimeConfig(
                allowed_domains_enabled=True,
                allowed_domains=["wiki.example.com"],
            )
        ),
    )

    assert settings.allowed_domains_enabled is True
    assert settings.allowed_domains == ["wiki.example.com"]


def test_settings_include_ui_language_from_runtime_config():
    settings = Settings.from_sources(
        BootstrapSettings(iris_password_bypass=True),
        AppConfig(runtime=RuntimeConfig(ui_language=UiLanguage.en)),
    )

    assert settings.ui_language == UiLanguage.en


def test_bootstrap_settings_require_password_or_bypass(tmp_path, monkeypatch):
    monkeypatch.delenv("IRIS_PASSWORD", raising=False)
    monkeypatch.delenv("IRIS_PASSWORD_BYPASS", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError, match="IRIS_PASSWORD OR IRIS_PASSWORD_BYPASS not set"):
        BootstrapSettings()


def test_bootstrap_settings_accept_password():
    settings = BootstrapSettings(iris_password="secret")

    assert settings.iris_password == "secret"
    assert settings.iris_password_bypass is False


def test_bootstrap_settings_accept_bypass_without_password(tmp_path, monkeypatch):
    monkeypatch.delenv("IRIS_PASSWORD", raising=False)
    monkeypatch.delenv("IRIS_PASSWORD_BYPASS", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = BootstrapSettings(iris_password_bypass=True)

    assert settings.iris_password == ""
    assert settings.iris_password_bypass is True


def test_bootstrap_settings_read_defaults_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IRIS_PASSWORD", raising=False)
    monkeypatch.delenv("IRIS_PASSWORD_BYPASS", raising=False)

    (tmp_path / ".env").write_text("IRIS_PASSWORD=from-dotenv\n", encoding="utf-8")

    settings = BootstrapSettings()

    assert settings.iris_password == "from-dotenv"
    assert settings.iris_password_bypass is False


def test_bootstrap_settings_prefer_environment_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IRIS_PASSWORD_BYPASS", raising=False)
    monkeypatch.setenv("IRIS_PASSWORD", "from-env")

    (tmp_path / ".env").write_text("IRIS_PASSWORD=from-dotenv\n", encoding="utf-8")

    settings = BootstrapSettings()

    assert settings.iris_password == "from-env"


def test_migrate_app_config_adds_search_api_defaults_for_v2_payload():
    migrated = migrate_app_config(
        {
            "schema_version": 2,
            "neo4j_profiles": [],
            "active_neo4j_profile_id": None,
            "llm_profiles": [],
            "active_llm_profile_id": None,
            "embedding_profiles": [],
            "active_embedding_profile_id": None,
            "runtime": {},
        },
        BootstrapSettings(iris_password_bypass=True),
    )

    assert migrated.schema_version == 4
    assert migrated.search_api.enabled is False
    assert migrated.search_api.validation_enabled is True
    assert migrated.search_api.permission_sources == []


def test_migrate_app_config_adds_default_ui_language_for_v3_payload():
    migrated = migrate_app_config(
        {
            "schema_version": 3,
            "neo4j_profiles": [],
            "active_neo4j_profile_id": None,
            "llm_profiles": [],
            "active_llm_profile_id": None,
            "embedding_profiles": [],
            "active_embedding_profile_id": None,
            "runtime": {},
            "search_api": {
                "enabled": False,
                "validation_enabled": True,
                "permission_sources": [],
            },
        },
        BootstrapSettings(iris_password_bypass=True),
    )

    assert migrated.schema_version == 4
    assert migrated.runtime.ui_language == UiLanguage.zh


def test_migrate_app_config_normalizes_blank_search_permission_source_ids():
    migrated = migrate_app_config(
        {
            "schema_version": 3,
            "neo4j_profiles": [],
            "active_neo4j_profile_id": None,
            "llm_profiles": [],
            "active_llm_profile_id": None,
            "embedding_profiles": [],
            "active_embedding_profile_id": None,
            "runtime": {},
            "search_api": {
                "enabled": True,
                "validation_enabled": True,
                "permission_sources": [
                    {
                        "id": "",
                        "kind": "ip",
                        "description": "Office network",
                        "enabled": True,
                        "allow_builtin_embedding": False,
                        "ip_value": "127.0.0.1/32",
                    }
                ],
            },
        },
        BootstrapSettings(iris_password_bypass=True),
    )

    assert migrated.search_api.permission_sources[0].id.startswith("ip-office-network-")
