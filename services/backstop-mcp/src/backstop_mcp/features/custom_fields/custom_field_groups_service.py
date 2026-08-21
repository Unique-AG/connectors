from datetime import timedelta
from typing import Self

from backstop_mcp.features.cached_catalog import CachedCatalog
from backstop_mcp.features.custom_fields.fetch_custom_field_groups import fetch_custom_field_groups
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldGroupDto


class CustomFieldGroupsService(CachedCatalog[CustomFieldGroupDto]):
    """Process-wide custom-field group catalog.

    Groups come from a real Backstop fetch and live in one in-memory dict keyed by group id.
    Until a fetch succeeds this service has nothing to serve. Constructed by
    `get_custom_field_groups_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is `CachedCatalog`.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        super().__init__(
            ttl=ttl,
            fetch=fetch_custom_field_groups,
            log_prefix="custom_fields.groups",
            subject="custom-field group",
        )

    @classmethod
    def with_ttl_minutes(cls, *, ttl_minutes: int) -> Self:
        return cls(ttl=timedelta(minutes=ttl_minutes))
