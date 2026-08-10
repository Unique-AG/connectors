"""Compact pagination cursor: a `_DecodedCursor` pydantic model serialized directly as JSON, plus
a filter-set digest.

The cursor is authoritative, not a hint: a caller supplying one alongside contradicting plain
filter arguments (`segment`, `entity_id`, `limit`) gets a `CursorConflict` naming the mismatch,
never a silent reinterpretation. `activity_types`/`since`/`until` travel only as a short digest
(they don't need to be compared field-by-field, only detected as changed), so a digest mismatch
can't be explained — it's reported as `InvalidCursor` with a restart instruction instead.

It is not signed: it carries no secret, only ids the caller already holds. The digest exists to
detect misuse, not to authenticate.

Wire payload: `_DecodedCursor.model_dump_json()` — a JSON *object* with named fields —

    {
        "version": 1,
        "segment": "organizations" | "people",
        "entity_id": "...",
        "limit": ...,
        "digest": "...",       # base64, exactly `_DIGEST_LENGTH` bytes decoded
        "consumed": {"meeting": ..., "call": ..., ...}   # one entry per active stream
    }

then base64url-encoded (no padding).

Each field's type is deliberately as tight as pydantic allows, so a structurally- or
semantically-invalid payload fails `model_validate_json`'s own `ValidationError` automatically:
an unsupported schema version, an unrecognized segment/stream name, a wrong-length digest, or a
missing/mistyped field are all rejected by the type itself — nothing here re-checks any of that
by hand.
"""

import base64
import binascii
import hashlib
from collections.abc import Collection, Mapping
from datetime import date
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backstop_mcp.features.activity_history.streams import ActivityStreamKind, Segment, StreamKind

__all__ = ["CursorConflict", "InvalidCursor", "decode_and_validate_cursor", "encode_cursor"]

_SCHEMA_VERSION = 1
_DIGEST_LENGTH = 6  # bytes — a handful, not a full sha256, to keep the cursor compact.

_RESTART_INSTRUCTION = "restart from page one without a cursor"

_Digest = Annotated[bytes, Field(min_length=_DIGEST_LENGTH, max_length=_DIGEST_LENGTH)]


class CursorConflict(Exception):
    """A supplied cursor's plain fields (`segment`/`entity_id`/`limit`) disagree with this call.

    These fields travel unhashed specifically so a mismatch can be named — the caller can see
    the problem and fix it (drop the cursor, or change the argument to match), so this is never
    a silent reinterpretation.
    """


class InvalidCursor(Exception):
    """A cursor can't be trusted: it failed to decode, or its filter-set digest doesn't match.

    Nothing here is actionable to name — a corrupt cursor has no "correct" reading, and a digest
    mismatch (`activity_types`/`since`/`until` changed) can't be un-hashed back into which field
    changed. Every message ends with the restart instruction: drop the cursor and start over.
    """


