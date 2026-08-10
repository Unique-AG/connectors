"""`merge_page`/`fetch_offsets`: the k-way merge across streams, over plain in-memory pages.

`merge_page` is a pure, synchronous function — no HTTP, no `respx`, no async fixtures. Each test
builds a plain `{stream: (items, end_of_stream)}` dict directly, which is the whole point of
decoupling fetching from merging (see `merge.py`'s module docstring): the merge algorithm cannot
tell a synthetic fixture from a page a real `BackstopClient`-backed layer fetched.

Each test targets one behaviour from the design doc: the exact `(occurred_at desc, stream asc,
id desc)` tie-break (including the date-only-vs-timestamp granularity mismatch), that
`fetch_offsets` always returns a limit-aligned offset (the regression test for Backstop's "offset
N is not a multiple of limit M" error), that future-dated activities sort normally, that the
AND-exhaustion rule (short page *and* fully-consumed buffer) keeps a stream active when only part
of its buffer was taken, and that the one reachable internal invariant `assert` — a page with more
items than the requested limit — actually fires.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from backstop_mcp.features.activity_history import ActivityItem, EmailItem, merge_page
from backstop_mcp.features.activity_history.merge import fetch_offsets
from backstop_mcp.features.activity_history.streams import ActivityStreamKind, StreamKind

_ActivityPage = tuple[Sequence[ActivityItem], bool]
_EmailPage = tuple[Sequence[EmailItem], bool]


def _activity(
    item_id: str, stream: ActivityStreamKind, effective_date: date | None
) -> ActivityItem:
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


def _email(item_id: str, sent_timestamp: datetime | None) -> EmailItem:
    return EmailItem(
        id=item_id,
        subject=None,
        sent_timestamp=sent_timestamp,
        from_email=None,
        to_emails=(),
        cc_emails=(),
        has_attachments=None,
        content_url=None,
    )


def _page(items: Sequence[ActivityItem], *, limit: int, offset: int) -> _ActivityPage:
    """Slice a full in-memory list the way a real fetch at `(limit, offset)` would have."""
    page = items[offset : offset + limit]
    return page, len(page) < limit


def _email_page(items: Sequence[EmailItem], *, limit: int, offset: int) -> _EmailPage:
    page = items[offset : offset + limit]
    return page, len(page) < limit


class TestOrdering:
    def test_orders_strictly_by_occurred_at_descending(self) -> None:
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("m1", "meeting", date(2026, 1, 1))], True),
            "note": ([_activity("n1", "note", date(2026, 3, 1))], True),
            "email": ([_email("e1", datetime(2026, 2, 1, tzinfo=UTC))], True),
        }
        result = merge_page(pages, {}, limit=10)
        assert [r.item.id for r in result.records] == ["n1", "e1", "m1"]

    def test_ties_break_by_stream_ascending_then_id_descending(self) -> None:
        same_day = date(2026, 5, 1)
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("z", "meeting", same_day)], True),
            "call": (
                [_activity("b", "call", same_day), _activity("a", "call", same_day)],
                True,
            ),
            "note": ([_activity("q", "note", same_day)], True),
        }
        result = merge_page(pages, {}, limit=10)
        # Same occurred_at everywhere: stream name ascending ("call" < "meeting" < "note"),
        # and within "call" (same stream, same timestamp), id descending ("b" before "a").
        assert [(r.stream, r.item.id) for r in result.records] == [
            ("call", "b"),
            ("call", "a"),
            ("meeting", "z"),
            ("note", "q"),
        ]

    def test_same_day_email_sorts_above_same_day_meeting(self) -> None:
        same_day = date(2026, 6, 15)
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("m1", "meeting", same_day)], True),
            "email": ([_email("e1", datetime(2026, 6, 15, 9, 30, tzinfo=UTC))], True),
        }
        result = merge_page(pages, {}, limit=10)
        # A date-only effective_date normalizes to midnight UTC, which is earlier than any
        # real same-day timestamp, so the email (09:30) outranks the meeting (00:00).
        assert [r.item.id for r in result.records] == ["e1", "m1"]

    def test_future_dated_activity_participates_normally(self) -> None:
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": (
                [
                    _activity("future", "meeting", date(2099, 1, 1)),
                    _activity("past", "meeting", date(2000, 1, 1)),
                    _activity("today", "meeting", date(2026, 8, 10)),
                ],
                True,
            )
        }
        result = merge_page(pages, {}, limit=10)
        # No special-casing: newest-first, future included like any other date.
        assert [r.item.id for r in result.records] == ["future", "today", "past"]


class TestFetchOffsets:
    def test_consumed_zero_yields_offset_zero(self) -> None:
        assert fetch_offsets(["meeting"], {}, limit=7) == {"meeting": 0}

    def test_stream_absent_from_consumed_defaults_to_offset_zero(self) -> None:
        assert fetch_offsets(["meeting", "note"], {"meeting": 12}, limit=5) == {
            "meeting": 10,
            "note": 0,
        }

    def test_consumed_mid_page_aligns_down(self) -> None:
        # consumed=7 with limit=5 -> aligned offset is 5 (7 // 5 * 5), not 7.
        assert fetch_offsets(["meeting"], {"meeting": 7}, limit=5) == {"meeting": 5}

    def test_consumed_exactly_at_a_page_boundary_stays_put(self) -> None:
        assert fetch_offsets(["meeting"], {"meeting": 10}, limit=5) == {"meeting": 10}


class TestOffsetAlignment:
    @pytest.mark.parametrize("limit", [1, 3, 5, 8])
    @pytest.mark.parametrize("consumed_value", [0, 1, 4, 9, 17])
    def test_offset_is_always_a_multiple_of_limit(self, limit: int, consumed_value: int) -> None:
        offsets = fetch_offsets(["meeting"], {"meeting": consumed_value}, limit=limit)
        assert offsets["meeting"] % limit == 0

    def test_resuming_mid_page_aligns_and_skips_client_side(self) -> None:
        items = [_activity(f"m{i}", "meeting", date(2026, 1, 20 - i)) for i in range(12)]
        # consumed=7 with limit=5 -> aligned offset must be 5 (7 // 5 * 5); the fetched page is
        # items[5:10] (m5..m9), and skip=2 drops m5/m6 client-side, leaving m7/m8/m9.
        offsets = fetch_offsets(["meeting"], {"meeting": 7}, limit=5)
        assert offsets == {"meeting": 5}
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": _page(items, limit=5, offset=offsets["meeting"])
        }
        result = merge_page(pages, {"meeting": 7}, limit=5)
        assert [r.item.id for r in result.records] == ["m7", "m8", "m9"]


class TestExhaustion:
    def test_stream_is_omitted_once_fully_drained(self) -> None:
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("only", "meeting", date(2026, 1, 1))], True)
        }
        result = merge_page(pages, {}, limit=10)
        assert [r.item.id for r in result.records] == ["only"]
        assert result.consumed == {}

    def test_stream_stays_active_when_page_is_only_partially_taken(self) -> None:
        items = [_activity(f"m{i}", "meeting", date(2026, 1, 10 - i)) for i in range(5)]
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": _page(items, limit=2, offset=0)
        }
        result = merge_page(pages, {}, limit=2)
        assert len(result.records) == 2
        assert result.consumed == {"meeting": 2}

    def test_stream_stays_active_when_short_page_is_outranked_by_another_stream(self) -> None:
        """Exhaustion requires BOTH a short page AND a fully-consumed buffer.

        Stream "meeting" returns a genuinely short page (`end_of_stream=True`), but stream
        "note" has enough newer-than-its-oldest-item records that only part of "meeting"'s
        buffer is taken this round. "meeting" must stay ACTIVE in `consumed`, not be dropped as
        exhausted, even though the backend told the truth about it being short.
        """
        a1 = _activity("a1", "meeting", date(2026, 1, 10))
        a2 = _activity("a2", "meeting", date(2026, 1, 1))
        # All sort strictly between a1 and a2.
        b_items = [_activity(f"b{i}", "note", date(2026, 1, 9 - i)) for i in range(5)]
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {
            "meeting": ([a1, a2], True),
            "note": _page(b_items, limit=5, offset=0),
        }
        result = merge_page(pages, {}, limit=5)

        assert [r.item.id for r in result.records] == ["a1", "b0", "b1", "b2", "b3"]
        # "meeting" had 2 buffered but only 1 taken (a2 was left over) -- still active.
        assert "meeting" in result.consumed
        assert result.consumed["meeting"] == 1
        assert result.consumed["note"] == 4


class TestInvariantAssertions:
    def test_page_with_more_than_the_requested_limit_trips_the_assertion(self) -> None:
        lied_items = [_activity(f"lie-{i}", "meeting", date(2026, 1, 1)) for i in range(999)]
        pages: dict[StreamKind, _ActivityPage | _EmailPage] = {"meeting": (lied_items, True)}
        with pytest.raises(AssertionError, match="more than the requested limit"):
            merge_page(pages, {}, limit=5)
