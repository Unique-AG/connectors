# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_access_token

from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream

# Without auth the server only serves on loopback, to the one person running it.
LOCAL_OWNER = "local"


def get_persistence(ctx: Context = CurrentContext()) -> Persistence:
    return cast(Persistence, ctx.lifespan_context["persistence"])


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])


def get_owner() -> str:
    """The Zitadel user id of the caller, which owns what the caller stores.

    A tool hands it to the context as a plain string, so no token reaches the domain.
    """
    token = get_access_token()
    if token is None:
        return LOCAL_OWNER
    subject = token.claims.get("sub")
    assert isinstance(subject, str), "a verified Zitadel token always names its subject"
    return subject
