"""Zitadel OIDC auth wiring for kb-mcp.

Builds mcp_auth's ZitadelSettings from kb's own Settings object instead of letting
the package read ZITADEL_* from the environment — see kb_mcp.settings for why that matters.
"""

from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp_auth.zitadel import create_zitadel_oidc_proxy
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl

from kb_mcp.auth.storage import build_storage
from kb_mcp.settings import Settings


def build_auth(settings: Settings) -> OIDCProxy:
    return create_zitadel_oidc_proxy(
        zitadel=ZitadelSettings(
            base_url=AnyHttpUrl(settings.zitadel_base_url),
            client_id=settings.zitadel_client_id,
            client_secret=None,
            jwt_signing_key=settings.zitadel_jwt_signing_key,
            org_id=None,
            _env_file=None,  # pyright: ignore[reportCallIssue]
        ),
        base_url=settings.base_url.encoded_string(),
        client_storage=build_storage(settings),
    )
