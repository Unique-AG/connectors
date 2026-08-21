"""Give every MCP message the trace context of the HTTP request that carried it.

Trap: an MCP session's server task is started once, during `initialize`, and every message for the
rest of that session's life runs inside it (mcp 1.28.1,
`mcp/server/streamable_http_manager.py:331`; a later request on the same session starts nothing,
`:261`). An asyncio task snapshots the contextvars of whoever created it, so every message handler
carries the OpenTelemetry context that was ambient during `initialize` and no other. FastMCP
prefers a valid ambient span over anything a message carries (fastmcp 3.4.5,
`fastmcp/telemetry.py:95-98`) and that stale one is valid, so a session's traces come out as one
ever-growing `initialize` trace plus one orphan HTTP span per request.

Bridging the incoming `traceparent` into `params._meta` was tried and measured doing nothing:
`extract_trace_context` consults `_meta` only when there is no valid ambient span. The ambient
context has to be replaced, not supplemented.

Hence two halves. `TraceContextCaptureMiddleware` records the ambient context on the ASGI `scope`,
which is per request and not a contextvar, so the session task's snapshot cannot make it stale; it
must be mounted INSIDE `OpenTelemetryMiddleware`, which for an outside-in Starlette list means
listed after it, or it captures the context from before the server span was made current and hands
every message the request's *parent*. `TraceContextRestoreMiddleware` reads that value back off the
request now being served and attaches it for the duration of the message.
"""

from collections.abc import Mapping
from typing import override

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from opentelemetry import context as otel_context
from opentelemetry.context import Context

from office_mcp.asgi import ASGIApp, ASGIReceive, ASGIScope, ASGISend

__all__ = ["TraceContextCaptureMiddleware", "TraceContextRestoreMiddleware"]

_SCOPE_KEY = "office_mcp.otel_context"


class TraceContextCaptureMiddleware:
    """Records the ambient context on the ASGI scope. Half of a pair; see the module docstring."""

    def __init__(self, app: ASGIApp) -> None:
        self._app: ASGIApp = app

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        # Writes to the caller's `scope`, against the house rule on arguments: ASGI gives a
        # middleware no return path, and a plain dict is what survives the session task's snapshot.
        if scope.get("type") == "http":
            scope[_SCOPE_KEY] = otel_context.get_current()
        await self._app(scope, receive, send)


class TraceContextRestoreMiddleware(Middleware):
    """Reads that context back and makes it current. Deleting either half restores the defect
    silently: the spans still look healthy, they just land in the wrong trace."""

    @override
    async def on_message(
        self,
        context: MiddlewareContext[object],
        call_next: CallNext[object, object],
    ) -> object:
        captured = _captured_trace_context()
        if captured is None:
            return await call_next(context)
        token = otel_context.attach(captured)
        try:
            return await call_next(context)
        finally:
            otel_context.detach(token)


def _captured_trace_context() -> Context | None:
    """`get_http_request` raises on the stdio transport and for an in-process client. Nothing is
    stale on those paths, so `None` leaves the caller's own ambient context alone."""
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    scope: Mapping[str, object] = request.scope
    captured = scope.get(_SCOPE_KEY)
    return captured if isinstance(captured, Context) else None
