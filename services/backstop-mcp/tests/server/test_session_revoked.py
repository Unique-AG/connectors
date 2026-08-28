import asyncio
import contextvars
from collections.abc import Mapping
from typing import Protocol, cast

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
            Route("/revoked", _revoked, methods=["POST"]),
        ],
        middleware=[Middleware(SessionRevokedToUnauthorizedMiddleware)],
    )
    return TestClient(app)


def _get(client: TestClient, path: str) -> _HttpResponse:
    return cast("_HttpResponse", client.get(path))  # pyright: ignore[reportUnknownMemberType]


def _post(client: TestClient, path: str) -> _HttpResponse:
    return cast("_HttpResponse", client.post(path))  # pyright: ignore[reportUnknownMemberType]


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

    def test_rewrites_a_post_whose_handler_revokes_before_returning(self) -> None:
        response = _post(_client(), "/revoked")

        assert response.status_code == 401
        assert "invalid_token" in response.headers["www-authenticate"]

    def test_rewrites_when_headers_were_sent_before_the_revoke(self) -> None:
        """SSE sends 200 before the tool runs; holding the POST is what makes 401 possible."""

        async def sse_then_revoke(_scope: Scope, _receive: Receive, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            try:
                raise BackstopSessionRevokedError()
            except BackstopSessionRevokedError:
                pass
            await send({"type": "http.response.body", "body": b"data: {}", "more_body": False})

        app = SessionRevokedToUnauthorizedMiddleware(sse_then_revoke)
        response = _post(TestClient(app), "/")

        assert response.status_code == 401
        assert "invalid_token" in response.headers["www-authenticate"]
        assert "credential_revoked" in response.headers["www-authenticate"]

    def test_rewrites_when_the_session_task_cannot_see_this_request_contextvar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The initialize-started session task has a stale ContextVar snapshot.

        Marking via `get_http_request().scope` is what the HTTP send path can still see.
        """
        held_scope: list[Scope] = []

        def fake_get_http_request() -> Request:
            return Request(held_scope[0])

        monkeypatch.setattr("fastmcp.server.dependencies.get_http_request", fake_get_http_request)

        async def session_like(scope: Scope, _receive: Receive, send: Send) -> None:
            held_scope.append(scope)
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )

            async def mark_from_empty_context() -> None:
                try:
                    raise BackstopSessionRevokedError()
                except BackstopSessionRevokedError:
                    pass

            await asyncio.create_task(mark_from_empty_context(), context=contextvars.Context())
            await send({"type": "http.response.body", "body": b"data: {}", "more_body": False})

        app = SessionRevokedToUnauthorizedMiddleware(session_like)
        response = _post(TestClient(app), "/")

        assert response.status_code == 401
        assert "invalid_token" in response.headers["www-authenticate"]

    def test_outer_middleware_sees_the_rewritten_401_on_post(self) -> None:
        """POST holds until the app returns, then `send`s 401. That `send` must be the outer
        stack's, or request-metrics / OTel record the JSON-RPC 200 and never see the rewrite.
        """
        seen: list[int] = []

        class _RecordStartStatus:
            app: ASGIApp
            statuses: list[int]

            def __init__(self, app: ASGIApp, statuses: list[int]) -> None:
                self.app = app
                self.statuses = statuses

            async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                async def send_wrapper(message: Message) -> None:
                    if message["type"] == "http.response.start":
                        self.statuses.append(cast("int", message["status"]))
                    await send(message)

                await self.app(scope, receive, send_wrapper)

        app = Starlette(
            routes=[Route("/revoked", _revoked, methods=["POST"])],
            middleware=[
                Middleware(_RecordStartStatus, statuses=seen),
                Middleware(SessionRevokedToUnauthorizedMiddleware),
            ],
        )
        response = _post(TestClient(app), "/revoked")

        assert response.status_code == 401
        assert seen == [401]
