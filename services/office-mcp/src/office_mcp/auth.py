"""Microsoft Entra auth via FastMCP's AzureProvider with durable Postgres storage."""

from collections.abc import Sequence

from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_mcp.config import DatabaseConfig, EntraConfig

_OAUTH_TABLE_NAME = "oauth_kv"

# Trap: oauth_kv is created by the store on first use. Database user needs CREATE on schema.
# No migration file exists; this is intentional.

# Trap: AzureProvider needs a non-OIDC scope. Entra omits OIDC scopes from scp claim.
_REQUIRED_SCOPES = ("access_as_user",)

_ENCRYPTION_SALT = "office-mcp-oauth-storage"


def build_oauth_storage(entra: EntraConfig, database: DatabaseConfig) -> AsyncKeyValue:
    """Create encrypted OAuth storage in Postgres. The client secret is the encryption key.

    Encryption is mandatory, not optional. A bare table would disable at-rest encryption
    silently while still looking like configuration. The key is derived from the client secret,
    so no second secret is needed. Rotating the secret makes existing rows unreadable: a
    decryption error is treated as a cache miss, so each user signs in once more instead of the
    server failing.
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
    """Create the auth provider. base_url must be the externally-reachable service URL.

    Trap: graph_scopes must include every permission any tool will need. Entra issues one token
    per resource, so the code exchange asks only for this service's scope. Graph permissions are
    redeemed per tool call via On-Behalf-Of. A permission never requested at authorize time cannot
    be consented to, so the exchange later fails.
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
