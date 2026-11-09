# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import Upstream


def get_persistence(ctx: Context = CurrentContext()) -> Persistence:
    return cast(Persistence, ctx.lifespan_context["persistence"])


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])
