import asyncio
import logging
from datetime import timedelta
from typing import Literal, Self

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.system_users.fetch_system_users import fetch_system_users
from backstop_mcp.features.system_users.internal_dto import SystemUserDto
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)

type CatalogResult = tuple[dict[str, SystemUserDto], Literal["ok", "stale"]]


class SystemUsersService:
    """Process-wide system-user catalog.

    Users come from a real Backstop fetch and live in one in-memory dict keyed by user id.
    Until a fetch succeeds this service has nothing to serve. Constructed by
    `get_system_users_service` in this feature's `dependencies.py`.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        self._users: dict[str, SystemUserDto] | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._in_flight: asyncio.Future[CatalogResult] | None = None

    @classmethod
    def with_ttl_minutes(cls, *, ttl_minutes: int) -> Self:
        return cls(ttl=timedelta(minutes=ttl_minutes))

    async def get(
        self, client: BackstopClient, *, refresh: bool = False
    ) -> tuple[dict[str, SystemUserDto], Literal["ok", "stale"]]:
        cached = self._users
        if cached is not None and self._freshness.within() and not refresh:
            return dict(cached), "ok"

        async with self._lock:
            cached = self._users
            if cached is not None and self._freshness.within() and not refresh:
                return dict(cached), "ok"
            if self._in_flight is not None and not self._in_flight.done():
                in_flight = self._in_flight
                owner = False
            else:
                in_flight = asyncio.get_running_loop().create_future()
                self._in_flight = in_flight
                owner = True

        if not owner:
            users, status = await in_flight
            return dict(users), status

        try:
            return await self._fetch(client, in_flight)
        except BaseException as error:
            if not in_flight.done():
                waiter_error: BaseException = error
                if isinstance(error, asyncio.CancelledError):
                    waiter_error = RuntimeError("system-user catalog fetch was cancelled")
                in_flight.set_exception(waiter_error)
            raise
        finally:
            await asyncio.shield(self._unpin_in_flight(in_flight))

    async def _unpin_in_flight(self, in_flight: asyncio.Future[CatalogResult]) -> None:
        async with self._lock:
            if self._in_flight is in_flight:
                self._in_flight = None

    async def _fetch(
        self, client: BackstopClient, in_flight: asyncio.Future[CatalogResult]
    ) -> CatalogResult:
        try:
            users = await fetch_system_users(client)
        except Exception as error:
            if self._users is not None:
                logger.warning(
                    "system_users.refresh_failed_serving_stale",
                    extra={
                        "fetched_at": (
                            self._freshness.marked_at.isoformat()
                            if self._freshness.marked_at
                            else None
                        ),
                    },
                    exc_info=True,
                )
                self._freshness.mark()
                result: CatalogResult = (dict(self._users), "stale")
                in_flight.set_result(result)
                return result
            in_flight.set_exception(error)
            raise

        self._users = users
        self._freshness.mark()
        logger.info("system_users.refreshed", extra={"users": len(users)})
        result = (dict(users), "ok")
        in_flight.set_result(result)
        return result
