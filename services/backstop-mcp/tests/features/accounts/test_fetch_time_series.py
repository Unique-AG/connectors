from datetime import date
from typing import cast

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.accounts import (
    ACCOUNT_SERIES,
    PRODUCT_SERIES,
    TimeSeriesName,
    fetch_time_series,
    require_series_for_entity,
)
from tests.helpers import BASE_URL, recorded_params, recorded_requests

_ACCOUNT_ID = "29431089"
_PRODUCT_ID = "1292283"
_VALUES_URL = f"{BASE_URL}/accounts/{_ACCOUNT_ID}/values"
_AUMS_URL = f"{BASE_URL}/products/{_PRODUCT_ID}/aums"
_EXPENSE_URL = f"{BASE_URL}/products/{_PRODUCT_ID}/expenseDataPoints"
_NEXT = (
    f"{BASE_URL}/accounts/{_ACCOUNT_ID}/values"
    "?page[offset]=100&page[limit]=100&sentinel=literal-next"
)


def _point(point_id: str, **attributes: object) -> dict[str, object]:
    return {"id": point_id, "type": "time-series", "attributes": attributes}


def _page(*points: dict[str, object], next_url: str | None = None) -> httpx.Response:
    payload: dict[str, object] = {"data": list(points)}
    if next_url is not None:
        payload["links"] = {"next": next_url}
    return httpx.Response(200, json=payload)


class TestRequireSeriesForEntity:
    def test_membership_sets_match_the_swagger_enums(self) -> None:
        assert len(ACCOUNT_SERIES) == 17
        assert len(PRODUCT_SERIES) == 11
        assert "currentMonthNetAssests" in ACCOUNT_SERIES
        assert "aums" in PRODUCT_SERIES

    def test_accepts_every_swagger_account_and_product_enum(self) -> None:
        for series in ACCOUNT_SERIES:
            require_series_for_entity("accounts", cast(TimeSeriesName, series))
        for series in PRODUCT_SERIES:
            require_series_for_entity("products", cast(TimeSeriesName, series))

    def test_rejects_a_series_that_belongs_to_the_other_entity(self) -> None:
        with pytest.raises(ValueError, match="not valid for accounts"):
            require_series_for_entity("accounts", "aums")
        with pytest.raises(ValueError, match="not valid for products"):
            require_series_for_entity("products", "values")


class TestFetchTimeSeries:
    @pytest.mark.asyncio
    @respx.mock
    async def test_pins_account_fields_sort_and_date_filters(self, client: BackstopClient) -> None:
        route = respx.get(_VALUES_URL).mock(
            return_value=_page(
                _point("1", date="2026-08-31", value=100.0, valueStatus="ESTIMATE"),
                _point("2", date="2026-07-31", value=90.0, valueStatus="ACTUAL"),
            )
        )

        points = await fetch_time_series(
            client,
            entity_type="accounts",
            entity_id=_ACCOUNT_ID,
            series="values",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )

        assert route.call_count == 1
        params = recorded_params(route)[0]
        assert params["sort"] == "-date"
        assert params["fields"] == "date,value,valueStatus"
        assert params["filter[date][ge]"] == "2026-01-01"
        assert params["filter[date][le]"] == "2026-12-31"
        assert params["page[limit]"] == "100"
        assert [point.value for point in points] == [100.0, 90.0]
        assert points[0].value_status == "ESTIMATE"
        assert points[0].source is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_omits_date_filters_when_no_window_is_given(self, client: BackstopClient) -> None:
        route = respx.get(_VALUES_URL).mock(return_value=_page())

        await fetch_time_series(
            client, entity_type="accounts", entity_id=_ACCOUNT_ID, series="values"
        )

        params = recorded_params(route)[0]
        assert "filter[date][ge]" not in params
        assert "filter[date][le]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_product_aums_ask_for_source(self, client: BackstopClient) -> None:
        route = respx.get(_AUMS_URL).mock(
            return_value=_page(
                _point("1", date="2026-08-31", value=1.5e9, source="AUM from Accounts")
            )
        )

        points = await fetch_time_series(
            client, entity_type="products", entity_id=_PRODUCT_ID, series="aums"
        )

        assert recorded_params(route)[0]["fields"] == "date,value,source"
        assert points[0].source == "AUM from Accounts"
        assert points[0].value_status is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_other_product_series_do_not_ask_for_source(self, client: BackstopClient) -> None:
        route = respx.get(_EXPENSE_URL).mock(
            return_value=_page(_point("1", date="2026-08-31", value=12.0))
        )

        await fetch_time_series(
            client,
            entity_type="products",
            entity_id=_PRODUCT_ID,
            series="expenseDataPoints",
        )

        assert recorded_params(route)[0]["fields"] == "date,value"

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_zero_and_unvalued_points_and_drops_undated(
        self, client: BackstopClient
    ) -> None:
        respx.get(_VALUES_URL).mock(
            return_value=_page(
                _point("new", date="2026-09-30T00:00:00.000-0400", valueStatus="ESTIMATE"),
                _point(
                    "zero",
                    date="2026-08-31T00:00:00.000-0400",
                    value=0.0,
                    valueStatus="ACTUAL",
                ),
                _point("undated", value=99.0),
            )
        )

        points = await fetch_time_series(
            client, entity_type="accounts", entity_id=_ACCOUNT_ID, series="values"
        )

        assert [(point.date.isoformat(), point.value) for point in points] == [
            ("2026-09-30", None),
            ("2026-08-31", 0.0),
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_request_for_a_single_page(self, client: BackstopClient) -> None:
        route = respx.get(_VALUES_URL).mock(return_value=_page(_point("1", date="2026-01-31")))

        await fetch_time_series(
            client, entity_type="accounts", entity_id=_ACCOUNT_ID, series="values"
        )

        assert route.call_count == 1
        assert len(recorded_requests(route.calls)) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_every_page_when_no_window_is_given(self, client: BackstopClient) -> None:
        route = respx.get(_VALUES_URL).mock(
            side_effect=[
                _page(_point("1", date="2026-08-31", value=2.0), next_url=_NEXT),
                _page(_point("2", date="2026-07-31", value=1.0)),
            ]
        )

        points = await fetch_time_series(
            client, entity_type="accounts", entity_id=_ACCOUNT_ID, series="values"
        )

        requests = recorded_requests(route.calls)
        assert route.call_count == 2
        assert str(requests[1].url) == _NEXT
        assert [point.value for point in points] == [2.0, 1.0]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_mid_chain_500_fails_rather_than_returning_a_prefix(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_VALUES_URL).mock(
            side_effect=[
                _page(_point("1", date="2026-08-31", value=1.0), next_url=_NEXT),
                httpx.Response(500, json={"errors": [{"title": "InternalServerException"}]}),
            ]
        )

        with pytest.raises(BackstopApiError) as caught:
            await fetch_time_series(
                client, entity_type="accounts", entity_id=_ACCOUNT_ID, series="values"
            )

        assert caught.value.status_code == 500
        assert route.call_count == 2
