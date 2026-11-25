from collections.abc import Awaitable, Callable
from functools import wraps

from fastmcp.exceptions import ToolError

from kyckr_mcp.upstream import kyckr_error
from kyckr_mcp.upstream import UpstreamError


def answers_failures[**P, R](tool: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Fail the call with Kyckr's status, message and correlationId when Kyckr fails."""

    @wraps(tool)
    async def answer(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await tool(*args, **kwargs)
        except UpstreamError as error:
            # No cause in the failure log: its text holds the URL, with the company id or search.
            raise ToolError(kyckr_error(error)) from None

    return answer
