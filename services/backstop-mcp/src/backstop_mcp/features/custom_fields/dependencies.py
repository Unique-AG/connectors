from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.custom_fields.custom_field_groups_service import CustomFieldGroupsService
from backstop_mcp.features.custom_fields.custom_fields_service import CustomFieldsService


@lru_cache(maxsize=1)
def get_custom_fields_service() -> CustomFieldsService:
    # CACHING CANDIDATE, and the strongest of the four: this walk is ~1000 definitions over many
    # pages and every party lookup joins against it. Off anyway unless
    # `BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED=true`. Decide from the two histograms in
    # `features/cached_catalog.py` — `catalog_get_duration_seconds_count{catalog="custom-field"}`
    # is the demand a TTL would absorb, `catalog_fetch_duration_seconds{catalog="custom-field"}`
    # what one walk costs.
    config = get_backstop_config()
    return CustomFieldsService.with_ttl_minutes(
        ttl_minutes=config.custom_field_schema_ttl_minutes,
        caching_enabled=config.custom_field_schema_cache_enabled,
    )


@lru_cache(maxsize=1)
def get_custom_field_groups_service() -> CustomFieldGroupsService:
    # CACHING CANDIDATE, on the same flag as the definitions catalog above
    # (`BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED`) because the two already share a TTL. The
    # histograms label them apart, so `catalog_get_duration_seconds_count` and
    # `catalog_fetch_duration_seconds` for `catalog="custom-field group"` can still say that this
    # much smaller walk wants a different answer than the definitions walk — which is when the
    # flag gets split rather than flipped.
    config = get_backstop_config()
    return CustomFieldGroupsService.with_ttl_minutes(
        ttl_minutes=config.custom_field_schema_ttl_minutes,
        caching_enabled=config.custom_field_schema_cache_enabled,
    )
