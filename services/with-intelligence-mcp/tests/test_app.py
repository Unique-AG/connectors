"""The composition root, exercised as a real ASGI app.

`create_app` is where the wiring lives that is easiest to get wrong — the lifespan, middleware
registration, the route table — so it is driven here through Starlette's `TestClient`, which
actually runs the lifespan.
"""

from collections.abc import Iterator
from typing import Protocol, cast

import pytest
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from with_intelligence_mcp.app import create_app
from with_intelligence_mcp.server.tools import TOOLS


# `starlette.testclient` returns httpx responses that this repo's strict type-checking sees as
# partially unknown. Narrowed once here so every assertion below is checked rather than `Any`.
class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...
    def json(self) -> dict[str, object]: ...


def _get(client: TestClient, path: str) -> _HttpResponse:
    return cast("_HttpResponse", client.get(path))  # pyright: ignore[reportUnknownMemberType]


def _checks(body: dict[str, object]) -> dict[str, object]:
    checks = body["checks"]
    assert isinstance(checks, dict)
    return cast("dict[str, object]", checks)


@pytest.fixture
def client(
    postgres_container: PostgresContainer, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A running app pointed at the test container, with a development-safe issuer."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DB_URL", postgres_container.get_connection_url().replace("+psycopg2", "+asyncpg")
    )
    with TestClient(create_app()) as running:
        yield running


class TestOpsEndpoints:
    def test_health_is_process_up(self, client: TestClient) -> None:
        assert _get(client, "/health").status_code == 200

    def test_metrics_is_served(self, client: TestClient) -> None:
        assert _get(client, "/metrics").status_code == 200

    def test_ready_reports_the_database_it_checked(self, client: TestClient) -> None:
        response = _get(client, "/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert _checks(body) == {"database": True}


class TestReadinessWithoutADatabase:
    def test_ready_is_503_when_postgres_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Readiness is the only thing that must fail here — liveness must not restart the pod."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("DB_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/nothing")
        with TestClient(create_app()) as client:
            response = _get(client, "/ready")
            assert response.status_code == 503
            body = response.json()
            assert body["status"] == "unhealthy"
            assert _checks(body) == {"database": False}
            assert _get(client, "/health").status_code == 200


class TestMcpEndpoint:
    def test_mcp_is_mounted(self, client: TestClient) -> None:
        """A GET without the streaming headers is rejected by the transport, not missing."""
        assert _get(client, "/mcp").status_code != 404

    def test_no_tools_are_registered_yet(self) -> None:
        """The registry is empty on purpose; rule 7 in `test_layering.py` keeps it honest."""
        assert TOOLS == ()
