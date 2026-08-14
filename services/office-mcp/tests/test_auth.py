"""What `auth.py` is responsible for, which is not OAuth.

`AzureProvider` implements the protocol and FastMCP tests it; the decisions made here are which
app registration it authenticates against and where its state is kept. The state store is the
part worth pinning down: getting it wrong produces a server that works perfectly on one replica
in development and logs users out unpredictably in production.
"""

from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_mcp.auth import build_auth, build_oauth_storage
from office_mcp.config import DatabaseConfig, EntraConfig

_DATABASE_URL = "postgresql://user:pass@db:5432/office"


def _entra_config() -> EntraConfig:
    return EntraConfig.model_validate(
        {
            "tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
            "client_id": "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061",
            "client_secret": "s3cr3t",
        }
    )


def _database_config(url: str = _DATABASE_URL) -> DatabaseConfig:
    return DatabaseConfig.model_validate({"url": url})


class TestOAuthStorage:
    def test_state_is_encrypted_and_kept_in_postgres_not_on_the_pod(self) -> None:
        """Three decisions in one shape, each of which fails only in production if wrong:

        * Postgres, because FastMCP's default is a file tree under the *process's* home
          directory — it cannot outlive a pod or be shared between replicas;
        * encrypted, because FastMCP encrypts that default store, so handing it a bare table
          would turn at-rest encryption off while looking like mere configuration;
        * decryption errors treated as misses, so rotating the client secret (which is the key
          material) costs each user one re-login instead of making every request raise until
          someone truncates the table by hand.
        """
        storage = build_oauth_storage(_entra_config(), _database_config())

        assert isinstance(storage, FernetEncryptionWrapper)
        assert isinstance(storage.key_value, PostgreSQLStore)
        assert storage.raise_on_decryption_error is False

    def test_the_store_gets_the_driver_dsn_not_the_configured_url(self) -> None:
        """The store hands this string to asyncpg itself, so the configured URL cannot go
        through unrewritten: a `postgresql+asyncpg://` scheme is not one libpq (or asyncpg)
        accepts, and `sslmode=verify` is a name asyncpg raises on. Neither shows up until a user
        logs in.
        """
        database = _database_config(f"{_DATABASE_URL}?sslmode=verify")
        storage = build_oauth_storage(_entra_config(), database)

        assert isinstance(storage, FernetEncryptionWrapper)
        store = storage.key_value
        assert isinstance(store, PostgreSQLStore)
        assert store._url == "postgresql://user:pass@db:5432/office?sslmode=verify-full"  # pyright: ignore[reportPrivateUsage]


_BASE_URL = "https://office-mcp.example"


def _build_auth(entra: EntraConfig | None = None) -> AzureProvider:
    entra = entra or _entra_config()
    return build_auth(
        entra,
        base_url=_BASE_URL,
        client_storage=build_oauth_storage(entra, _database_config()),
    )


class TestAuthProvider:
    def test_the_app_registration_comes_from_config(self) -> None:
        entra = _entra_config()

        provider = _build_auth(entra)

        assert provider.identifier_uri == f"api://{entra.client_id}"

    def test_the_server_gates_access_on_its_own_scope_not_a_graph_one(self) -> None:
        """Entra omits OIDC scopes from `scp`, so the provider requires a custom API scope to
        enforce. Graph permissions are a separate channel, requested by the tools that need
        them — so nothing Graph-shaped should be gating access to the server itself.
        """
        provider = _build_auth()

        assert provider.required_scopes == ["access_as_user"]

    def test_it_uses_the_exact_storage_it_was_given(self) -> None:
        """White-box on purpose: passing `client_storage` is the whole difference between a
        deployment that survives a restart and one that does not, and nothing about the
        provider's public surface reveals which store it ended up with.

        Identity, not just type: `create_app` hands the same object to the readiness probe, so
        a provider that copied or rebuilt its store would leave `/ready` proving a connection
        the provider does not use.
        """
        storage = build_oauth_storage(_entra_config(), _database_config())

        provider = build_auth(_entra_config(), base_url=_BASE_URL, client_storage=storage)

        assert provider._client_storage is storage  # pyright: ignore[reportPrivateUsage]
