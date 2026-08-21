"""One bounded value for the `name` label `unique_mcp` puts on every MCP call it counts.

`unique_mcp.monitoring._McpMetrics` labels `mcp_calls_total` and `mcp_call_duration_seconds` with
`getattr(context.message, "name", "unknown")` — the name the *client* sent, read before FastMCP has
resolved it — so one authenticated caller sending `tools/call {"name": "aaa1"}` mints a Prometheus
series that dies only with the process. `resources/read` and `prompts/get` are labelled the same
way, off `str(uri)` and off the prompt name.

This has to sit outside the middleware that reads the label: the `FastMCP(...)` constructor list is
outer to anything `add_middleware` appends, and `setup_ops` appends the metrics one. `app.py` states
that ordering and `tests/test_app.py` asserts the label that comes out.

Trap: substituting the message is what makes the rename stick — FastMCP's innermost `call_next`
re-reads `context.message.name` and dispatches under the new name. Hence each handler resolves
first and renames only a call that was going to be refused. What the caller reads is unchanged:
`_call_tool_mcp` builds `Unknown tool: {key!r}` from the original request params, outside this
chain.

The real fix belongs upstream in `unique_mcp`: label the component the call resolved to, or take a
name-normaliser hook. Delete this module when either lands.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import override

from fastmcp.prompts.base import PromptResult
from fastmcp.resources.base import ResourceResult
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams, GetPromptRequestParams, ReadResourceRequestParams
from starlette.routing import BaseRoute, Match

__all__ = [
    "UNMATCHED_METHOD",
    "UNMATCHED_PATH",
    "UNRESOLVED_NAME",
    "BoundedNameMiddleware",
    "BoundedRequestMiddleware",
]

# Angle brackets so it cannot collide with a registered tool, whose name is a Python identifier.
# Deliberately not `unknown`, which is `unique_mcp`'s own fallback for a message that carried no
# name at all.
UNRESOLVED_NAME = "<unknown>"


class BoundedNameMiddleware(Middleware):
    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        fastmcp_context = context.fastmcp_context
        assert fastmcp_context is not None, "tools/call reached middleware with no server context"
        # Asked of the server, not of the resolved `Selection`: the selection knows what
        # `register_tools` registered, not what this server will dispatch, and the two differ the
        # moment anything is mounted (`setup_ops` mounts its own server after this is built).
        if await fastmcp_context.fastmcp.get_tool(context.message.name) is not None:
            return await call_next(context)
        renamed = context.message.model_copy(update={"name": UNRESOLVED_NAME})
        return await call_next(context.copy(message=renamed))

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[ReadResourceRequestParams],
        call_next: CallNext[ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        # Trap: `uri` is typed `AnyUrl` and this puts a `str` there. `model_copy` does not validate,
        # and both readers — the metrics label and FastMCP's own `call_next` — reach it via `str()`.
        #
        # Unlike the tool path, upstream words the "not found" out of the exception rather than the
        # original params, so a refused caller sees the sentinel instead of the URI they sent.
        fastmcp_context = context.fastmcp_context
        assert fastmcp_context is not None, (
            "resources/read reached middleware with no server context"
        )
        if await fastmcp_context.fastmcp.get_resource(str(context.message.uri)) is not None:
            return await call_next(context)
        renamed = context.message.model_copy(update={"uri": UNRESOLVED_NAME})
        return await call_next(context.copy(message=renamed))

    @override
    async def on_get_prompt(
        self,
        context: MiddlewareContext[GetPromptRequestParams],
        call_next: CallNext[GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        fastmcp_context = context.fastmcp_context
        assert fastmcp_context is not None, "prompts/get reached middleware with no server context"
        if await fastmcp_context.fastmcp.get_prompt(context.message.name) is not None:
            return await call_next(context)
        renamed = context.message.model_copy(update={"name": UNRESOLVED_NAME})
        return await call_next(context.copy(message=renamed))


UNMATCHED_PATH = "__unmatched__"
UNMATCHED_METHOD = "__other__"

# h11 accepts any RFC 7230 token, so `method` is as client-chosen as `path`, and multiplies with it.
_SERVED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

type _Scope = MutableMapping[str, object]
type _Message = MutableMapping[str, object]
type _Receive = Callable[[], Awaitable[_Message]]
type _Send = Callable[[_Message], Awaitable[None]]
type _ASGIApp = Callable[[_Scope, _Receive, _Send], Awaitable[None]]


class BoundedRequestMiddleware:
    """Collapse an unrouted path and an unserved method before either becomes a metric label.

    `unique_toolkit.monitoring.MetricsMiddleware` labels `python_http_requests_total` and
    `python_http_request_duration_seconds` with `scope["path"]` and `scope["method"]` exactly as the
    client sent them, and this service's OAuth endpoints are on the public internet: one
    `GET /wp-login.php` from a scanner mints a counter series and a whole histogram.

    `route.matches(scope)` is the same question Starlette's own router asks, so this cannot disagree
    with it about which paths exist; and it rewrites rather than refuses, so a route somebody forgot
    to register still 404s instead of becoming an outage. A hand-written set of known paths in front
    of the router is what both failures look like.

    Mounted second: inside the request-id middleware, because the log line and uvicorn's access line
    are where the real path has to survive; outside everything else, because
    `OpenTelemetryMiddleware` names its span and sets `url.full` from that same `scope["path"]`.

    The real fix belongs upstream, in `unique_toolkit`: label with `scope["path"]` only when routing
    matched (Starlette leaves `endpoint` in the scope when it does), and clamp the method there.
    Delete this class when it lands.
    """

    def __init__(self, app: _ASGIApp) -> None:
        self._app: _ASGIApp = app

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        await self._app({**scope, **self._bounded(scope)}, receive, send)

    def _bounded(self, scope: _Scope) -> dict[str, object]:
        bounded: dict[str, object] = {}
        method = scope.get("method")
        if method not in _SERVED_METHODS:
            bounded["method"] = UNMATCHED_METHOD
        if not self._routed(scope):
            # `raw_path` too, or the client's real URL stays in the scope for anything reading it.
            bounded["path"] = UNMATCHED_PATH
            bounded["raw_path"] = UNMATCHED_PATH.encode()
        return bounded

    def _routed(self, scope: _Scope) -> bool:
        """`Match.PARTIAL` counts as routed: the path exists and only the method is wrong. The
        method is bounded separately, which is what stops `BANANA /mcp` being an unbounded pair."""
        app = scope.get("app")
        routes: list[BaseRoute] = getattr(app, "routes", [])
        return any(route.matches(scope)[0] is not Match.NONE for route in routes)
