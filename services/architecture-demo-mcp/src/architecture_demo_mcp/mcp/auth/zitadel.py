from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from unique_mcp.auth.zitadel.oidc_proxy import create_zitadel_oidc_proxy
from unique_mcp.auth.zitadel.oidc_proxy import ZitadelOIDCProxySettings
from unique_mcp.auth.zitadel.scopes import ZITADEL_DEFAULT_MCP_SCOPES

from architecture_demo_mcp.mcp.auth.settings import AuthMode
from architecture_demo_mcp.mcp.auth.settings import AuthSettings
from architecture_demo_mcp.persistence import sign_in_store
from architecture_demo_mcp.persistence import StoreSettings


def create_auth(
    *, auth: AuthSettings, server: ServerSettings, store: StoreSettings
) -> OIDCProxy | None:
    """Signs users in with Zitadel, unless `auth` turns sign-in off.

    Requires only the identity scopes: Zitadel drops the `mcp:*` scopes it is asked for, so
    requiring them would reject every token.
    """
    if auth.mode is AuthMode.NONE:
        return None
    zitadel = ZitadelSettings()  # pyright: ignore[reportCallIssue]
    signing_key = zitadel.jwt_signing_key.get_secret_value()
    return create_zitadel_oidc_proxy(
        mcp_server_base_url=server.base_url,
        zitadel_oidc_proxy_settings=ZitadelOIDCProxySettings(
            base_url=zitadel.issuer,
            client_id=zitadel.client_id,
            client_secret=zitadel.client_secret,
            jwt_signing_key=zitadel.jwt_signing_key,
        ),
        # Tokens at rest in Redis are encrypted with a key derived from the signing key, so
        # rotating it signs everyone out, as it would anyway.
        client_storage=FernetEncryptionWrapper(
            key_value=sign_in_store(store),
            source_material=signing_key,
            salt="architecture-demo-mcp-sign-in",
            raise_on_decryption_error=False,
        ),
        verify_id_token=True,
        required_scopes=zitadel.required_scopes,
        extra_authorize_params={
            "scope": " ".join(
                dict.fromkeys([*ZITADEL_DEFAULT_MCP_SCOPES, *zitadel.required_scopes])
            )
        },
    )
