"""The composition root, exercised as a real ASGI app.

Checks that the app starts, its lifespan runs, the process-health routes behave, and that Entra
auth is actually mounted and enforced. The tools it exposes are exercised over the MCP protocol in
`test_mcp_tools.py`.

Nothing here reaches Entra: constructing the provider performs no I/O, and the assertions below
only touch metadata this service serves itself plus one unauthenticated request that is rejected
before any upstream call would happen.
"""

import ast
import asyncio
import importlib
import inspect
import json
import logging
import os
import pathlib
import re
from collections.abc import Callable, Iterator, Sequence
from types import ModuleType, UnionType
from typing import Protocol, cast, final, get_args, get_origin, get_type_hints, override
from unittest.mock import MagicMock

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.server.auth.providers.azure import AzureProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.memory import MemoryStore
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.base import BaseWrapper
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.types import TextContent
from starlette.applications import Starlette
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer
from unique_mcp.monitoring import _McpMetrics  # pyright: ignore[reportPrivateUsage]
from unique_toolkit.monitoring import get_metrics

import office_mcp.app as app_module
from office_mcp.app import create_app
from office_mcp.auth import build_auth, build_oauth_storage
from office_mcp.cardinality import (
    UNMATCHED_METHOD,
    UNMATCHED_PATH,
    UNRESOLVED_NAME,
    BoundedNameMiddleware,
)
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_mcp.graph_client import GraphSettings, create_graph_transport
from office_mcp.server import readiness
from office_mcp.shared.seam import REQUESTABLE_PERMISSIONS, graph_scope
from office_mcp.tools import ALWAYS_ON, Selection, register_tools, resolve

_PUBLIC_BASE_URL = "https://office-mcp.example"

# A database nothing can reach, for the tests that compose the real app but never make a request
# that touches one. The connection is opened on first use, so the app itself starts fine.
_UNREACHABLE_DSN = "postgresql://user:pass@127.0.0.1:1/nope"


class _ToolModule(Protocol):
    """The two things this test reads off a tool file.

    `tools/__init__.py` owns the whole of a tool module's contract; these are the parts of it that
    decide what reaches the consent screen — the permissions, and the name a selection asks for the
    tool by.
    """

    TOOL_NAME: str
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


def _surface_config() -> SurfaceConfig:
    """Every tool there is, which is what this file is about.

    A selection is mandatory — `create_app` refuses to start without one, deliberately — so every
    test here has to state which surface it composes. `teams` is the widest and the one whose scope
    list every assertion below is written against; the narrowed surfaces are
    `tests/test_tool_selection.py`'s subject.
    """
    return SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS})


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


def _request(client: TestClient, method: str, path: str) -> _HttpResponse:
    """The same narrowing as `_get`, for a verb `TestClient` has no method for.

    Which is the point of the one caller: a method this service does not serve is a label value a
    client chose, so the test has to be able to send one.
    """
    return cast(
        "_HttpResponse",
        client.request(method, path),  # pyright: ignore[reportUnknownMemberType]
    )


def _app(config: AppConfig | None = None) -> Starlette:
    """The real app on a database nothing reaches, for the tests that never make a stateful call."""
    return create_app(
        config=config or AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
        database_config=DatabaseConfig.model_validate({"url": _UNREACHABLE_DSN}),
        entra_config=_entra_config(),
        surface_config=_surface_config(),
    )


def _server_of(app: Starlette) -> FastMCP[None]:
    """The FastMCP server `create_app` composed, which is what an MCP client talks to."""
    return cast("FastMCP[None]", app.state.fastmcp_server)


def _error_text(result: CallToolResult) -> str:
    """Everything the model would read of a failed call."""
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


_NAME_LABEL = re.compile(r'name="([^"]*)"')


