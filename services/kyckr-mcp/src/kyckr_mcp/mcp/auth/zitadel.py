import logging
from typing import override

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.oidc_proxy import DEFAULT_OIDC_DISCOVERY_TIMEOUT_SECONDS
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl
from unique_mcp.auth.zitadel.oidc_proxy import create_zitadel_oidc_proxy
from unique_mcp.auth.zitadel.oidc_proxy import ZitadelOIDCProxySettings
from unique_mcp.auth.zitadel.scopes import ZITADEL_DEFAULT_MCP_SCOPES

# Zitadel adds it for the `urn:zitadel:iam:user:resourceowner` scope, which every sign-in asks for.
ORG_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
_ORG_SCOPE = "urn:zitadel:iam:org:id:"
_OFFLINE_ACCESS = "offline_access"
_logger = logging.getLogger(__name__)


class IdTokenVerifier(TokenVerifier):
    """`verifier` plus, with `org_id`, a check that the user is in that org: no claim, no access.
    `required_scopes` is the floor FastMCP checks on its own tokens, never on the id token.
    """

    _verifier: TokenVerifier
    _org_id: str | None

    def __init__(
        self, verifier: TokenVerifier, *, org_id: str | None, required_scopes: list[str]
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self._verifier = verifier
        self._org_id = org_id

    @override
    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await self._verifier.verify_token(token)
        if verified is None:
            return None
        if self._org_id is not None:
            org = verified.claims.get(ORG_CLAIM)
            if org != self._org_id:
                _logger.warning(
                    "Sign-in refused: %s",
                    "token has no org claim" if org is None else "token is for a different org",
                )
                return None
        return verified


def create_auth(
    *, zitadel: ZitadelSettings, server: ServerSettings, store: AsyncKeyValue
) -> OIDCProxy:
    """Signs users in with Zitadel. Clients may register identity scopes and `offline_access`. With
    an org id the proxy also asks Zitadel for the org scope, never registered, and checks the token.
    """
    signing_key = zitadel.jwt_signing_key.get_secret_value()
    # Zitadel sends a refresh token only for `offline_access`: asked for and registrable, never
    # required, since a required scope is checked on every token. The org scope is only asked for.
    registrable = [*ZITADEL_DEFAULT_MCP_SCOPES, _OFFLINE_ACCESS]
    return create_zitadel_oidc_proxy(
        mcp_server_base_url=server.base_url,
        zitadel_oidc_proxy_settings=ZitadelOIDCProxySettings(
            base_url=zitadel.issuer,
            client_id=zitadel.client_id,
            client_secret=zitadel.client_secret,
            jwt_signing_key=zitadel.jwt_signing_key,
        ),
        # Tokens at rest in Postgres are encrypted with a key derived from the signing key, so
        # rotating it signs everyone out, as it would anyway.
        client_storage=FernetEncryptionWrapper(
            key_value=store,
            source_material=signing_key,
            salt="kyckr-mcp-sign-in",
            raise_on_decryption_error=False,
        ),
        verify_id_token=True,
        token_verifier=_id_token_verifier(zitadel),
        valid_scopes=registrable,
        extra_authorize_params={
            "scope": " ".join(dict.fromkeys([*registrable, *zitadel.required_scopes]))
        },
    )


def _id_token_verifier(zitadel: ZitadelSettings) -> IdTokenVerifier:
    """The verifier `OIDCProxy(verify_id_token=True)` builds itself, plus the org check."""
    oidc = OIDCConfiguration.get_oidc_configuration(
        AnyHttpUrl(zitadel.config_url),
        strict=None,
        timeout_seconds=DEFAULT_OIDC_DISCOVERY_TIMEOUT_SECONDS,
    )
    return IdTokenVerifier(
        JWTVerifier(
            jwks_uri=str(oidc.jwks_uri), issuer=str(oidc.issuer), audience=zitadel.client_id
        ),
        org_id=zitadel.org_id,
        required_scopes=[
            scope for scope in zitadel.required_scopes if not scope.startswith(_ORG_SCOPE)
        ],
    )
