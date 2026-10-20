from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


def get_persistence(ctx: Context = CurrentContext()) -> Persistence:
    return cast(Persistence, ctx.lifespan_context["persistence"])


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])
