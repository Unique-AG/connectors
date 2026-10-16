from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context
from mcp_openapi.upstream import OperationClient

from kyckr_mcp.settings import Settings


def get_api(ctx: Context = CurrentContext()) -> OperationClient:
    return ctx.lifespan_context["api"]


def get_settings(ctx: Context = CurrentContext()) -> Settings:
    return ctx.lifespan_context["settings"]
