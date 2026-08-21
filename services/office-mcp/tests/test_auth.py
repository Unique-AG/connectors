"""What `auth.py` is responsible for, which is not OAuth.

`AzureProvider` implements the protocol and FastMCP tests it. What is decided here is which app
registration it authenticates against and where its state is kept. Get the state store wrong and
the server works on one replica in development and logs users out unpredictably in production.
"""

from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from office_mcp.auth import build_auth, build_oauth_storage
from office_mcp.config import DatabaseConfig, EntraConfig

_DATABASE_URL = "postgresql://user:pass@db:5432/office"

_GRAPH_SCOPES = ("https://graph.microsoft.com/User.Read",)


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
        """Three decisions, each of which fails only in production if wrong:

        * Postgres, because FastMCP's default is a file tree under the *process's* home
          directory. That tree cannot outlive a pod or be shared between replicas.
        * Encrypted, because FastMCP encrypts that default store. A bare table would turn
          at-rest encryption off while looking like configuration.
        * Decryption errors treated as misses, so rotating the client secret (the key material)
          costs each user one re-login instead of raising on every request until someone
          truncates the table by hand.
        """
        storage = build_oauth_storage(_entra_config(), _database_config())

        assert isinstance(storage, FernetEncryptionWrapper)
        assert isinstance(storage.key_value, PostgreSQLStore)
        assert storage.raise_on_decryption_error is False

    def test_the_store_gets_the_driver_dsn_not_the_configured_url(self) -> None:
        """The store hands this string to asyncpg itself, so the configured URL has to be
        rewritten: neither libpq nor asyncpg accepts a `postgresql+asyncpg://` scheme, and
        asyncpg raises on `sslmode=verify`. Neither failure shows up until a user logs in.
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
        graph_scopes=_GRAPH_SCOPES,
    )


class TestAuthProvider:
    def test_the_app_registration_comes_from_config(self) -> None:
        entra = _entra_config()

        provider = _build_auth(entra)

        assert provider.identifier_uri == f"api://{entra.client_id}"

    def test_the_server_gates_access_on_its_own_scope_not_a_graph_one(self) -> None:
        """Entra omits OIDC scopes from `scp`, so the provider requires a custom API scope to
        enforce. Graph permissions ride the separate channel tested below. A Graph scope among
        the required ones would be validated on every token and fail every request, because this
        API's tokens never carry Graph permissions.
        """
        provider = _build_auth()

        assert provider.required_scopes == ["access_as_user"]

    def test_the_graph_permissions_ride_the_authorize_request(self) -> None:
        """Without this, sign-in never asks for Graph consent and the On-Behalf-Of exchange each
        tool performs fails with AADSTS65001. That failure happens per tool call, long after the
        sign-in that would have fixed it, and no tool can explain it to its caller.

        Containment, not equality: the provider adds `offline_access` to this list itself, and
        that is not something this service should pin.
        """
        provider = _build_auth()

        assert set(_GRAPH_SCOPES) <= set(provider.additional_authorize_scopes)
        assert not set(_GRAPH_SCOPES) & set(provider.required_scopes)

    def test_it_uses_the_exact_storage_it_was_given(self) -> None:
        """White-box on purpose: `client_storage` is the difference between a deployment that
        survives a restart and one that does not, and the provider's public surface does not
        reveal which store it kept.

        Identity, not just type: `create_app` hands the same object to the readiness probe, so a
        provider that copied or rebuilt its store would leave `/ready` proving a connection the
        provider does not use.
        """
        storage = build_oauth_storage(_entra_config(), _database_config())

        provider = build_auth(
            _entra_config(),
            base_url=_BASE_URL,
            client_storage=storage,
            graph_scopes=_GRAPH_SCOPES,
        )

        assert provider._client_storage is storage  # pyright: ignore[reportPrivateUsage]