class _DecodedCursor(BaseModel):
    """The cursor's wire payload — encoded directly to JSON and decoded directly from it — and
    also the result of parsing a cursor's bytes, before it is validated against the current call.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, ser_json_bytes="base64", val_json_bytes="base64"
    )
    # `ser_json_bytes`/`val_json_bytes="base64"` is required for the digest field: pydantic's
    # default JSON handling of raw `bytes` expects valid UTF-8, which a sha256-derived digest
    # isn't. Confirmed empirically (round-tripping an arbitrary non-UTF8 6-byte value through
    # `model_dump_json`/`model_validate_json` before relying on it here).

    # Mirrors `_SCHEMA_VERSION` by hand: `Literal[...]` requires an actual literal, not a
    # reference to a module-level variable, even one holding a literal value — basedpyright
    # rejects `Literal[_SCHEMA_VERSION]`.
    version: Literal[1] = 1
    segment: Segment
    entity_id: str
    limit: int
    digest: _Digest
    consumed: Mapping[StreamKind, int]


def _normalized_filter_payload(
    activity_types: Collection[ActivityStreamKind] | None, since: date | None, until: date | None
) -> bytes:
    """The exact bytes hashed into the filter digest — order-independent in `activity_types`."""
    types_part = ",".join(sorted(set(activity_types))) if activity_types else ""
    since_part = since.isoformat() if since is not None else ""
    until_part = until.isoformat() if until is not None else ""
    return f"{types_part}|{since_part}|{until_part}".encode()


def _filter_digest(
    activity_types: Collection[ActivityStreamKind] | None, since: date | None, until: date | None
) -> bytes:
    payload = _normalized_filter_payload(activity_types, since, until)
    return hashlib.sha256(payload).digest()[:_DIGEST_LENGTH]


def _parse_cursor(raw: bytes) -> _DecodedCursor:
    """Validate `raw` against `_DecodedCursor` and translate any `ValidationError` to
    `InvalidCursor`.

    `_DecodedCursor`'s field types already police shape and semantics — schema version,
    segment/stream membership, and digest length — so there is nothing left to check by hand
    here.
    """
    try:
        return _DecodedCursor.model_validate_json(raw)
    except ValidationError as exc:
        raise InvalidCursor(f"Cursor has an unrecognized shape; {_RESTART_INSTRUCTION}.") from exc


def encode_cursor(
    *,
    segment: Segment,
    entity_id: str,
    limit: int,
    activity_types: Collection[ActivityStreamKind] | None,
    since: date | None,
    until: date | None,
    consumed: Mapping[StreamKind, int],
) -> str | None:
    """Encode a next-page cursor, or `None` when `consumed` is empty (every stream exhausted).

    `segment`/`entity_id`/`limit` travel as their own plain fields (compared directly on decode,
    see `decode_and_validate_cursor`); `activity_types`/`since`/`until` travel only as a digest.
    """
    if not consumed:
        return None

    for stream, count in consumed.items():
        assert count >= 0, f"cursor invariant violated: negative consumed count for {stream!r}"

    decoded = _DecodedCursor(
        version=_SCHEMA_VERSION,
        segment=segment,
        entity_id=entity_id,
        limit=limit,
        digest=_filter_digest(activity_types, since, until),
        consumed=consumed,
    )
    dumped = decoded.model_dump_json().encode()
    return base64.urlsafe_b64encode(dumped).rstrip(b"=").decode("ascii")


def decode_and_validate_cursor(
    cursor: str,
    *,
    segment: Segment,
    entity_id: str,
    limit: int,
    activity_types: Collection[ActivityStreamKind] | None,
    since: date | None,
    until: date | None,
) -> dict[StreamKind, int]:
    """Decode `cursor` and validate it against the current call, raising on any mismatch.

    A plain-field mismatch (`segment`/`entity_id`/`limit`) is a `CursorConflict` naming what
    differed — the caller can see and fix it. A decode failure, or a filter-digest mismatch
    (`activity_types`/`since`/`until` changed), is an `InvalidCursor` instructing a restart —
    there is nothing specific to name, since a digest can't be un-hashed. On success, returns the
    `consumed` mapping ready to hand to `merge_page`.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursor(f"Cursor is not valid base64; {_RESTART_INSTRUCTION}.") from exc

    decoded = _parse_cursor(raw)

    mismatches = [
        f"{name} (cursor={cursor_value!r}, argument={argument_value!r})"
        for name, cursor_value, argument_value in (
            ("segment", decoded.segment, segment),
            ("entity_id", decoded.entity_id, entity_id),
            ("limit", decoded.limit, limit),
        )
        if cursor_value != argument_value
    ]
    if mismatches:
        raise CursorConflict(
            "Cursor conflicts with this call's arguments: "
            + "; ".join(mismatches)
            + ". Drop the cursor, or change the argument(s) to match what the cursor was "
            + "issued for."
        )

    expected_digest = _filter_digest(activity_types, since, until)
    if decoded.digest != expected_digest:
        raise InvalidCursor(
            "Cursor's activity_types/since/until no longer match this call; "
            + f"{_RESTART_INSTRUCTION}."
        )

    return dict(decoded.consumed)
