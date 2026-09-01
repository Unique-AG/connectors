"""One live vendor session per authenticated user, renewed under a lock.

The lock is the point. With Intelligence access tokens live an hour, so several of one user's
tool calls can find theirs expired at once, and each would otherwise spend the refresh token
independently. Whoever takes the lock second finds the fresh session already there.

Sessions are held in memory only. What is persisted is the password (see
`features/auth/credential_store.py`), so a restart costs one sign-in rather than a re-login:
storing a 1-hour access token would expire long before the row was read again.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from with_intelligence_mcp.with_intelligence_client import (
    VendorCredential,
    VendorSession,
    WithIntelligenceClientFactory,
)

logger = logging.getLogger(__name__)

# Well above any plausible concurrent user count for one process; exists so a long-lived
# process with high user churn cannot grow the registry without bound.
MAX_TRACKED_SUBJECTS = 512

type CredentialProvider = Callable[[], Awaitable[VendorCredential]]


@dataclass
class _Holder:
    session: VendorSession | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    in_flight: int = 0


class VendorSessionRegistry:
    """Vendor sessions keyed by MCP subject."""

    def __init__(self, factory: WithIntelligenceClientFactory) -> None:
        self._factory: WithIntelligenceClientFactory = factory
        self._holders: dict[str, _Holder] = {}
        self._registry_lock: asyncio.Lock = asyncio.Lock()

    async def access_token(self, subject: str, credential: CredentialProvider) -> str:
        holder = await self._holder_for(subject)
        held = holder.session
        if held is not None and held.is_fresh:
            return held.access_token.get_secret_value()
        return await self._renew(holder, credential, stale=held)

    async def renewed_access_token(self, subject: str, credential: CredentialProvider) -> str:
        holder = await self._holder_for(subject)
        return await self._renew(holder, credential, stale=holder.session)

    def forget(self, subject: str) -> None:
        """Drop a subject's session, so the next call signs in again."""
        _ = self._holders.pop(subject, None)

    async def _renew(
        self, holder: _Holder, credential: CredentialProvider, *, stale: VendorSession | None
    ) -> str:
        async with holder.lock:
            current = holder.session
            if current is not None and current is not stale and current.is_fresh:
                return current.access_token.get_secret_value()

            if current is not None:
                try:
                    holder.session = await self._factory.refresh(current)
                    logger.info("vendor_session.refreshed")
                    return holder.session.access_token.get_secret_value()
                except Exception:
                    # A spent or rejected refresh token is not a dead session: the stored
                    # password can obtain a new one.
                    logger.warning("vendor_session.refresh_failed", exc_info=True)

            holder.session = await self._factory.sign_in(await credential())
            logger.info("vendor_session.signed_in")
            return holder.session.access_token.get_secret_value()

    async def _holder_for(self, subject: str) -> _Holder:
        async with self._registry_lock:
            holder = self._holders.get(subject)
            if holder is None:
                if len(self._holders) >= MAX_TRACKED_SUBJECTS:
                    self._evict_idle_unlocked()
                holder = _Holder()
                self._holders[subject] = holder
            return holder

    def _evict_idle_unlocked(self) -> None:
        """Evicting a holder is always safe — the next call for that subject signs in again."""
        idle = [subject for subject, holder in self._holders.items() if not holder.lock.locked()]
        for subject in idle:
            del self._holders[subject]
        logger.debug(
            "vendor_session.evicted", extra={"evicted": len(idle), "retained": len(self._holders)}
        )
