from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

from tiingo_mcp.helpers.upstream import OperationClient


def get_api(ctx: Context = CurrentContext()) -> OperationClient:
    return ctx.lifespan_context["api"]
