"""`encode_cursor`/`decode_cursor`, and the full merge+cursor paging round-trip.

The round-trip test drives a synthetic multi-stream fixture (plain in-memory pages, no HTTP)
through `merge_page` + `encode_cursor`/`decode_cursor` to full exhaustion, across several
`limit` values and deliberately uneven stream lengths (one empty from the start, one much longer
than the rest) — the regression test for a dropped or duplicated record anywhere across a paging
session. `consumed[s]` is used directly as each stream's next `page[offset]`.
"""

import base64
import json
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import cast

import pytest

from backstop_mcp.features.activity_history import (
    ActivityItem,
    ActivityType,
    InvalidCursor,
    Segment,
    decode_cursor,
    encode_cursor,
    merge_page,
)
from backstop_mcp.features.activity_history.fetch_activities import BackstopActivityType

_ActivityPage = tuple[Sequence[ActivityItem], bool]


def _activity(item_id: str, stream: BackstopActivityType, effective_date: date) -> ActivityItem:
    return ActivityItem(
        id=item_id,
        stream=stream,
        title=None,
        description=None,
        effective_date=effective_date,
        resource_type=None,
        resource_id=None,
        created_timestamp=None,
        modified_timestamp=None,
    )


def _fetch(items: Sequence[ActivityItem], *, limit: int, offset: int) -> _ActivityPage:
    page = items[offset : offset + limit]
    return page, len(page) < limit


def _fixture() -> dict[ActivityType, list[ActivityItem]]:
    """Deliberately uneven: `call` empty from the start, `note` much longer than the rest."""
    return {
        "meeting": [
            _activity(f"meeting-{i}", "meeting", date(2026, 1, 30 - i)) for i in range(5)
        ],
        "call": [],
        "note": [_activity(f"note-{i}", "note", date(2026, 2, 28 - i)) for i in range(23)],
        "document": [
            _activity(f"document-{i}", "document", date(2026, 3, 5 - i)) for i in range(3)
        ],
    }


class TestCursorRoundTrip:
    @pytest.mark.parametrize("limit", [1, 2, 3, 4, 5, 7, 10])
    def test_pages_to_exhaustion_with_no_gaps_or_duplicates(self, limit: int) -> None:
        fixture = _fixture()
        expected_ids = {item.id for items in fixture.values() for item in items}

        collected: list[str] = []
        consumed: dict[ActivityType, int] = {}
        cursor: str | None = None
        for _ in range(200):  # generous cap: a real bug here would otherwise hang the suite
            if cursor is None:
                # First page: every stream is active, none exhausted yet.
                active_streams = set(fixture.keys())
                page_limit = limit
            else:
                decoded = decode_cursor(cursor)
                # Every still-active stream appears in `consumed` (even at 0) — an exhausted
                # stream is the only thing omitted, so its keys are exactly the active set.
                consumed = dict(decoded.consumed)
                active_streams = set(consumed.keys())
                page_limit = decoded.limit

            pages: dict[ActivityType, _ActivityPage] = {
                stream: _fetch(
                    fixture[stream], limit=page_limit, offset=consumed.get(stream, 0)
                )
                for stream in active_streams
            }
            result = merge_page(pages, consumed)
            collected.extend(record.item.id for record in result.records)
            cursor = encode_cursor(
                segment="organizations",
                entity_id="42",
                limit=page_limit,
                activity_types=None,
                since=None,
                until=None,
                consumed=result.consumed,
            )
            if cursor is None:
                break
        else:
            pytest.fail("paging did not terminate within 200 pages")

        assert len(collected) == len(expected_ids), "duplicate record emitted somewhere"
        assert set(collected) == expected_ids, "at least one record was never emitted"


class TestEncodeCursor:
    def test_returns_none_when_every_stream_is_exhausted(self) -> None:
        assert (
            encode_cursor(
                segment="people",
                entity_id="1",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
                consumed={},
            )
            is None
        )

    def test_round_trips_full_query_state(self) -> None:
        cursor = encode_cursor(
            segment="organizations",
            entity_id="123456",
            limit=25,
            activity_types=["meeting", "call"],
            since=date(2026, 1, 1),
            until=date(2026, 12, 31),
            consumed={"meeting": 25, "call": 50, "note": 5},
        )
        assert cursor is not None
        decoded = decode_cursor(cursor)
        assert decoded.segment == "organizations"
        assert decoded.entity_id == "123456"
        assert decoded.limit == 25
        assert decoded.activity_types == ("call", "meeting")  # sorted unique
        assert decoded.since == date(2026, 1, 1)
        assert decoded.until == date(2026, 12, 31)
        assert dict(decoded.consumed) == {"meeting": 25, "call": 50, "note": 5}


