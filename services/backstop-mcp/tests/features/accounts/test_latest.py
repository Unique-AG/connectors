from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopResponseSchemaError
from backstop_mcp.features.accounts.fetch_series import (
    SeriesPointResource,
    _latest_figure,
    fetch_series,
)
from backstop_mcp.features.accounts.internal_dto import SeriesFigureDto, SeriesPointDto
from tests.helpers import BASE_URL

_PATH = "/accounts/27871657/values"
_URL = f"{BASE_URL}{_PATH}"


def _point(point_id: str, **attributes: object) -> dict[str, object]:
    return {"id": point_id, "type": "values", "attributes": attributes}


def _resource(point_id: str, **attributes: object) -> SeriesPointResource:
    return SeriesPointResource.model_validate(_point(point_id, **attributes))


def _page(*points: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(points)})


class TestLatestFigure:
    def test_picks_the_greatest_date(self) -> None:
        point = _latest_figure(
            (
                _resource("1", date="2026-05-31", value=10.0, valueStatus="ACTUAL"),
                _resource("2", date="2026-06-15", value=11.0, valueStatus="ESTIMATE"),
                _resource("3", date="2026-06-30", value=12.0, valueStatus="ACTUAL"),
            )
        )

        latest = SeriesPointDto(date=date(2026, 6, 30), value=12.0, value_status="ACTUAL")
        assert point == SeriesFigureDto(latest=latest, valued=latest)

    def test_a_mid_month_point_after_month_end_wins(self) -> None:
        point = _latest_figure(
            (
                _resource("1", date="2026-06-30", value=100.0, valueStatus="ACTUAL"),
                _resource("2", date="2026-07-15", value=101.5, valueStatus="ESTIMATE"),
            )
        )

        assert point is not None
        assert point.valued is not None
        assert point.valued.date == date(2026, 7, 15)
        assert point.valued.value == 101.5
        assert point.valued.value_status == "ESTIMATE"

    def test_omits_value_status_when_backstop_omits_it(self) -> None:
        point = _latest_figure((_resource("1", date="2026-06-30", value=50.0),))

        latest = SeriesPointDto(date=date(2026, 6, 30), value=50.0, value_status=None)
        assert point == SeriesFigureDto(latest=latest, valued=latest)

    def test_skips_points_without_a_date(self) -> None:
        point = _latest_figure(
            (
                _resource("1", value=1.0),
                _resource("2", date="2026-01-31", value=2.0),
            )
        )

        assert point is not None
        assert point.valued is not None
        assert point.valued.date == date(2026, 1, 31)
        assert point.valued.value == 2.0

    def test_empty_page_is_none(self) -> None:
        assert _latest_figure(()) is None

    def test_all_undated_points_are_none(self) -> None:
        assert _latest_figure((_resource("1", value=1.0),)) is None

    def test_a_dated_point_without_a_value_does_not_shadow_the_last_number(self) -> None:
        figure = _latest_figure(
            (
                _resource("1", date="2026-06-30", value=1_000_000.0, valueStatus="ACTUAL"),
                _resource("2", date="2026-07-31", valueStatus="ESTIMATE"),
            )
        )

        assert figure is not None
        assert figure.latest.date == date(2026, 7, 31)
        assert figure.latest.value is None
        assert figure.valued is not None
        assert figure.valued.date == date(2026, 6, 30)
        assert figure.valued.value == 1_000_000.0

    def test_a_series_of_valueless_points_has_no_valued_point(self) -> None:
        figure = _latest_figure(
            (
                _resource("1", date="2026-06-30"),
                _resource("2", date="2026-07-31"),
            )
        )

        assert figure is not None
        assert figure.latest.date == date(2026, 7, 31)
        assert figure.valued is None


class TestFetchLatestFigure:
    @pytest.mark.asyncio
    @respx.mock
    async def test_asks_for_the_ten_newest_rows(self, client: BackstopClient) -> None:
        route = respx.get(_URL).mock(
            return_value=_page(_point("1", date="2026-07-31", value=9.0, valueStatus="ESTIMATE"))
        )

        point = await fetch_series(client, _PATH)

        params = route.calls.last.request.url.params
        assert route.call_count == 1
        assert params["sort"] == "-date"
        assert params["page[limit]"] == "10"
        latest = SeriesPointDto(date=date(2026, 7, 31), value=9.0, value_status="ESTIMATE")
        assert point == SeriesFigureDto(latest=latest, valued=latest)

    @pytest.mark.asyncio
    @respx.mock
    async def test_picks_max_date_on_the_page(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(
            return_value=_page(
                _point("1", date="2026-05-31", value=10.0),
                _point("2", date="2026-07-15", value=11.0, valueStatus="ESTIMATE"),
            )
        )

        point = await fetch_series(client, _PATH)

        assert point is not None
        assert point.valued is not None
        assert point.valued.date == date(2026, 7, 15)
        assert point.valued.value_status == "ESTIMATE"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_valueless_newest_row_does_not_hide_the_last_number(
        self, client: BackstopClient
    ) -> None:
        respx.get(_URL).mock(
            return_value=_page(
                _point("2", date="2026-07-31", valueStatus="ESTIMATE"),
                _point("1", date="2026-06-30", value=7.0, valueStatus="ACTUAL"),
            )
        )

        point = await fetch_series(client, _PATH)

        assert point is not None
        assert point.latest.date == date(2026, 7, 31)
        assert point.valued is not None
        assert point.valued.value == 7.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_series_is_none(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(return_value=_page())

        assert await fetch_series(client, _PATH) is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_malformed_point_fails_the_page(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(
            return_value=_page(
                {"type": "values", "attributes": {"date": "2026-07-31", "value": 1.0}}
            )
        )

        with pytest.raises(BackstopResponseSchemaError):
            await fetch_series(client, _PATH)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_non_numeric_value_is_unvalued_not_a_failed_page(
        self, client: BackstopClient
    ) -> None:
        respx.get(_URL).mock(
            return_value=_page(_point("1", date="2026-07-31", value="not-a-number"))
        )

        point = await fetch_series(client, _PATH)

        assert point is not None
        assert point.latest.date == date(2026, 7, 31)
        assert point.latest.value is None
        assert point.valued is None
