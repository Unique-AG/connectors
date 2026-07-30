from dataclasses import dataclass

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.auth.credential_store import get_credential
from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.db.engine import get_session


class NotConnectedError(ToolError):
    """Raised when the caller isn't authenticated, or has no Backstop credential on file.

    Surfaced to the MCP client as a tool error telling them to (re)connect this server —
    see `docs/plans/2026-07-30-backstop-mcp-oauth-design.md` for the login flow this refers to.
    """


@dataclass(frozen=True)
class BackstopAuthContext:
    """The pieces `get_current_backstop_credential` needs, wired up once at app startup."""

    session_factory: async_sessionmaker[AsyncSession]
    encryption_key: bytes


_context: BackstopAuthContext | None = None


def configure(context: BackstopAuthContext) -> None:
    """Set the process-wide auth context. Call once, during `create_app()`."""
    global _context
    _context = context


async def get_current_backstop_credential() -> BackstopCredentialSecret:
    """Resolve the calling MCP user's stored Backstop credential.

    Reads the access token FastMCP has already validated for the current request (see
    `fastmcp.server.dependencies.get_access_token`) and uses its `subject` — the `user_id`
    `auth/provider.py` set when the login form was submitted — to look up and decrypt the
    matching row from `credential_store`. Call this from within a tool implementation, where
    an authenticated request is active.
    """
    assert _context is not None, "auth.context.configure() must be called during app startup"

    access_token = get_access_token()
    if access_token is None or access_token.subject is None:
        raise NotConnectedError(
            "Not connected to Backstop yet — add this MCP server to your client and "
            + "complete the login flow first."
        )

    async with get_session(_context.session_factory) as session:
        credential = await get_credential(session, access_token.subject, _context.encryption_key)

    if credential is None:
        raise NotConnectedError(
            "No Backstop credential on file for this connection — please reconnect."
        )

    return credential
