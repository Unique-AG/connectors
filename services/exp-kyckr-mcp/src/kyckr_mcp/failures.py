from collections.abc import Awaitable, Callable
from functools import wraps
from typing import get_type_hints

from mcp_openapi.upstream import UpstreamError

from kyckr_mcp.client import KyckrApiError
from kyckr_mcp.models.replies import Reply


def _failure(error: KyckrApiError | UpstreamError) -> dict[str, object]:
    if isinstance(error, KyckrApiError):
        return {
            "success": False,
            "statusCode": error.status,
            "message": str(error),
            "correlationId": error.correlation_id,
        }
    return {"success": False, "message": str(error)}


def answers_failures[**P, R: Reply](tool: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Answer a failed Kyckr call with a failed reply of the tool's return type."""
    reply_type = get_type_hints(tool)["return"]

    @wraps(tool)
    async def answer(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await tool(*args, **kwargs)
        except (KyckrApiError, UpstreamError) as error:
            return reply_type(**_failure(error))

    return answer
