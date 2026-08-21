from collections.abc import Awaitable, Callable
from typing import ClassVar

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopCredentialSecret
from backstop_mcp.db import read_session
from backstop_mcp.features.auth.credential_store import get_credential


class NotConnectedError(ToolError):
    """Raised when the caller isn't authenticated, or has no Backstop credential on file.

    Surfaced to the MCP client as a tool error telling them to (re)connect this server —
    see `auth/provider.py` for the login flow this refers to.
    """


def current_subject() -> str | None:
    """Return the MCP access-token subject for the active request, if any."""
    access_token = get_access_token()
    return access_token.subject if access_token is not None else None


class BackstopAuthContext(BaseModel):
    """Resolves "whose Backstop credential" for the in-flight MCP request.

    The concrete implementation of `backstop_client.credential.CallerAuthContext` — satisfied
    structurally, so the transport layer never imports this module. Constructed once in
    `create_app()` and handed to `BackstopClientFactory`; there is no module-level instance.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    session_factory: async_sessionmaker[AsyncSession]
    encryption_key: bytes
    revoke_tokens_for_subject: Callable[[str], Awaitable[None]]

    async def current_credential(self) -> BackstopCredentialSecret:
        """Resolve the calling MCP user's stored Backstop credential.

        Reads the access token FastMCP has already validated for the current request (see
        `fastmcp.server.dependencies.get_access_token`) and uses its `subject` — the `user_id`
        `auth/provider.py` set when the login form was submitted — to look up and decrypt the
        matching row from `credential_store`. Call this from within a tool implementation,
        where an authenticated request is active.
        """
        subject = current_subject()
        if subject is None:
            raise NotConnectedError(
                "Not connected to Backstop yet — add this MCP server to your client and "
                + "complete the login flow first."
            )

        async with read_session(self.session_factory) as session:
            credential = await get_credential(session, subject, self.encryption_key)

        if credential is None:
            raise NotConnectedError(
                "No Backstop credential on file for this connection — please reconnect."
            )

        return credential

    async def revoke_current_subject_tokens(self) -> None:
        """Revoke MCP tokens for the active subject after a mid-session Backstop 401."""
        subject = current_subject()
        if subject is not None:
            await self.revoke_tokens_for_subject(subject)
