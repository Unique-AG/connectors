"""Give every MCP message the trace context of the HTTP request that carried it.

Trap: an MCP session's server task is started once, and every message for the rest of that
session's life runs inside it. `StreamableHTTPSessionManager` starts that task when the session is
created — which is during `initialize` (mcp 1.28.1, `mcp/server/streamable_http_manager.py:331`,
`await self._task_group.start(run_server)`) — and a later request on the same session is handed to
the already-running transport without starting anything (`:261`). An asyncio task snapshots the
contextvars of whoever created it, so that task, and therefore every message handler it ever runs,
carries the OpenTelemetry context that was ambient during `initialize` and no other.

What that costs: FastMCP prefers a valid ambient span over anything a message carries (fastmcp
3.4.5, `fastmcp/telemetry.py:95-98`, "Don't override existing trace context"). The stale ambient
span is the `initialize` request's server span, and it is valid. So every MCP span for the whole
life of the session — a `tools/call` an hour later included — is parented into the `initialize`
request's trace, while that call's own HTTP server span sits alone in a trace with no MCP span in
it. A session's traces come out as one ever-growing `initialize` trace plus one orphan HTTP span
per request.

Trap: bridging the incoming `traceparent` into `params._meta` does not fix this, and was measured
doing nothing at all. `extract_trace_context` consults `_meta` only when there is no valid ambient
span (`fastmcp/telemetry.py:95-98` again), and the stale one is valid. The ambient context has to be
replaced, not supplemented.

Hence two halves, which only work together:

`TraceContextCaptureMiddleware` records the ambient OpenTelemetry context on the ASGI `scope`. The
scope is per request and is not a contextvar, so it is the one channel the session task's snapshot
cannot staleen. It must be mounted INSIDE `OpenTelemetryMiddleware` — outside-in, that means listed
after it — or it captures the context from before the server span was made current and hands every
message the request's *parent* instead of the request.

`TraceContextRestoreMiddleware` reads that value back off the request now being served and attaches
it for the duration of the message, so the span FastMCP opens next parents into the request that
actually carried the message.

Neither half is redundant with the other, and neither is redundant with `OpenTelemetryMiddleware`.
Deleting either one puts the defect back silently: the spans keep being emitted and keep looking
healthy, they just go to the wrong trace, which nothing that counts spans would notice.
"""

from collections.abc import Mapping
from typing import override

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from opentelemetry import context as otel_context
from opentelemetry.context import Context

from office_mcp.asgi import ASGIApp, ASGIReceive, ASGIScope, ASGISend

__all__ = ["TraceContextCaptureMiddleware", "TraceContextRestoreMiddleware"]

# Namespaced because the scope is shared with every other middleware in the stack, this service's
# and its frameworks'. The two halves below are the only readers and the only writer.
_SCOPE_KEY = "office_mcp.otel_context"


class TraceContextCaptureMiddleware:
    """Record the ambient trace context on the scope. Mount inside `OpenTelemetryMiddleware`."""

    def __init__(self, app: ASGIApp) -> None:
        self._app: ASGIApp = app

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        # Design decision: this writes to its caller's `scope`, which the house rule against
        # mutating arguments would otherwise forbid. The ASGI scope is the protocol's own
        # per-request state channel — there is no return path from a middleware to the app it
        # wraps — and being a plain dict rather than a contextvar is the entire point: it is what
        # survives the session task's contextvar snapshot. See the module docstring.
        if scope.get("type") == "http":
            scope[_SCOPE_KEY] = otel_context.get_current()
        await self._app(scope, receive, send)


class TraceContextRestoreMiddleware(Middleware):
    """Attach the capturing middleware's context around each MCP message."""

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
    """The context recorded for the request now being served, or `None` if there is no request.

    There is no request on the stdio transport and none for an in-process client, and
    `get_http_request` says so by raising. Nothing is stale on those paths, so nothing needs
    correcting: the ambient context is already the caller's own.
    """
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    # Read through `Mapping[str, object]`: Starlette's own `Scope` alias would make this an `Any`.
    scope: Mapping[str, object] = request.scope
    captured = scope.get(_SCOPE_KEY)
    return captured if isinstance(captured, Context) else None
