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

from kb_mcp.auth.storage import build_storage
from kb_mcp.settings import Settings

# Identity only. mcp:* stays advertised via the wrapper, never required —
# RequireAuthMiddleware 403s any scope Zitadel did not grant.
_REQUIRED_SCOPES = [
    "openid",
    "profile",
    "urn:zitadel:iam:user:resourceowner",
]


def build_auth(settings: Settings) -> OIDCProxy:
    return create_zitadel_oidc_proxy(
        mcp_server_base_url=settings.base_url.encoded_string(),
        zitadel_oidc_proxy_settings=ZitadelOIDCProxySettings(
            base_url=settings.zitadel_base_url,
            client_id=settings.zitadel_client_id,
            client_secret=None,
            jwt_signing_key=settings.zitadel_jwt_signing_key.get_secret_value(),
        ),
        client_storage=build_storage(settings),
        # Zitadel issues opaque access tokens even when configured for JWT.
        verify_id_token=True,
        required_scopes=list(_REQUIRED_SCOPES),
    )
