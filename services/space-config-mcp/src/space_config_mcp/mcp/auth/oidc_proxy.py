"""Zitadel OIDC auth wiring for space-config-mcp.

Constructs ZitadelOIDCProxySettings explicitly from local AuthSettings instead of
letting it read ZITADEL_* from the environment inside unique_mcp.
"""

from fastmcp.server.auth.oidc_proxy import OIDCProxy
from unique_mcp.auth.zitadel.oidc_proxy import create_zitadel_oidc_proxy
from unique_mcp.auth.zitadel.oidc_proxy import ZitadelOIDCProxySettings
from unique_mcp.auth.zitadel.scopes import ZITADEL_DEFAULT_MCP_SCOPES

from space_config_mcp.mcp.auth.settings import AuthSettings
from space_config_mcp.mcp.auth.storage import build_storage

# Identity only. mcp:* stays advertised via the wrapper, never required —
# RequireAuthMiddleware 403s any scope Zitadel did not grant.
_REQUIRED_SCOPES = [
    "openid",
    "profile",
    "urn:zitadel:iam:user:resourceowner",
]

# Zitadel issues a refresh token only for offline_access, and only to apps
# with the Refresh Token grant.
_AUTHORIZE_SCOPES = [*ZITADEL_DEFAULT_MCP_SCOPES, "offline_access"]


def build_auth(settings: AuthSettings) -> OIDCProxy:
    return create_zitadel_oidc_proxy(
        mcp_server_base_url=settings.public_base_url.encoded_string(),
        zitadel_oidc_proxy_settings=ZitadelOIDCProxySettings(
            base_url=settings.zitadel_base_url,
            client_id=settings.zitadel_client_id,
            client_secret=None,
            jwt_signing_key=settings.zitadel_jwt_signing_key,
        ),
        client_storage=build_storage(settings),
        # Zitadel issues opaque access tokens even when configured for JWT.
        verify_id_token=True,
        required_scopes=list(_REQUIRED_SCOPES),
        # Sent to Zitadel in place of whatever the MCP client asked for.
        extra_authorize_params={"scope": " ".join(_AUTHORIZE_SCOPES)},
        # Advertised and accepted from MCP clients at registration and /authorize.
        valid_scopes=list(_AUTHORIZE_SCOPES),
    )
