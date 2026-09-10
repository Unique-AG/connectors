import logging
from datetime import timedelta
from typing import Self, overload

from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue, CacheFreshness
from backstop_mcp.features.time_zones.api_responses import TimeZoneAttributes
from backstop_mcp.features.time_zones.internal_dto import TimeZoneDto

logger = logging.getLogger(__name__)


class TimeZonesService:
    """Process-wide time-zone catalog.

    Zones come from a real Backstop fetch and live in one in-memory dict keyed by zone id.
    A meeting's `timeZone` is a `/time-zones` `shortName`, so callers use `resolve_short_name`
    and send that string. Until a fetch succeeds this service has nothing to serve.
    Constructed by `get_time_zones_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is the composed `CachedValue`.
    """

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, caching_enabled: bool = True
    ) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, TimeZoneDto]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="time-zone",
            log_prefix="time_zones",
            caching_enabled=caching_enabled,
        )

    @classmethod
    def with_ttl_minutes(
        cls, *, client: BackstopClient, ttl_minutes: int, caching_enabled: bool = True
    ) -> Self:
        return cls(
            client=client, ttl=timedelta(minutes=ttl_minutes), caching_enabled=caching_enabled
        )

    async def get(self, *, refresh: bool = False) -> tuple[dict[str, TimeZoneDto], CacheFreshness]:
        return await self._cache.get(self._fetch_time_zones, refresh=refresh)

    @overload
    async def resolve_short_name(self, short_name_id_or_name: None) -> None: ...

    @overload
    async def resolve_short_name(self, short_name_id_or_name: str) -> str: ...

    @overload
    async def resolve_short_name(self, short_name_id_or_name: str | None) -> str | None: ...

    async def resolve_short_name(self, short_name_id_or_name: str | None) -> str | None:
        """Canonical `/time-zones` shortName, or `None` when the caller omitted a zone."""
        if short_name_id_or_name is None:
            return None
        zone = await self.resolve(short_name_id_or_name)
        return zone.short_name

    async def resolve(self, short_name_id_or_name: str) -> TimeZoneDto:
        """Match `shortName` first, then `id`, then a unique display `name`."""
        catalog, _freshness = await self.get()
        needle = short_name_id_or_name.casefold()
        zones = list(catalog.values())

        by_short_name = [zone for zone in zones if zone.short_name.casefold() == needle]
        if len(by_short_name) == 1:
            return by_short_name[0]
        if len(by_short_name) > 1:
            raise ToolError(
                f"{short_name_id_or_name!r} matches more than one Backstop time zone shortName."
            )

        by_id = [zone for zone in zones if zone.id.casefold() == needle]
        if len(by_id) == 1:
            return by_id[0]
        if len(by_id) > 1:
            raise ToolError(
                f"{short_name_id_or_name!r} matches more than one Backstop time zone id."
            )

        by_name = [
            zone for zone in zones if zone.name is not None and zone.name.casefold() == needle
        ]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            candidates = ", ".join(sorted(zone.short_name for zone in by_name))
            raise ToolError(
                f"{short_name_id_or_name!r} matches more than one Backstop time zone. "
                + f"Pass one of these shortNames: {candidates}."
            )
        raise ToolError(
            f"{short_name_id_or_name!r} is not a known Backstop time zone. "
            + "Pass a shortName like 'US/Eastern' or 'America/Chicago'."
        )

    async def _fetch_time_zones(self) -> dict[str, TimeZoneDto]:
        page = await self._client.paginate(
            "/time-zones",
            schema=BackstopApiResource[TimeZoneAttributes],
            max_records=None,
            page_size=200,
        )

        zones_by_id: dict[str, TimeZoneDto] = {}
        for resource in page.items:
            zone = TimeZoneDto.from_resource(resource)
            if zone is None:
                continue
            existing = zones_by_id.get(zone.id)
            if existing is None:
                zones_by_id[zone.id] = zone
            elif existing != zone:
                logger.warning(
                    "Conflicting time zones for duplicate id %r; retaining first zone", zone.id
                )
        return zones_by_id
