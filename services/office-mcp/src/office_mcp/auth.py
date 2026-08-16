"""Microsoft Entra auth via FastMCP's AzureProvider with durable state.

This module holds no OAuth code — AzureProvider is a full OAuth 2.1 proxy that owns the authorize
endpoint, PKCE on both hops, redirect callback, token refresh, and On-Behalf-Of exchange. This
service only decides which app registration and state store to use.

The state store is critical. Every token is a reference token re-validated on each request. The
default store is an encrypted file tree in the process's home directory, which logs users out on
each pod restart and breaks at the second replica. Postgres, which this service already runs, makes
the deployment horizontally scalable.
"""

from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_mcp.config import DatabaseConfig, EntraConfig

# Trap: created by the store on first use; database user needs CREATE on schema. No migration
# because columns are the store library's to define and keep in sync.
_OAUTH_TABLE_NAME = "oauth_kv"

# Trap: AzureProvider requires a non-OIDC scope. Entra omits OIDC scopes from `scp` claim, so
# they cannot be enforced. Graph permissions (requested per tool via On-Behalf-Of) are separate;
# none exist yet.
_REQUIRED_SCOPES = ("access_as_user",)

_ENCRYPTION_SALT = "office-mcp-oauth-storage"


def build_oauth_storage(entra: EntraConfig, database: DatabaseConfig) -> AsyncKeyValue:
    """Durable encrypted OAuth state storage for Entra tokens.

    This store holds users' Entra access tokens and refresh tokens. It stays encrypted even
    though the rows never leave our own database. Encryption is mandatory, not optional. FastMCP's
    default store encrypts. Handing a bare table would disable at-rest encryption silently while
    looking like configuration.

    The client secret is the key material (derived via PBKDF2). No second secret is needed. Rotating
    the secret makes existing rows unreadable. Decryption errors are treated as cache misses, so
    users re-authenticate once instead of the server failing. This trade-off avoids a separate
    secret provisioning path.
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


def build_auth(entra: EntraConfig, base_url: str, client_storage: AsyncKeyValue) -> AzureProvider:
    """Build the auth provider.

    `base_url` must be the externally-reachable URL of this service. OAuth metadata and the
    redirect URI Entra sends browsers to are derived from it. The redirect path is the provider's
    default `/auth/callback`. The app registration must list `{base_url}/auth/callback` exactly,
    as a Web platform redirect URI.

    `client_storage` is passed rather than built here so the readiness probe uses the same object,
    proving the provider's connection to Postgres works. A separate readiness connection would pass
    while the provider's connection fails, masking sign-in outages.
    """
    return AzureProvider(
        client_id=entra.client_id,
        client_secret=entra.client_secret.get_secret_value(),
        tenant_id=entra.tenant_id,
        required_scopes=list(_REQUIRED_SCOPES),
        base_url=base_url,
        client_storage=client_storage,
    )