def _call_label_values(kind: str) -> set[str]:
    """Every `name` label `mcp_calls_total` carries for one kind of call, from a live scrape.

    Read out of the process-wide Prometheus registry rather than over `/metrics`, because that
    route serves the same registry and going through HTTP would need a signed-in caller too. The
    registry is process-wide and never reset, so assert on values this test produced itself.
    """
    return {
        match.group(1)
        for line in get_metrics().decode().splitlines()
        if line.startswith("mcp_calls_total{") and f'kind="{kind}"' in line
        for match in [_NAME_LABEL.search(line)]
        if match is not None
    }


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
        surface_config=_surface_config(),
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

    def test_only_one_family_measures_request_latency(self, app_client: TestClient) -> None:
        """Two histograms for one latency is a dashboard that disagrees with itself.

        `OpenTelemetryMiddleware` brings its own instruments, and left to the global meter provider
        they land in the same registry `/metrics` scrapes as unique_toolkit's — so a scrape would
        answer `http_server_duration_milliseconds` *and* `python_http_request_duration_seconds` for
        the same requests, differing in unit, in bucket boundaries and in labels. `app.py` hands
        that middleware a no-op meter provider so the toolkit series is the only one; this is what
        says so. Asserted on the family names rather than on the middleware's arguments, because
        what must not regress is the scrape.
        """
        # A request has to have been served before a latency histogram exists to find. The scrape
        # itself does not count: it is still in flight when the registry is read.
        assert _get(app_client, "/health").status_code == 200

        histograms = {
            line.split()[2]
            for line in _get(app_client, "/metrics").text.splitlines()
            if line.startswith("# TYPE ") and line.endswith(" histogram")
        }
        latency = {name for name in histograms if "http" in name and "duration" in name}

        assert latency == {"python_http_request_duration_seconds"}, (
            f"expected one HTTP request-latency family, got {sorted(latency)}"
        )

    def test_the_request_latency_histogram_reaches_past_ten_seconds(
        self, app_client: TestClient
    ) -> None:
        """The buckets are the whole of what this histogram can say about a slow request.

        `prometheus_client`'s default layout stops at 10 s. One inbound MCP request contains a tool
        call and every Graph call that tool made — four 30 s attempts before any Retry-After wait,
        several requests for a paged walk — so at the default every slow request falls into `+Inf`
        and p95 and p99 both read 10, which is the one number the panel must not invent. Asserted on
        the scrape rather than on the argument, because a histogram is registered once per process
        and the first middleware to declare it wins: the argument is only correct if it arrived
        first, and only the scrape says whether it did.

        `/manifest` and not `/health`, which `setup_ops` excludes from these metrics along with the
        other probe routes — a scrape after a health check finds the family declared and empty, and
        a histogram with no observations has no buckets to read.
        """
        assert _get(app_client, "/manifest").status_code == 200

        boundaries = {
            line.partition('le="')[2].partition('"')[0]
            for line in _get(app_client, "/metrics").text.splitlines()
            if line.startswith("python_http_request_duration_seconds_bucket")
        }

        assert {"30.0", "60.0", "120.0", "300.0"} <= boundaries, (
            f"the slow buckets are missing from the scrape, which has {sorted(boundaries)}"
        )

    def test_the_resolved_surface_is_served(self, app_client: TestClient) -> None:
        """`/manifest` is where an operator reads the exact permission list without a pod's logs.

        Asserted here rather than only against `surface_manifest`, because the spec asks for a log
        line *and a route*: a test that calls the function directly passes just as happily with the
        route deleted, and the permission list is the one thing about this deployment that cannot be
        corrected after a tenant has consented to it.
        """
        response = _get(app_client, "/manifest")

        assert response.status_code == 200
        assert "resolved tool surface" in response.text
        assert f"{ALWAYS_ON} (always on)" in response.text

    def test_the_resolved_surface_is_logged_once_at_startup(
        self, postgres_container: PostgresContainer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """And the other half of it: an operator who never calls the route still finds the list in
        the pod's log. Once, not per request — this runs in the lifespan, and a manifest that landed
        on every call would bury the line that matters in a log nobody reads twice.
        """
        url = postgres_container.get_connection_url().replace("+psycopg2", "")
        app = create_app(
            config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
            database_config=DatabaseConfig.model_validate({"url": url}),
            entra_config=_entra_config(),
            surface_config=_surface_config(),
        )

        with caplog.at_level(logging.INFO, logger=app_module.__name__), TestClient(app) as client:
            _get(client, "/health")

        logged = [
            record.getMessage()
            for record in caplog.records
            if "resolved tool surface" in record.getMessage()
        ]

        assert len(logged) == 1, f"expected the surface logged once at startup, got {len(logged)}"
        assert f"{ALWAYS_ON} (always on)" in logged[0]


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
    on both sides of it. So two of the assertions here compare them against
    `shared/seam.py`'s `REQUESTABLE_PERMISSIONS`, which is written out by hand precisely so that it
    is not a derivation, and against the one shape a permission tuple may not have.

    Every assertion is written against the widest surface — `TOOLS_PRESET=teams`, every tool there
    is — because that is the selection under which "every tool file's permissions" has anything to
    mean. What a *narrowed* surface asks for is `tests/test_tool_selection.py`'s subject.
    """

    def test_the_widest_surface_has_something_to_contribute(self) -> None:
        """Guards the guard: against an empty registry every assertion below holds vacuously —
        `()` equals `()`, and every one of no tools is covered."""
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        assert selection.tools, "the widest preset resolves to no tools at all"
        assert selection.graph_scopes, "the widest preset derives no scopes"

    def test_the_scope_list_follows_the_tools_it_was_resolved_from(self) -> None:
        """The scopes are that selection's own tools' permissions, deduplicated, in the order the
        tools are in — not a set, and not a second union assembled anywhere else.

        Read off the tool *files*, keyed by the selection's own tool order, so this is not a
        derivation compared with itself: a permission dropped, added or reordered fails here, and
        the order is what production is keyed by. Two tools naming the same permission is normal, so
        a set comparison would let a reorder — or the loss of a tool whose every permission another
        tool also names — pass unnoticed.
        """
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        # Keyed by the name a selection uses, which is the tool file's own `TOOL_NAME` and not its
        # file stem — the two agree today and nothing makes them.
        by_name = {module.TOOL_NAME: module for _stem, module in _tool_modules()}

        expected = tuple(
            dict.fromkeys(
                graph_scope(permission)
                for name in selection.tools
                for permission in by_name[name].GRAPH_PERMISSIONS
            )
        )

        assert selection.graph_scopes == expected, (
            "the scope list sign-in asks for is the selected tools' own permissions in the "
            + "registry's order — anything else is a second derivation of the one value that "
            + "cannot be corrected after consent"
        )

    def test_every_tool_file_has_its_permissions_on_that_list(self) -> None:
        """Read off the files rather than off the registry, which is the whole point: a tool file
        that was never added to `_TOOL_MODULES` registers nothing and asks for nothing, and a
        registry compared against itself would never say so."""
        asked_for = set(resolve(preset=ToolsPreset.TEAMS, enabled=None).graph_scopes)

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

    def test_create_app_resolves_the_surface_once_and_both_halves_come_from_it(self) -> None:
        """The scopes Entra is asked for belong to the very selection the tools were registered
        from — asserted by identity, which is the whole of what is being asserted.

        Two resolutions would be two chances to disagree about a tool, and the disagreement is
        unfixable either way round: a tool registered whose permission was not requested fails at
        its first call with AADSTS65001, and a permission requested for a tool nobody registered
        widens every user's consent screen for a tool that is not there. So both consumers are
        watched, and what is compared is the object rather than its contents — two lists that merely
        looked equal would be exactly the second derivation this forbids.
        """
        asked_for: list[Sequence[str]] = []
        registered: list[Selection] = []

        def _auth(
            entra: EntraConfig,
            base_url: str,
            client_storage: AsyncKeyValue,
            graph_scopes: Sequence[str],
        ) -> AzureProvider:
            asked_for.append(graph_scopes)
            return build_auth(
                entra,
                base_url=base_url,
                client_storage=client_storage,
                graph_scopes=graph_scopes,
            )

        def _register(mcp: FastMCP, transport: httpx.AsyncClient, selection: Selection) -> None:
            registered.append(selection)
            register_tools(mcp, transport, selection)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(app_module, "build_auth", _auth)
            patch.setattr(app_module, "register_tools", _register)
            app = create_app(
                config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
                database_config=DatabaseConfig.model_validate(
                    {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
                ),
                entra_config=_entra_config(),
                surface_config=_surface_config(),
            )
            # Run the lifespan, so what this composes is started and shut down as it is in
            # production; nothing here reaches Postgres, which is only touched by a request.
            with TestClient(app):
                pass

        assert len(asked_for) == 1, "the auth provider is built once, at the composition root"
        assert len(registered) == 1, "the tools are registered once, at the composition root"
        assert asked_for[0] is registered[0].graph_scopes, (
            "create_app must resolve the tool surface once and hand the same Selection's scopes to "
            + "build_auth — a list rebuilt at the call site is a second derivation to keep in step "
            + "with the one the tools came from"
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
            surface_config=_surface_config(),
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


class _NeverAnswers(BaseWrapper):
    """An OAuth store whose read never completes.

    A `MemoryStore` underneath so the wrapper is a real one, and a `get` that never delegates to
    it: what is under test is the deadline, and any store that could answer would not exercise it.
    """

    def __init__(self) -> None:
        self.key_value: AsyncKeyValue = MemoryStore()

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, object] | None:
        await asyncio.Event().wait()
        raise AssertionError("unreachable: the wait above never returns")


class TestReadyReportsDatabaseUnreachable:
    def test_ready_is_503_when_postgres_is_unreachable(self) -> None:
        app = create_app(
            config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
            database_config=DatabaseConfig.model_validate(
                {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
            ),
            entra_config=_entra_config(),
            surface_config=_surface_config(),
        )
        with TestClient(app) as client:
            response = _get(client, "/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert _checks(body)["database"] is False

    async def test_ready_is_503_when_postgres_never_answers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A database that hangs must not hang the probe.

        Nothing under `oauth_storage.get` carries a deadline of its own: the store hands asyncpg a
        bare DSN, so there is no `command_timeout`, and pool acquisition with `timeout=None` waits
        on its queue forever. uvicorn does not cancel the handler when kubelet stops waiting, so
        without the deadline this call never returns and the waiter it left is permanent. The
        assertion is therefore first that it returns at all — the test hangs rather than fails if
        the deadline is removed — and then that a database too slow to answer reads as not ready.
        """
        monkeypatch.setattr(readiness, "_PROBE_TIMEOUT_SECONDS", 0.01)

        response = await readiness.ready_response(_NeverAnswers())

        assert response.status_code == 503
        body = cast("dict[str, object]", json.loads(bytes(response.body)))
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
        # `create_app` builds a `SurfaceConfig` too, and it has no default on purpose: without a
        # selection the import aborts, which is the same refusal an operator meets.
        os.environ["TOOLS_PRESET"] = ToolsPreset.TEAMS

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


class TestTheGraphTimeoutBudgetIsInjected:
    """`graph_client/` may not read config (rule 2), so the composition root translates it.

    The seam existed before these tests and carried nothing through it: every construction in the
    repo was a bare `GraphSettings()`, which made the three values operators most want to turn —
    the request timeout, the connect timeout and the retry count — unreachable without a code
    change, while three files said the opposite.
    """

    def test_the_composition_root_hands_the_transport_what_an_operator_configured(self) -> None:
        built: list[GraphSettings] = []

        def _record(settings: GraphSettings) -> httpx.AsyncClient:
            built.append(settings)
            return create_graph_transport(settings)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(app_module, "create_graph_transport", _record)
            _app(
                AppConfig.model_validate(
                    {
                        "public_base_url": _PUBLIC_BASE_URL,
                        "graph_request_timeout_seconds": 12.5,
                        "graph_connect_timeout_seconds": 2.5,
                        "graph_max_retries": 0,
                    }
                )
            )

        assert built == [
            GraphSettings(request_timeout_seconds=12.5, connect_timeout_seconds=2.5, max_retries=0)
        ]

    def test_an_unconfigured_deployment_gets_the_budget_it_had_before(self) -> None:
        """The defaults on both sides are the same three numbers, so making them settable moved
        nothing. Asserted against `GraphSettings()` rather than against literals: the two sets of
        defaults are only allowed to drift together."""
        built: list[GraphSettings] = []

        def _record(settings: GraphSettings) -> httpx.AsyncClient:
            built.append(settings)
            return create_graph_transport(settings)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(app_module, "create_graph_transport", _record)
            _app()

        assert built == [GraphSettings()]


class TestTheNameLabelIsBoundedByWhatIsRegistered:
    """`mcp_calls_total{name=…}` is labelled with what the client sent, so this server bounds it.

    `unique_mcp`'s metrics middleware reads `context.message.name` before FastMCP has resolved
    anything, and the dashboard groups by that label — so one authenticated caller looping over
    `tools/call {"name": "aaa1"}` mints a time series per name, permanently. `BoundedNameMiddleware`
    renames a call the server cannot resolve before that middleware sees it; see `cardinality.py`
    for why the fix belongs upstream instead.
    """

    def test_the_sentinel_is_not_a_tool_this_server_registers(self) -> None:
        """Otherwise a bogus call would not just be counted as a real tool — it would run one."""
        assert UNRESOLVED_NAME not in resolve(preset=ToolsPreset.TEAMS, enabled=None).tools

    async def test_this_server_registers_no_resource_and_no_prompt_today(self) -> None:
        """Records the state the resource and prompt paths are exercised against, not a decision.

        All three paths now resolve before renaming, so nothing here depends on the registries being
        empty. What being empty does mean is that the resolve-first branch on those two is never the
        one taken in this deployment — so when the Outlook or SharePoint surfaces add a member, this
        fails and says to go and cover the branch that starts running.
        """
        async with Client(FastMCPTransport(_server_of(_app()))) as client:
            assert await client.list_resources() == []
            assert await client.list_resource_templates() == []
            assert await client.list_prompts() == []

    async def test_a_resource_and_a_prompt_that_do_resolve_keep_their_own_name(self) -> None:
        """The resolve-first branch on the two paths this deployment cannot reach yet.

        Asserted on a server built here rather than on the composed app, because the composed app
        registers neither — which is the whole reason this branch would otherwise go untested until
        the day something depended on it.
        """
        server: FastMCP[None] = FastMCP("Office MCP", middleware=[BoundedNameMiddleware()])

        @server.resource("resource://kept")
        def kept_resource() -> str:
            return "resource reached"

        @server.prompt
        def kept_prompt() -> str:
            return "prompt reached"

        async with Client(FastMCPTransport(server)) as client:
            read = await client.read_resource("resource://kept")
            got = await client.get_prompt("kept_prompt")

        assert [getattr(content, "text", None) for content in read] == ["resource reached"]
        assert [
            block.text
            for message in got.messages
            if isinstance(block := message.content, TextContent)
        ] == ["prompt reached"]

    async def test_every_registered_tool_still_dispatches_under_its_own_name(self) -> None:
        """The renaming is only allowed to touch a call that was going to be refused anyway.

        Every tool is called with no arguments, so each fails — on its arguments, or on the
        On-Behalf-Of exchange an unauthenticated in-process client cannot make. What matters is
        that none of them fails as *unknown*, which is what a renamed call would have become.
        """
        async with Client(FastMCPTransport(_server_of(_app()))) as client:
            registered = [tool.name for tool in await client.list_tools()]
            refused = {
                name: _error_text(await client.call_tool(name, {}, raise_on_error=False))
                for name in registered
            }

        assert registered, "the guard for everything below: a surface with no tools proves nothing"
        for name, message in refused.items():
            assert "Unknown tool" not in message, f"{name} stopped dispatching: {message}"
            assert UNRESOLVED_NAME not in message, f"{name} was renamed: {message}"
        assert set(registered) <= _call_label_values("tool"), (
            "and each was counted under its own name"
        )

    async def test_an_unknown_tool_is_still_refused_by_the_name_the_caller_sent(self) -> None:
        """What the caller reads is unchanged, because it is not built here: `_call_tool_mcp`
        wraps the failure with `Unknown tool: {key!r}` from the original request params, outside
        the middleware chain entirely. The renaming reaches the label and stops there."""
        async with Client(FastMCPTransport(_server_of(_app()))) as client:
            result = await client.call_tool("no_such_tool", {}, raise_on_error=False)

        assert result.is_error
        assert _error_text(result) == "Unknown tool: 'no_such_tool'"

    async def test_the_refusal_is_word_for_word_the_one_an_unguarded_server_gives(self) -> None:
        """The same claim, asserted against a server that does not carry this middleware rather
        than against a literal — so an upstream rewording moves both sides or fails here."""
        texts: list[str] = []
        for middleware in ([], [BoundedNameMiddleware()]):
            server: FastMCP[None] = FastMCP("Office MCP", middleware=middleware)

            @server.tool
            def registered() -> str:
                return "reached"

            async with Client(FastMCPTransport(server)) as client:
                texts.append(
                    _error_text(await client.call_tool("no_such_tool", {}, raise_on_error=False))
                )

        assert texts[0] == texts[1], "the middleware changed what an unknown tool call answers"

    async def test_an_unresolvable_name_is_counted_as_one_value(self) -> None:
        """The whole point, and the only assertion that proves the mounting order: the label is
        read by a middleware `setup_ops` *appends*, so this passes only while the renaming one is
        still outside it. A reordering fails here rather than in a dashboard."""
        async with Client(FastMCPTransport(_server_of(_app()))) as client:
            for attempt in range(3):
                await client.call_tool(f"zz_probe_{attempt}", {}, raise_on_error=False)

        counted = _call_label_values("tool")
        assert UNRESOLVED_NAME in counted
        assert not [name for name in counted if name.startswith("zz_probe_")], (
            "three made-up names became three permanent time series"
        )

    def test_it_is_mounted_outside_the_middleware_that_reads_the_label(self) -> None:
        """The structural half of the test above. FastMCP builds its chain over
        `reversed(self.middleware)`, so earlier in the list is further out: the constructor's
        middlewares wrap everything `add_middleware` appends, and `setup_ops` appends."""
        installed = _server_of(_app()).middleware
        ours = [i for i, mw in enumerate(installed) if isinstance(mw, BoundedNameMiddleware)]
        metrics = [i for i, mw in enumerate(installed) if isinstance(mw, _McpMetrics)]

        assert len(ours) == 1 and len(metrics) == 1, f"expected one of each: {installed}"
        assert ours[0] < metrics[0], (
            "BoundedNameMiddleware has to run outside unique_mcp's metrics middleware, which reads "
            + "the tool name the client sent as a Prometheus label before anything resolves it"
        )


def _http_label_values(label: str) -> set[str]:
    """Every value one label of `python_http_requests_total` carries, from a live scrape.

    Same registry and same caveat as `_call_label_values`: process-wide and never reset, so assert
    on values this test produced itself.
    """
    pattern = re.compile(rf'{label}="([^"]*)"')
    return {
        match.group(1)
        for line in get_metrics().decode().splitlines()
        if line.startswith("python_http_requests_total{")
        for match in [pattern.search(line)]
        if match is not None
    }


class TestThePathAndMethodLabelsAreBoundedByTheRouter:
    """`python_http_requests_total{path,method}` is labelled with what the client sent.

    Both labels come from `unique_toolkit`'s metrics middleware, which reads `scope["path"]` and
    `scope["method"]` verbatim. This service publishes its OAuth endpoints on the public internet,
    so unlike the MCP `name` label these need no credential at all: one `GET /wp-login.php` from a
    scanner mints a counter series and a whole histogram that live until the process dies.
    `BoundedRequestMiddleware` collapses an unrouted path and an unserved verb before that
    middleware sees either. See `cardinality.py` for why the fix belongs upstream instead.
    """

    def test_the_sentinels_are_not_routes_or_methods_this_service_serves(self) -> None:
        """Otherwise the bucket would collide with real traffic and hide it."""
        paths = {getattr(route, "path", None) for route in _app().routes}

        assert UNMATCHED_PATH not in paths
        assert UNMATCHED_METHOD not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

    def test_many_unrouted_paths_become_one_label_value(self, app_client: TestClient) -> None:
        """The whole point. Three shapes a scanner sends, one of them carrying a Teams id."""
        for path in ("/wp-login.php", "/.env", "/chats/19:meeting_abc@thread.v2/messages"):
            assert _get(app_client, path).status_code == 404

        counted = _http_label_values("path")
        assert UNMATCHED_PATH in counted
        assert not [path for path in counted if "wp-login" in path or "thread.v2" in path], (
            "an unauthenticated request minted a permanent time series per path"
        )

    def test_a_verb_nobody_serves_becomes_one_label_value(self, app_client: TestClient) -> None:
        """`method` is as client-chosen as `path` is — h11 accepts any RFC 7230 token — and it
        multiplies against it. A bogus verb on a *real* path is the case the path rule cannot
        catch: the router answers `Match.PARTIAL` there, so the path is genuine and only the verb
        is invented.

        `/manifest` rather than `/health`, because the toolkit middleware excludes the health and
        metrics paths from its own metrics, so nothing would be recorded to assert on."""
        assert _request(app_client, "BANANA", "/manifest").status_code in {404, 405}

        assert UNMATCHED_METHOD in _http_label_values("method")
        assert "BANANA" not in _http_label_values("method")

    def test_a_real_route_keeps_its_own_path_and_still_answers(
        self, app_client: TestClient
    ) -> None:
        """The renaming may only touch a request that was going to be refused.

        `/manifest` rather than `/health`, because the toolkit middleware excludes the health and
        metrics paths from its own metrics, so they could not show a surviving label either way.
        """
        assert _get(app_client, "/manifest").status_code == 200

        assert "/manifest" in _http_label_values("path")

    def test_an_unrouted_path_still_gets_starlettes_own_404(self, app_client: TestClient) -> None:
        """This middleware rewrites and passes through; it refuses nothing.

        So a route somebody forgets to register still answers 404 exactly as before, rather than a
        missing registration becoming an outage — which is what a known-paths gate in front of the
        router would have made it.
        """
        answered = _get(app_client, "/not-a-route-at-all")

        assert answered.status_code == 404
        assert answered.text == "Not Found", "Starlette's own 404, not one this middleware wrote"

    def test_it_is_mounted_inside_the_request_id_line_and_outside_everything_else(self) -> None:
        """Ordering, both directions, and each side is load-bearing.

        Starlette applies `user_middleware` outside-in, so earlier in the list is further out.
        Outside the toolkit's metrics middleware, or the label has already been read. Inside the
        request-id one, so an operator reading a flood of 404s still sees the real paths — a log
        line is where that truth belongs, and a metric label is the one place it must not
        accumulate.
        """
        # `Middleware.cls` is typed as a factory protocol rather than a class, so the name comes
        # off it through `type[object]`. Names rather than identities because three of the readers
        # being ordered against belong to other packages.
        installed = [
            cast("type[object]", middleware.cls).__name__ for middleware in _app().user_middleware
        ]

        def position(name: str) -> int:
            found = [i for i, installed_name in enumerate(installed) if installed_name == name]
            assert len(found) == 1, f"expected exactly one {name}, got {installed}"
            return found[0]

        ours = position("BoundedRequestMiddleware")

        assert position("HttpRequestIdMiddleware") < ours, (
            "the request-id line has to see the real path, or a 404 flood is unreadable in the logs"
        )
        for reader in ("OpenTelemetryMiddleware", "MetricsMiddleware"):
            assert ours < position(reader), (
                f"{reader} turns the path into a label or a span attribute, so the bounding has to "
                + f"happen outside it. Got {installed}"
            )


# What a method that releases what an object holds is called. Anchored at the start, so `is_closed`
# — a flag, and the one that lied about this service's own Graph transport — can never be mistaken
# for one.
_CLOSER = re.compile(r"^a?close(_|$)|^(?:shutdown|disconnect|dispose)$")

# Long-lived objects `create_app` builds that the lifespan deliberately does not close, and why.
# An entry is a decision to hold a resource until the process exits, so it says what closing would
# have bought. Anything neither closed nor named here fails the rule below.
_LEFT_OPEN_ON_PURPOSE: dict[str, str] = {
    "graph_transport": (
        "aclose() is a no-op — the SDK's AsyncGraphTransport inherits httpx's, whose body is "
        "`pass` (microsoft/kiota-python#494) — so calling it would only look like cleanup"
    ),
}


def _create_app_function() -> ast.FunctionDef:
    """`create_app`'s syntax tree, which is where its long-lived objects are visible as a set."""
    module = ast.parse(pathlib.Path(app_module.__file__).read_text())
    found = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    ]

    assert len(found) == 1, f"expected one create_app in app.py, got {len(found)}"
    return found[0]


