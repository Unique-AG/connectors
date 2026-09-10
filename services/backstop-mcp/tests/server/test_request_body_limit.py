"""The Starlette edge rejects bodies over 20 MB before the handler runs."""

from collections.abc import Mapping
from typing import Protocol, cast

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backstop_mcp.server.request_body_limit import (
    REQUEST_BODY_MAX_BYTES,
    RequestBodyLimitMiddleware,
)


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...
    def json(self) -> dict[str, object]: ...


async def _ok(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _client() -> TestClient:
    app = Starlette(
        routes=[Route("/", _ok, methods=["POST"])],
        middleware=[
            Middleware(RequestBodyLimitMiddleware, max_body_size=REQUEST_BODY_MAX_BYTES),
        ],
    )
    return TestClient(app)


def _post(
    client: TestClient, content: bytes, *, headers: Mapping[str, str] | None = None
) -> _HttpResponse:
    return cast(
        "_HttpResponse",
        client.post("/", content=content, headers=dict(headers or {})),
    )


def test_a_body_under_the_cap_is_accepted() -> None:
    response = _post(_client(), b'{"ok":true}')

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_a_declared_oversize_body_is_413_before_the_handler() -> None:
    response = _post(
        _client(),
        b"x",
        headers={"content-length": str(REQUEST_BODY_MAX_BYTES + 1)},
    )

    assert response.status_code == 413
    assert "too large" in response.text.lower()
