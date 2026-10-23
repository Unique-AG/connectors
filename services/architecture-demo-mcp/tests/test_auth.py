from fastmcp.server.auth.oidc_proxy import OIDCProxy
import httpx2
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr
import pytest

from architecture_demo_mcp.mcp import create_auth
from architecture_demo_mcp.persistence import StoreSettings

ISSUER = "https://zitadel.example.com"
OIDC_CONFIGURATION = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/oauth/v2/authorize",
    "token_endpoint": f"{ISSUER}/oauth/v2/token",
    "jwks_uri": f"{ISSUER}/oauth/v2/keys",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
}
STORE = StoreSettings(url=SecretStr("redis://localhost:6379/0"), _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def zitadel_discovery(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The discovery URLs the proxy fetched, answered without a network."""
    requested: list[str] = []

    def get(url: str, **_: object) -> httpx2.Response:
        requested.append(url)
        return httpx2.Response(200, json=OIDC_CONFIGURATION, request=httpx2.Request("GET", url))

    monkeypatch.setattr(httpx2, "get", get)
    return requested


def test_create_auth_signs_no_one_in_without_zitadel_settings(
    server_settings: ServerSettings,
) -> None:
    assert create_auth(zitadel=None, server=server_settings, store=STORE) is None


def test_create_auth_signs_in_through_the_zitadel_it_is_given(
    server_settings: ServerSettings, zitadel_discovery: list[str]
) -> None:
    zitadel = ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="architecture-demo",
        jwt_signing_key=SecretStr("k" * 32),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    auth = create_auth(zitadel=zitadel, server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    assert zitadel_discovery == [f"{ISSUER}/.well-known/openid-configuration"]
    assert auth.required_scopes == zitadel.required_scopes
