"""One bounded value for the `name` label `unique_mcp` puts on every MCP call it counts.

`unique_mcp.monitoring._McpMetrics` labels `mcp_calls_total` and `mcp_call_duration_seconds` with
the name the **client** sent — `getattr(context.message, "name", "unknown")`, read before anything
has resolved it. FastMCP builds that `MiddlewareContext` out of the raw wire name and only looks the
tool up inside `call_next`, and the MCP SDK underneath rejects nothing earlier either. So one
authenticated caller sending `tools/call {"name": "aaa1"}` mints a Prometheus time series that
outlives the request and dies with the process, and the dashboard groups by exactly that label
(`sum by (name) (rate(mcp_calls_total{…}[5m]))`, twice). `resources/read` and `prompts/get` are
labelled the same way, off `str(uri)` and off the prompt name, and are as client-chosen as the tool
name is. Nothing bounds any of the three.

This middleware replaces a name the server cannot resolve with one sentinel, so the label's value
set is the tools this deployment registered plus `UNRESOLVED_NAME`.

**It only works from outside the middleware that reads the label**, which is what mounting it in the
`FastMCP(...)` constructor list buys: that list is outer to anything `add_middleware` appends, and
`setup_ops` appends the metrics one. `app.py` states the ordering and `tests/test_app.py` asserts
the label that actually comes out, so a reordering fails there rather than in production.

**Substituting the message is what makes the substitution stick, and is also the whole risk.**
FastMCP's innermost `call_next` re-reads `context.message.name` from the context it is handed, so a
renamed call is *dispatched* under the new name too — which is why the tool path resolves the name
against the server first and only replaces one that was going to be refused anyway. What the caller
reads is unchanged: `_call_tool_mcp` builds `Unknown tool: {key!r}` from the original request
params, outside this chain entirely.

**The real fix belongs upstream.** `unique_mcp` is a first-party Unique package, and the label
belongs on the component the call resolved to — or its middleware takes a name-normaliser hook.
Delete this module when either lands.
"""

from typing import override

from fastmcp.prompts.base import PromptResult
from fastmcp.resources.base import ResourceResult
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams, GetPromptRequestParams, ReadResourceRequestParams

__all__ = ["UNRESOLVED_NAME", "BoundedNameMiddleware"]

# What an unresolvable name is counted as. The angle brackets are what keep it from colliding with a
# registered tool — a tool is registered from a Python function and its name is an identifier — and
# they read as a bucket rather than as a tool in a legend grouped by `name`. Deliberately not
# `unknown`, which is `unique_mcp`'s own fallback for a message that carried no name at all: one
# says the client asked for something that does not exist, the other says the message had no name to
# read, and a dashboard that cannot tell them apart is one label worse off.
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
        # The same question dispatch asks first, asked one layer earlier: `call_tool` resolves the
        # name with `get_tool` and raises `NotFoundError` when that is None. Asked of the server
        # rather than of the resolved `Selection` deliberately — the selection knows what this
        # module registered, not what this server will dispatch, and the two differ the moment
        # anything is mounted (`setup_ops` mounts its own server after this middleware is built).
        # Anything that would have run still runs, under its own name.
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
        # Pinned rather than resolved, because this server registers no resources and no prompts:
        # every one of these names something that does not exist, so there is nothing to look up
        # and nothing that can be broken by not looking. The cost is that the "not found" the
        # caller reads names the sentinel instead of what they asked for — upstream builds those
        # two messages out of the exception rather than out of the original params, unlike the tool
        # one. `tests/test_app.py` fails the day either surface gains a member, which is when this
        # needs the tool path's resolve-first shape and the caller's string back.
        #
        # `uri` is typed `AnyUrl` and this puts a `str` there. `model_copy` does not validate, and
        # both readers of the field — the metrics label and FastMCP's own `call_next` — reach it
        # through `str()`, so the substitution is total.
        renamed = context.message.model_copy(update={"uri": UNRESOLVED_NAME})
        return await call_next(context.copy(message=renamed))

    @override
    async def on_get_prompt(
        self,
        context: MiddlewareContext[GetPromptRequestParams],
        call_next: CallNext[GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        renamed = context.message.model_copy(update={"name": UNRESOLVED_NAME})
        return await call_next(context.copy(message=renamed))
