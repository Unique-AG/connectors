"""The composition root, exercised as a real ASGI app.

Checks that the app starts, its lifespan runs, the process-health routes behave, and that Entra
auth is actually mounted and enforced. No Microsoft Graph client and no tools yet.

Nothing here reaches Entra: constructing the provider performs no I/O, and the assertions below
only touch metadata this service serves itself plus one unauthenticated request that is rejected
before any upstream call would happen.
"""

import importlib
import os
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Protocol, cast, final, override
from unittest.mock import MagicMock

import pytest
from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.base import BaseWrapper
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from starlette.applications import Starlette
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

import office_mcp.app as app_module
from office_mcp.app import create_app
from office_mcp.auth import build_auth, build_oauth_storage
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig

_PUBLIC_BASE_URL = "https://office-mcp.example"


def _entra_config() -> EntraConfig:
    return EntraConfig.model_validate(
        {
            "tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
            "client_id": "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061",
            "client_secret": "s3cr3t",
        }
    )


# `starlette.testclient` returns httpx responses that this repo's strict type-checking sees as
# partially unknown. Narrowed once here, so every assertion below is checked rather than
# silently `Any`.
class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...
    def json(self) -> dict[str, object]: ...


def _get(client: TestClient, path: str) -> _HttpResponse:
    return cast("_HttpResponse", client.get(path))  # pyright: ignore[reportUnknownMemberType]


def _checks(body: dict[str, object]) -> dict[str, object]:
    """The `checks` sub-object of a `/ready` body, narrowed for assertion."""
    checks = body["checks"]
    assert isinstance(checks, dict), f"expected a checks object, got {checks!r}"
    return cast("dict[str, object]", checks)


@pytest.fixture
def app_client(postgres_container: PostgresContainer) -> Iterator[TestClient]:
    """The real app, with its lifespan run."""
    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    app = create_app(
        config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
        database_config=DatabaseConfig.model_validate({"url": url}),
        entra_config=_entra_config(),
    )
    with TestClient(app) as client:
        yield client


