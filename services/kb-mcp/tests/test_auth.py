"""Tests for OAuth wiring — the P0: client_storage must never be None.

FastMCP's OAuthProxy falls back to an on-disk store under
``settings.home / "oauth-proxy"`` whenever ``client_storage`` is ``None``.
That fallback directory does not exist in the deployed container (no ``$HOME``,
read-only root filesystem) and, even where it does exist, is per-pod and does
not survive a rollout or a second replica. These tests assert kb-mcp never
lets that fallback trigger.
"""

import secrets
from unittest.mock import MagicMock, patch

import pytest

from kb_mcp.auth import build_auth
from kb_mcp.auth.storage import build_storage
from kb_mcp.settings import get_settings

pytestmark = pytest.mark.ai


@pytest.fixture
def durable_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/kb_mcp")
    monkeypatch.setenv("ENCRYPTION_KEY", secrets.token_hex(32))
    # .env.test defaults this to true; override it for the durable case.
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "false")
    get_settings.cache_clear()
    settings = get_settings()
    get_settings.cache_clear()
    return settings


@pytest.fixture
def ephemeral_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()
    get_settings.cache_clear()
    return settings


def test_build_storage_with_database_url_returns_a_store(durable_settings):
    assert build_storage(durable_settings) is not None


def test_build_storage_ephemeral_opt_in_returns_a_store(ephemeral_settings):
    assert build_storage(ephemeral_settings) is not None


def test_build_auth_never_passes_none_client_storage(durable_settings):
    with patch("kb_mcp.auth.oidc_proxy.create_zitadel_oidc_proxy") as mock_create:
        mock_create.return_value = MagicMock()
        build_auth(durable_settings)

    _, kwargs = mock_create.call_args
    assert kwargs["client_storage"] is not None


def test_build_auth_uses_a_secretless_zitadel_client(durable_settings, monkeypatch):
    monkeypatch.setenv("ZITADEL_CLIENT_SECRET", "legacy-secret")
    with patch("kb_mcp.auth.oidc_proxy.create_zitadel_oidc_proxy") as mock_create:
        mock_create.return_value = MagicMock()
        build_auth(durable_settings)

    _, kwargs = mock_create.call_args
    zitadel_settings = kwargs["zitadel_oidc_proxy_settings"]
    assert zitadel_settings.client_secret is None
    # Local secret for FastMCP's own downstream JWTs, never sent to Zitadel —
    # required because OIDCProxy raises without either client_secret or this.
    assert zitadel_settings.jwt_signing_key.get_secret_value() == "test-jwt-signing-key"


def test_build_auth_passes_required_scopes(durable_settings):
    with patch("kb_mcp.auth.oidc_proxy.create_zitadel_oidc_proxy") as mock_create:
        mock_create.return_value = MagicMock()
        build_auth(durable_settings)

    _, kwargs = mock_create.call_args
    # Identity only — mcp:* must stay advertised, not required (RequireAuthMiddleware).
    assert kwargs["required_scopes"] == [
        "openid",
        "profile",
        "urn:zitadel:iam:user:resourceowner",
    ]
    assert kwargs["verify_id_token"] is True


def test_build_storage_treats_decryption_errors_as_misses(durable_settings):
    store = build_storage(durable_settings)
    assert store.raise_on_decryption_error is False


def test_build_auth_passes_storage_even_in_ephemeral_dev_mode(ephemeral_settings):
    with patch("kb_mcp.auth.oidc_proxy.create_zitadel_oidc_proxy") as mock_create:
        mock_create.return_value = MagicMock()
        build_auth(ephemeral_settings)

    _, kwargs = mock_create.call_args
    assert kwargs["client_storage"] is not None


def test_missing_database_url_raises_instead_of_falling_back(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    # .env.test defaults this to true; override it to hit the "not durable" branch.
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "false")
    get_settings.cache_clear()
    with pytest.raises(Exception, match="OAuth storage is not durable"):
        get_settings()
    get_settings.cache_clear()
