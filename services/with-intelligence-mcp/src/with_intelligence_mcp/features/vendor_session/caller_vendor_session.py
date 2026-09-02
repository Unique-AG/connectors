from with_intelligence_mcp.features.auth import WithIntelligenceAuthContext
from with_intelligence_mcp.features.vendor_session.vendor_session_registry import (
    VendorSessionRegistry,
)


class CallerVendorSession:
    """The `CallerSession` the transport asks for a token: whoever is calling right now.

    Satisfies the transport's Protocol structurally. Reading and renewing are handed to the
    auth context as callables, so this class never touches the database or the encryption key
    and the registry never learns what a subject is.
    """

    def __init__(
        self, registry: VendorSessionRegistry, context: WithIntelligenceAuthContext
    ) -> None:
        self._registry: VendorSessionRegistry = registry
        self._context: WithIntelligenceAuthContext = context

    async def access_token(self) -> str:
        return await self._registry.access_token(
            self.subject(), self._context.current_session, self._context.renew_session
        )

    async def renewed_access_token(self) -> str:
        return await self._registry.renewed_access_token(
            self.subject(), self._context.current_session, self._context.renew_session
        )

    def subject(self) -> str:
        """Who the token belongs to. Also keys the per-caller concurrency gate."""
        return self._context.require_subject()
