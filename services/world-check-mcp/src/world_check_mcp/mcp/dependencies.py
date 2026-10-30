# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_access_token

from world_check_mcp.mcp.approval import ApprovalGate
from world_check_mcp.persistence import Persistence
from world_check_mcp.upstream import Upstream


def get_persistence(ctx: Context = CurrentContext()) -> Persistence:
    return cast(Persistence, ctx.lifespan_context["persistence"])


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])


def get_approvals(ctx: Context = CurrentContext()) -> ApprovalGate:
    return cast(ApprovalGate, ctx.lifespan_context["approvals"])


def get_reviewer(ctx: Context = CurrentContext()) -> str:
    """Who approved, appended to the LSEG note. The service account still performs the write."""
    if ctx.fastmcp.auth is None:
        return "local development (unauthenticated)"
    token = get_access_token()
    if token is None:
        raise ToolError("Authentication is required for regulatory decisions.")
    claims = cast(dict[str, object], token.claims)
    named = claims.get("sub")
    subject = named if isinstance(named, str) and named else token.subject
    if not isinstance(subject, str) or not subject:
        raise ToolError("The authenticated token is missing its subject claim.")
    issuer = claims.get("iss")
    where = issuer if isinstance(issuer, str) and issuer else "the configured identity provider"
    return f"Zitadel {where} subject {subject}"
