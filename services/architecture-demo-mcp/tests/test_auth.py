from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr
import pytest

from architecture_demo_mcp.mcp import create_auth
from architecture_demo_mcp.persistence import StoreSettings

ISSUER = "https://zitadel.example.com"
ORG_SCOPE = "urn:zitadel:iam:org:id:123456789"
STORE = StoreSettings(url=SecretStr("redis://localhost:6379/0"), _env_file=None)  # pyright: ignore[reportCallIssue]


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
    assert auth.required_scopes == ["openid", "profile", "urn:zitadel:iam:user:resourceowner"]


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_asks_for_the_organisation_scope_without_registering_it(
    server_settings: ServerSettings,
) -> None:
    zitadel = ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="architecture-demo",
        jwt_signing_key=SecretStr("k" * 32),
        org_id="123456789",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    auth = create_auth(zitadel=zitadel, server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    registration = auth.client_registration_options
    assert registration is not None
    assert ORG_SCOPE not in (auth.required_scopes or [])
    assert ORG_SCOPE not in (registration.valid_scopes or [])
    assert ORG_SCOPE in auth._extra_authorize_params["scope"].split()


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_asks_zitadel_for_a_refresh_token_without_requiring_one(
    server_settings: ServerSettings,
) -> None:
    zitadel = ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="architecture-demo",
        jwt_signing_key=SecretStr("k" * 32),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    auth = create_auth(zitadel=zitadel, server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    registration = auth.client_registration_options
    assert registration is not None
    assert registration.valid_scopes is not None
    assert "offline_access" in auth._extra_authorize_params["scope"].split()
    assert "offline_access" in registration.valid_scopes
    assert "offline_access" not in auth.required_scopes
