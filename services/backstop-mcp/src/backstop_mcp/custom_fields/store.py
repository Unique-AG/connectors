from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from backstop_mcp.custom_fields.types import AllowedValue, CustomFieldDefinition
from backstop_mcp.db.models import CustomFieldSchemaSnapshot


def _as_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _as_object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast(list[object], value)


def definition_to_payload(definition: CustomFieldDefinition) -> dict[str, object]:
    return {
        "definition_id": definition.definition_id,
        "entity_type": definition.entity_type,
        "crm_name": definition.crm_name,
        "display_name": definition.display_name,
        "aliases": list(definition.aliases),
        "description": definition.description,
        "field_type": definition.field_type,
        "field_type_display": definition.field_type_display,
        "is_time_series": definition.is_time_series,
        "allowed_values": [{"id": v.id, "label": v.label} for v in definition.allowed_values],
        "raw": definition.raw,
    }


def definition_from_payload(payload: dict[str, object]) -> CustomFieldDefinition:
    allowed: list[AllowedValue] = []
    for item in _as_object_list(payload.get("allowed_values")):
        item_dict = _as_object_dict(item)
        if item_dict is None:
            continue
        label = item_dict.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        option_id = item_dict.get("id")
        allowed.append(
            AllowedValue(
                id=str(option_id) if option_id is not None else None,
                label=label.strip(),
            )
        )

    aliases = tuple(a for a in _as_object_list(payload.get("aliases")) if isinstance(a, str))

    raw_dict = _as_object_dict(payload.get("raw"))
    return CustomFieldDefinition(
        definition_id=str(payload["definition_id"]),
        entity_type=str(payload["entity_type"]),
        crm_name=str(payload["crm_name"]),
        display_name=str(payload["display_name"]),
        aliases=aliases,
        description=(
            str(payload["description"]) if payload.get("description") is not None else None
        ),
        field_type=str(payload["field_type"]) if payload.get("field_type") is not None else None,
        field_type_display=(
            str(payload["field_type_display"])
            if payload.get("field_type_display") is not None
            else None
        ),
        is_time_series=bool(payload.get("is_time_series", False)),
        allowed_values=tuple(allowed),
        raw=raw_dict if raw_dict is not None else {},
    )


@dataclass(frozen=True)
class StoredSnapshot:
    """A persisted schema snapshot plus when it was fetched, so callers can judge staleness."""

    definitions: list[CustomFieldDefinition]
    fetched_at: datetime


async def load_snapshot(session: AsyncSession, base_url: str) -> StoredSnapshot | None:
    row = await session.get(CustomFieldSchemaSnapshot, base_url)
    if row is None:
        return None
    definitions: list[CustomFieldDefinition] = []
    for item in _as_object_list(row.payload):
        item_dict = _as_object_dict(item)
        if item_dict is not None:
            definitions.append(definition_from_payload(item_dict))
    return StoredSnapshot(definitions=definitions, fetched_at=row.fetched_at)


async def save_snapshot(
    session: AsyncSession,
    base_url: str,
    definitions: list[CustomFieldDefinition],
    fetched_at: datetime,
) -> None:
    """Upsert the snapshot for `base_url`, stamped with the caller's fetch time.

    `fetched_at` is passed in rather than read from the clock here so the caller that also
    tracks freshness in memory stamps both from a single reading.
    """
    payload: object = [definition_to_payload(d) for d in definitions]
    row = await session.get(CustomFieldSchemaSnapshot, base_url)
    if row is None:
        session.add(
            CustomFieldSchemaSnapshot(base_url=base_url, payload=payload, fetched_at=fetched_at)
        )
    else:
        row.payload = payload
        row.fetched_at = fetched_at
