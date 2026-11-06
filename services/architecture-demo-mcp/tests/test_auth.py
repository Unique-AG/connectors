from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr

from architecture_demo_mcp.mcp import create_auth
from architecture_demo_mcp.persistence import StoreSettings

ISSUER = "https://zitadel.example.com"
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
    assert auth.required_scopes == zitadel.required_scopes
