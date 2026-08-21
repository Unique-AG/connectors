"""One bounded value for the `name` label `unique_mcp` puts on every MCP call it counts.

`unique_mcp.monitoring._McpMetrics` labels `mcp_calls_total` and `mcp_call_duration_seconds` with
the name the *client* sent, `getattr(context.message, "name", "unknown")`, read before anything has
resolved it. FastMCP builds that `MiddlewareContext` out of the raw wire name and looks the tool up
only inside `call_next`, and the MCP SDK underneath rejects nothing earlier. So one authenticated
caller sending `tools/call {"name": "aaa1"}` mints a Prometheus time series that outlives the
request and dies with the process, and the dashboard groups by that label. `resources/read` and
`prompts/get` are labelled the same way, off `str(uri)` and off the prompt name, and are as
client-chosen as the tool name is. Nothing bounds any of the three.

`BoundedNameMiddleware` replaces a name the server cannot resolve with one sentinel, so the label's
value set is the tools this deployment registered plus `UNRESOLVED_NAME`.

It has to sit outside the middleware that reads the label, which is what the `FastMCP(...)`
constructor list buys: that list is outer to anything `add_middleware` appends, and `setup_ops`
appends the metrics one. `app.py` states the ordering and `tests/test_app.py` asserts the label that
comes out, so a reordering fails there rather than in production.

Substituting the message is what makes the rename stick, and it is the whole risk. FastMCP's
innermost `call_next` re-reads `context.message.name` from the context it is handed, so a renamed
call is dispatched under the new name too. That is why the tool path resolves the name first and
renames only a call that was going to be refused. What the caller reads is unchanged:
`_call_tool_mcp` builds `Unknown tool: {key!r}` from the original request params, outside this
chain.

The real fix belongs upstream. `unique_mcp` is a first-party Unique package, and the label belongs
on the component the call resolved to, or its middleware takes a name-normaliser hook. Delete this
module when either lands.
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

# What an unresolvable name is counted as. The angle brackets keep it from colliding with a
# registered tool, whose name comes from a Python function and is therefore an identifier, and they
# read as a bucket rather than as a tool in a legend grouped by `name`. Deliberately not `unknown`,
# which is `unique_mcp`'s own fallback for a message that carried no name at all: one says the
# client asked for something that does not exist, the other says the message had no name to read.
UNRESOLVED_NAME = "<unknown>"


class BoundedNameMiddleware(Middleware):
    """Rename a call the server cannot resolve, before its name becomes a metric label."""

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        fastmcp_context = context.fastmcp_context
        assert fastmcp_context is not None, "tools/call reached middleware with no server context"
        # The question dispatch asks first, one layer earlier: `call_tool` resolves the name with
        # `get_tool` and raises `NotFoundError` when that finds nothing. Asked of the server rather
        # than of the resolved `Selection` deliberately: the selection knows what `register_tools`
        # registered, not what this server will dispatch, and the two differ the moment anything is
        # mounted (`setup_ops` mounts its own server after this middleware is built). Anything that
        # would have run still runs, under its own name.
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
        # Resolved first, exactly as the tool path is. This server registers no resources today, so
        # every one of these is unresolvable and the branch below is the only one taken. Resolving
        # first keeps that a fact about the registry rather than an assumption baked into this
        # module, and the Outlook and SharePoint surfaces are what will change it.
        #
        # `uri` is typed `AnyUrl` and the substitution puts a `str` there. `model_copy` does not
        # validate, and both readers of the field, the metrics label and FastMCP's own `call_next`,
        # reach it through `str()`, so the substitution is total.
        #
        # One cost the tool path does not have: upstream words the "not found" out of the exception
        # rather than the original params, so the caller sees the sentinel instead of the URI they
        # sent. Only a request that was going to be refused pays it.
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


# What a request nobody routed is counted as, and what a method nobody serves is counted as.
# Sentinels for the same reason as `UNRESOLVED_NAME`: a bucket a reader can see, spelled so it
# cannot collide with a real route or a real method.
UNMATCHED_PATH = "__unmatched__"
UNMATCHED_METHOD = "__other__"

# The methods this service serves. Anything else is a word the client made up: h11 accepts any
# RFC 7230 token, so `method` is as client-chosen as `path` is, and it multiplies against it.
_SERVED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

type _Scope = MutableMapping[str, object]
type _Message = MutableMapping[str, object]
type _Receive = Callable[[], Awaitable[_Message]]
type _Send = Callable[[_Message], Awaitable[None]]
type _ASGIApp = Callable[[_Scope, _Receive, _Send], Awaitable[None]]


class BoundedRequestMiddleware:
    """Collapse an unrouted path and an unserved method before either becomes a metric label.

    `unique_toolkit.monitoring.MetricsMiddleware` labels `python_http_requests_total` and
    `python_http_request_duration_seconds` with `scope["path"]` and `scope["method"]`, both exactly
    as the client sent them. This service publishes its OAuth endpoints on the public internet, so
    both labels are reachable without a credential: one `GET /wp-login.php` from a scanner mints a
    counter series and a whole histogram that outlive the request and die with the process. It is
    the same defect as the MCP `name` label above, one layer down and larger, because that one needs
    a session and this one needs nothing.

    The router decides, not a list kept here. `route.matches(scope)` is the same question
    Starlette's own router asks, so this class cannot disagree with it about which paths exist, and
    a real route mistaken for an unrouted one would 404 a working endpoint. It refuses nothing
    either: it rewrites and passes through, so a route somebody forgets to register still answers
    404 exactly as before instead of becoming an outage. A hand-written set of known paths in front
    of the router is what both failures look like.

    It hands the app a copy, never a mutated scope. The house rule against mutating arguments holds
    here with no exception, unlike `tracing.py`, because there is something to hand down: the inner
    app reads whatever scope it is given.

    Mounted second, inside the request-id middleware and outside everything else. Inside, because
    the log line and uvicorn's access line are where the real path has to survive: an operator
    reading a 404 flood needs the paths, and a label is the one place they must not accumulate.
    Outside the rest, because `OpenTelemetryMiddleware` names its span and sets `url.full` from that
    same `scope["path"]`, and a trace backend keeps a span attribute as long as Prometheus keeps a
    series.

    The real fix belongs upstream, in `unique_toolkit`: label with `scope["path"]` only when routing
    matched (Starlette leaves `endpoint` in the scope when it does), and clamp the method there.
    That fixes every Unique service at once. Delete this class when it lands.
    """

    def __init__(self, app: _ASGIApp) -> None:
        self._app: _ASGIApp = app

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        await self._app({**scope, **self._bounded(scope)}, receive, send)

    def _bounded(self, scope: _Scope) -> dict[str, object]:
        """The label-bearing keys to replace on this request, and nothing else."""
        bounded: dict[str, object] = {}
        method = scope.get("method")
        if method not in _SERVED_METHODS:
            bounded["method"] = UNMATCHED_METHOD
        if not self._routed(scope):
            # `raw_path` too: it is the same URL in bytes, so bounding `path` alone would leave the
            # client's real URL in the scope for anything downstream that reads the bytes.
            bounded["path"] = UNMATCHED_PATH
            bounded["raw_path"] = UNMATCHED_PATH.encode()
        return bounded

    def _routed(self, scope: _Scope) -> bool:
        """Whether Starlette's own router has a route for this request.

        `Match.PARTIAL` counts as routed: the path exists and only the method is wrong, so the path
        is one of this service's own and belongs under its own label. The method is bounded
        separately, which is what stops `BANANA /mcp` from being an unbounded pair.
        """
        app = scope.get("app")
        routes: list[BaseRoute] = getattr(app, "routes", [])
        return any(route.matches(scope)[0] is not Match.NONE for route in routes)