class TestRoutes:
    def test_health_is_unauthenticated(self, app_client: TestClient) -> None:
        response = _get(app_client, "/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_probe_is_process_up(self, app_client: TestClient) -> None:
        """`setup_ops` `/probe` is liveness-style; Postgres readiness lives on `/ready`."""
        response = _get(app_client, "/probe")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready_reports_the_checks_it_ran(self, app_client: TestClient) -> None:
        response = _get(app_client, "/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert _checks(body)["database"] is True

    def test_metrics_is_served(self, app_client: TestClient) -> None:
        response = _get(app_client, "/metrics")

        assert response.status_code == 200


class TestAuthIsMountedAndEnforced:
    """Auth is the reason this service has a public base URL at all."""

    def test_the_mcp_endpoint_rejects_an_unauthenticated_call(self, app_client: TestClient) -> None:
        response = _get(app_client, "/mcp")

        assert response.status_code == 401

    def test_discovery_advertises_this_service_as_the_issuer(self, app_client: TestClient) -> None:
        """Clients find the authorization endpoints through this document, so a wrong issuer
        sends them somewhere unreachable — the failure `AppConfig` guards the base URL for."""
        response = _get(app_client, "/.well-known/oauth-authorization-server")

        assert response.status_code == 200
        metadata = response.json()
        assert metadata["issuer"] == f"{_PUBLIC_BASE_URL}/"
        assert metadata["authorization_endpoint"] == f"{_PUBLIC_BASE_URL}/authorize"
        assert metadata["token_endpoint"] == f"{_PUBLIC_BASE_URL}/token"

    def test_the_protected_resource_metadata_is_served(self, app_client: TestClient) -> None:
        response = _get(app_client, "/.well-known/oauth-protected-resource/mcp")

        assert response.status_code == 200


@final
class _ProbeRecordingStorage(BaseWrapper):
    """The OAuth state store, counting the reads made through it.

    A pass-through wrapper rather than a fake: the readiness probe has to reach the real
    `PostgreSQLStore` underneath, or the test would prove nothing about Postgres.
    """

    def __init__(self, key_value: AsyncKeyValue) -> None:
        self.key_value = key_value
        self.reads = 0

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, object] | None:
        self.reads += 1
        value = await self.key_value.get(key, collection=collection)
        return cast("dict[str, object] | None", value)


class TestReadyProbesTheConnectionSignInDependsOn:
    """`/ready` must prove the connection production uses, which is the OAuth store's.

    The store hands its DSN to asyncpg itself and takes no connect args, so a probe that opened
    a connection of its own — configured by any other route, as this one once was — negotiates
    TLS by another route entirely and can answer 200 while every sign-in fails. The pod then
    reports ready and nobody can log in.
    """

    def test_ready_reads_through_the_store_the_auth_provider_was_given(
        self, postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fails if the probe opens a connection of its own (no read reaches the store), and
        fails if the provider is handed a different store than the one probed."""
        url = postgres_container.get_connection_url().replace("+psycopg2", "")
        database_config = DatabaseConfig.model_validate({"url": url})
        entra_config = _entra_config()
        # A fresh recorder per call, so building a *second* store — one that would connect on
        # its own behind the provider's back — is visible as a second entry rather than
        # silently answering as the first.
        built: list[_ProbeRecordingStorage] = []
        provider_was_given: list[AsyncKeyValue] = []

        def _storage(entra: EntraConfig, database: DatabaseConfig) -> AsyncKeyValue:
            storage = _ProbeRecordingStorage(build_oauth_storage(entra, database))
            built.append(storage)
            return storage

        def _auth(
            entra: EntraConfig, base_url: str, client_storage: AsyncKeyValue
        ) -> AzureProvider:
            provider_was_given.append(client_storage)
            return build_auth(entra, base_url=base_url, client_storage=client_storage)

        monkeypatch.setattr(app_module, "build_oauth_storage", _storage)
        monkeypatch.setattr(app_module, "build_auth", _auth)
        app = create_app(
            config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
            database_config=database_config,
            entra_config=entra_config,
        )

        assert built, "create_app must build the OAuth state store"
        with TestClient(app) as client:
            reads_before = built[0].reads
            response = _get(client, "/ready")

        assert response.status_code == 200
        assert len(built) == 1, (
            "the OAuth store must be built once, at the composition root — a second one is a "
            "second connection pool, and probing it proves nothing about the provider's"
        )
        assert provider_was_given == [built[0]], (
            "the auth provider must be handed the same store /ready probes"
        )
        assert built[0].reads == reads_before + 1, (
            "/ready must ask the OAuth store itself — a probe on a connection of its own "
            "reports on something no sign-in uses"
        )

    def test_the_probed_store_carries_the_asyncpg_dsn(self) -> None:
        """And the same DSN, not merely the same database: `driver_dsn` is what asyncpg parses,
        carrying the `sslmode` that decides whether this connection is encrypted at all."""
        database_config = DatabaseConfig.model_validate(
            {"url": "postgresql://user:pass@db:5432/office?sslmode=verify"}
        )

        storage = build_oauth_storage(_entra_config(), database_config)

        assert isinstance(storage, FernetEncryptionWrapper)
        store = storage.key_value
        assert isinstance(store, PostgreSQLStore)
        assert store._url == database_config.driver_dsn  # pyright: ignore[reportPrivateUsage]


class TestReadyReportsDatabaseUnreachable:
    def test_ready_is_503_when_postgres_is_unreachable(self) -> None:
        app = create_app(
            config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
            database_config=DatabaseConfig.model_validate(
                {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
            ),
            entra_config=_entra_config(),
        )
        with TestClient(app) as client:
            response = _get(client, "/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert _checks(body)["database"] is False


# `office_mcp.main` is a module, not a class, so pyright sees every attribute access on it as
# `Any` unless narrowed. This describes just the surface `TestMainEntrypoint` touches.
class _MainModule(Protocol):
    app: Starlette
    uvicorn: ModuleType
    main: Callable[[], None]
    _config: AppConfig


@pytest.fixture
def main_module() -> Iterator[_MainModule]:
    """Import `office_mcp.main`, containing its `load_dotenv()` module-level side effect.

    `office_mcp.main` calls `load_dotenv()` at import time — right for an operator launching the
    process, but it would otherwise push this service's local `.env` into `os.environ` for the
    rest of the test session the first time anything imports this module. The module is only
    ever exec'd once per process, so the whole environment — not just the handful of vars `.env`
    sets — is snapshotted and restored around that one import.
    """
    environment_before = os.environ.copy()
    try:
        # Importing the module runs `AppConfig()` and `create_app()` — which builds a
        # `DatabaseConfig()` too — so the import needs a complete environment or it raises.
        # Set one here rather than relying on the developer's local `.env`: CI has no `.env`,
        # and `load_dotenv()` doesn't override variables that are already set, so these win in
        # both places. Postgres is never reached — the OAuth store connects lazily, on its first
        # read, and nothing here serves a request — so an unroutable URL is enough.
        os.environ["PUBLIC_BASE_URL"] = _PUBLIC_BASE_URL
        os.environ["DB_URL"] = "postgresql://user:pass@127.0.0.1:1/nope"
        # `create_app` builds an `EntraConfig` too, and all three of these are required.
        os.environ["ENTRA_TENANT_ID"] = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
        os.environ["ENTRA_CLIENT_ID"] = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
        os.environ["ENTRA_CLIENT_SECRET"] = "s3cr3t"

        # Imported through `importlib`, then widened via `object` before being narrowed: the
        # `import` statement form infers a literal `Module("office_mcp.main")` type that
        # `reportInvalidCast` refuses to convert to `_MainModule` at all — even through
        # `object` — whereas the plain `ModuleType` `import_module` returns widens cleanly.
        yield cast("_MainModule", cast("object", importlib.import_module("office_mcp.main")))
    finally:
        os.environ.clear()
        os.environ.update(environment_before)


class TestMainEntrypoint:
    """`office_mcp.main.main()`, exercised without ever letting uvicorn actually serve.

    A string target (`"office_mcp.main:app"`) makes uvicorn re-import this module under its own
    name when run as a script rather than through the `office-mcp` console script — re-running
    `create_app()` a second time, with a second OAuth store (and a second connection pool behind
    it) that nothing ever shuts down. Passing the already-built `app` object avoids the
    re-import entirely.
    """

    def test_uvicorn_is_given_the_app_object_not_a_string_target(
        self, main_module: _MainModule, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = MagicMock()
        monkeypatch.setattr(main_module.uvicorn, "run", run)

        main_module.main()

        run.assert_called_once()
        target = cast("Starlette", run.call_args.args[0])
        assert target is main_module.app

    def test_main_reuses_the_module_level_config_instead_of_rebuilding_it(
        self, main_module: _MainModule, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = MagicMock()
        monkeypatch.setattr(main_module.uvicorn, "run", run)
        app_config = MagicMock(
            side_effect=AssertionError("AppConfig() must not be re-instantiated in main()")
        )
        monkeypatch.setattr(main_module, "AppConfig", app_config)

        main_module.main()

        app_config.assert_not_called()
        # Reaching into the module's private `_config` is the point of this white-box test: it
        # proves `main()` served the *same* config object `app` was already built from.
        assert run.call_args.kwargs["port"] == main_module._config.port  # pyright: ignore[reportPrivateUsage]
