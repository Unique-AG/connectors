"""Self-contained pagination cursor: an `ActivityCursor` pydantic model serialized as JSON.

The cursor carries the full query state for the next page — `segment`, `entity_id`, `limit`,
`activity_types`, `since`, `until`, and `consumed` — so a caller only needs to pass the cursor
string to continue. Filters are not re-supplied alongside it; wanting a different query means
starting over without a cursor.

It is not signed: it carries no secret, only ids and filter values the caller already holds.

Wire payload: `ActivityCursor.model_dump_json()` — a JSON *object* with named fields —

    {
        "version": 1,
        "segment": "organizations" | "people",
        "entity_id": "...",
        "limit": ...,
        "activity_types": ["meeting", "call", ...] | null,  # sorted unique; null = all types
        "since": "YYYY-MM-DD" | null,
        "until": "YYYY-MM-DD" | null,
        "consumed": {"meeting": ..., "call": ..., ...}   # one entry per active stream
    }

then base64url-encoded (no padding).

Each field's type is deliberately as tight as pydantic allows, so a structurally- or
semantically-invalid payload fails `model_validate_json`'s own `ValidationError` automatically:
an unsupported schema version, an unrecognized segment/stream name, a mistyped date, or a
missing/mistyped field are all rejected by the type itself — nothing here re-checks any of that
by hand.
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

_SCHEMA_VERSION = 1

_RESTART_INSTRUCTION = "restart from page one without a cursor"


class InvalidCursor(Exception):
    """A cursor can't be trusted: it failed to decode or has an unrecognized shape.

    Nothing here is actionable to name — a corrupt cursor has no "correct" reading. Every
    message ends with the restart instruction: drop the cursor and start over.
    """


class ActivityCursor(BaseModel):
    """The cursor's wire payload — encoded directly to JSON and decoded directly from it.

    Also the result of a successful `decode_cursor`: everything needed to fetch the next page.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    # Mirrors `_SCHEMA_VERSION` by hand: `Literal[...]` requires an actual literal, not a
    # reference to a module-level variable, even one holding a literal value — basedpyright
    # rejects `Literal[_SCHEMA_VERSION]`.
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
    """Sorted unique types, or `None` when unrestricted (including an empty collection)."""
    if not activity_types:
        return None
    return tuple(sorted(set(activity_types)))


def _parse_cursor(raw: bytes) -> ActivityCursor:
    """Validate `raw` against `ActivityCursor` and translate any `ValidationError` to
    `InvalidCursor`.

    `ActivityCursor`'s field types already police shape and semantics — schema version,
    segment/stream membership, and date parsing — so there is nothing left to check by hand
    here.
    """
    try:
        return ActivityCursor.model_validate_json(raw)
    except ValidationError as exc:
        raise InvalidCursor(f"Cursor has an unrecognized shape; {_RESTART_INSTRUCTION}.") from exc


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
    """Encode a next-page cursor, or `None` when `consumed` is empty (every stream exhausted).

    The encoded cursor is self-contained: every field needed to continue the same query is
    stored in the payload. Callers of `decode_cursor` need only the cursor string.
    """
    if not consumed:
        return None

    for stream, count in consumed.items():
        assert count >= 0, f"cursor invariant violated: negative consumed count for {stream!r}"

    decoded = ActivityCursor(
        version=_SCHEMA_VERSION,
        segment=segment,
        entity_id=entity_id,
        limit=limit,
        activity_types=_normalize_activity_types(activity_types),
        since=since,
        until=until,
        consumed=consumed,
    )
    dumped = decoded.model_dump_json().encode()
    return base64.urlsafe_b64encode(dumped).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> ActivityCursor:
    """Decode `cursor` into the full query state for the next page.

    On success, returns an `ActivityCursor` with segment, entity, limit, filters, and `consumed`
    ready to hand to `merge_page` (and as the next `page[offset]` per stream). A corrupt or
    unrecognized payload raises `InvalidCursor` instructing a restart.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursor(f"Cursor is not valid base64; {_RESTART_INSTRUCTION}.") from exc

    return _parse_cursor(raw)
