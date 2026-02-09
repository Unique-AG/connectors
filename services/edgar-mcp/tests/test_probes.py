from collections.abc import Callable
from typing import TypedDict, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edgar_mcp.api.probes import HealthResponse, ProbeResponse, create_probe_router
from edgar_mcp.config import AppConfig

type MakeClient = Callable[..., TestClient]


def _make_session_factory(*, succeeds: bool = True) -> MagicMock:
    mock_session = AsyncMock()
    # AsyncMock attributes are inherently Any-typed; suppression is expected
    mock_session.__aenter__.return_value = mock_session  # pyright: ignore[reportAny]
    mock_session.__aexit__.return_value = None  # pyright: ignore[reportAny]
    if succeeds:
        mock_session.execute = AsyncMock()
    else:
        mock_session.execute = AsyncMock(side_effect=Exception("Connection refused"))
    return MagicMock(return_value=mock_session)


def _make_rabbitmq_connection(*, is_closed: bool = False) -> MagicMock:
    mock_connection = MagicMock()
    mock_connection.is_closed = is_closed
    return mock_connection


@pytest.fixture
def make_client() -> MakeClient:
    def _make(
        session_factory: MagicMock | None = None,
        rabbitmq_connection: MagicMock | None = None,
        config: AppConfig | None = None,
    ) -> TestClient:
        app = FastAPI()
        config = config or AppConfig()
        app.include_router(create_probe_router(config, session_factory, rabbitmq_connection))
        return TestClient(app)

    return _make


class OpenApiSchema(TypedDict, total=False):
    paths: dict[str, object]


class TestProbeEndpoint:
    """Test /probe endpoint behavior."""

    def test_returns_version(self, make_client: MakeClient) -> None:
        """GET /probe returns configured version."""
        client = make_client(config=AppConfig(version="1.2.3"))
        response = client.get("/probe")

        assert response.status_code == 200
        data = cast(ProbeResponse, response.json())
        assert data == {"version": "1.2.3"}

    def test_probe_not_in_openapi_schema(self, make_client: MakeClient) -> None:
        """Probe endpoint is excluded from OpenAPI schema."""
        client = make_client()
        response = client.get("/openapi.json")

        schema = cast(OpenApiSchema, response.json())
        assert "/probe" not in schema.get("paths", {})


class TestHealthEndpoint:
    """Test /health endpoint behavior."""

    def test_returns_healthy_when_db_ok(self, make_client: MakeClient) -> None:
        """GET /health returns healthy when database responds."""
        client = make_client(session_factory=_make_session_factory())
        response = client.get("/health")

        assert response.status_code == 200
        data = cast(HealthResponse, response.json())
        assert data["status"] == "healthy"
        assert data["checks"]["postgres"] == "ok"

    def test_returns_unhealthy_when_db_fails(self, make_client: MakeClient) -> None:
        """GET /health returns 503 when database check fails."""
        client = make_client(session_factory=_make_session_factory(succeeds=False))
        response = client.get("/health")

        assert response.status_code == 503
        data = cast(HealthResponse, response.json())
        assert data["status"] == "unhealthy"
        assert data["checks"]["postgres"] == "error"

    def test_checks_rabbitmq_connection(self, make_client: MakeClient) -> None:
        """GET /health checks RabbitMQ connection status."""
        client = make_client(rabbitmq_connection=_make_rabbitmq_connection())
        response = client.get("/health")

        assert response.status_code == 200
        data = cast(HealthResponse, response.json())
        assert data["checks"]["rabbitmq"] == "ok"

    def test_unhealthy_when_rabbitmq_closed(self, make_client: MakeClient) -> None:
        """GET /health returns 503 when RabbitMQ connection is closed."""
        client = make_client(rabbitmq_connection=_make_rabbitmq_connection(is_closed=True))
        response = client.get("/health")

        assert response.status_code == 503
        data = cast(HealthResponse, response.json())
        assert data["status"] == "unhealthy"
        assert data["checks"]["rabbitmq"] == "error"

    def test_checks_all_dependencies(self, make_client: MakeClient) -> None:
        """GET /health checks both Postgres and RabbitMQ together."""
        client = make_client(
            session_factory=_make_session_factory(),
            rabbitmq_connection=_make_rabbitmq_connection(),
        )
        response = client.get("/health")

        assert response.status_code == 200
        data = cast(HealthResponse, response.json())
        assert data["status"] == "healthy"
        assert data["checks"]["postgres"] == "ok"
        assert data["checks"]["rabbitmq"] == "ok"

    def test_unhealthy_when_one_dependency_fails(self, make_client: MakeClient) -> None:
        """GET /health returns unhealthy if any single dependency fails."""
        client = make_client(
            session_factory=_make_session_factory(),
            rabbitmq_connection=_make_rabbitmq_connection(is_closed=True),
        )
        response = client.get("/health")

        assert response.status_code == 503
        data = cast(HealthResponse, response.json())
        assert data["status"] == "unhealthy"
        assert data["checks"]["postgres"] == "ok"
        assert data["checks"]["rabbitmq"] == "error"

    def test_healthy_with_no_dependencies(self, make_client: MakeClient) -> None:
        """GET /health returns healthy when no dependencies are configured."""
        client = make_client()
        response = client.get("/health")

        assert response.status_code == 200
        data = cast(HealthResponse, response.json())
        assert data["status"] == "healthy"
        assert data["checks"] == {}
