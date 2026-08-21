"""Microsoft Entra auth via FastMCP's AzureProvider with durable state.

This module holds no OAuth code. AzureProvider is a full OAuth 2.1 proxy that owns the authorize
endpoint, PKCE on both hops, redirect callback, token refresh, and On-Behalf-Of exchange. This
service only decides which app registration and state store to use.

The state store is critical, because every token is a reference token re-validated on each request.
The default store is an encrypted file tree in the process's home directory, which logs users out on
each pod restart and breaks at the second replica. Postgres, which this service already runs, makes
the deployment horizontally scalable.
"""

from collections.abc import Sequence

from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_mcp.config import DatabaseConfig, EntraConfig

# Trap: created by the store on first use; database user needs CREATE on schema. No migration
# because columns are the store library's to define and keep in sync.
_OAUTH_TABLE_NAME = "oauth_kv"

# Trap: AzureProvider requires a non-OIDC scope. Entra omits OIDC scopes from `scp` claim, so
# they cannot be enforced. Graph permissions (requested per tool via On-Behalf-Of) are separate.
_REQUIRED_SCOPES = ("access_as_user",)

_ENCRYPTION_SALT = "office-mcp-oauth-storage"


def build_oauth_storage(entra: EntraConfig, database: DatabaseConfig) -> AsyncKeyValue:
    """Durable encrypted OAuth state storage for Entra tokens.

    This store holds users' Entra access tokens and refresh tokens, and stays encrypted even though
    the rows never leave our own database. FastMCP's default store encrypts, so handing it a bare
    table would silently disable at-rest encryption while looking like configuration.

    The client secret is the key material, derived via PBKDF2, so no second secret is needed and
    there is no separate secret-provisioning path. Rotating the secret makes existing rows
    unreadable. Decryption errors are treated as cache misses, so users re-authenticate once instead
    of the server failing.
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
    """Build the auth provider.

    `base_url` must be the externally-reachable URL of this service. OAuth metadata and the
    redirect URI Entra sends browsers to are derived from it. The redirect path is the provider's
    default `/auth/callback`. The app registration must list `{base_url}/auth/callback` exactly,
    as a Web platform redirect URI.

    `client_storage` is passed rather than built here so the readiness probe uses the same object,
    proving the provider's connection to Postgres works. A separate readiness connection would pass
    while the provider's connection fails, masking sign-in outages.

    `graph_scopes` are the Microsoft Graph permissions the tools need. The tools decide them, so
    they arrive from outside rather than being listed here. They ride the authorize request only:
    Entra issues one token per resource (AADSTS28000), so the code exchange asks only for this API's
    own scope, and the Graph ones are redeemed later, per tool call, by the On-Behalf-Of exchange.
    Sending them at authorize time is what makes that possible at all, because OBO can only redeem a
    permission the user or an administrator has already consented to, and a permission that is never
    requested is never consented to.
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
