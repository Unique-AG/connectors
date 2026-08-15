"""The composition root, exercised as a real ASGI app.

Checks that the app starts, its lifespan runs, the process-health routes behave, and that Entra
auth is actually mounted and enforced. The tools it exposes are exercised over the MCP protocol in
`test_mcp_tools.py`.

Nothing here reaches Entra: constructing the provider performs no I/O, and the assertions below
only touch metadata this service serves itself plus one unauthenticated request that is rejected
before any upstream call would happen.
"""

import importlib
import os
import pathlib
from collections.abc import Callable, Iterator, Sequence
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
from office_mcp.shared.seam import REQUESTABLE_PERMISSIONS, graph_scope
from office_mcp.tools import GRAPH_SCOPES as REGISTRY_SCOPES

_PUBLIC_BASE_URL = "https://office-mcp.example"


class _ToolModule(Protocol):
    """The one thing this test reads off a tool file.

    `tools/__init__.py` owns the whole of a tool module's contract; this is the part of it that
    has to reach the consent screen.
    """

    GRAPH_PERMISSIONS: tuple[str, ...]


def _tool_modules() -> list[tuple[str, _ToolModule]]:
    """Every file under `src/office_mcp/tools/` that is a tool, found on disk, with its name.

    `__init__.py` is the registry rather than a tool, and is what this deliberately does not ask:
    the point of reading the directory is to see a tool file the registry forgot.
    """
    tools_dir = pathlib.Path(app_module.__file__).parent / "tools"
    return [
        (
            source.stem,
            cast(
                "_ToolModule",
                # Through `object`: a `ModuleType` never structurally overlaps a Protocol, which
                # is the same widening `_MainModule` below needs for the same reason.
                cast("object", importlib.import_module(f"office_mcp.tools.{source.stem}")),
            ),
        )
        for source in sorted(tools_dir.glob("*.py"))
        if source.name != "__init__.py"
    ]


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


