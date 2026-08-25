from datetime import date
from inspect import signature
from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import ToolMeta

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.accounts import (
    ProductAmbiguousResponse,
    TimeSeriesResolvedResponse,
)
from backstop_mcp.features.accounts.tools.get_time_series import get_time_series
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_decline, ctx_never_elicit
from tests.helpers import BASE_URL, recorded_params
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_ACCOUNT_ID = "29431089"
_PRODUCT_ID = "1292283"
_PRODUCTS_URL = f"{BASE_URL}/products"
_PRODUCT_URL = f"{BASE_URL}/products/{_PRODUCT_ID}"
_VALUES_URL = f"{BASE_URL}/accounts/{_ACCOUNT_ID}/values"
_IRRS_URL = f"{BASE_URL}/accounts/{_ACCOUNT_ID}/irrs"
_AUMS_URL = f"{BASE_URL}/products/{_PRODUCT_ID}/aums"


def _product_page(*products: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(products)})


def _product_document(product: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": product})


def _product_by_id_rejected(product_key: str, *, status: int) -> respx.Route:
    return respx.get(f"{_PRODUCTS_URL}/{product_key}").mock(
        return_value=httpx.Response(status, json={"errors": [{"title": "rejected"}]})
    )


def _cgup() -> dict[str, object]:
    return {
        "id": _PRODUCT_ID,
        "type": "products",
        "attributes": {
            "name": "Capstone Global Unconstrained Portfolio",
            "configuration": {"productShortName": "CGUP"},
        },
    }


def _point(point_id: str, **attributes: object) -> dict[str, object]:
    return {"id": point_id, "type": "time-series", "attributes": attributes}


def _series_page(*points: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(points)})


