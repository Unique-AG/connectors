"""Serialization of a fetched custom-field schema for the `custom_field_schema_snapshots` row.

Carries an explicit `version`. Snapshots outlive deploys, so a shape change will meet rows
written by the previous version; a mismatch (or any validation failure) is treated as a cache
miss and re-fetched, instead of raising from inside a cache read.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError

from backstop_mcp.features.custom_fields.types import CustomFieldDefinition

logger = logging.getLogger(__name__)

# Bump whenever the persisted shape changes incompatibly. Existing rows then read as a miss.
SNAPSHOT_VERSION = 1


class SnapshotPayload(BaseModel):
    version: int = SNAPSHOT_VERSION
    definitions: list[CustomFieldDefinition] = Field(default_factory=list)


def dump_definitions(definitions: list[CustomFieldDefinition]) -> dict[str, object]:
    return SnapshotPayload(version=SNAPSHOT_VERSION, definitions=definitions).model_dump(
        mode="json"
    )


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

    return list(parsed.definitions)


@dataclass(frozen=True)
class StoredSnapshot:
    """A persisted schema snapshot plus when it was fetched, so callers can judge staleness."""

    definitions: list[CustomFieldDefinition]
    fetched_at: datetime
