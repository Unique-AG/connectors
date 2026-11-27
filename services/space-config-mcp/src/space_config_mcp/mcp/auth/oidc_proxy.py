from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp_auth.zitadel import create_zitadel_oidc_proxy
from mcp_configs import ZitadelSettings

from space_config_mcp.mcp.auth.settings import AuthSettings
from space_config_mcp.mcp.auth.storage import build_storage


def build_auth(settings: AuthSettings) -> OIDCProxy:
    return create_zitadel_oidc_proxy(
        zitadel=ZitadelSettings(
            base_url=settings.zitadel_base_url,
            client_id=settings.zitadel_client_id,
            client_secret=None,
            jwt_signing_key=settings.zitadel_jwt_signing_key,
            org_id=None,
        ),
        base_url=settings.public_base_url.encoded_string(),
        client_storage=build_storage(settings),
        encryption_salt=None,
    )
