"""Process-local WI session cache."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from with_intelligence_mcp.with_intelligence_client import (
    WiSession,
    WithIntelligenceClientFactory,
)

logger = logging.getLogger(__name__)

MAX_TRACKED_SUBJECTS = 512

type SessionReader = Callable[[], Awaitable[WiSession]]
type SessionRenewer = Callable[
    [Callable[[WiSession], Awaitable[WiSession]], WiSession | None], Awaitable[WiSession]
]


@dataclass
class _Holder:
    session: WiSession | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WiSessionCache:
    """With Intelligence sessions keyed by MCP subject, cached in this process."""

    def __init__(self, factory: WithIntelligenceClientFactory) -> None:
        self._factory: WithIntelligenceClientFactory = factory
        self._holders: dict[str, _Holder] = {}
        self._holders_lock: asyncio.Lock = asyncio.Lock()

    async def access_token(self, subject: str, read: SessionReader, renew: SessionRenewer) -> str:
        holder = await self._holder_for(subject)
        return await self._refresh_subject(subject, read, renew, stale=holder.session)

    async def renewed_access_token(
        self, subject: str, read: SessionReader, renew: SessionRenewer
    ) -> str:
        holder = await self._holder_for(subject)
        return await self._refresh_subject(subject, read, renew, stale=holder.session)

    async def _refresh_subject(
        self,
        subject: str,
        read: SessionReader,
        renew: SessionRenewer,
        *,
        stale: WiSession | None,
    ) -> str:
        holder = await self._holder_for(subject)
        async with holder.lock:
            current = holder.session
            if current is not None and current is not stale and current.is_fresh:
                return current.access_token.get_secret_value()

            stored = await read()
            if stored.is_fresh and stored.has_different_access_token(stale):
                holder.session = stored
                return stored.access_token.get_secret_value()

            holder.session = await renew(self._factory.refresh, stale)
            logger.info("wi_session.renewed")
            return holder.session.access_token.get_secret_value()

    async def _holder_for(self, subject: str) -> _Holder:
        async with self._holders_lock:
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
            "wi_session.evicted", extra={"evicted": len(idle), "retained": len(self._holders)}
        )
