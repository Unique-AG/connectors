"""Give every MCP message the trace context of the HTTP request that carried it.

A session's server task starts once, during `initialize`, and runs every later message inside
it (mcp 2.1.1, `mcp/server/streamable_http_manager.py:353`; a later request on the same session
starts nothing new, `:257`), so its ambient OpenTelemetry context is permanently stale, and
FastMCP prefers a valid ambient span (fastmcp 4.0.2, `fastmcp/telemetry.py:281-282`).
`TraceContextCaptureMiddleware` goes after `OpenTelemetryMiddleware`, or it captures the
request's parent.
"""

from collections.abc import Mapping
from typing import override

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from opentelemetry import context as otel_context
from opentelemetry.context import Context

from office_365_mcp.asgi import ASGIApp, ASGIReceive, ASGIScope, ASGISend

__all__ = ["TraceContextCaptureMiddleware", "TraceContextRestoreMiddleware"]

_SCOPE_KEY = "office_365_mcp.otel_context"


class TraceContextCaptureMiddleware:
    """Records the ambient context on the ASGI scope. Half of a pair. See the module docstring."""

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