class TestDecodeCursor:
    def _cursor(
        self,
        *,
        segment: Segment = "organizations",
        entity_id: str = "42",
        limit: int = 10,
        activity_types: Collection[ActivityType] | None = None,
        since: date | None = None,
        until: date | None = None,
        consumed: Mapping[ActivityType, int] | None = None,
    ) -> str:
        cursor = encode_cursor(
            segment=segment,
            entity_id=entity_id,
            limit=limit,
            activity_types=activity_types,
            since=since,
            until=until,
            consumed=consumed if consumed is not None else {"meeting": 10},
        )
        assert cursor is not None
        return cursor

    def _decode_payload(self, cursor: str) -> dict[str, object]:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = cast("object", json.loads(base64.urlsafe_b64decode(padded)))
        assert isinstance(payload, dict)
        return cast("dict[str, object]", payload)

    def _encode_payload(self, payload: dict[str, object]) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def test_empty_activity_types_normalizes_to_none(self) -> None:
        cursor = self._cursor(activity_types=[])
        decoded = decode_cursor(cursor)
        assert decoded.activity_types is None

    def test_activity_types_order_independent(self) -> None:
        cursor = self._cursor(activity_types=["note", "meeting", "meeting"])
        decoded = decode_cursor(cursor)
        assert decoded.activity_types == ("meeting", "note")

    def test_activity_types_accepts_email(self) -> None:
        # `email` lives on a separate endpoint from the four `/activities` types, but it's still
        # a selectable value in `activity_types` — a caller can ask for email-only, or exclude it
        # from an otherwise-default set.
        cursor = self._cursor(activity_types=["email", "meeting"])
        decoded = decode_cursor(cursor)
        assert decoded.activity_types == ("email", "meeting")

    def test_corrupted_cursor_string_raises_invalid_cursor(self) -> None:
        with pytest.raises(InvalidCursor):
            decode_cursor("not-a-valid-cursor-at-all-!!!")

    def test_truncated_cursor_raises_invalid_cursor(self) -> None:
        cursor = self._cursor()
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor[: len(cursor) // 2])

    def test_malformed_json_payload_raises_invalid_cursor(self) -> None:
        # JSON strings (including `entity_id`) are always valid Unicode text by construction, so
        # a decoded field with invalid UTF-8 bytes can't arise from otherwise well-formed JSON.
        # The decode failure this scenario targets instead is bytes that are valid base64 but
        # aren't syntactically valid JSON at all — `model_validate_json` raises its own
        # `ValidationError` on those, which must surface as `InvalidCursor`, not propagate.
        raw = bytes([0xFF, 0xFE, 0x00, 0x01, 0x02, 0x03])
        cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor)

    def test_unrecognized_shape_raises_invalid_cursor(self) -> None:
        # A well-formed JSON object that is missing every field `ActivityCursor` requires —
        # valid JSON, but pydantic's required-field validation rejects it on its own.
        raw = json.dumps({"unrelated": True}).encode()
        cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor)

    def test_missing_required_field_raises_invalid_cursor(self) -> None:
        # A well-formed JSON object with `consumed` dropped entirely — valid JSON, but
        # `ActivityCursor.consumed` is required, so pydantic rejects the omission on its own.
        payload = self._decode_payload(self._cursor())
        del payload["consumed"]
        cursor = self._encode_payload(payload)
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor)

    def test_wrong_field_type_raises_invalid_cursor(self) -> None:
        # `limit` as a string instead of an int — pydantic's strict-enough int coercion rejects
        # a non-numeric string on its own.
        payload = self._decode_payload(self._cursor())
        payload["limit"] = "not-a-number"
        cursor = self._encode_payload(payload)
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor)

    def test_unrecognized_segment_value_raises_invalid_cursor(self) -> None:
        # `segment` outside `Segment`'s `Literal["organizations", "people"]` membership —
        # pydantic rejects this on its own.
        payload = self._decode_payload(self._cursor())
        payload["segment"] = "not_a_real_segment"
        cursor = self._encode_payload(payload)
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor)

    def test_unrecognized_stream_key_raises_invalid_cursor(self) -> None:
        # A `consumed` key outside `ActivityType`'s five valid values — pydantic rejects this on
        # its own.
        payload = self._decode_payload(self._cursor())
        payload["consumed"] = {"not_a_real_stream": 1}
        cursor = self._encode_payload(payload)
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor)

    def test_unrecognized_activity_type_raises_invalid_cursor(self) -> None:
        payload = self._decode_payload(self._cursor())
        payload["activity_types"] = ["not_a_real_type"]
        cursor = self._encode_payload(payload)
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor)

    def test_unsupported_schema_version_raises_invalid_cursor(self) -> None:
        # Same shape as a valid cursor, but with the version field bumped past what's supported.
        # `Literal[1]` rejects this on its own (no manual version check left to name the failure
        # specifically), so this surfaces as the same generic "unrecognized shape" message as any
        # other pydantic validation failure.
        payload = self._decode_payload(self._cursor())
        version = payload["version"]
        assert isinstance(version, int)
        payload["version"] = version + 1
        bumped = self._encode_payload(payload)
        with pytest.raises(InvalidCursor, match="unrecognized shape"):
            decode_cursor(bumped)