def _own_scope(node: ast.AST) -> Iterator[ast.AST]:
    """Every node of one function's own scope, excluding the functions nested inside it.

    `create_app` defines the lifespan and two routes in its body, and what those bind lives as long
    as one request — which is the opposite of what this is about.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        yield child
        yield from _own_scope(child)


def _constructors(value: ast.expr) -> list[ast.expr]:
    """What a bound expression calls to produce its value — the outermost calls only.

    `create_graph_transport(GraphSettings(...))` produces a transport; the settings it was handed
    are an argument rather than something the composition root is left holding.
    """
    if isinstance(value, ast.Call):
        return [value.func]
    if isinstance(value, ast.BoolOp):
        return [called for operand in value.values for called in _constructors(operand)]
    if isinstance(value, ast.IfExp):
        branches = (value.body, value.orelse)
        return [called for branch in branches for called in _constructors(branch)]
    return []


def _built_by(function: ast.FunctionDef) -> dict[str, list[ast.expr]]:
    """Each name the function binds in its own scope, with the callables that produced it."""
    built: dict[str, list[ast.expr]] = {}
    for node in _own_scope(function):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                built.setdefault(target.id, []).extend(_constructors(value))
    return built


def _resolved(called: ast.expr) -> object | None:
    """The callable `create_app` names, looked up in `app.py`'s own namespace."""
    attributes: list[str] = []
    node: ast.expr = called
    while isinstance(node, ast.Attribute):
        attributes.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    found: object = app_module
    for attribute in [node.id, *reversed(attributes)]:
        found = cast("object", getattr(found, attribute, None))
        if found is None:
            return None
    return found


