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


def build_auth(settings: Settings) -> OIDCProxy:
    return create_zitadel_oidc_proxy(
        mcp_server_base_url=settings.base_url.encoded_string(),
        zitadel_oidc_proxy_settings=ZitadelOIDCProxySettings(
            base_url=settings.zitadel_base_url,
            client_id=settings.zitadel_client_id,
            client_secret=settings.zitadel_client_secret.get_secret_value(),
        ),
        client_storage=build_storage(settings),
        # Zitadel often issues opaque (non-JWT) access tokens even when the app
        # is configured for JWT. Verify the OIDC id_token instead so the
        # token-swap after /token succeeds; otherwise every /mcp call returns
        # invalid_token despite a successful login.
        verify_id_token=True,
        # OIDCProxy's docstring warns required_scopes causes an invalid_token
        # loop — stale for verify_id_token=True: FastMCP only wires
        # required_scopes into the JWT verifier when verify_id_token=False.
        # With verify_id_token=True it withholds them from the verifier (id
        # tokens carry no scope claim) and instead records them as
        # self.required_scopes + calls update_default_scopes for us
        # (fastmcp.server.auth.oidc_proxy.OIDCProxy.__init__).
        required_scopes=list(ZITADEL_DEFAULT_MCP_SCOPES),
    )
