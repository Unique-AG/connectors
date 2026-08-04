from __future__ import annotations

from fastmcp.server.auth.oidc_proxy import OIDCProxy

from q_bridge_mcp.auth.storage import create_storage
from q_bridge_mcp.config.settings import settings

REQUIRED_SCOPES = [
    "openid",
    "profile",
    "urn:zitadel:iam:user:resourceowner",
]


def setup_auth() -> OIDCProxy:
    return OIDCProxy(
        config_url=settings.zitadel_openid_configuration,
        client_id=settings.zitadel_client_id,
        client_secret=settings.zitadel_client_secret.get_secret_value(),
        base_url=str(settings.mcp_base_url),
        jwt_signing_key=settings.mcp_jwt_signing_key.get_secret_value(),
        client_storage=create_storage(),
        required_scopes=REQUIRED_SCOPES,
        verify_id_token=True,
        strict=True,
    )