def _classes_named_by(annotation: object) -> list[type]:
    """The classes an annotation names: itself, a generic's origin, or a union's members.

    The union is why its members are reached through `get_args` rather than through the origin:
    `X | None` has `types.UnionType` for one, which is itself a class and would otherwise answer
    for the annotation as though the union were the thing that had been built.
    """
    if isinstance(annotation, type):
        return [annotation]
    origin = get_origin(annotation)
    if isinstance(origin, type) and origin is not UnionType:
        return [origin]
    arguments = cast("tuple[object, ...]", get_args(annotation))
    return [named for argument in arguments for named in _classes_named_by(argument)]


def _produced_by(called: ast.expr) -> list[type] | None:
    """The classes one call at the composition root can produce, or None if it cannot be told.

    A class produces itself; anything else produces what its return annotation names. That
    annotation is the whole of what the composition root is promised, which is the honest reading
    of it — see the class below on `oauth_storage`.
    """
    resolved = _resolved(called)
    if inspect.isclass(resolved):
        return [resolved]
    if not callable(resolved):
        return None
    returned = cast("object", get_type_hints(resolved).get("return"))
    return None if returned is None else _classes_named_by(returned)


def _async_closers(produced: type) -> set[str]:
    """The async methods a type owns whose job is to release what it holds."""
    return {
        name
        for name in dir(produced)
        if _CLOSER.match(name)
        and inspect.iscoroutinefunction(cast("object", getattr(produced, name, None)))
    }


