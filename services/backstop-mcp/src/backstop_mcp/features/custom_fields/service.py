import asyncio
import logging
from datetime import timedelta
from typing import Literal

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields.fetch import fetch_custom_field_definitions
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.metrics import CUSTOM_FIELD_SCHEMA_LOADS
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)


class CustomFieldsService:
    """Process-wide custom-field schema catalog.

    Definitions come from a real Backstop fetch and live in one in-memory list. Until a
    fetch succeeds this service has nothing to serve. Constructed by `create_app()` and
    reached via `runtime.get_services().custom_fields`.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        self._definitions: list[CustomFieldDefinition] | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get(
        self, client: BackstopClient, *, refresh: bool = False
    ) -> tuple[list[CustomFieldDefinition], Literal["ok", "stale"]]:
        cached = self._definitions
        if cached is not None and self._freshness.within() and not refresh:
            return list(cached), "ok"

        async with self._lock:
            cached = self._definitions
            if cached is not None and self._freshness.within() and not refresh:
                return list(cached), "ok"
            try:
                definitions = await fetch_custom_field_definitions(client)
            except Exception:
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
                    return list(self._definitions), "stale"
                raise

            self._definitions = definitions
            self._freshness.mark()
            CUSTOM_FIELD_SCHEMA_LOADS.add(1, {"source": "backstop"})
            logger.info(
                "custom_fields.schema.refreshed",
                extra={"definitions": len(definitions)},
            )
            return list(definitions), "ok"


def create_custom_fields_service(*, ttl_minutes: int) -> CustomFieldsService:
    return CustomFieldsService(ttl=timedelta(minutes=ttl_minutes))
