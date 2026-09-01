"""A `CallerSession` backed by one credential from configuration.

**Interim.** It authenticates every MCP caller as a single shared account, which is not what
this connector is meant to do — a hosted login form per user, with the session encrypted per
user in Postgres, replaces it. It exists so tools can be built and run against real data before
that lands, and because it holds the token exactly the way the per-user store will have to: one
holder, one lock, renewed under it.

That replacement is this class and nothing else — tools depend on the `CallerSession` Protocol,
not on this.
"""

import asyncio
import logging

from with_intelligence_mcp.with_intelligence_client import (
    SignInFailed,
    VendorCredential,
    VendorSession,
    WithIntelligenceClientFactory,
)

logger = logging.getLogger(__name__)

SERVICE_ACCOUNT_SUBJECT = "service-account"


class ServiceAccountSession:
    """Holds one vendor session, signing in on first use and renewing under a lock.

    The lock is the point. Several tool calls can find the token expired at once, and each
    would otherwise spend the refresh token independently. Whoever takes the lock second finds
    a fresh session already there and uses it.
    """

    def __init__(
        self, factory: WithIntelligenceClientFactory, credential: VendorCredential | None
    ) -> None:
        self._factory: WithIntelligenceClientFactory = factory
        self._credential: VendorCredential | None = credential
        self._session: VendorSession | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def access_token(self) -> str:
        session = self._session
        if session is not None and session.is_fresh:
            return session.access_token.get_secret_value()
        return await self._renew(stale=session)

    async def renewed_access_token(self) -> str:
        return await self._renew(stale=self._session)

    def subject(self) -> str:
        return SERVICE_ACCOUNT_SUBJECT

    def _require_credential(self) -> VendorCredential:
        """Checked here rather than when the provider is built, so an unconfigured deployment
        fails with this sentence instead of a dependency-resolution error."""
        if self._credential is None:
            raise SignInFailed(
                "WITH_INTELLIGENCE_USERNAME and WITH_INTELLIGENCE_PASSWORD are not set. This "
                + "service needs them until the per-user login form lands."
            )
        return self._credential

    async def _renew(self, *, stale: VendorSession | None) -> str:
        async with self._lock:
            current = self._session
            if current is not None and current is not stale and current.is_fresh:
                return current.access_token.get_secret_value()

            if current is not None:
                try:
                    self._session = await self._factory.refresh(current)
                    logger.info("vendor_session.refreshed")
                    return self._session.access_token.get_secret_value()
                except Exception:
                    logger.warning("vendor_session.refresh_failed", exc_info=True)

            self._session = await self._factory.sign_in(self._require_credential())
            logger.info("vendor_session.signed_in")
            return self._session.access_token.get_secret_value()
