from datetime import date, timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopResponseSchemaError
from backstop_mcp.features.accounts.latest import (
    SeriesPointResource,
    fetch_latest_point,
    latest_point,
)
from backstop_mcp.features.accounts.types import SeriesPoint
from tests.helpers import BASE_URL, FIXED_TODAY

_PATH = "/accounts/27871657/values"
_URL = f"{BASE_URL}{_PATH}"
_NEXT = f"{_PATH}?page[offset]=100"
_NINETY_CUTOFF = (FIXED_TODAY - timedelta(days=90)).isoformat()
_YEAR_CUTOFF = (FIXED_TODAY - timedelta(days=365)).isoformat()


def _point(point_id: str, **attributes: object) -> dict[str, object]:
    return {"id": point_id, "type": "values", "attributes": attributes}


def _resource(point_id: str, **attributes: object) -> SeriesPointResource:
    return SeriesPointResource.model_validate(_point(point_id, **attributes))


def _page(
    *points: dict[str, object],
    next_url: str | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {"data": list(points)}
    if next_url is not None:
        payload["links"] = {"next": next_url}
    return httpx.Response(200, json=payload)


class TestLatestPoint:
    def test_picks_the_greatest_date(self) -> None:
        point = latest_point(
            (
                _resource("1", date="2026-05-31", value=10.0, valueStatus="ACTUAL"),
                _resource("2", date="2026-06-15", value=11.0, valueStatus="ESTIMATE"),
                _resource("3", date="2026-06-30", value=12.0, valueStatus="ACTUAL"),
            )
        )

        assert point == SeriesPoint(
            date=date(2026, 6, 30),
            value=12.0,
            value_status="ACTUAL",
        )

    def test_a_mid_month_point_after_month_end_wins(self) -> None:
        point = latest_point(
            (
                _resource("1", date="2026-06-30", value=100.0, valueStatus="ACTUAL"),
                _resource("2", date="2026-07-15", value=101.5, valueStatus="ESTIMATE"),
            )
        )

        assert point is not None
        assert point.date == date(2026, 7, 15)
        assert point.value == 101.5
        assert point.value_status == "ESTIMATE"

    def test_omits_value_status_when_backstop_omits_it(self) -> None:
        point = latest_point((_resource("1", date="2026-06-30", value=50.0),))

        assert point == SeriesPoint(date=date(2026, 6, 30), value=50.0, value_status=None)

    def test_skips_points_without_a_date(self) -> None:
        point = latest_point(
            (
                _resource("1", value=1.0),
                _resource("2", date="2026-01-31", value=2.0),
            )
        )

        assert point is not None
        assert point.date == date(2026, 1, 31)
        assert point.value == 2.0

    def test_empty_page_is_none(self) -> None:
        assert latest_point(()) is None

    def test_all_undated_points_are_none(self) -> None:
        assert latest_point((_resource("1", value=1.0),)) is None


class TestFetchLatestPoint:
    @pytest.mark.asyncio
    @respx.mock
    async def test_uses_the_ninety_day_window_when_it_has_points(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_URL).mock(
            return_value=_page(_point("1", date="2026-07-31", value=9.0, valueStatus="ESTIMATE"))
        )

        point = await fetch_latest_point(client, _PATH, today=FIXED_TODAY)

        params = route.calls.last.request.url.params
        assert route.call_count == 1
        assert params["filter[date][ge]"] == _NINETY_CUTOFF
        assert params["page[limit]"] == "100"
        assert point == SeriesPoint(date=date(2026, 7, 31), value=9.0, value_status="ESTIMATE")

    @pytest.mark.asyncio
    @respx.mock
    async def test_widens_to_a_year_when_ninety_days_are_empty(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_URL).mock(
            side_effect=[
                _page(),
                _page(_point("1", date="2025-12-31", value=4.0)),
            ]
        )

        point = await fetch_latest_point(client, _PATH, today=FIXED_TODAY)

        assert route.call_count == 2
        assert route.calls[0].request.url.params["filter[date][ge]"] == _NINETY_CUTOFF
        assert route.calls[1].request.url.params["filter[date][ge]"] == _YEAR_CUTOFF
        assert point is not None
        assert point.date == date(2025, 12, 31)
        assert point.value_status is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_paginates_unfiltered_when_both_windows_are_empty(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_URL).mock(
            side_effect=[
                _page(),
                _page(),
                _page(_point("1", date="2020-01-31", value=1.0), next_url=_NEXT),
                _page(_point("2", date="2020-06-15", value=2.0)),
            ]
        )

        point = await fetch_latest_point(client, _PATH, today=FIXED_TODAY)

        assert route.call_count == 4
        assert "filter[date][ge]" not in route.calls[2].request.url.params
        assert point is not None
        assert point.date == date(2020, 6, 15)
        assert point.value == 2.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_paginates_the_window_so_an_older_first_page_cannot_win(
        self, client: BackstopClient
    ) -> None:
        respx.get(_URL).mock(
            side_effect=[
                _page(_point("1", date="2026-05-31", value=10.0), next_url=_NEXT),
                _page(_point("2", date="2026-07-15", value=11.0, valueStatus="ESTIMATE")),
            ]
        )

        point = await fetch_latest_point(client, _PATH, today=FIXED_TODAY)

        assert point is not None
        assert point.date == date(2026, 7, 15)
        assert point.value_status == "ESTIMATE"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_series_is_none(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(side_effect=[_page(), _page(), _page()])

        assert await fetch_latest_point(client, _PATH, today=FIXED_TODAY) is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_malformed_point_fails_the_page(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(
            return_value=_page(
                _point("ok", date="2026-07-31", value=1.0),
                _point("bad", date="2026-07-31", value="not-a-number"),
            )
        )

        with pytest.raises(BackstopResponseSchemaError):
            await fetch_latest_point(client, _PATH, today=FIXED_TODAY)
