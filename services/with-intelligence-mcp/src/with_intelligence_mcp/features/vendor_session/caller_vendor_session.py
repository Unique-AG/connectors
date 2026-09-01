from with_intelligence_mcp.features.auth import NotConnectedError, WithIntelligenceAuthContext
from with_intelligence_mcp.features.vendor_session.vendor_session_registry import (
    VendorSessionRegistry,
)


class CallerVendorSession:
    """The `CallerSession` the transport asks for a token: whoever is calling right now.

    Satisfies the transport's Protocol structurally. The credential is fetched lazily, and only
    when a sign-in is actually needed, so a request served from a live session never touches the
    database or the encryption key.
    """

    def __init__(
        self, registry: VendorSessionRegistry, context: WithIntelligenceAuthContext
    ) -> None:
        self._registry: VendorSessionRegistry = registry
        self._context: WithIntelligenceAuthContext = context

    async def access_token(self) -> str:
        return await self._registry.access_token(self.subject(), self._context.current_credential)

    async def renewed_access_token(self) -> str:
        return await self._registry.renewed_access_token(
            self.subject(), self._context.current_credential
        )

    def subject(self) -> str:
        """Who the token belongs to. Also keys the per-caller concurrency gate."""
        subject = self._context.current_subject()
        if subject is None:
            raise NotConnectedError(
                "Not connected to With Intelligence yet — add this MCP server to your client "
                + "and complete the login flow first."
            )
        return subject
