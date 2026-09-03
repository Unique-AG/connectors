from collections.abc import Awaitable, Callable
from typing import ClassVar

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from with_intelligence_mcp.db import read_session, transaction
from with_intelligence_mcp.features.auth.crypto import InvalidSessionEnvelopeError
from with_intelligence_mcp.features.auth.session_store import (
    get_session,
    lock_session,
    replace_session,
)
from with_intelligence_mcp.with_intelligence_client import VendorSession


class NotConnectedError(ToolError):
    """Raised when the caller isn't authenticated, or has no usable session on file.

    Surfaced to the MCP client as a tool error telling them to reconnect this server. With no
    stored password there is nothing to retry with, so this is the only way back.
    """


class WithIntelligenceAuthContext(BaseModel):
    """Resolves whose vendor session to use for the in-flight MCP request, and renews it.

    Satisfies the transport's expectations structurally, so that layer never imports this
    module.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    session_factory: async_sessionmaker[AsyncSession]
    encryption_key: bytes
    revoke_tokens_for_subject: Callable[[str], Awaitable[None]]

    async def current_session(self) -> VendorSession:
        """The calling user's stored vendor session, whatever its freshness."""
        subject = self.require_subject()
        async with read_session(self.session_factory) as session:
            try:
                stored = await get_session(session, subject, self.encryption_key)
            except InvalidSessionEnvelopeError as exc:
                # A rotated encryption key makes every stored session unreadable. Nothing can
                # recover it, so treat it as never having connected.
                raise NotConnectedError(
                    "Your stored With Intelligence session could not be read — please reconnect."
                ) from exc
        if stored is None:
            raise self._not_connected()
        return stored

    async def renew_session(
        self, renew: Callable[[VendorSession], Awaitable[VendorSession]]
    ) -> VendorSession:
        """Renew under a row lock, so one caller renews and the rest read the result.

        The lock is held across the vendor call on purpose (see `lock_session`), which the
        transport timeout bounds.

        A refused refresh revokes the caller's MCP tokens: without a stored password there is
        nothing to fall back on, so the client has to come back through the login form.
        """
        subject = self.require_subject()
        async with transaction(self.session_factory) as session:
            stored = await lock_session(session, subject, self.encryption_key)
            if stored is None:
                raise self._not_connected()
            if stored.is_fresh:
                # Another caller renewed while this one waited for the lock.
                return stored
            try:
                renewed = await renew(stored)
            except Exception as exc:
                await self.revoke_current_subject_tokens()
                raise NotConnectedError(
                    "Your With Intelligence session has expired and could not be renewed — "
                    + "please reconnect."
                ) from exc
            await replace_session(session, subject, renewed, self.encryption_key)
            return renewed

    def current_subject(self) -> str | None:
        access_token = get_access_token()
        return access_token.subject if access_token is not None else None

    def require_subject(self) -> str:
        subject = self.current_subject()
        if subject is None:
            raise NotConnectedError(
                "Not connected to With Intelligence yet — add this MCP server to your client "
                + "and complete the login flow first."
            )
        return subject

    async def revoke_current_subject_tokens(self) -> None:
        subject = self.current_subject()
        if subject is not None:
            await self.revoke_tokens_for_subject(subject)

    @staticmethod
    def _not_connected() -> NotConnectedError:
        return NotConnectedError(
            "No With Intelligence session on file for this connection — please reconnect."
        )
