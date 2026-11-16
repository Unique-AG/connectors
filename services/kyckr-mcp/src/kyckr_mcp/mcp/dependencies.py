# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

from kyckr_mcp.persistence import Persistence
from kyckr_mcp.upstream import Upstream
from kyckr_mcp.upstream import UpstreamSettings


def get_persistence(ctx: Context = CurrentContext()) -> Persistence:
    return cast(Persistence, ctx.lifespan_context["persistence"])


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])


def get_upstream_settings(ctx: Context = CurrentContext()) -> UpstreamSettings:
    return cast(UpstreamSettings, ctx.lifespan_context["upstream_settings"])
