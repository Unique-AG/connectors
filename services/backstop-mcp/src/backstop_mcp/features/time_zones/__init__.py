"""Cached Backstop time-zone catalog.

A meeting's `timeZone` is a `/time-zones` `shortName` (e.g. `US/Eastern`), not the catalog
`id` and not the display `name` — `name` is ambiguous. `TimeZonesService` is the TTL-cached
instance catalog; `resolve` matches shortName, then id, then name so callers can send `.short_name`.
"""

from backstop_mcp.features.time_zones.api_responses import TimeZoneAttributes
from backstop_mcp.features.time_zones.dependencies import get_time_zones_service
from backstop_mcp.features.time_zones.internal_dto import TimeZoneDto
from backstop_mcp.features.time_zones.time_zones_service import TimeZonesService

__all__ = [
    "TimeZoneAttributes",
    "TimeZoneDto",
    "TimeZonesService",
    "get_time_zones_service",
]
