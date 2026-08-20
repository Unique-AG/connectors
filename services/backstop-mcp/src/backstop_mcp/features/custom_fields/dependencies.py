from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.custom_fields.custom_field_groups_service import CustomFieldGroupsService
from backstop_mcp.features.custom_fields.custom_fields_service import CustomFieldsService


@lru_cache(maxsize=1)
def get_custom_fields_service() -> CustomFieldsService:
    return CustomFieldsService.with_ttl_minutes(
        ttl_minutes=get_backstop_config().custom_field_schema_ttl_minutes,
    )


@lru_cache(maxsize=1)
def get_custom_field_groups_service() -> CustomFieldGroupsService:
    return CustomFieldGroupsService.with_ttl_minutes(
        ttl_minutes=get_backstop_config().custom_field_schema_ttl_minutes,
    )
