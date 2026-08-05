from typing import ClassVar

import structlog
from opentelemetry import trace
from starlette.types import ASGIApp, Receive, Scope, Send


class TraceContextMiddleware:
    """Bind the active span's trace id into structlog's context for the request's lifetime.

    Raw ASGI rather than Starlette's `BaseHTTPMiddleware`: that class buffers the response
    through an anyio memory stream, which interferes with the long-lived streaming responses
    the MCP HTTP transport uses. Since all this needs is to touch `scope` before delegating, it
    has no reason to sit in the response path at all.
    """

    EXCLUDED_PATHS: ClassVar[frozenset[str]] = frozenset({"/probe", "/health", "/metrics"})

    def __init__(self, app: ASGIApp) -> None:
        self.app: ASGIApp = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return

        structlog.contextvars.clear_contextvars()
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            structlog.contextvars.bind_contextvars(trace_id=format(span_context.trace_id, "032x"))
        await self.app(scope, receive, send)
