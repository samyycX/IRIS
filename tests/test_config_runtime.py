import pytest
from pydantic import ValidationError

from app.core.config import BootstrapSettings, Settings
from app.models import AppConfig, LLMProfile, Neo4jProfile, RuntimeConfig


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


def test_bootstrap_settings_require_password_or_bypass():
    with pytest.raises(ValidationError, match="IRIS_PASSWORD OR IRIS_PASSWORD_BYPASS not set"):
        BootstrapSettings()


def test_bootstrap_settings_accept_password():
    settings = BootstrapSettings(iris_password="secret")

    assert settings.iris_password == "secret"
    assert settings.iris_password_bypass is False


def test_bootstrap_settings_accept_bypass_without_password():
    settings = BootstrapSettings(iris_password_bypass=True)

    assert settings.iris_password == ""
    assert settings.iris_password_bypass is True
