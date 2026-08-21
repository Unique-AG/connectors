import asyncio
import logging
from datetime import timedelta
from typing import Literal

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields.fetch import fetch_custom_field_definitions
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldDefinitionDto
from backstop_mcp.metrics import CUSTOM_FIELD_SCHEMA_LOADS
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)

type CatalogResult = tuple[list[CustomFieldDefinitionDto], Literal["ok", "stale"]]


class CustomFieldsService:
    """Process-wide custom-field schema catalog.

    Definitions come from a real Backstop fetch and live in one in-memory list. Until a
    fetch succeeds this service has nothing to serve. Constructed by `create_app()` and
    reached via `runtime.get_services().custom_fields`.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        self._definitions: list[CustomFieldDefinitionDto] | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._in_flight: asyncio.Future[CatalogResult] | None = None

    async def get(
        self, client: BackstopClient, *, refresh: bool = False
    ) -> tuple[list[CustomFieldDefinitionDto], Literal["ok", "stale"]]:
        cached = self._definitions
        if cached is not None and self._freshness.within() and not refresh:
            return list(cached), "ok"

        async with self._lock:
            cached = self._definitions
            if cached is not None and self._freshness.within() and not refresh:
                return list(cached), "ok"
            if self._in_flight is not None and not self._in_flight.done():
                in_flight = self._in_flight
                owner = False
            else:
                in_flight = asyncio.get_running_loop().create_future()
                self._in_flight = in_flight
                owner = True

        if not owner:
            definitions, status = await in_flight
            return list(definitions), status

        try:
            return await self._fetch(client, in_flight)
        except BaseException as error:
            if not in_flight.done():
                # Don't stamp CancelledError onto the shared future — waiters would then
                # look cancelled themselves. A regular exception lets them fail and retry.
                waiter_error: BaseException = error
                if isinstance(error, asyncio.CancelledError):
                    waiter_error = RuntimeError("custom-field catalog fetch was cancelled")
                in_flight.set_exception(waiter_error)
            raise
        finally:
            # Shield so a CancelledError cannot skip unpinning and leave later
            # get()s joining a finished future until process restart.
            await asyncio.shield(self._unpin_in_flight(in_flight))

    async def _unpin_in_flight(self, in_flight: asyncio.Future[CatalogResult]) -> None:
        async with self._lock:
            if self._in_flight is in_flight:
                self._in_flight = None

    async def _fetch(
        self, client: BackstopClient, in_flight: asyncio.Future[CatalogResult]
    ) -> CatalogResult:
        try:
            definitions = await fetch_custom_field_definitions(client)
        except Exception as error:
            if self._definitions is not None:
                logger.warning(
                    "custom_fields.schema.refresh_failed_serving_stale",
                    extra={
                        "fetched_at": (
                            self._freshness.marked_at.isoformat()
                            if self._freshness.marked_at
                            else None
                        ),
                    },
                    exc_info=True,
                )
                CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "stale"})
                self._freshness.mark()
                result: CatalogResult = (list(self._definitions), "stale")
                in_flight.set_result(result)
                return result
            in_flight.set_exception(error)
            raise

        self._definitions = definitions
        self._freshness.mark()
        CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "backstop"})
        logger.info(
            "custom_fields.schema.refreshed",
            extra={"definitions": len(definitions)},
        )
        result = (list(definitions), "ok")
        in_flight.set_result(result)
        return result


def create_custom_fields_service(*, ttl_minutes: int) -> CustomFieldsService:
    return CustomFieldsService(ttl=timedelta(minutes=ttl_minutes))
