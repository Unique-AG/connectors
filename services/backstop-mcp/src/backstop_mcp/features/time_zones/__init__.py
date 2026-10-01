"""Cached Backstop time zones.

A meeting's time zone is a short name (for example `US/Eastern`). A unique display name
also resolves. Caching is off by default. `resolve_short_name` matches short name, then id,
then a unique display name, and returns the canonical short name.
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
