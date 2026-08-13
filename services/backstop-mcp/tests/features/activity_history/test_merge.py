"""`merge_page`: the k-way merge across streams, over plain in-memory pages.

`merge_page` is a pure, synchronous function — no HTTP, no `respx`, no async fixtures. Each test
builds a plain `{stream: (items, end_of_stream)}` dict directly, which is the whole point of
decoupling fetching from merging (see `merge.py`'s module docstring): the merge algorithm cannot
tell a synthetic fixture from a page a real `BackstopClient`-backed layer fetched.

Each test targets one behaviour from the design doc: the exact `(occurred_at desc, stream asc,
id desc)` tie-break (including the date-only-vs-timestamp granularity mismatch), that future-dated
activities sort normally, and that a short page (`end_of_stream=True`) drops the stream from
`consumed`.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from backstop_mcp.features.activity_history import ActivityItem, EmailItem, merge_page
from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityType,
    BackstopActivityType,
)

_ActivityPage = tuple[Sequence[ActivityItem], bool]
_EmailPage = tuple[Sequence[EmailItem], bool]


def _activity(
    item_id: str, stream: BackstopActivityType, effective_date: date | None
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


class TestOrdering:
    def test_orders_strictly_by_occurred_at_descending(self) -> None:
        pages: dict[ActivityType, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("m1", "meeting", date(2026, 1, 1))], True),
            "note": ([_activity("n1", "note", date(2026, 3, 1))], True),
            "email": ([_email("e1", datetime(2026, 2, 1, tzinfo=UTC))], True),
        }
        result = merge_page(pages, {})
        assert [r.item.id for r in result.records] == ["n1", "e1", "m1"]

    def test_ties_break_by_stream_ascending_then_id_descending(self) -> None:
        same_day = date(2026, 5, 1)
        pages: dict[ActivityType, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("z", "meeting", same_day)], True),
            "call": (
                [_activity("b", "call", same_day), _activity("a", "call", same_day)],
                True,
            ),
            "note": ([_activity("q", "note", same_day)], True),
        }
        result = merge_page(pages, {})
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
        pages: dict[ActivityType, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("m1", "meeting", same_day)], True),
            "email": ([_email("e1", datetime(2026, 6, 15, 9, 30, tzinfo=UTC))], True),
        }
        result = merge_page(pages, {})
        # A date-only effective_date normalizes to midnight UTC, which is earlier than any
        # real same-day timestamp, so the email (09:30) outranks the meeting (00:00).
        assert [r.item.id for r in result.records] == ["e1", "m1"]

    def test_future_dated_activity_participates_normally(self) -> None:
        pages: dict[ActivityType, _ActivityPage | _EmailPage] = {
            "meeting": (
                [
                    _activity("future", "meeting", date(2099, 1, 1)),
                    _activity("past", "meeting", date(2000, 1, 1)),
                    _activity("today", "meeting", date(2026, 8, 10)),
                ],
                True,
            )
        }
        result = merge_page(pages, {})
        # No special-casing: newest-first, future included like any other date.
        assert [r.item.id for r in result.records] == ["future", "today", "past"]


class TestExhaustion:
    def test_stream_is_omitted_once_fully_drained(self) -> None:
        pages: dict[ActivityType, _ActivityPage | _EmailPage] = {
            "meeting": ([_activity("only", "meeting", date(2026, 1, 1))], True)
        }
        result = merge_page(pages, {})
        assert [r.item.id for r in result.records] == ["only"]
        assert result.consumed == {}

    def test_stream_stays_active_when_page_is_full(self) -> None:
        items = [_activity(f"m{i}", "meeting", date(2026, 1, 10 - i)) for i in range(5)]
        pages: dict[ActivityType, _ActivityPage | _EmailPage] = {
            "meeting": _page(items, limit=2, offset=0)
        }
        result = merge_page(pages, {})
        assert [r.item.id for r in result.records] == ["m0", "m1"]
        assert result.consumed == {"meeting": 2}

    def test_merges_every_item_from_every_stream(self) -> None:
        """No merged-page size cap — every fetched item is in the result, ordered."""
        a1 = _activity("a1", "meeting", date(2026, 1, 10))
        a2 = _activity("a2", "meeting", date(2026, 1, 1))
        b_items = [_activity(f"b{i}", "note", date(2026, 1, 9 - i)) for i in range(5)]
        pages: dict[ActivityType, _ActivityPage | _EmailPage] = {
            "meeting": ([a1, a2], True),
            "note": _page(b_items, limit=5, offset=0),
        }
        result = merge_page(pages, {})

        assert [r.item.id for r in result.records] == ["a1", "b0", "b1", "b2", "b3", "b4", "a2"]
        # meeting's page was short → omitted; note's page was full → still active.
        assert "meeting" not in result.consumed
        assert result.consumed == {"note": 5}
