from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.stores.memory import MemoryStore
from mcp_auth.zitadel import create_zitadel_oidc_proxy
from mcp_configs import ZitadelSettings

from tiingo_mcp.settings import AuthMode, Settings


def create_auth(settings: Settings) -> OIDCProxy | None:
    if settings.mcp_auth_mode == AuthMode.NONE:
        return None

    assert settings.zitadel_issuer_url
    assert settings.zitadel_client_id
    assert settings.mcp_jwt_signing_key
    return create_zitadel_oidc_proxy(
        zitadel=ZitadelSettings(
            base_url=settings.zitadel_issuer_url,
            client_id=settings.zitadel_client_id,
            client_secret=None,  # public client with PKCE
            jwt_signing_key=settings.mcp_jwt_signing_key,
            org_id=settings.zitadel_org_id,
        ),
        base_url=settings.base_url,
        # In memory: sessions end with the process. A deployment needs durable storage (see kb-mcp).
        client_storage=MemoryStore(),
        encryption_salt=None,
    )
