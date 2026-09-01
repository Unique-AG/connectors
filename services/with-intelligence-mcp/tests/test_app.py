"""`create_app` driven as a real ASGI app, so the lifespan and middleware actually run."""

from collections.abc import Iterator
from typing import Protocol, cast

import pytest
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from with_intelligence_mcp.app import create_app
from with_intelligence_mcp.server.tools import TOOLS


# TestClient's httpx responses are partially unknown to this repo's type-checking mode.
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
        """Readiness must fail here and liveness must not — a restart would not help."""
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

    def test_the_registered_tools_are_reachable(self) -> None:
        assert [getattr(fn, "__name__", "") for fn in TOOLS] == [
            "get_investor",
            "get_people_for_investor",
        ]