def _long_lived_objects() -> dict[str, set[str] | None]:
    """Each name `create_app` builds from a call, with the async closers its value owns.

    `None` where a call cannot be resolved to a type: an object this rule cannot read is one it
    cannot vouch for, which is a different answer from "nothing to close".
    """
    found: dict[str, set[str] | None] = {}
    for name, constructors in _built_by(_create_app_function()).items():
        if not constructors:
            continue
        produced = [_produced_by(called) for called in constructors]
        if any(classes is None for classes in produced):
            found[name] = None
            continue
        found[name] = {
            closer
            for classes in produced
            if classes is not None
            for produces in classes
            for closer in _async_closers(produces)
        }
    return found


def _closed_in_the_lifespan() -> set[str]:
    """The names the lifespan awaits a closer on, wherever in it that happens.

    Where is left to the author on purpose: `try`/`finally` is how `app.py` does it today, and it
    is not the only correct shape for it.
    """
    found = [
        node
        for node in ast.walk(_create_app_function())
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
    ]
    assert len(found) == 1, f"expected one lifespan inside create_app, got {len(found)}"

    closed: set[str] = set()
    for node in ast.walk(found[0]):
        if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
            continue
        called = node.value.func
        if (
            isinstance(called, ast.Attribute)
            and isinstance(called.value, ast.Name)
            and _CLOSER.match(called.attr)
        ):
            closed.add(called.value.id)
    return closed


