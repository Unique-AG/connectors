"""Serialization of a fetched custom-field schema for the `custom_field_schema_snapshots` row.

Carries an explicit `version`. Snapshots outlive deploys, so a shape change will meet rows
written by the previous version; a mismatch (or any validation failure) is treated as a cache
miss and re-fetched, instead of raising from inside a cache read.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError

from backstop_mcp.features.custom_fields.types import AllowedValue, CustomFieldDefinition

logger = logging.getLogger(__name__)

# Bump whenever the persisted shape changes incompatibly. Existing rows then read as a miss.
SNAPSHOT_VERSION = 1


class _AllowedValuePayload(BaseModel):
    id: str | None = None
    label: str


class _DefinitionPayload(BaseModel):
    definition_id: str
    entity_type: str
    crm_name: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    field_type: str | None = None
    field_type_display: str | None = None
    is_time_series: bool = False
    allowed_values: list[_AllowedValuePayload] = Field(default_factory=list)
    lov_set_id: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class SnapshotPayload(BaseModel):
    version: int = SNAPSHOT_VERSION
    definitions: list[_DefinitionPayload] = Field(default_factory=list)


def dump_definitions(definitions: list[CustomFieldDefinition]) -> dict[str, object]:
    payload = SnapshotPayload(
        version=SNAPSHOT_VERSION,
        definitions=[
            _DefinitionPayload(
                definition_id=definition.definition_id,
                entity_type=definition.entity_type,
                crm_name=definition.crm_name,
                display_name=definition.display_name,
                aliases=list(definition.aliases),
                description=definition.description,
                field_type=definition.field_type,
                field_type_display=definition.field_type_display,
                is_time_series=definition.is_time_series,
                allowed_values=[
                    _AllowedValuePayload(id=value.id, label=value.label)
                    for value in definition.allowed_values
                ],
                lov_set_id=definition.lov_set_id,
                raw=definition.raw,
            )
            for definition in definitions
        ],
    )
    return payload.model_dump(mode="json")


def load_definitions(payload: object) -> list[CustomFieldDefinition] | None:
    """Parse a persisted payload, or None if it is from an incompatible/unreadable snapshot."""
    try:
        parsed = SnapshotPayload.model_validate(payload)
    except ValidationError as exc:
        logger.warning("custom_fields.snapshot.unreadable", extra={"error": str(exc)})
        return None

    if parsed.version != SNAPSHOT_VERSION:
        logger.info(
            "custom_fields.snapshot.version_mismatch",
            extra={"found": parsed.version, "expected": SNAPSHOT_VERSION},
        )
        return None

    return [
        CustomFieldDefinition(
            definition_id=item.definition_id,
            entity_type=item.entity_type,
            crm_name=item.crm_name,
            display_name=item.display_name,
            aliases=tuple(item.aliases),
            description=item.description,
            field_type=item.field_type,
            field_type_display=item.field_type_display,
            is_time_series=item.is_time_series,
            allowed_values=tuple(
                AllowedValue(id=value.id, label=value.label) for value in item.allowed_values
            ),
            lov_set_id=item.lov_set_id,
            raw=item.raw,
        )
        for item in parsed.definitions
    ]


@dataclass(frozen=True)
class StoredSnapshot:
    """A persisted schema snapshot plus when it was fetched, so callers can judge staleness."""

    definitions: list[CustomFieldDefinition]
    fetched_at: datetime
