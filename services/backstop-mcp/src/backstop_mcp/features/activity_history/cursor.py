"""Self-contained activity-history pagination cursor.

Encodes the full query state (`segment`, `entity_id`, `limit`, filters, `consumed`) as a
base64url JSON blob so the next page needs only the cursor string. Not signed — carries no
secret. Corrupt or unrecognized payloads raise `InvalidCursor`.
"""

import base64
import binascii
from collections.abc import Collection, Mapping
from datetime import date
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityType,
    BackstopActivityType,
    Segment,
)

__all__ = ["ActivityCursor", "InvalidCursor", "decode_cursor", "encode_cursor"]

_RESTART = "restart from page one without a cursor"


class InvalidCursor(Exception):
    """Cursor failed to decode; drop it and start over."""


class ActivityCursor(BaseModel):
    """Wire payload and the result of `decode_cursor`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    version: Literal[1] = 1
    segment: Segment
    entity_id: str
    limit: int
    activity_types: tuple[BackstopActivityType, ...] | None = None
    since: date | None = None
    until: date | None = None
    consumed: Mapping[ActivityType, int]


def _normalize_activity_types(
    activity_types: Collection[BackstopActivityType] | None,
) -> tuple[BackstopActivityType, ...] | None:
    if not activity_types:
        return None
    return tuple(sorted(set(activity_types)))


def encode_cursor(
    *,
    segment: Segment,
    entity_id: str,
    limit: int,
    activity_types: Collection[BackstopActivityType] | None,
    since: date | None,
    until: date | None,
    consumed: Mapping[ActivityType, int],
) -> str | None:
    """Encode the next-page cursor, or `None` when every stream is exhausted."""
    if not consumed:
        return None

    for stream, count in consumed.items():
        assert count >= 0, f"cursor invariant violated: negative consumed count for {stream!r}"

    payload = ActivityCursor(
        segment=segment,
        entity_id=entity_id,
        limit=limit,
        activity_types=_normalize_activity_types(activity_types),
        since=since,
        until=until,
        consumed=consumed,
    )
    return base64.urlsafe_b64encode(payload.model_dump_json().encode()).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> ActivityCursor:
    """Decode a cursor into the full next-page query state."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursor(f"Cursor is not valid base64; {_RESTART}.") from exc

    try:
        return ActivityCursor.model_validate_json(raw)
    except ValidationError as exc:
        raise InvalidCursor(f"Cursor has an unrecognized shape; {_RESTART}.") from exc
