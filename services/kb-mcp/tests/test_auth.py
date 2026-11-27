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

import httpx2
import pytest
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.stores.memory import MemoryStore

from kb_mcp.auth import build_auth
from kb_mcp.auth.storage import build_storage
from kb_mcp.settings import get_settings

pytestmark = pytest.mark.ai

_SIGNING_KEY = "test-jwt-signing-key-0123456789abcdef"


@pytest.fixture
def zitadel_discovery(monkeypatch):
    """Answers the proxy's OIDC discovery request without a network."""

    def get(url: str, **_: object) -> httpx2.Response:
        issuer = url.removesuffix("/.well-known/openid-configuration")
        configuration = {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/v2/authorize",
            "token_endpoint": f"{issuer}/oauth/v2/token",
            "jwks_uri": f"{issuer}/oauth/v2/keys",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        return httpx2.Response(
            200, json=configuration, request=httpx2.Request("GET", url)
        )

    monkeypatch.setattr(httpx2, "get", get)


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
    assert kwargs.get("encryption_salt") is None


def test_build_auth_uses_a_secretless_zitadel_client(durable_settings, monkeypatch):
    monkeypatch.setenv("ZITADEL_CLIENT_SECRET", "legacy-secret")
    with patch("kb_mcp.auth.oidc_proxy.create_zitadel_oidc_proxy") as mock_create:
        mock_create.return_value = MagicMock()
        build_auth(durable_settings)

    _, kwargs = mock_create.call_args
    zitadel = kwargs["zitadel"]
    assert zitadel.client_secret is None
    assert zitadel.org_id is None
    assert zitadel.client_id == "test-client-id"
    assert zitadel.issuer == "https://id.test.unique.app"
    # Local secret for FastMCP's own downstream JWTs, never sent to Zitadel —
    # required because OIDCProxy raises without either client_secret or this.
    assert zitadel.jwt_signing_key.get_secret_value() == _SIGNING_KEY
    assert kwargs["base_url"] == durable_settings.base_url.encoded_string()


@pytest.mark.usefixtures("zitadel_discovery")
def test_build_auth_requires_identity_scopes_and_verifies_the_id_token(
    durable_settings,
):
    proxy = build_auth(durable_settings)

    assert isinstance(proxy, OIDCProxy)
    # Identity only — mcp:* must stay advertised, not required (RequireAuthMiddleware).
    assert proxy.required_scopes == [
        "openid",
        "profile",
        "urn:zitadel:iam:user:resourceowner",
    ]
    # FastMCP has no public accessor for this; pinned by fastmcp's version in uv.lock.
    assert proxy._verify_id_token


@pytest.mark.usefixtures("zitadel_discovery")
def test_build_auth_requests_offline_access_from_zitadel(durable_settings):
    proxy = build_auth(durable_settings)

    registration_options = proxy.client_registration_options
    assert registration_options is not None
    asked = proxy._extra_authorize_params["scope"].split()
    assert "offline_access" in asked
    assert "offline_access" in (registration_options.valid_scopes or [])
    assert "offline_access" not in (proxy.required_scopes or [])
    assert not {s for s in proxy.required_scopes or [] if s.startswith("mcp:")}
    assert {"mcp:tools", "mcp:prompts", "mcp:resources"} <= set(asked)


def test_build_storage_treats_decryption_errors_as_misses(durable_settings):
    store = build_storage(durable_settings)
    assert store.raise_on_decryption_error is False


@pytest.mark.usefixtures("zitadel_discovery")
def test_build_auth_passes_storage_even_in_ephemeral_dev_mode(ephemeral_settings):
    store = MemoryStore()
    with patch("kb_mcp.auth.oidc_proxy.build_storage", return_value=store):
        proxy = build_auth(ephemeral_settings)

    assert proxy._client_storage is store


def test_missing_database_url_raises_instead_of_falling_back(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    # .env.test defaults this to true; override it to hit the "not durable" branch.
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "false")
    get_settings.cache_clear()
    with pytest.raises(Exception, match="OAuth storage is not durable"):
        get_settings()
    get_settings.cache_clear()
