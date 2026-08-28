from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.custom_fields.custom_field_groups_service import CustomFieldGroupsService
from backstop_mcp.features.custom_fields.custom_fields_service import CustomFieldsService


@lru_cache(maxsize=1)
def get_custom_fields_service() -> CustomFieldsService:
    # Measured: 3,274 definitions, 2.77 MiB, 6.15 s unfiltered. Caching is on
    # (`BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED`, default true, TTL 120 minutes) so
    # get_organization / get_person / get_product do not each pay that walk.
    # `page[limit]` is ignored on this endpoint, so `_DEFINITIONS_PAGE_SIZE` does not reduce
    # the fetch. A definition added by a CRM admin is invisible for up to the TTL;
    # `list_custom_fields(refresh=true)` forces a refetch.
    config = get_backstop_config()
    return CustomFieldsService.with_ttl_minutes(
        ttl_minutes=config.custom_field_schema_ttl_minutes,
        caching_enabled=config.custom_field_schema_cache_enabled,
    )


@lru_cache(maxsize=1)
def get_custom_field_groups_service() -> CustomFieldGroupsService:
    # Same flag as the definitions catalog (`BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED`)
    # because the two already share a TTL. The histograms label them apart
    # (`catalog="custom-field group"`), so a split is still the next step if they diverge.
    config = get_backstop_config()
    return CustomFieldGroupsService.with_ttl_minutes(
        ttl_minutes=config.custom_field_schema_ttl_minutes,
        caching_enabled=config.custom_field_schema_cache_enabled,
    )
