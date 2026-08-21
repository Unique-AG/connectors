"""Microsoft Entra auth via FastMCP's AzureProvider with durable state.

Trap: the default state store is an encrypted file tree in the process's home directory. Every
token is a reference token re-validated on each request, so that store logs users out on every pod
restart and breaks outright at the second replica.
"""

from collections.abc import Sequence

from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_mcp.config import DatabaseConfig, EntraConfig

# Trap: created by the store on first use, so the database user needs CREATE on schema. No
# migration: the columns are the store library's to define and keep in sync.
_OAUTH_TABLE_NAME = "oauth_kv"

# Trap: AzureProvider requires a non-OIDC scope. Entra omits OIDC scopes from the `scp` claim, so
# they cannot be enforced. Graph permissions are separate, redeemed per tool call by On-Behalf-Of.
_REQUIRED_SCOPES = ("access_as_user",)

_ENCRYPTION_SALT = "office-mcp-oauth-storage"


def build_oauth_storage(entra: EntraConfig, database: DatabaseConfig) -> AsyncKeyValue:
    """Trap: FastMCP's default store encrypts, so handing it a bare table would silently disable
    at-rest encryption while looking like configuration. The key material is the client secret via
    PBKDF2, so rotating that secret makes every existing row unreadable; a decryption error is then
    treated as a cache miss and the user signs in again.
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


def build_auth(
    entra: EntraConfig,
    base_url: str,
    client_storage: AsyncKeyValue,
    graph_scopes: Sequence[str],
) -> AzureProvider:
    """The app registration must list `{base_url}/auth/callback` exactly, as a Web platform
    redirect URI; that path is the provider's default.

    `client_storage` is passed in so the readiness probe uses the same object: a separate readiness
    connection would pass while the provider's own fails, masking a sign-in outage.

    `graph_scopes` ride the authorize request only. Entra issues one token per resource
    (AADSTS28000), so the code exchange asks for this API's own scope and the Graph ones are
    redeemed per tool call by On-Behalf-Of, which can only redeem a permission already consented to.
    """
    return AzureProvider(
        client_id=entra.client_id,
        client_secret=entra.client_secret.get_secret_value(),
        tenant_id=entra.tenant_id,
        required_scopes=list(_REQUIRED_SCOPES),
        additional_authorize_scopes=list(graph_scopes),
        base_url=base_url,
        client_storage=client_storage,
    )