class TestGetTimeSeries:
    @pytest.mark.asyncio
    @respx.mock
    async def test_account_values_return_dated_points(self, client: BackstopClient) -> None:
        route = respx.get(_VALUES_URL).mock(
            return_value=_series_page(
                _point("new", date="2026-09-30", valueStatus="ESTIMATE"),
                _point("valued", date="2026-08-31", value=3619868606.0, valueStatus="ESTIMATE"),
            )
        )

        result = tool_model(
            await get_time_series(
                ctx_never_elicit(),
                entity_type="accounts",
                entity_id=_ACCOUNT_ID,
                series="values",
                client=client,
            ),
            TimeSeriesResolvedResponse,
        )

        assert route.call_count == 1
        params = recorded_params(route)[0]
        assert params["sort"] == "-date"
        assert params["fields"] == "date,value,valueStatus"
        assert "filter[date][ge]" not in params
        assert result.entity_id == _ACCOUNT_ID
        assert result.series == "values"
        payload = tool_payload(result)
        points = [object_dict(item) for item in object_list(payload["points"])]
        assert points[0] == {"date": "2026-09-30", "value_status": "ESTIMATE"}
        assert points[1]["value"] == 3619868606.0
        assert "source" not in points[0]

    @pytest.mark.asyncio
    @respx.mock
    async def test_date_window_is_sent_as_inclusive_filters(self, client: BackstopClient) -> None:
        route = respx.get(_IRRS_URL).mock(return_value=_series_page())

        await get_time_series(
            ctx_never_elicit(),
            entity_type="accounts",
            entity_id=_ACCOUNT_ID,
            series="irrs",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            client=client,
        )

        params = recorded_params(route)[0]
        assert route.call_count == 1
        assert params["filter[date][ge]"] == "2025-01-01"
        assert params["filter[date][le]"] == "2025-12-31"

    @pytest.mark.asyncio
    @respx.mock
    async def test_product_short_name_resolves_then_fetches_aums(
        self, client: BackstopClient
    ) -> None:
        by_id = _product_by_id_rejected("CGUP", status=400)
        catalog = respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        aums = respx.get(_AUMS_URL).mock(
            return_value=_series_page(
                _point("1", date="2026-08-31", value=4.5e9, source="AUM from Accounts")
            )
        )

        result = tool_model(
            await get_time_series(
                ctx_never_elicit(),
                entity_type="products",
                entity_id="CGUP",
                series="aums",
                client=client,
            ),
            TimeSeriesResolvedResponse,
        )

        assert by_id.call_count == 0
        assert catalog.call_count == 1
        assert aums.call_count == 1
        assert recorded_params(aums)[0]["fields"] == "date,value,source"
        assert result.entity_id == _PRODUCT_ID
        assert result.points[0].source == "AUM from Accounts"
        dumped = object_dict(object_list(tool_payload(result)["points"])[0])
        assert dumped["source"] == "AUM from Accounts"

    @pytest.mark.asyncio
    @respx.mock
    async def test_numeric_product_id_is_a_by_id_get_not_a_catalog_walk(
        self, client: BackstopClient
    ) -> None:
        by_id = respx.get(_PRODUCT_URL).mock(return_value=_product_document(_cgup()))
        catalog = respx.get(_PRODUCTS_URL).mock(return_value=_product_page())
        respx.get(_AUMS_URL).mock(return_value=_series_page())

        result = tool_model(
            await get_time_series(
                ctx_never_elicit(),
                entity_type="products",
                entity_id=_PRODUCT_ID,
                series="aums",
                client=client,
            ),
            TimeSeriesResolvedResponse,
        )

        assert by_id.call_count == 1
        assert catalog.call_count == 0
        assert result.entity_id == _PRODUCT_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_account_is_not_found(self, client: BackstopClient) -> None:
        respx.get(_VALUES_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )

        result = tool_model(
            await get_time_series(
                ctx_never_elicit(),
                entity_type="accounts",
                entity_id=_ACCOUNT_ID,
                series="values",
                client=client,
            ),
            NotFoundResponse,
        )

        assert result.query == _ACCOUNT_ID
        assert result.scope == "accounts"

    @pytest.mark.asyncio
    @respx.mock
    async def test_series_500_propagates(self, client: BackstopClient) -> None:
        respx.get(_VALUES_URL).mock(
            return_value=httpx.Response(
                500, json={"errors": [{"title": "InternalServerException"}]}
            )
        )

        with pytest.raises(BackstopApiError) as caught:
            await get_time_series(
                ctx_never_elicit(),
                entity_type="accounts",
                entity_id=_ACCOUNT_ID,
                series="values",
                client=client,
            )

        assert caught.value.status_code == 500

    @pytest.mark.asyncio
    @respx.mock
    async def test_product_series_404_after_resolve_is_not_unknown_product(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_cgup()))
        respx.get(_AUMS_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )

        with pytest.raises(BackstopApiError) as caught:
            await get_time_series(
                ctx_never_elicit(),
                entity_type="products",
                entity_id=_PRODUCT_ID,
                series="aums",
                client=client,
            )

        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    @respx.mock
    async def test_numeric_short_name_falls_through_to_the_catalog(
        self, client: BackstopClient
    ) -> None:
        by_id = _product_by_id_rejected("9001", status=404)
        catalog = respx.get(_PRODUCTS_URL).mock(
            return_value=_product_page(
                {
                    "id": _PRODUCT_ID,
                    "type": "products",
                    "attributes": {
                        "name": "Numeric Code Fund",
                        "configuration": {"productShortName": "9001"},
                    },
                }
            )
        )
        respx.get(_AUMS_URL).mock(return_value=_series_page())

        result = tool_model(
            await get_time_series(
                ctx_never_elicit(),
                entity_type="products",
                entity_id="9001",
                series="aums",
                client=client,
            ),
            TimeSeriesResolvedResponse,
        )

        assert by_id.call_count == 1
        assert catalog.call_count == 1
        assert result.entity_id == _PRODUCT_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_duplicate_short_name_is_ambiguous(self, client: BackstopClient) -> None:
        by_id = _product_by_id_rejected("BLUC", status=400)
        respx.get(_PRODUCTS_URL).mock(
            return_value=_product_page(
                {
                    "id": "1",
                    "type": "products",
                    "attributes": {
                        "name": "Blue One",
                        "configuration": {"productShortName": "BLUC"},
                    },
                },
                {
                    "id": "2",
                    "type": "products",
                    "attributes": {
                        "name": "Blue Two",
                        "configuration": {"productShortName": "BLUC"},
                    },
                },
            )
        )

        result = tool_model(
            await get_time_series(
                ctx_decline(),
                entity_type="products",
                entity_id="BLUC",
                series="aums",
                client=client,
            ),
            ProductAmbiguousResponse,
        )

        assert by_id.call_count == 0
        assert [candidate.id for candidate in result.candidates] == ["1", "2"]

    async def test_start_after_end_fails_before_any_request(self, client: BackstopClient) -> None:
        with pytest.raises(ValueError, match="start_date must not be after end_date"):
            await get_time_series(
                ctx_never_elicit(),
                entity_type="accounts",
                entity_id=_ACCOUNT_ID,
                series="values",
                start_date=date(2026, 12, 31),
                end_date=date(2026, 1, 1),
                client=client,
            )

    async def test_series_on_the_wrong_entity_fails_before_any_request(
        self, client: BackstopClient
    ) -> None:
        with pytest.raises(ValueError, match="not valid for accounts"):
            await get_time_series(
                ctx_never_elicit(),
                entity_type="accounts",
                entity_id=_ACCOUNT_ID,
                series="aums",
                client=client,
            )

    async def test_slash_in_entity_id_fails_before_any_request(
        self, client: BackstopClient
    ) -> None:
        with pytest.raises(ValueError, match="must not contain '/'"):
            await get_time_series(
                ctx_never_elicit(),
                entity_type="accounts",
                entity_id="29431089/values",
                series="values",
                client=client,
            )

    def test_is_registered_and_names_the_zero_trap(self) -> None:
        assert get_time_series in TOOLS
        names = {fn.__name__ for fn in TOOLS}
        assert "get_product_positions" not in names
        meta = get_fastmcp_meta(get_time_series)
        assert isinstance(meta, ToolMeta)
        doc = get_time_series.__doc__ or ""
        assert "assets under management" in doc
        assert "not one investor's balance" in doc
        assert "not in yet" in doc
        assert "analytics" in doc
        assert "fan-out" in doc
        series_help = ""
        annotation = cast(object, signature(get_time_series).parameters["series"].annotation)
        for extra in cast("tuple[object, ...]", get_args(annotation)):
            description = getattr(extra, "description", None)
            if isinstance(description, str):
                series_help = description
                break
        assert "lifetime P&L" in series_help
        assert "0.007" in series_help
        assert "life-to-date IRR" in series_help
        assert "beginning-of-period" in series_help
