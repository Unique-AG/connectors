"""Turn a confirmed MCP-token revocation into HTTP 401 on the in-flight `/mcp` call.

FastMCP catches tool exceptions and answers JSON-RPC with HTTP 200. After we revoke tokens the
client would only learn on the *next* call, when the access token fails validation. This
middleware rewrites the current response to 401 once `BackstopSessionRevokedError` has marked
the request, so Unique's MCP client reconnects immediately.
"""

from typing import cast

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backstop_mcp.backstop_client import (
    mcp_session_was_revoked,
    reset_mcp_session_revoked,
    restore_mcp_session_revoked,
)

_WWW_AUTHENTICATE = b'Bearer error="invalid_token", error_description="credential_revoked"'


class SessionRevokedToUnauthorizedMiddleware:
    app: ASGIApp

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = reset_mcp_session_revoked()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and mcp_session_was_revoked():
                headers = [
                    (key, value)
                    for key, value in cast("list[tuple[bytes, bytes]]", message.get("headers", []))
                    if key.lower() != b"www-authenticate"
                ]
                headers.append((b"www-authenticate", _WWW_AUTHENTICATE))
                message = {**message, "status": 401, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            restore_mcp_session_revoked(token)
