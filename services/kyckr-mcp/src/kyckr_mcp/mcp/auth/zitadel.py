from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.protocols import AsyncKeyValue
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from mcp_zitadel import create_zitadel_oidc_proxy


def create_auth(
    *, zitadel: ZitadelSettings, server: ServerSettings, store: AsyncKeyValue
) -> OIDCProxy:
    """Signs users in with Zitadel. The sign-in state is encrypted with the JWT signing key."""
    return create_zitadel_oidc_proxy(
        zitadel=zitadel,
        base_url=server.base_url,
        client_storage=store,
        encryption_salt="kyckr-mcp-sign-in",
    )
