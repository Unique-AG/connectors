from typing import override

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams
from pydantic import ValidationError

from office_365_mcp.graph_client import measured_graph_operation

__all__ = ["TOOL_REFUSALS", "GraphOperationMiddleware"]

TOOL_REFUSALS: tuple[type[Exception], ...] = (ToolError, ValidationError)


class GraphOperationMiddleware(Middleware):
    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        with measured_graph_operation(context.message.name, not_failures=TOOL_REFUSALS):
            return await call_next(context)
