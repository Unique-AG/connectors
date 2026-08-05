from dataclasses import dataclass

from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type

# Key format: `{entityType}:{crmName}`. crmName is the CRM's own field identifier (e.g.
# `is1`) — unique per entity type and stable across tenants, unlike the numeric
# definitionId Backstop assigns per instance.


@dataclass(frozen=True)
class FieldOverride:
    """A human-facing overlay for one CRM custom-field definition.

    The domain's own type, not the env-parsing model. `config.CustomFieldOverrideConfig` is the
    pydantic shape `BACKSTOP_CUSTOM_FIELD_OVERRIDES` is deserialized into; `create_app` converts
    it to this before handing it to the service, so nothing under `features/custom_fields` has to
    import `config` for a type that isn't configuration.
    """

    display_name: str | None = None
    aliases: tuple[str, ...] = ()
    description: str | None = None


type OverrideIndex = dict[tuple[str, str], FieldOverride]


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


def index_overrides(overrides: dict[str, FieldOverride]) -> OverrideIndex:
    """Map (normalized_entity_type, crm_name) → override."""
    indexed: OverrideIndex = {}
    for key, override in overrides.items():
        entity_type, crm_name = parse_override_key(key)
        indexed[(normalize_entity_type(entity_type), crm_name)] = override
    return indexed
