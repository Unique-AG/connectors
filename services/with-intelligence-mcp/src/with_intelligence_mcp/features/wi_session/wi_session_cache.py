"""Process-local WI session cache."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from with_intelligence_mcp.with_intelligence_client import (
    WiSession,
    WithIntelligenceClientFactory,
)

logger = logging.getLogger(__name__)

_MAX_TRACKED_SUBJECTS = 512

type SessionReader = Callable[[], Awaitable[WiSession]]
type SessionRenewer = Callable[
    [Callable[[WiSession], Awaitable[WiSession]], WiSession | None], Awaitable[WiSession]
]


@dataclass
class _Holder:
    session: WiSession | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class WiSessionCache:
    """With Intelligence sessions keyed by MCP subject, cached in this process."""

    def __init__(self, factory: WithIntelligenceClientFactory) -> None:
        self._factory: WithIntelligenceClientFactory = factory
        self._holders: dict[str, _Holder] = {}
        self._holders_lock: asyncio.Lock = asyncio.Lock()

    async def get_access_token(
        self, subject: str, read: SessionReader, renew: SessionRenewer
    ) -> str:
        return await self._resolve_access_token(subject, read, renew, force_renewal=False)

    async def refresh_access_token(
        self, subject: str, read: SessionReader, renew: SessionRenewer
    ) -> str:
        return await self._resolve_access_token(subject, read, renew, force_renewal=True)

    async def _resolve_access_token(
        self,
        subject: str,
        read: SessionReader,
        renew: SessionRenewer,
        *,
        force_renewal: bool,
    ) -> str:
        async with self._hold(subject) as holder:
            cached_before_wait = holder.session
            async with holder.lock:
                cached_after_wait = holder.session
                if (
                    cached_after_wait is not None
                    and cached_after_wait is not cached_before_wait
                    and cached_after_wait.is_fresh
                ):
                    return cached_after_wait.access_token.get_secret_value()
                stored = await read()
                if stored.is_fresh and (
                    not force_renewal
                    or (
                        cached_before_wait is not None
                        and stored.has_different_access_token(cached_before_wait)
                    )
                ):
                    holder.session = stored
                    return stored.access_token.get_secret_value()

                rejected = (
                    stored if force_renewal and cached_before_wait is None else cached_before_wait
                )
                holder.session = await renew(self._factory.refresh, rejected)
                logger.info("wi_session.renewed")
                return holder.session.access_token.get_secret_value()

    @asynccontextmanager
    async def _hold(self, subject: str) -> AsyncGenerator[_Holder]:
        async with self._holders_lock:
            holder = self._holders.get(subject)
            if holder is None:
                if len(self._holders) >= _MAX_TRACKED_SUBJECTS:
                    self._evict_idle_unlocked()
                holder = _Holder()
                self._holders[subject] = holder
            holder.users += 1
        try:
            yield holder
        finally:
            async with self._holders_lock:
                holder.users -= 1

    def _evict_idle_unlocked(self) -> None:
        """Evicting a holder is always safe — the next call reads the stored session again."""
        idle = [subject for subject, holder in self._holders.items() if holder.users == 0]
        for subject in idle:
            del self._holders[subject]
        logger.debug(
            "wi_session.evicted", extra={"evicted": len(idle), "retained": len(self._holders)}
        )