class TestEveryLongLivedObjectIsClosedOnShutdown:
    """The composition root builds each long-lived object once, and shutdown is the only release.

    A pool the lifespan forgets leaks for as long as the pod lives, and it is silent while it does:
    the app starts, every request is served, and nothing counts the sockets. The mistake is one
    line missing from a `finally` block that the commit adding the object had no reason to touch.

    Structural rather than behavioural, for two reasons. A behavioural test can only assert about
    the objects it was written to know, and the one this exists for is the object nobody wrote a
    test for — visible only in what `create_app` binds. And `test_mcp_tools.py`'s
    `TestTheTransportTheToolsShare` records a behavioural version of exactly this check that passed
    while the pool it was about survived every shutdown: it asserted `is_closed`, and `is_closed`
    was the only thing `aclose()` moved.

    What is closeable is read off the type the composition root is handed, which is why
    `oauth_storage` needs no exemption below: `build_oauth_storage` answers `AsyncKeyValue`, a
    protocol that declares no closer at all. Reaching through its encryption wrapper for the store's
    own is exactly what `app.py`'s lifespan explains it is not doing.
    """

    def test_the_root_builds_something_closeable_and_the_lifespan_closes_it(self) -> None:
        """Guards the guard from both ends: a rule that found nothing closeable would pass by
        reading the wrong function, and one that never saw a close would pass by not recognising
        one. `auth.close_obo_credentials()` is both today."""
        closeable = {name for name, closers in _long_lived_objects().items() if closers}

        assert closeable, "create_app builds nothing this rule can see a closer on"
        assert closeable & _closed_in_the_lifespan(), (
            "the lifespan closes none of them, so this rule cannot tell a close from a leak"
        )

    def test_every_name_left_open_on_purpose_is_still_left_open(self) -> None:
        """An exemption outlives what it was written for: the object is renamed or dropped, or
        somebody finds a close that works and calls it, and the entry stays behind recording a
        decision nobody is making any more."""
        built = _built_by(_create_app_function())
        closed = _closed_in_the_lifespan()
        stale = sorted(
            f"{name}: {reason}"
            for name, reason in _LEFT_OPEN_ON_PURPOSE.items()
            if name not in built or name in closed
        )

        assert not stale, (
            "_LEFT_OPEN_ON_PURPOSE names something create_app no longer builds, or something the "
            + "lifespan now closes. Delete the entry — the reason it carries has stopped being "
            + "the reason:\n  "
            + "\n  ".join(stale)
        )

    def test_every_long_lived_object_is_closed_or_left_open_on_purpose(self) -> None:
        closed = _closed_in_the_lifespan()
        leaked: list[str] = []
        for name, closers in sorted(_long_lived_objects().items()):
            if name in closed or name in _LEFT_OPEN_ON_PURPOSE:
                continue
            if closers is None:
                leaked.append(f"{name} is built by a call this rule cannot resolve to a type")
            elif closers:
                leaked.append(f"{name} owns {', '.join(sorted(closers))}, and nothing awaits it")

        assert not leaked, (
            "every long-lived object create_app builds has to be released when the process stops "
            + "serving, or it is a connection pool that lives as long as the pod and that nothing "
            + "counts. Await its closer in the lifespan's finally block; if closing it would buy "
            + "nothing, name it in _LEFT_OPEN_ON_PURPOSE and the reason becomes the record:\n  "
            + "\n  ".join(leaked)
        )
