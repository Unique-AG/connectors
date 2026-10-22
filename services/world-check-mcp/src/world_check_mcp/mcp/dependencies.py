# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

from world_check_mcp.upstream import Upstream


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])
