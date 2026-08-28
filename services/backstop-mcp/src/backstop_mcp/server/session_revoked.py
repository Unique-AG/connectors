"""Turn a confirmed MCP-token revocation into HTTP 401 on the in-flight `/mcp` call.

FastMCP catches tool exceptions and answers JSON-RPC with HTTP 200. After we revoke tokens the
client would only learn on the *next* call, when the access token fails validation. This
middleware rewrites the current response to 401 once `BackstopSessionRevokedError` has marked
the request, so Unique's MCP client reconnects immediately.

Two traps, both properties of streamable HTTP, not of a same-task unit test:

1. The MCP session task is started at `initialize` and reused for every later message
   (`mcp/server/streamable_http_manager.py`). A ContextVar set in that task does not appear on
   the HTTP `send` path. The revoke flag is a mutable box on the ASGI `scope` — the same dict
   FastMCP passes into the session as `request_context`.
2. SSE sends `http.response.start` (200) before the tool runs. POST bodies are held until the
   app returns so a revoke after that start can still become 401. GET is not held: the
   standalone SSE stream never returns.
"""

from typing import cast

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backstop_mcp.backstop_client import (
    mcp_session_was_revoked,
    reset_mcp_session_revoked,
    restore_mcp_session_revoked,
)

_WWW_AUTHENTICATE = b'Bearer error="invalid_token", error_description="credential_revoked"'
_UNAUTHORIZED_BODY = b"{}"


class SessionRevokedToUnauthorizedMiddleware:
    app: ASGIApp

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = reset_mcp_session_revoked(scope)
        try:
            if scope.get("method") == "POST":
                await _send_when_complete(self.app, scope, receive, send)
            else:
                await _send_rewriting_start(self.app, scope, receive, send)
        finally:
            restore_mcp_session_revoked(token)


async def _send_rewriting_start(app: ASGIApp, scope: Scope, receive: Receive, send: Send) -> None:
    """GET/HEAD: headers go out after the handler, so rewrite `http.response.start` in place."""

    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start" and mcp_session_was_revoked(scope):
            headers = [
                (key, value)
                for key, value in cast("list[tuple[bytes, bytes]]", message.get("headers", []))
                if key.lower() != b"www-authenticate"
            ]
            headers.append((b"www-authenticate", _WWW_AUTHENTICATE))
            message = {**message, "status": 401, "headers": headers}
        await send(message)

    await app(scope, receive, send_wrapper)


async def _send_when_complete(app: ASGIApp, scope: Scope, receive: Receive, send: Send) -> None:
    """POST: hold the response until the app returns, then 401 if the session task revoked."""
    held: list[Message] = []

    async def send_wrapper(message: Message) -> None:
        held.append(message)

    await app(scope, receive, send_wrapper)
    if mcp_session_was_revoked(scope):
        await send(_unauthorized_start())
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY, "more_body": False})
        return
    for message in held:
        await send(message)


def _unauthorized_start() -> Message:
    body_len = str(len(_UNAUTHORIZED_BODY)).encode()
    return {
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"www-authenticate", _WWW_AUTHENTICATE),
            (b"content-type", b"application/json"),
            (b"content-length", body_len),
        ],
    }
