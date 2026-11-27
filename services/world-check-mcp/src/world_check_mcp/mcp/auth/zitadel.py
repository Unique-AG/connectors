from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp_auth.zitadel import create_zitadel_oidc_proxy
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings

from world_check_mcp.persistence import sign_in_store
from world_check_mcp.persistence import StoreSettings


def create_auth(
    *, zitadel: ZitadelSettings | None, server: ServerSettings, store: StoreSettings | None
) -> OIDCProxy | None:
    """Signs users in with Zitadel. Without `zitadel`, as with `MCP_AUTH_MODE=none`, it is None.

    The LSEG service account is a separate credential.
    """
    if zitadel is None:
        return None
    assert store is not None, "Zitadel sign-in needs DATABASE_URL"
    return create_zitadel_oidc_proxy(
        zitadel=zitadel,
        base_url=server.base_url,
        client_storage=sign_in_store(store),
        encryption_salt="world-check-mcp-sign-in",
    )
