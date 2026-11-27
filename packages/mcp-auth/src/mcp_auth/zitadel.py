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
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl

_IDENTITY_SCOPES = (
    "openid",
    "profile",
    "urn:zitadel:iam:user:resourceowner",
)
# Asked for and registrable. Zitadel drops `mcp:*` from the token, so requiring them rejects
# every sign-in. `offline_access` is what makes Zitadel send a refresh token.
_ADVERTISED_SCOPES = (
    "mcp:tools",
    "mcp:prompts",
    "mcp:resources",
    "mcp:resource-templates",
    "email",
    *_IDENTITY_SCOPES,
    "offline_access",
)
# Asked for when an org id is set, never registered. Zitadel rejects a client that registers it.
_ORG_SCOPE_PREFIX = "urn:zitadel:iam:org:id:"
_ORG_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
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
            org = verified.claims.get(_ORG_CLAIM)
            if org != self._org_id:
                _logger.warning(
                    "Sign-in refused: %s",
                    "token has no org claim" if org is None else "token is for a different org",
                )
                return None
        return verified


def create_zitadel_oidc_proxy(
    *,
    zitadel: ZitadelSettings,
    base_url: str,
    client_storage: AsyncKeyValue,
    encryption_salt: str | None = None,
) -> OIDCProxy:
    """Signs users in with Zitadel from `ZitadelSettings`.

    Identity scopes are required. The advertised scopes are registrable and asked for, and are
    not required. With an org id, that org's scope is asked for and checked on the id token.
    `encryption_salt` encrypts `client_storage` with a key derived from the JWT signing key.
    """
    secret = _client_secret(zitadel)
    store = client_storage
    if encryption_salt:
        store = FernetEncryptionWrapper(
            key_value=client_storage,
            source_material=zitadel.jwt_signing_key.get_secret_value(),
            salt=encryption_salt,
            raise_on_decryption_error=False,
        )
    org_scope = f"{_ORG_SCOPE_PREFIX}{zitadel.org_id}" if zitadel.org_id else None
    authorize = [*_ADVERTISED_SCOPES, *([org_scope] if org_scope else [])]
    return OIDCProxy(
        config_url=zitadel.config_url,
        client_id=zitadel.client_id,
        client_secret=secret,
        base_url=base_url,
        token_endpoint_auth_method="none" if secret is None else "client_secret_post",
        client_storage=store,
        jwt_signing_key=zitadel.jwt_signing_key.get_secret_value(),
        verify_id_token=True,
        token_verifier=_id_token_verifier(zitadel),
        valid_scopes=list(_ADVERTISED_SCOPES),
        extra_authorize_params={"scope": " ".join(authorize)},
    )


def _client_secret(zitadel: ZitadelSettings) -> str | None:
    secret = zitadel.client_secret
    if secret is None:
        return None
    return secret.get_secret_value() or None


def _id_token_verifier(zitadel: ZitadelSettings) -> IdTokenVerifier:
    oidc = OIDCConfiguration.get_oidc_configuration(
        AnyHttpUrl(zitadel.config_url),
        strict=None,
        timeout_seconds=DEFAULT_OIDC_DISCOVERY_TIMEOUT_SECONDS,
    )
    return IdTokenVerifier(
        JWTVerifier(
            jwks_uri=str(oidc.jwks_uri),
            issuer=str(oidc.issuer),
            audience=zitadel.client_id,
        ),
        org_id=zitadel.org_id,
        required_scopes=list(_IDENTITY_SCOPES),
    )


__all__ = ["IdTokenVerifier", "create_zitadel_oidc_proxy"]
