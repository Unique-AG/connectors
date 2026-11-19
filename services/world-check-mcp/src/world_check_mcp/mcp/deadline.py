import asyncio
from typing import override

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
import mcp_types as mt

# Unique's client gives up on a tool call after 60 seconds, so a call that runs longer only does
# its work for nobody. A tool that waits for a human is not bound by it.
TOOL_DEADLINE_SECONDS = 50.0
WAITS_FOR_A_PERSON = frozenset({"resolve_result", "verify_passport_check"})


class ToolDeadlineMiddleware(Middleware):
    """Stops a tool call that outlasts the client's own timeout, with an error that says so."""

    _seconds: float
    _exempt: frozenset[str]

    def __init__(
        self,
        seconds: float = TOOL_DEADLINE_SECONDS,
        *,
        exempt: frozenset[str] = WAITS_FOR_A_PERSON,
    ) -> None:
        super().__init__()
        self._seconds = seconds
        self._exempt = exempt

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        if name in self._exempt:
            return await call_next(context)
        try:
            async with asyncio.timeout(self._seconds):
                return await call_next(context)
        except TimeoutError as error:
            raise ToolError(
                f"{name} did not finish within {self._seconds:g} seconds. A write may still "
                "have gone through: check with get_case or search_cases before retrying."
            ) from error
