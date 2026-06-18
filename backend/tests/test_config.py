"""Tests de la configuration (pydantic-settings)."""

import pytest

from app.config import Settings, get_settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "PaceRunner"
    assert settings.environment == "dev"
    assert settings.api_token is None


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("API_TOKEN", "secret123")
    settings = Settings()
    assert settings.environment == "prod"
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == "secret123"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
