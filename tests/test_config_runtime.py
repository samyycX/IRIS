from app.core.config import BootstrapSettings, Settings
from app.models import AppConfig, LLMProfile, RuntimeConfig


def test_profiles_only_require_id():
    config = AppConfig(
        llm_profiles=[LLMProfile(id="llm-main", model="gpt-4.1")],
        active_llm_profile_id="llm-main",
    )

    assert config.llm_profiles[0].model_dump() == {
        "id": "llm-main",
        "description": None,
        "base_url": "",
        "api_key": "",
        "model": "gpt-4.1",
    }


def test_settings_disable_allowed_domains_when_whitelist_is_off():
    settings = Settings.from_sources(
        BootstrapSettings(),
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
        BootstrapSettings(),
        AppConfig(
            runtime=RuntimeConfig(
                allowed_domains_enabled=True,
                allowed_domains=["wiki.example.com"],
            )
        ),
    )

    assert settings.allowed_domains_enabled is True
    assert settings.allowed_domains == ["wiki.example.com"]
