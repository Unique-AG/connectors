"""`GetActivityHistoryQuery._group_page`: per-stream date_range and next continuation.

Grouping is a private method on the query — no HTTP, no `respx`, no async fixtures.
Each test builds a list of `ActivityRecordResponse`/`EmailRecordResponse` plus fetch params.

Each test targets one behaviour: this page's min/max `occurred_at` (including that start is the
oldest date even when Backstop returns newest-first), `date_range` of `None` when nothing dated
is present, UTC-normalized email timestamps, `next` present with an advanced offset when the
page was full and `None` when short/exhausted, echoed `limit`/`since`/`until`, and items
returned in input order.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import cast

import pytest
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    ActivityContinuationResponse,
    ActivityGroupResponse,
    ActivityRecordResponse,
    ActivityType,
    BackstopActivityType,
    DateRangeResponse,
    EmailRecordResponse,
    GetActivityHistoryQuery,
    TimelineRecord,
)


def _activity(
    item_id: str, stream: BackstopActivityType, effective_date: date | None
) -> ActivityRecordResponse:
    return ActivityRecordResponse(
        type=stream,
        activity_id=item_id,
        occurred_at=effective_date,
    )


def _email(item_id: str, sent_timestamp: datetime | None) -> EmailRecordResponse:
    return EmailRecordResponse(activity_id=item_id, occurred_at=sent_timestamp)


def _group(
    items: Sequence[TimelineRecord],
    *,
    activity_type: ActivityType = "meeting",
    end_of_stream: bool,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> ActivityGroupResponse[TimelineRecord]:
    query = GetActivityHistoryQuery(client=cast(BackstopClient, object()))
    return query._group_page(  # pyright: ignore[reportPrivateUsage]
        items,
        activity_type=activity_type,
        end_of_stream=end_of_stream,
        limit=limit,
        offset=offset,
        since=since,
        until=until,
    )


class TestDateRange:
    def test_start_is_oldest_and_end_is_newest_on_the_page(self) -> None:
        items = [
            _activity("newest", "meeting", date(2026, 3, 1)),
            _activity("middle", "meeting", date(2026, 2, 1)),
            _activity("oldest", "meeting", date(2026, 1, 1)),
        ]
        result = _group(items, end_of_stream=True, limit=10, offset=0)

        assert result.date_range == DateRangeResponse(start=date(2026, 1, 1), end=date(2026, 3, 1))

    def test_returns_none_when_page_is_empty(self) -> None:
        result = _group((), end_of_stream=True, limit=10, offset=0)

        assert result.date_range is None

    def test_returns_none_when_every_item_lacks_a_date(self) -> None:
        items = [_activity("a", "meeting", None), _email("e", None)]
        result = _group(items, end_of_stream=True, limit=10, offset=0)

        assert result.date_range is None

    def test_omits_items_that_lack_a_date_from_the_range(self) -> None:
        items = [
            _activity("dated", "meeting", date(2026, 2, 1)),
            _activity("undated", "meeting", None),
        ]
        result = _group(items, end_of_stream=True, limit=10, offset=0)

        assert result.date_range == DateRangeResponse(start=date(2026, 2, 1), end=date(2026, 2, 1))

    def test_email_timestamp_contributes_its_utc_date(self) -> None:
        # 23:00 US Eastern is the next calendar day in UTC.
        sent = datetime(2026, 1, 15, 23, 0, tzinfo=timezone(timedelta(hours=-5)))
        result = _group(
            [_email("e1", sent)], activity_type="email", end_of_stream=True, limit=10, offset=0
        )

        assert result.date_range == DateRangeResponse(
            start=date(2026, 1, 16), end=date(2026, 1, 16)
        )

    def test_naive_email_timestamp_is_treated_as_utc(self) -> None:
        sent = datetime(2026, 1, 15, 23, 0)
        result = _group(
            [_email("e1", sent)], activity_type="email", end_of_stream=True, limit=10, offset=0
        )

        assert result.date_range == DateRangeResponse(
            start=date(2026, 1, 15), end=date(2026, 1, 15)
        )


class TestNext:
    def test_advances_offset_when_page_is_full(self) -> None:
        items = [_activity(f"m{i}", "meeting", date(2026, 1, 10 - i)) for i in range(5)]
        result = _group(items, end_of_stream=False, limit=5, offset=10)

        assert result.next == ActivityContinuationResponse(
            limit=5, offset=15, since=None, until=None
        )

    def test_returns_none_when_page_is_short(self) -> None:
        result = _group(
            [_activity("only", "meeting", date(2026, 1, 1))],
            end_of_stream=True,
            limit=5,
            offset=0,
        )

        assert result.next is None

    def test_returns_none_when_page_is_empty(self) -> None:
        result = _group((), end_of_stream=True, limit=5, offset=0)

        assert result.next is None

    def test_echoes_limit_since_and_until(self) -> None:
        items = [_activity("m0", "meeting", date(2026, 1, 1))]
        result = _group(
            items,
            end_of_stream=False,
            limit=3,
            offset=0,
            since=date(2020, 1, 1),
            until=date(2026, 12, 31),
        )

        assert result.next == ActivityContinuationResponse(
            limit=3,
            offset=1,
            since=date(2020, 1, 1),
            until=date(2026, 12, 31),
        )


class TestItems:
    def test_returns_items_in_input_order(self) -> None:
        items = [
            _activity("newest", "meeting", date(2026, 3, 1)),
            _activity("oldest", "meeting", date(2026, 1, 1)),
            _activity("middle", "meeting", date(2026, 2, 1)),
        ]
        result = _group(items, end_of_stream=True, limit=10, offset=0)

        assert [item.activity_id for item in result.items] == ["newest", "oldest", "middle"]

    def test_carries_the_requested_activity_type(self) -> None:
        result = _group((), activity_type="email", end_of_stream=True, limit=10, offset=0)

        assert result.activity_type == "email"


class TestDateRangeBounds:
    def test_rejects_start_after_end(self) -> None:
        with pytest.raises(ValidationError, match="date_range.start must not be after"):
            DateRangeResponse(start=date(2026, 2, 1), end=date(2026, 1, 1))

    def test_accepts_equal_start_and_end(self) -> None:
        span = DateRangeResponse(start=date(2026, 1, 1), end=date(2026, 1, 1))
        assert span.start == span.end


class TestActivityContinuationBounds:
    def test_rejects_since_after_until(self) -> None:
        with pytest.raises(ValidationError, match="since must not be after until"):
            ActivityContinuationResponse(
                limit=10, offset=0, since=date(2026, 2, 1), until=date(2026, 1, 1)
            )

    def test_rejects_non_positive_limit(self) -> None:
        with pytest.raises(ValidationError):
            ActivityContinuationResponse(limit=0, offset=0)

    def test_rejects_negative_offset(self) -> None:
        with pytest.raises(ValidationError):
            ActivityContinuationResponse(limit=10, offset=-1)
