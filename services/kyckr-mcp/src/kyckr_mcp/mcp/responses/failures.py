from collections.abc import Awaitable, Callable
from functools import wraps

from kyckr_mcp.mcp.responses.replies import Reply
from kyckr_mcp.upstream import kyckr_error
from kyckr_mcp.upstream import UpstreamError


def answers_failures[**P](tool: Callable[P, Awaitable[Reply]]) -> Callable[P, Awaitable[Reply]]:
    """Answer a failed Kyckr call with a failed reply rather than a tool error."""

    @wraps(tool)
    async def answer(*args: P.args, **kwargs: P.kwargs) -> Reply:
        try:
            return await tool(*args, **kwargs)
        except UpstreamError as error:
            message, correlation_id = kyckr_error(error)
            return Reply.model_validate(
                {
                    "success": False,
                    "statusCode": error.status_code,
                    "message": message,
                    "correlationId": correlation_id,
                }
            )

    return answer
