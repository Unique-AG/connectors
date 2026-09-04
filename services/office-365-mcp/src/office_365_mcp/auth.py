"""Microsoft Entra auth via FastMCP's AzureProvider with durable state.

Trap: the default state store is an encrypted file tree in the process's home directory. Every
token is a reference token re-validated on each request, so that store logs users out on every pod
restart and breaks outright at the second replica.

`ENTRA_TENANT_ID=organizations` invalidates two things the stock provider derives from `tenant_id`:
no token carries the `.../organizations/v2.0` issuer it expects, and On-Behalf-Of must name the
tenant that issued the assertion. FastMCP's `AzureJWTVerifier` answers the first by skipping the
issuer check for these authorities, leaving the audience as the only gate;
`OrganizationsAzureProvider` applies Microsoft's rule instead — `tid` is a GUID, `iss` is that
tenant's issuer — and runs OBO on `tid`.
"""

import hashlib
import logging
import re
from collections.abc import Mapping, Sequence
from typing import TypedDict, Unpack, final, override

from azure.identity.aio import OnBehalfOfCredential
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.utilities.auth import decode_jwt_payload
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_365_mcp.config import ORGANIZATIONS, DatabaseConfig, EntraConfig

logger = logging.getLogger(__name__)

# Trap: created by the store on first use, so the database user needs CREATE on schema. No
# migration: the columns are the store library's to define and keep in sync.
_OAUTH_TABLE_NAME = "oauth_kv"

# Trap: AzureProvider requires a non-OIDC scope. Entra omits OIDC scopes from the `scp` claim, so
# they cannot be enforced. Graph permissions are separate, redeemed per tool call by On-Behalf-Of.
_REQUIRED_SCOPES = ("access_as_user",)

_ENCRYPTION_SALT = "office-365-mcp-oauth-storage"

# Passed to the provider rather than left to its default, because the Entra module's registry is
# generated from this constant. A library default is a path the app registration carries, with no
# Python name for the registry to read.
_CALLBACK_PATH = "/auth/callback"

# Public cloud, hardcoded: `AzureProvider.base_authority` selects a sovereign cloud instead,
# and a token's issuer is compared against this verbatim.
_ENTRA_AUTHORITY = "login.microsoftonline.com"

# Entra spells `tid` and the tenant segment of `iss` the same way, so the issuer is matched with the
# `tid` as written rather than case-folded.
_TENANT_GUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def build_oauth_storage(entra: EntraConfig, database: DatabaseConfig) -> AsyncKeyValue:
    """Trap: FastMCP's default store encrypts. Handing it a bare table silently disables at-rest
    encryption while looking like valid configuration. The key material is the client secret via
    PBKDF2, so rotating that secret makes every existing row unreadable. A decryption error is then
    treated as a cache miss, and the user signs in again.
    """
    return FernetEncryptionWrapper(
        key_value=PostgreSQLStore(
            url=database.driver_dsn,
            table_name=_OAUTH_TABLE_NAME,
            auto_create=True,
        ),
        source_material=entra.client_secret.get_secret_value(),
        salt=_ENCRYPTION_SALT,
        raise_on_decryption_error=False,
    )


def tenant_issuer(tenant_id: str) -> str:
    return f"https://{_ENTRA_AUTHORITY}/{tenant_id}/v2.0"


def home_tenant(claims: Mapping[str, object]) -> str | None:
    """Microsoft's rule for a multi-tenant app: `tid` is a GUID, `iss` is that tenant's issuer."""
    tid = claims.get("tid")
    if not isinstance(tid, str) or _TENANT_GUID.fullmatch(tid) is None:
        return None
    if claims.get("iss") != tenant_issuer(tid):
        return None
    return tid


class TenantBoundJWTVerifier(JWTVerifier):
    """The provider's own verifier, with `home_tenant` in place of the single-issuer check."""

    def __init__(self, stock: JWTVerifier) -> None:
        super().__init__(
            public_key=stock.public_key,
            jwks_uri=stock.jwks_uri,
            issuer=None,
            audience=stock.audience,
            algorithm=stock.algorithm,
            required_scopes=stock.required_scopes,
            base_url=stock.base_url,
            ssrf_safe=stock.ssrf_safe,
            http_client=stock._http_client,
        )

    @override
    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = await super().load_access_token(token)
        if access_token is None:
            return None
        if home_tenant(access_token.claims) is None:
            logger.warning(
                "Bearer token rejected for client %s: issuer %r is not tenant %r's",
                access_token.client_id,
                access_token.claims.get("iss"),
                access_token.claims.get("tid"),
            )
            return None
        return access_token


class _Registration(TypedDict):
    client_id: str
    client_secret: str
    required_scopes: list[str]
    additional_authorize_scopes: list[str]
    redirect_path: str
    base_url: str
    client_storage: AsyncKeyValue


@final
class OrganizationsAzureProvider(AzureProvider):
    """`AzureProvider` for `organizations`: tenant-bound verification and OBO."""

    def __init__(self, **registration: Unpack[_Registration]) -> None:
        super().__init__(tenant_id=ORGANIZATIONS, **registration)
        stock = self._token_validator
        assert isinstance(stock, JWTVerifier), (
            f"AzureProvider validates tokens with {type(stock).__name__}, not a JWTVerifier"
        )
        self._token_validator = TenantBoundJWTVerifier(stock)

    @override
    async def get_obo_credential(self, user_assertion: str) -> OnBehalfOfCredential:
        """Copied: the parent binds the credential to `self._tenant_id`, `organizations` here."""
        key = hashlib.sha256(user_assertion.encode()).hexdigest()
        cached = self._obo_credentials.get(key)
        if cached is not None:
            self._obo_credentials.move_to_end(key)
            return cached

        tenant_id = home_tenant(decode_jwt_payload(user_assertion))
        assert tenant_id is not None, "the verifier accepted a token that binds no tenant"
        assert self._upstream_client_secret is not None, "EntraConfig requires a client secret"
        credential = OnBehalfOfCredential(
            tenant_id=tenant_id,
            client_id=self._upstream_client_id,
            user_assertion=user_assertion,
            client_secret=self._upstream_client_secret.get_secret_value(),
            authority=f"https://{self._base_authority}",
        )
        self._obo_credentials[key] = credential
        while len(self._obo_credentials) > self._obo_max_credentials:
            _, evicted = self._obo_credentials.popitem(last=False)
            await evicted.close()
        return credential


def build_auth(
    entra: EntraConfig,
    base_url: str,
    client_storage: AsyncKeyValue,
    graph_scopes: Sequence[str],
) -> AzureProvider:
    """The app registration must list `{base_url}{_CALLBACK_PATH}` exactly, as a Web redirect URI.

    Entra issues one token per resource (AADSTS28000), so `graph_scopes` ride the authorize request
    only and are redeemed per tool call by On-Behalf-Of. `client_storage` is the readiness probe's
    connection too, or the probe reports ready while sign-in fails.
    """
    registration = _Registration(
        client_id=entra.client_id,
        client_secret=entra.client_secret.get_secret_value(),
        required_scopes=list(_REQUIRED_SCOPES),
        additional_authorize_scopes=list(graph_scopes),
        redirect_path=_CALLBACK_PATH,
        base_url=base_url,
        client_storage=client_storage,
    )
    if entra.multi_tenant:
        return OrganizationsAzureProvider(**registration)
    return AzureProvider(tenant_id=entra.tenant_id, **registration)
