"""Tests for the consolidated kb_mcp Settings module."""

import secrets

import pytest
from pydantic import ValidationError

from kb_mcp.settings import Settings, get_settings

pytestmark = pytest.mark.ai


def test_frontend_base_url_str_none_when_unset(monkeypatch):
    monkeypatch.delenv("UNIQUE_MCP_FRONTEND_BASE_URL", raising=False)
    get_settings.cache_clear()
    assert get_settings().frontend_base_url_str() is None


def test_frontend_base_url_str_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("UNIQUE_MCP_FRONTEND_BASE_URL", "https://example.unique.app/")
    get_settings.cache_clear()
    assert get_settings().frontend_base_url_str() == "https://example.unique.app"


def test_get_settings_is_cached(monkeypatch):
    assert get_settings() is get_settings()


def test_storage_must_be_durable_without_ephemeral_opt_in(monkeypatch):
    monkeypatch.delenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValidationError, match="OAuth storage is not durable"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_storage_allowed_when_ephemeral_opt_in_set(monkeypatch):
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.allow_ephemeral_oauth_storage is True


def test_storage_allowed_with_database_url_and_encryption_key(monkeypatch):
    monkeypatch.delenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/kb_mcp")
    monkeypatch.setenv("ENCRYPTION_KEY", secrets.token_hex(32))
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url is not None


def test_storage_rejects_encryption_key_that_is_not_valid_hex(monkeypatch):
    monkeypatch.delenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/kb_mcp")
    monkeypatch.setenv("ENCRYPTION_KEY", "z" * 64)  # right length, not hex
    with pytest.raises(ValidationError, match="not valid hex"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_storage_rejects_encryption_key_with_wrong_length(monkeypatch):
    monkeypatch.delenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/kb_mcp")
    monkeypatch.setenv("ENCRYPTION_KEY", secrets.token_hex(16))  # 32 hex chars, not 64
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_storage_rejects_database_url_without_encryption_key(monkeypatch):
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/kb_mcp")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValidationError, match="half-configured"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_storage_rejects_ephemeral_flag_with_durable_pair(monkeypatch):
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/kb_mcp")
    monkeypatch.setenv("ENCRYPTION_KEY", "a" * 64)
    with pytest.raises(ValidationError, match="Refuse ALLOW_EPHEMERAL"):
        Settings(_env_file=None)  # type: ignore[call-arg]