class TestSignInAsksForEveryPermissionAnyToolCanRedeem:
    """The scope list handed to the auth provider, which is the one thing a restart cannot fix.

    `tools/__init__.py` derives it from the tool modules and is guarded where it is built. What is
    guarded here is that the value actually reaching Entra *is* that derivation, and that every
    tool file on disk is inside it. Either failure is silent and late: every tool still registers,
    every schema is unchanged, every other test in this suite passes, and the failure only appears
    in a live tenant as AADSTS65001 from the On-Behalf-Of exchange — before the tool body runs, for
    a permission that cannot be obtained after sign-in.

    A set comparison is not enough here, and that is not a stylistic preference. Two tools name the
    same permission all over this registry, so a change that reordered the list — or that dropped a
    tool whose every permission another tool also names — would leave the *set* identical and move
    only the order. The tuple is therefore what is asserted, which is also the property that
    matters in production: the consent screen and every cached On-Behalf-Of token key are keyed by
    this list as a string.

    What a derivation cannot check is the *names*: every assertion that reads the tool files and
    compares them with a list built from those same files agrees with a typo, because the typo is
    on both sides of it. So the last two assertions here compare them against
    `shared/seam.py`'s `REQUESTABLE_PERMISSIONS`, which is written out by hand precisely so that it
    is not a derivation, and against the one shape a permission tuple may not have.
    """

    def test_the_registry_has_something_to_contribute(self) -> None:
        """Guards the guard: against an empty registry both assertions below hold vacuously —
        `()` equals `()`, and every one of no tools is covered."""
        assert REGISTRY_SCOPES, "tools/__init__.py derives no scopes"

    def test_the_scope_list_is_the_registry_verbatim(self) -> None:
        """`app.GRAPH_SCOPES` is the registry's tuple and not a copy assembled here: a second
        derivation is a second place to forget a tool, and it would drift just as quietly."""
        assert app_module.GRAPH_SCOPES == REGISTRY_SCOPES, (
            "the scope list sign-in asks for is `tools/__init__.py`'s, in its order — anything "
            + "else is a second derivation of the one value that cannot be corrected after "
            + "consent"
        )

    def test_every_tool_file_has_its_permissions_on_that_list(self) -> None:
        """Read off the files rather than off the registry, which is the whole point: a tool file
        that was never added to `_TOOL_MODULES` registers nothing and asks for nothing, and a
        registry compared against itself would never say so."""
        asked_for = set(app_module.GRAPH_SCOPES)

        missing = {
            f"{name}: {permission}"
            for name, module in _tool_modules()
            for permission in module.GRAPH_PERMISSIONS
            if graph_scope(permission) not in asked_for
        }

        assert not missing, (
            "every permission a tool file declares has to reach the consent screen; these do "
            + "not, so the tools naming them fail at sign-in and no later call can redeem "
            + f"them: {sorted(missing)}"
        )

    def test_every_declared_permission_is_one_this_connector_may_ask_for(self) -> None:
        """The check the two above cannot make. Both compare the tool files against a list derived
        from those same files, so a misspelling is on both sides of the comparison and holds:
        `GRAPH_PERMISSIONS = ("Chat.Raed",)` passes every other assertion in this suite while
        putting a scope Entra does not know into `additional_authorize_scopes` — and Entra rejects
        an authorize request carrying an unknown scope, so every sign-in fails, for every user, for
        a tool nobody called. `shared/seam.py` writes the names out once, independently, which is
        the only thing that can catch it.
        """
        unknown = {
            f"{name}: {permission}"
            for name, module in _tool_modules()
            for permission in module.GRAPH_PERMISSIONS
            if permission not in REQUESTABLE_PERMISSIONS
        }

        assert not unknown, (
            "a permission a tool declares has to be one Microsoft defines and one this connector "
            + "is willing to ask every user to consent to — check the spelling against "
            + "`REQUESTABLE_PERMISSIONS` in shared/seam.py, and if the permission is genuinely "
            + f"new, add it there deliberately and to the README's table: {sorted(unknown)}"
        )

    def test_no_tool_declares_an_empty_permission_tuple(self) -> None:
        """`GRAPH_PERMISSIONS = ()` is the same failure spelled the other way and is just as quiet:
        it contributes nothing to the union, so nothing is missing from it, and the tool's own
        On-Behalf-Of exchange then asks for no scope at all. Every tool here reads a live tenant,
        so there is no such thing as one that needs no permission."""
        empty = [name for name, module in _tool_modules() if not module.GRAPH_PERMISSIONS]

        assert not empty, (
            "every tool calls Microsoft Graph on behalf of the signed-in user, so every tool "
            + f"declares the permissions its own requests are made under: {sorted(empty)}"
        )

    def test_create_app_hands_the_provider_that_exact_list(self) -> None:
        """And not a second union assembled at the call site: a re-derivation is a second place
        to forget a registry, and it would drift in exactly the same way and just as quietly.
        Identity rather than equality, because that is the whole of what is being asserted."""
        given: list[Sequence[str]] = []

        def _auth(
            entra: EntraConfig,
            base_url: str,
            client_storage: AsyncKeyValue,
            graph_scopes: Sequence[str],
        ) -> AzureProvider:
            given.append(graph_scopes)
            return build_auth(
                entra,
                base_url=base_url,
                client_storage=client_storage,
                graph_scopes=graph_scopes,
            )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(app_module, "build_auth", _auth)
            app = create_app(
                config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
                database_config=DatabaseConfig.model_validate(
                    {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
                ),
                entra_config=_entra_config(),
            )
            # Run the lifespan so the Graph transport this builds is closed again; nothing here
            # reaches Postgres, which is only touched by a request.
            with TestClient(app):
                pass

        assert len(given) == 1, "the auth provider is built once, at the composition root"
        assert given[0] is app_module.GRAPH_SCOPES, (
            "create_app must pass the composition root's own GRAPH_SCOPES — a list rebuilt here "
            + "is a second union to keep in step with the registries"
        )


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
            entra: EntraConfig,
            base_url: str,
            client_storage: AsyncKeyValue,
            graph_scopes: Sequence[str],
        ) -> AzureProvider:
            provider_was_given.append(client_storage)
            return build_auth(
                entra,
                base_url=base_url,
                client_storage=client_storage,
                graph_scopes=graph_scopes,
            )

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
