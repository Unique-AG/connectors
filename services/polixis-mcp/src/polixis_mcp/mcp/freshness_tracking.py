from typing import override

from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
import mcp_types as mt

from polixis_mcp import contexts


class FreshnessTracking(Middleware):
    """Records the cached Polixis answers each tool call reads, so its result can say whether its
    data came from the cache and when that was cached.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        with contexts.tracking_freshness():
            return await call_next(context)
