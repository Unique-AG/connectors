"""`create_app` driven as a real ASGI app, so the lifespan and middleware actually run."""

from collections.abc import Iterator, Mapping
from typing import Protocol, cast

import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from with_intelligence_mcp.app import create_app
from with_intelligence_mcp.server.tools import TOOLS


class _HttpResponse(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]

    def json(self) -> object: ...


def _get(client: TestClient, path: str) -> _HttpResponse:
    return cast(_HttpResponse, cast(object, client.get(path)))


def _headers(response: object) -> dict[str, str]:
    headers = cast(_HttpResponse, response).headers
    return {key.lower(): value for key, value in headers.items()}


def _json_object(response: _HttpResponse) -> dict[str, object]:
    body = response.json()
    assert isinstance(body, dict)
    return cast("dict[str, object]", body)


def _checks(body: dict[str, object]) -> dict[str, object]:
    checks = body["checks"]
    assert isinstance(checks, dict)
    return cast("dict[str, object]", checks)


@pytest.fixture
def client(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DB_URL", database_url)
    monkeypatch.setenv("WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
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
        body = _json_object(response)
        assert body["status"] == "healthy"
        assert _checks(body) == {"database": True}


class TestReadinessWithoutADatabase:
    def test_ready_is_503_when_postgres_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Readiness must fail here and liveness must not — a restart would not help."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("DB_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/nothing")
        monkeypatch.setenv("WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        with TestClient(create_app()) as client:
            response = _get(client, "/ready")
            assert response.status_code == 503
            body = _json_object(response)
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
            "get_investments",
            "get_mandates",
        ]


class TestAuthIsRequired:
    def test_an_anonymous_initialize_is_refused(self, client: TestClient) -> None:
        """The whole point of the auth slice: no tool call without a login."""
        response = client.post(
            "/mcp",
            headers={"accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert response.status_code == 401

    def test_the_401_points_at_the_resource_metadata(self, client: TestClient) -> None:
        """How a client discovers where to authenticate."""
        response = client.post(
            "/mcp",
            headers={"accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert response.status_code == 401
        assert "resource_metadata" in _headers(response)["www-authenticate"]

    def test_the_authorization_server_advertises_registration_and_pkce(
        self, client: TestClient
    ) -> None:
        metadata = _json_object(_get(client, "/.well-known/oauth-authorization-server"))
        registration = metadata["registration_endpoint"]
        methods = metadata["code_challenge_methods_supported"]
        assert isinstance(registration, str)
        assert isinstance(methods, list)
        assert registration.endswith("/register")
        assert "S256" in cast("list[object]", methods)

    def test_the_login_route_exists_and_refuses_an_unknown_request(
        self, client: TestClient
    ) -> None:
        response = _get(client, "/login?request_id=nope")
        assert response.status_code == 400
        assert "expired" in response.text
