"""Pin incoming connections to the handshake protocol era.

FastMCP 4 answers `server/discover` with `2026-07-28`. An auto client then adopts the
sessionless era, which has no back-channel for `ctx.elicit()`. Refusing discover is the
server-side equivalent of `Client(..., mode="legacy")`: auto peers fall back to
`initialize` and elicitation stays a mid-call prompt.

A successful discover that only lists handshake versions is not enough — the probe still
locks the connection modern, and the fallback `initialize` is then rejected.
"""

from typing import Any, override

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp.shared.exceptions import MCPError
from mcp.types import METHOD_NOT_FOUND, DiscoverRequest, DiscoverResult


class HandshakeOnlyProtocolMiddleware(Middleware):
    @override
    async def on_discover(
        self,
        context: MiddlewareContext[DiscoverRequest],
        call_next: CallNext[DiscoverRequest, DiscoverResult | dict[str, Any]],
    ) -> DiscoverResult | dict[str, Any]:
        _ = context, call_next
        raise MCPError(
            code=METHOD_NOT_FOUND,
            message="This server speaks the initialize handshake only",
        )
