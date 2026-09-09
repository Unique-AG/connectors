from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller, get_backstop_config
from backstop_mcp.features.time_zones.time_zones_service import TimeZonesService


@lru_cache(maxsize=1)
def get_time_zones_service(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> TimeZonesService:
    # CACHING CANDIDATE, off unless `BACKSTOP_TIME_ZONE_CACHE_ENABLED=true`: by default every
    # read walks `/time-zones`. Decide from the two histograms in `caching/cached_value.py`
    # — `catalog_get_duration_seconds_count{catalog="time-zone"}` is the demand a TTL would
    # absorb, `catalog_fetch_duration_seconds{catalog="time-zone"}` what one walk costs.
    config = get_backstop_config()
    return TimeZonesService.with_ttl_minutes(
        client=client,
        ttl_minutes=config.time_zone_ttl_minutes,
        caching_enabled=config.time_zone_cache_enabled,
    )
