from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.stores.memory import MemoryStore
from unique_mcp.auth.zitadel.oidc_proxy import (
    ZitadelOIDCProxySettings,
    create_zitadel_oidc_proxy,
)
from unique_mcp.auth.zitadel.scopes import ZITADEL_DEFAULT_MCP_SCOPES

from tiingo_mcp.settings import AuthMode, Settings

# Identity only: Zitadel drops the mcp:* scopes, so requiring them would reject every token.
_REQUIRED_SCOPES = ["openid", "profile", "urn:zitadel:iam:user:resourceowner"]


def create_auth(settings: Settings) -> OIDCProxy | None:
    if settings.mcp_auth_mode == AuthMode.NONE:
        return None

    assert settings.zitadel_issuer_url
    assert settings.zitadel_client_id
    assert settings.mcp_jwt_signing_key
    required = list(_REQUIRED_SCOPES)
    authorize_scopes = list(ZITADEL_DEFAULT_MCP_SCOPES)
    if settings.zitadel_org_id:
        org_scope = f"urn:zitadel:iam:org:id:{settings.zitadel_org_id}"
        required.append(org_scope)
        authorize_scopes.append(org_scope)

    return create_zitadel_oidc_proxy(
        mcp_server_base_url=settings.base_url,
        zitadel_oidc_proxy_settings=ZitadelOIDCProxySettings(
            base_url=str(settings.zitadel_issuer_url).rstrip("/"),
            client_id=settings.zitadel_client_id,
            client_secret=None,  # public client with PKCE, as in kb-mcp
            jwt_signing_key=settings.mcp_jwt_signing_key,
        ),
        # In memory: sessions end with the process. A deployment needs durable storage (see kb-mcp).
        client_storage=MemoryStore(),
        verify_id_token=True,
        required_scopes=required,
        extra_authorize_params={"scope": " ".join(authorize_scopes)},
    )
