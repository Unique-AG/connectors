"""`GetActivityHistoryQuery.run` grouping: per-stream date_range and next continuation.

Each test drives a mocked page through `run` and reads the published group. Date-range and
continuation bounds on the response models are checked without HTTP.
"""

from datetime import date

import httpx
import pytest
import respx
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    ActivityContinuationResponse,
    ActivityGroupResponse,
    ActivityType,
    DateRangeResponse,
    Segment,
    TimelineRecord,
)
from backstop_mcp.features.party_resolver import ResolvedPartyDto
from tests.features.activity_history.conftest import make_get_activity_history_query
from tests.helpers import BASE_URL, collection, resource


def _activity(item_id: str, effective_date: str | None = None) -> dict[str, object]:
    if effective_date is None:
        return resource(item_id, "activities", title=item_id)
    return resource(item_id, "activities", title=item_id, effectiveDate=effective_date)


def _email(item_id: str, sent_timestamp: str | None = None) -> dict[str, object]:
    if sent_timestamp is None:
        return resource(item_id, "emails", subject=item_id)
    return resource(item_id, "emails", subject=item_id, sentTimestamp=sent_timestamp)


def _mock_party(segment: str, entity_id: str) -> None:
    respx.get(f"{BASE_URL}/{segment}/{entity_id}").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"type": segment, "id": entity_id, "attributes": {"name": "Party"}}},
        )
    )


async def _run_group(
    client: BackstopClient,
    *rows: dict[str, object],
    activity_type: ActivityType = "meeting",
    segment: Segment = "organizations",
    entity_id: str = "42",
    limit: int = 10,
    offset: int = 0,
    since: date | None = None,
    until: date | None = None,
) -> ActivityGroupResponse[TimelineRecord]:
    _mock_party(segment, entity_id)
    collection_name = "emails" if activity_type == "email" else "activities"
    respx.get(f"{BASE_URL}/{segment}/{entity_id}/{collection_name}").mock(
        return_value=httpx.Response(200, json=collection(*rows))
    )
    result = await make_get_activity_history_query(client).run(
        segment=segment,
        entity_id=entity_id,
        party=ResolvedPartyDto(id=entity_id, search_type=segment, name="Party"),
        continuations={
            activity_type: ActivityContinuationResponse(
                limit=limit,
                offset=offset,
                since=since,
                until=until,
            )
        },
        gist_max_chars=300,
    )
    return result.groups[activity_type]


class TestDateRange:
    @pytest.mark.asyncio
    @respx.mock
    async def test_start_is_oldest_and_end_is_newest_on_the_page(
        self, client: BackstopClient
    ) -> None:
        result = await _run_group(
            client,
            _activity("newest", "2026-03-01"),
            _activity("middle", "2026-02-01"),
            _activity("oldest", "2026-01-01"),
        )

        assert result.date_range == DateRangeResponse(start=date(2026, 1, 1), end=date(2026, 3, 1))

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_page_is_empty(self, client: BackstopClient) -> None:
        result = await _run_group(client)

        assert result.date_range is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_every_item_lacks_a_date(self, client: BackstopClient) -> None:
        result = await _run_group(client, _activity("a"), _activity("b"))

        assert result.date_range is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_omits_items_that_lack_a_date_from_the_range(
        self, client: BackstopClient
    ) -> None:
        result = await _run_group(
            client,
            _activity("dated", "2026-02-01"),
            _activity("undated"),
        )

        assert result.date_range == DateRangeResponse(start=date(2026, 2, 1), end=date(2026, 2, 1))

    @pytest.mark.asyncio
    @respx.mock
    async def test_email_timestamp_contributes_its_utc_date(self, client: BackstopClient) -> None:
        # 23:00 US Eastern is the next calendar day in UTC.
        result = await _run_group(
            client,
            _email("e1", "2026-01-15T23:00:00-05:00"),
            activity_type="email",
        )

        assert result.date_range == DateRangeResponse(
            start=date(2026, 1, 16), end=date(2026, 1, 16)
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_naive_email_timestamp_is_treated_as_utc(self, client: BackstopClient) -> None:
        result = await _run_group(
            client,
            _email("e1", "2026-01-15T23:00:00"),
            activity_type="email",
        )

        assert result.date_range == DateRangeResponse(
            start=date(2026, 1, 15), end=date(2026, 1, 15)
        )


class TestNext:
    @pytest.mark.asyncio
    @respx.mock
    async def test_advances_offset_when_page_is_full(self, client: BackstopClient) -> None:
        rows = tuple(_activity(f"m{i}", f"2026-01-{10 - i:02d}") for i in range(5))
        result = await _run_group(client, *rows, limit=5, offset=10)

        assert result.next == ActivityContinuationResponse(
            limit=5, offset=15, since=None, until=None
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_page_is_short(self, client: BackstopClient) -> None:
        result = await _run_group(
            client,
            _activity("only", "2026-01-01"),
            limit=5,
        )

        assert result.next is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_page_is_empty(self, client: BackstopClient) -> None:
        result = await _run_group(client, limit=5)

        assert result.next is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_echoes_limit_since_and_until(self, client: BackstopClient) -> None:
        result = await _run_group(
            client,
            _activity("m0", "2026-01-03"),
            _activity("m1", "2026-01-02"),
            _activity("m2", "2026-01-01"),
            limit=3,
            since=date(2020, 1, 1),
            until=date(2026, 12, 31),
        )

        assert result.next == ActivityContinuationResponse(
            limit=3,
            offset=3,
            since=date(2020, 1, 1),
            until=date(2026, 12, 31),
        )


class TestItems:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_items_in_input_order(self, client: BackstopClient) -> None:
        result = await _run_group(
            client,
            _activity("newest", "2026-03-01"),
            _activity("oldest", "2026-01-01"),
            _activity("middle", "2026-02-01"),
        )

        assert [item.activity_id for item in result.items] == ["newest", "oldest", "middle"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_carries_the_requested_activity_type(self, client: BackstopClient) -> None:
        result = await _run_group(client, activity_type="email")

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
