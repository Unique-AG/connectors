from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp_auth.zitadel import create_zitadel_oidc_proxy
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from architecture_demo_mcp.persistence import sign_in_store
from architecture_demo_mcp.persistence import StoreSettings


def create_auth(
    *, zitadel: ZitadelSettings | None, server: ServerSettings, store: StoreSettings
) -> OIDCProxy | None:
    """Signs users in with Zitadel. Without `zitadel`, as with `MCP_AUTH_MODE=none`, it is None."""
    if zitadel is None:
        return None
    return create_zitadel_oidc_proxy(
        zitadel=zitadel,
        base_url=server.base_url,
        client_storage=sign_in_store(store),
        encryption_salt="architecture-demo-mcp-sign-in",
    )
