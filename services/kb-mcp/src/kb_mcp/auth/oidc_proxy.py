"""Zitadel OIDC auth wiring for kb-mcp.

Constructs ZitadelOIDCProxySettings explicitly from local Settings instead of
letting it read ZITADEL_* from the environment inside unique_mcp — see
kb_mcp.settings for why that matters.
"""

from fastmcp.server.auth.oidc_proxy import OIDCProxy
from unique_mcp.auth.zitadel.oidc_proxy import (
    ZitadelOIDCProxySettings,
    create_zitadel_oidc_proxy,
)
from unique_mcp.auth.zitadel.scopes import ZITADEL_DEFAULT_MCP_SCOPES

from kb_mcp.auth.storage import build_storage
from kb_mcp.settings import Settings

# Identity only. mcp:* stays advertised via the wrapper, never required —
# RequireAuthMiddleware 403s any scope Zitadel did not grant.
_REQUIRED_SCOPES = [
    "openid",
    "profile",
    "urn:zitadel:iam:user:resourceowner",
]

# Zitadel issues a refresh token only for offline_access, and only to an app
# with the Refresh Token grant enabled. Without one, kb-mcp cannot issue its
# own refresh token and the session ends with Zitadel's access token.
_AUTHORIZE_SCOPES = [*ZITADEL_DEFAULT_MCP_SCOPES, "offline_access"]


def build_auth(settings: Settings) -> OIDCProxy:
    return create_zitadel_oidc_proxy(
        mcp_server_base_url=settings.base_url.encoded_string(),
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
        fastmcp_access_token_expiry_seconds=settings.access_token_expires_in_seconds,
        # Zitadel sends no refresh_expires_in, so this always sets the lifetime.
        fallback_refresh_token_expiry_seconds=settings.refresh_token_expires_in_seconds,
    )
