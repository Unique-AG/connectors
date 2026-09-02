"""One live vendor session per authenticated user, in front of the stored one.

Two layers, because they solve different problems. The in-memory holder keeps a fresh access
token for its hour so an ordinary tool call touches neither the database nor the encryption key.
The stored row is the source of truth, and renewal goes through it under a row lock — the
in-memory lock is per process, and this service runs several replicas.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from with_intelligence_mcp.with_intelligence_client import (
    VendorSession,
    WithIntelligenceClientFactory,
)

logger = logging.getLogger(__name__)

# Well above any plausible concurrent user count for one process; exists so a long-lived
# process with high user churn cannot grow the registry without bound.
MAX_TRACKED_SUBJECTS = 512

type SessionReader = Callable[[], Awaitable[VendorSession]]
type SessionRenewer = Callable[
    [Callable[[VendorSession], Awaitable[VendorSession]]], Awaitable[VendorSession]
]


@dataclass
class _Holder:
    session: VendorSession | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class VendorSessionRegistry:
    """Vendor sessions keyed by MCP subject, cached in front of the store."""

    def __init__(self, factory: WithIntelligenceClientFactory) -> None:
        self._factory: WithIntelligenceClientFactory = factory
        self._holders: dict[str, _Holder] = {}
        self._registry_lock: asyncio.Lock = asyncio.Lock()

    async def access_token(self, subject: str, read: SessionReader, renew: SessionRenewer) -> str:
        holder = await self._holder_for(subject)
        held = holder.session
        if held is not None and held.is_fresh:
            return held.access_token.get_secret_value()
        return await self._refresh_holder(holder, read, renew, stale=held)

    async def renewed_access_token(
        self, subject: str, read: SessionReader, renew: SessionRenewer
    ) -> str:
        holder = await self._holder_for(subject)
        return await self._refresh_holder(holder, read, renew, stale=holder.session)

    def forget(self, subject: str) -> None:
        """Drop a subject's cached session, so the next call reads the stored one."""
        _ = self._holders.pop(subject, None)

    async def _refresh_holder(
        self,
        holder: _Holder,
        read: SessionReader,
        renew: SessionRenewer,
        *,
        stale: VendorSession | None,
    ) -> str:
        async with holder.lock:
            current = holder.session
            if current is not None and current is not stale and current.is_fresh:
                return current.access_token.get_secret_value()

            # The stored session may already be fresher than this process knows — another
            # replica may have renewed it — so read before deciding to renew.
            stored = await read()
            if stored.is_fresh and stored is not stale:
                holder.session = stored
                return stored.access_token.get_secret_value()

            holder.session = await renew(self._factory.refresh)
            logger.info("vendor_session.renewed")
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
        """Evicting a holder is always safe — the next call reads the stored session again."""
        idle = [subject for subject, holder in self._holders.items() if not holder.lock.locked()]
        for subject in idle:
            del self._holders[subject]
        logger.debug(
            "vendor_session.evicted", extra={"evicted": len(idle), "retained": len(self._holders)}
        )
