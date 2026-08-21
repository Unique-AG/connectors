"""The composition root, exercised as a real ASGI app.

Scaffolding only: no auth, no Microsoft Graph client, no tools yet — this just checks the app
starts, its lifespan runs, and the process-health routes behave.
"""

import importlib
import os
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Protocol, cast
from unittest.mock import MagicMock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from office_mcp.app import create_app
from office_mcp.config import AppConfig, DatabaseConfig


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
        config=AppConfig.model_validate({"public_base_url": "https://office-mcp.example"}),
        database_config=DatabaseConfig.model_validate({"url": url}),
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


class TestReadyReportsDatabaseUnreachable:
    def test_ready_is_503_when_postgres_is_unreachable(self) -> None:
        app = create_app(
            config=AppConfig.model_validate({"public_base_url": "https://office-mcp.example"}),
            database_config=DatabaseConfig.model_validate(
                {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
            ),
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
    rest of the test session the first time anything imports this module. The module is only ever
    exec'd once per process, so the whole environment — not just the handful of vars `.env`
    sets — is snapshotted and restored around that one import.
    """
    environment_before = os.environ.copy()
    try:
        # Importing the module runs `AppConfig()` and `create_app()` — which builds a
        # `DatabaseConfig()` too — so the import needs a complete environment or it raises.
        # Set one here rather than relying on the developer's local `.env`: CI has no `.env`,
        # and `load_dotenv()` doesn't override variables that are already set, so these win in
        # both places. The app's lifespan doesn't run in these tests, so an unroutable URL
        # is enough — the database is never connected to.
        os.environ["PUBLIC_BASE_URL"] = "https://office-mcp.example"
        os.environ["DB_URL"] = "postgresql://user:pass@127.0.0.1:1/nope"

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
    name when run as a script — re-running `create_app()` a second time and creating a
    duplicate app instance whose lifespan context would never be disposed. Passing the
    already-built `app` object avoids the re-import entirely.
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
