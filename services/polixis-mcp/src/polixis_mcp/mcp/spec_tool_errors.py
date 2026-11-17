from typing import override

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
import httpx2
import mcp_types as mt

from polixis_mcp import contexts


class SpecToolErrors(Middleware):
    """A tool served from the spec fails on an error status with FastMCP's `HTTPStatusError`,
    which `mask_error_details` turns into a bare `ToolError` naming only the tool. Its message is
    the status and up to 1,000 characters of Polixis's body, such as the former members of a
    dissolved pid, so this puts it back. Our own tools raise an `UpstreamError`, a subclass,
    which reaches the client as it is. A paged tool's `ResultChangedError`, which tells the
    agent to page again from the start, is put back the same way.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except ToolError as error:
            cause = error.__cause__
            if type(error) is ToolError and isinstance(
                cause, httpx2.HTTPStatusError | contexts.ResultChangedError
            ):
                raise ToolError(str(cause)) from cause
            raise
