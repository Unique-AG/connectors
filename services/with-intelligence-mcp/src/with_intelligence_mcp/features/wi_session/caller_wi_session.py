from with_intelligence_mcp.features.auth import WithIntelligenceAuthContext
from with_intelligence_mcp.features.wi_session.wi_session_cache import WiSessionCache


class CallerWiSession:
    """Provides the current caller's WI access token."""

    def __init__(self, cache: WiSessionCache, context: WithIntelligenceAuthContext) -> None:
        self._cache: WiSessionCache = cache
        self._context: WithIntelligenceAuthContext = context

    async def access_token(self) -> str:
        return await self._cache.access_token(
            self.subject(), self._context.current_session, self._context.renew_session
        )

    async def renewed_access_token(self) -> str:
        return await self._cache.renewed_access_token(
            self.subject(), self._context.current_session, self._context.renew_session
        )

    def subject(self) -> str:
        """Who the token belongs to. Also keys the per-caller concurrency gate."""
        return self._context.require_subject()
