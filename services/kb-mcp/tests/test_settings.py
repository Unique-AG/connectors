"""Tests for kb_mcp-specific server settings."""

import pytest

from kb_mcp.settings import KbMcpServerSettings

pytestmark = pytest.mark.ai


def test_frontend_base_url_str_none_when_unset(monkeypatch):
    monkeypatch.delenv("UNIQUE_MCP_FRONTEND_BASE_URL", raising=False)
    assert KbMcpServerSettings().frontend_base_url_str() is None


def test_frontend_base_url_str_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("UNIQUE_MCP_FRONTEND_BASE_URL", "https://example.unique.app/")
    assert KbMcpServerSettings().frontend_base_url_str() == "https://example.unique.app"
