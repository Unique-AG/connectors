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

from office_365_mcp.config import DatabaseConfig, EntraConfig

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


def build_auth(
    entra: EntraConfig,
    base_url: str,
    client_storage: AsyncKeyValue,
    graph_scopes: Sequence[str],
) -> AzureProvider:
    """The app registration must list `{base_url}{_CALLBACK_PATH}` exactly, as a Web platform
    redirect URI. `redirect_path` is passed rather than defaulted so that constant is what the
    registration is generated from.

    `client_storage` is passed in so the readiness probe uses the same object. A separate readiness
    connection can report ready while the provider's own connection fails, and that gap hides a
    sign-in outage from the probe.

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
        redirect_path=_CALLBACK_PATH,
        base_url=base_url,
        client_storage=client_storage,
    )
