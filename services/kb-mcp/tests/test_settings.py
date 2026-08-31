"""Tests for the consolidated kb_mcp Settings module."""

import secrets

import pytest
from pydantic import ValidationError

from kb_mcp.settings import KNOWN_MCP_TOOLS, Settings, get_settings

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


def test_enabled_tools_defaults_to_all_known(monkeypatch):
    monkeypatch.delenv("KB_MCP_ENABLED_TOOLS", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.enabled_tools == KNOWN_MCP_TOOLS
    assert settings.disabled_tool_names() == frozenset()


def test_enabled_tools_empty_string_defaults_to_all(monkeypatch):
    monkeypatch.setenv("KB_MCP_ENABLED_TOOLS", "")
    get_settings.cache_clear()
    assert get_settings().enabled_tools == KNOWN_MCP_TOOLS


def test_enabled_tools_parses_comma_list(monkeypatch):
    monkeypatch.setenv("KB_MCP_ENABLED_TOOLS", "search, read_file")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.enabled_tools == frozenset({"search", "read_file"})
    assert settings.disabled_tool_names() == frozenset({"content_tree"})


def test_enabled_tools_rejects_unknown_name(monkeypatch):
    monkeypatch.setenv("KB_MCP_ENABLED_TOOLS", "search,nope")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="Unknown tool"):
        get_settings()


def test_enabled_tools_rejects_empty_list(monkeypatch):
    monkeypatch.setenv("KB_MCP_ENABLED_TOOLS", "  ,  ")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="empty"):
        get_settings()
