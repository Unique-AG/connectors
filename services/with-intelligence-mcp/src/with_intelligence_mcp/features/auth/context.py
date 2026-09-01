from collections.abc import Awaitable, Callable
from typing import ClassVar

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from with_intelligence_mcp.db import read_session
from with_intelligence_mcp.features.auth.credential_store import get_credential
from with_intelligence_mcp.with_intelligence_client import VendorCredential


class NotConnectedError(ToolError):
    """Raised when the caller isn't authenticated, or has no credential on file.

    Surfaced to the MCP client as a tool error telling them to reconnect this server.
    """


class WithIntelligenceAuthContext(BaseModel):
    """Resolves whose credential to use for the in-flight MCP request.

    Satisfies `with_intelligence_client.credential`'s expectations structurally, so the
    transport layer never imports this module.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    session_factory: async_sessionmaker[AsyncSession]
    encryption_key: bytes
    revoke_tokens_for_subject: Callable[[str], Awaitable[None]]

    async def current_credential(self) -> VendorCredential:
        """The calling MCP user's stored username and password.

        Reads the access token FastMCP has already validated for this request and uses its
        `subject` — the `user_id` the login form resolved — to look up and decrypt the row.
        """
        subject = self.current_subject()
        if subject is None:
            raise NotConnectedError(
                "Not connected to With Intelligence yet — add this MCP server to your client "
                + "and complete the login flow first."
            )

        async with read_session(self.session_factory) as session:
            credential = await get_credential(session, subject, self.encryption_key)

        if credential is None:
            raise NotConnectedError(
                "No With Intelligence credential on file for this connection — please reconnect."
            )

        return credential

    def current_subject(self) -> str | None:
        access_token = get_access_token()
        return access_token.subject if access_token is not None else None

    async def revoke_current_subject_tokens(self) -> None:
        """Revoke MCP tokens for the active subject once their stored password stops working."""
        subject = self.current_subject()
        if subject is not None:
            await self.revoke_tokens_for_subject(subject)
