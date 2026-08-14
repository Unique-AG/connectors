"""Microsoft Entra auth: FastMCP's own Azure provider, pointed at durable state.

There is no OAuth code in this module and there should never be any. `AzureProvider` is a full
OAuth 2.1 proxy — it presents a DCR-capable authorization server to MCP clients and translates it
onto the Entra app registration, so the authorize endpoint, PKCE (enforced on both hops), the
redirect callback, the consent screen, refresh-token rotation and the On-Behalf-Of exchange that
turns a user's token into a Microsoft Graph one are all its own. What is left for this service to
decide is the two things the library cannot know: which app registration to use, and where the
resulting state is kept.

The second one is not a preference. Every token FastMCP issues is a reference token that is
re-validated against this store on every single request, and the default store is an encrypted
file tree under the *process's own* home directory — so on Kubernetes it would log every user out
on each pod restart and fail outright as soon as a second replica served a request. Postgres,
which this service already runs, is what makes the deployment horizontally scalable.
"""

from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_mcp.config import DatabaseConfig, EntraConfig

# Created by the store itself on first use (`auto_create`), so the app's database user needs
# CREATE on its schema. Deliberately not a migration of ours: the columns are the store
# library's to define, and a revision duplicating them would be ours to keep in sync.
_OAUTH_TABLE_NAME = "oauth_kv"

# The custom scope the app registration exposes under its Application ID URI, which is what
# gates access to *this* server. `AzureProvider` refuses to start without at least one non-OIDC
# scope here, because Entra omits OIDC scopes from the `scp` claim and they therefore cannot be
# enforced. Graph permissions are a separate channel and are not listed here: they are requested
# by the tools that need them, via the On-Behalf-Of exchange, and none exist yet.
_REQUIRED_SCOPES = ("access_as_user",)

_ENCRYPTION_SALT = "office-mcp-oauth-storage"


def build_oauth_storage(entra: EntraConfig, database: DatabaseConfig) -> AsyncKeyValue:
    """Durable, encrypted storage for OAuth state.

    Encryption is not optional here even though the rows never leave our own database: this
    store holds users' upstream Entra access tokens and refresh-token material, and FastMCP
    encrypts its *default* store — so handing it a bare table would quietly turn at-rest
    encryption off while looking like pure configuration.

    The client secret doubles as the key material (the wrapper derives the key with PBKDF2), so
    there is no second secret for an operator to provision, lose, or leave out of a replica. The
    cost of that choice is that rotating the client secret makes the existing rows unreadable —
    which is why decryption errors are treated as cache misses: users re-authenticate once
    instead of the server failing every request until the table is cleared by hand.
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
    """The auth provider — `create_app` is its only caller.

    `base_url` must be the externally-reachable URL of this service: the OAuth metadata clients
    discover, and the redirect URI Entra sends the browser back to, are both derived from it. The
    redirect path is the provider's default, `/auth/callback`, and the app registration must list
    `{base_url}/auth/callback` verbatim as a Web platform redirect URI.

    `client_storage` is what `build_oauth_storage` returns, taken as an argument rather than
    built here: the readiness probe answers by reading through the very same object, so that a
    200 means *this* provider's store can reach Postgres and not merely that some second
    connection resembling it could.
    """
    return AzureProvider(
        client_id=entra.client_id,
        client_secret=entra.client_secret.get_secret_value(),
        tenant_id=entra.tenant_id,
        required_scopes=list(_REQUIRED_SCOPES),
        base_url=base_url,
        client_storage=client_storage,
    )
