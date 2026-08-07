from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition

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


def apply_overrides(
    definitions: list[CustomFieldDefinition],
    overrides: OverrideIndex,
) -> list[CustomFieldDefinition]:
    """Re-merge current overrides onto definitions from CRM-native fields.

    Snapshots may have been written under an older override map. Always rebuild
    `display_name` / `aliases` / `description` from `crm_name` + `raw` attributes so config
    drift applies without waiting for the next Backstop fetch. Does not invent fields that
    are not already in `definitions`.
    """
    applied: list[CustomFieldDefinition] = []
    for definition in definitions:
        override = overrides.get((definition.entity_type, definition.crm_name))
        crm_description = _crm_description(definition)
        if override is None:
            applied.append(
                definition.model_copy(
                    update={
                        "display_name": definition.crm_name,
                        "aliases": (),
                        "description": crm_description,
                    }
                )
            )
            continue
        display_name = (
            override.display_name.strip() if override.display_name else definition.crm_name
        )
        aliases = tuple(a.strip() for a in override.aliases if a.strip())
        description = override.description if override.description else crm_description
        applied.append(
            definition.model_copy(
                update={
                    "display_name": display_name,
                    "aliases": aliases,
                    "description": description,
                }
            )
        )
    return applied


def _crm_description(definition: CustomFieldDefinition) -> str | None:
    attributes = definition.raw.get("attributes")
    if not isinstance(attributes, Mapping):
        return None
    description = cast("Mapping[str, object]", attributes).get("description")
    if not isinstance(description, str):
        return None
    return description.strip() or None


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
        normalized = normalize_entity_type(entity_type)
        if normalized is None:
            raise ValueError(f"Override key {key!r} has unknown entityType {entity_type!r}")
        indexed[(normalized, crm_name)] = override
    return indexed
