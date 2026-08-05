from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type

# Key format: `{entityType}:{crmName}`. crmName is the CRM's own field identifier (e.g.
# `is1`) — unique per entity type and stable across tenants, unlike the numeric
# definitionId Backstop assigns per instance.

type OverrideIndex = dict[tuple[str, str], CustomFieldOverrideConfig]


def parse_override_key(key: str) -> tuple[str, str]:
    """Split `entityType:crmName` into parts."""
    parts = key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Override key {key!r} must be entityType:crmName "
            + "(exactly one colon separating the two segments)"
        )
    entity_type, crm_name = (p.strip() for p in parts)
    if not entity_type or not crm_name:
        raise ValueError(f"Override key {key!r} requires non-empty entityType and crmName")
    return entity_type, crm_name


def index_overrides(overrides: dict[str, CustomFieldOverrideConfig]) -> OverrideIndex:
    """Map (normalized_entity_type, crm_name) → override."""
    indexed: OverrideIndex = {}
    for key, override in overrides.items():
        entity_type, crm_name = parse_override_key(key)
        indexed[(normalize_entity_type(entity_type), crm_name)] = override
    return indexed
