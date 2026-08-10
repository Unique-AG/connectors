"""`encode_cursor`/`decode_and_validate_cursor`, and the full merge+cursor paging round-trip.

The round-trip test drives a synthetic multi-stream fixture (plain in-memory pages, no HTTP)
through `fetch_offsets` + `merge_page` + `encode_cursor`/`decode_and_validate_cursor` to full
exhaustion, across several `limit` values and deliberately uneven stream lengths (one empty from
the start, one much longer than the rest) — the regression test for a dropped or duplicated
record anywhere across a paging session.
"""

import base64
import json
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import cast

import pytest

from backstop_mcp.features.activity_history import (
    ActivityItem,
    CursorConflict,
    InvalidCursor,
    Segment,
    StreamKind,
    decode_and_validate_cursor,
    encode_cursor,
    fetch_offsets,
    merge_page,
)
from backstop_mcp.features.activity_history.streams import ActivityStreamKind

_ActivityPage = tuple[Sequence[ActivityItem], bool]


def _activity(item_id: str, stream: ActivityStreamKind, effective_date: date) -> ActivityItem:
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


def _fixture() -> dict[StreamKind, list[ActivityItem]]:
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
        consumed: dict[StreamKind, int] = {}
        cursor: str | None = None
        for _ in range(200):  # generous cap: a real bug here would otherwise hang the suite
            if cursor is None:
                # First page: every stream is active, none exhausted yet.
                active_streams = set(fixture.keys())
            else:
                consumed = decode_and_validate_cursor(
                    cursor,
                    segment="organizations",
                    entity_id="42",
                    limit=limit,
                    activity_types=None,
                    since=None,
                    until=None,
                )
                # Every still-active stream appears in `consumed` (even at 0) — an exhausted
                # stream is the only thing omitted, so its keys are exactly the active set.
                active_streams = set(consumed.keys())

            offsets = fetch_offsets(active_streams, consumed, limit=limit)
            pages: dict[StreamKind, _ActivityPage] = {
                stream: _fetch(fixture[stream], limit=limit, offset=offsets[stream])
                for stream in active_streams
            }
            result = merge_page(pages, consumed, limit=limit)
            collected.extend(record.item.id for record in result.records)
            cursor = encode_cursor(
                segment="organizations",
                entity_id="42",
                limit=limit,
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

    def test_is_reasonably_compact(self) -> None:
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
        # Not a strict byte-count assertion — a sanity check that this stays "short", per the
        # design doc's ~30-40 char target for typical inputs.
        assert len(cursor) < 80


class TestCursorAuthority:
    def _cursor(
        self,
        *,
        segment: Segment = "organizations",
        entity_id: str = "42",
        limit: int = 10,
        activity_types: Collection[ActivityStreamKind] | None = None,
        since: date | None = None,
        until: date | None = None,
        consumed: Mapping[StreamKind, int] | None = None,
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

    def test_conflicting_entity_id_raises_cursor_conflict(self) -> None:
        cursor = self._cursor(entity_id="42")
        with pytest.raises(CursorConflict, match="entity_id"):
            decode_and_validate_cursor(
                cursor,
                segment="organizations",
                entity_id="99",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
            )

    def test_conflicting_limit_raises_cursor_conflict(self) -> None:
        cursor = self._cursor(limit=10)
        with pytest.raises(CursorConflict, match="limit"):
            decode_and_validate_cursor(
                cursor,
                segment="organizations",
                entity_id="42",
                limit=25,
                activity_types=None,
                since=None,
                until=None,
            )

    def test_conflicting_segment_raises_cursor_conflict(self) -> None:
        cursor = self._cursor(segment="organizations")
        with pytest.raises(CursorConflict, match="segment"):
            decode_and_validate_cursor(
                cursor,
                segment="people",
                entity_id="42",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
            )

    def test_digest_mismatch_raises_invalid_cursor_with_restart_instruction(self) -> None:
        cursor = self._cursor(activity_types=["meeting"], since=date(2026, 1, 1))
        with pytest.raises(InvalidCursor, match="restart from page one"):
            decode_and_validate_cursor(
                cursor,
                segment="organizations",
                entity_id="42",
                limit=10,
                activity_types=["meeting", "call"],  # differs from what the cursor was issued for
                since=date(2026, 1, 1),
                until=None,
            )

    def test_matching_plain_fields_and_digest_round_trip_consumed(self) -> None:
        cursor = self._cursor(
            activity_types=["meeting", "note"],
            since=date(2026, 1, 1),
            until=date(2026, 6, 1),
            consumed={"meeting": 10, "note": 3},
        )
        consumed = decode_and_validate_cursor(
            cursor,
            segment="organizations",
            entity_id="42",
            limit=10,
            activity_types=["note", "meeting"],  # order-independent
            since=date(2026, 1, 1),
            until=date(2026, 6, 1),
        )
        assert consumed == {"meeting": 10, "note": 3}

    def test_corrupted_cursor_string_raises_invalid_cursor(self) -> None:
        with pytest.raises(InvalidCursor):
            decode_and_validate_cursor(
                "not-a-valid-cursor-at-all-!!!",
                segment="organizations",
                entity_id="42",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
            )

    def test_truncated_cursor_raises_invalid_cursor(self) -> None:
        cursor = self._cursor()
        with pytest.raises(InvalidCursor):
            decode_and_validate_cursor(
                cursor[: len(cursor) // 2],
                segment="organizations",
                entity_id="42",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
            )

    def test_malformed_json_payload_raises_invalid_cursor(self) -> None:
        # JSON strings (including `entity_id`) are always valid Unicode text by construction, so
        # a decoded field with invalid UTF-8 bytes can't arise from otherwise well-formed JSON.
        # The decode failure this scenario targets instead is bytes that are valid base64 but
        # aren't syntactically valid JSON at all — `TypeAdapter.validate_json` raises its own
        # `ValidationError` on those, which must surface as `InvalidCursor`, not propagate.
        raw = bytes([0xFF, 0xFE, 0x00, 0x01, 0x02, 0x03])
        cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        with pytest.raises(InvalidCursor):
            decode_and_validate_cursor(
                cursor,
                segment="organizations",
                entity_id="42",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
            )

    def test_unrecognized_shape_raises_invalid_cursor(self) -> None:
        # A well-formed JSON array (3 elements) that doesn't match the 6-element cursor tuple
        # type at all — valid JSON, but the `TypeAdapter`'s fixed-length tuple type rejects the
        # wrong arity on its own.
        raw = json.dumps([1, 2, 3]).encode()
        cursor = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        with pytest.raises(InvalidCursor):
            decode_and_validate_cursor(
                cursor,
                segment="organizations",
                entity_id="42",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
            )

    def test_unsupported_schema_version_raises_invalid_cursor(self) -> None:
        # Same shape as a valid cursor, but with the version field bumped past what's supported.
        # `Literal[1]` rejects this on its own (no manual version check left to name the failure
        # specifically), so this now surfaces as the same generic "unrecognized shape" message as
        # any other `TypeAdapter` validation failure.
        cursor = self._cursor()
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = cast("list[object]", json.loads(base64.urlsafe_b64decode(padded)))
        version = payload[0]
        assert isinstance(version, int)
        payload[0] = version + 1
        bumped_raw = json.dumps(payload).encode()
        bumped = base64.urlsafe_b64encode(bumped_raw).rstrip(b"=").decode("ascii")
        with pytest.raises(InvalidCursor, match="unrecognized shape"):
            decode_and_validate_cursor(
                bumped,
                segment="organizations",
                entity_id="42",
                limit=10,
                activity_types=None,
                since=None,
                until=None,
            )
