from collections.abc import Mapping
from typing import Protocol, cast

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backstop_mcp.backstop_client import BackstopSessionRevokedError
from backstop_mcp.server.session_revoked import SessionRevokedToUnauthorizedMiddleware


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    def json(self) -> dict[str, object]: ...


async def _ok(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def _revoked(_request: Request) -> JSONResponse:
    try:
        raise BackstopSessionRevokedError()
    except BackstopSessionRevokedError:
        return JSONResponse({"handled": True})


def _client() -> TestClient:
    app = Starlette(
        routes=[
            Route("/ok", _ok),
            Route("/revoked", _revoked),
        ],
        middleware=[Middleware(SessionRevokedToUnauthorizedMiddleware)],
    )
    return TestClient(app)


def _get(client: TestClient, path: str) -> _HttpResponse:
    return cast("_HttpResponse", client.get(path))  # pyright: ignore[reportUnknownMemberType]


class TestSessionRevokedToUnauthorizedMiddleware:
    def test_leaves_an_ordinary_response_alone(self) -> None:
        response = _get(_client(), "/ok")

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_rewrites_the_current_response_to_401_after_tokens_are_revoked(self) -> None:
        response = _get(_client(), "/revoked")

        assert response.status_code == 401
        assert "invalid_token" in response.headers["www-authenticate"]
        assert response.json() == {"handled": True}
