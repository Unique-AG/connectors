from fastmcp.server.auth.oidc_proxy import OIDCProxy
import httpx2
from mcp_auth.zitadel import IdTokenVerifier
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr
import pytest

from world_check_mcp.mcp import create_auth
from world_check_mcp.persistence import StoreSettings

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
ORG_SCOPE = "urn:zitadel:iam:org:id:123456789"
STORE = StoreSettings(
    url=SecretStr("postgresql://user:secret@localhost:5432/world_check"),
    _env_file=None,  # pyright: ignore[reportCallIssue]
)


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
    assert create_auth(zitadel=None, server=server_settings, store=None) is None


def _zitadel(org_id: str | None = None) -> ZitadelSettings:
    return ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="world-check",
        jwt_signing_key=SecretStr("k" * 32),
        org_id=org_id,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


def test_create_auth_signs_in_with_identity_scopes_and_verifies_the_id_token(
    server_settings: ServerSettings, zitadel_discovery: list[str]
) -> None:
    auth = create_auth(zitadel=_zitadel(), server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    assert zitadel_discovery == [f"{ISSUER}/.well-known/openid-configuration"]
    assert auth.required_scopes == ["openid", "profile", "urn:zitadel:iam:user:resourceowner"]
    # FastMCP has no public accessor for these; both are pinned by fastmcp's version in uv.lock.
    assert auth._verify_id_token
    assert isinstance(auth._token_validator, IdTokenVerifier)
    assert auth._token_validator._org_id is None


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_asks_for_the_organisation_scope_without_registering_or_requiring_it(
    server_settings: ServerSettings,
) -> None:
    auth = create_auth(zitadel=_zitadel("123456789"), server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    registration = auth.client_registration_options
    assert registration is not None
    assert ORG_SCOPE not in (registration.valid_scopes or [])
    assert ORG_SCOPE not in (auth.required_scopes or [])
    assert ORG_SCOPE in auth._extra_authorize_params["scope"].split()
    assert isinstance(auth._token_validator, IdTokenVerifier)
    assert auth._token_validator._org_id == "123456789"


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_asks_zitadel_for_a_refresh_token_without_requiring_one(
    server_settings: ServerSettings,
) -> None:
    auth = create_auth(zitadel=_zitadel(), server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    registration = auth.client_registration_options
    assert registration is not None
    assert registration.valid_scopes is not None
    assert "offline_access" in auth._extra_authorize_params["scope"].split()
    assert "offline_access" in registration.valid_scopes
    assert "offline_access" not in auth.required_scopes
