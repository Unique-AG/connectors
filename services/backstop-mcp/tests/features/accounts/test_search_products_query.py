from collections.abc import Mapping, Sequence
from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.accounts import ProductFetchDto
from backstop_mcp.features.custom_fields import CustomFieldMatch
from tests.features.accounts.conftest import make_search_products_query
from tests.helpers import BASE_URL, recorded_requests

_PRODUCTS_URL = f"{BASE_URL}/products"
_FLAVOR = "8830337"
_REGION = "8830335"


def _product(
    product_id: str,
    *,
    name: str,
    short_name: str,
    product_type: str | None = None,
    is_onshore: bool | None = None,
    inception_date: str | None = None,
    values: Sequence[Mapping[str, object]] | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "name": name,
        "configuration": {"productShortName": short_name},
        **(extra or {}),
    }
    if product_type is not None:
        attributes["productType"] = product_type
    if is_onshore is not None:
        attributes["isOnshore"] = is_onshore
    if inception_date is not None:
        attributes["inceptionDate"] = inception_date
    if values is not None:
        attributes["regularCustomFieldValues"] = list(values)
    return {"id": product_id, "type": "products", "attributes": attributes}


def _page(*products: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(products), "links": {"next": None}})


_GLOBAL_US = _product(
    "1",
    name="Northwind Global (US), LP",
    short_name="CGUP",
    product_type="ONSHORE_BALANCE_DRIVEN_TMV",
    is_onshore=True,
    inception_date="2007-08-01T00:00:00.000-0400",
    extra={
        "configuration": {
            "productShortName": "CGUP",
            "masterProductName": "masterName",
            "fiscalYearStartMonth": 1,
        },
        "defaultProductCurrency": "USD",
        "returnCalculationMethodology": "TWRR_MV_MR",
        "modifiedTimestamp": "2026-10-02T20:52:44.083-0400",
        "location": {"city": "Springfield", "stateOrProvince": "XX", "country": "Freedonia"},
        "description": {"fundDescription": "A fund.", "managerBio": "", "thesis": "Because."},
        "riskFreeRate": {"floating": True, "floatingRateBenchmarkSymbol": "None"},
        "serviceProviders": {"administrator": "Acme Admin", "auditors": " ", "custodian": 7},
    },
    values=[
        {"definitionId": _FLAVOR, "name": "Flavor", "value": "Alpha"},
        {"definitionId": _REGION, "name": "Region", "value": "South"},
    ],
)
_GLOBAL_OFFSHORE = _product(
    "2",
    name="Northwind Global (Offshore) Limited",
    short_name="CGOL",
    product_type="OFFSHORE_BALANCE_DRIVEN_TMV",
    is_onshore=False,
    values=[
        {"definitionId": _FLAVOR, "name": "Flavor", "value": "Beta"},
        {"definitionId": _REGION, "name": "Region", "value": "North"},
    ],
)
_BARE = _product("3", name="Bare Fund", short_name="BARE")


def _ids(products: Sequence[ProductFetchDto]) -> list[str]:
    return [item.product.id for item in products]


def _by_id_routes(*products: dict[str, object]) -> list[respx.Route]:
    return [
        respx.get(f"{_PRODUCTS_URL}/{product['id']}").mock(
            return_value=httpx.Response(200, json={"data": product})
        )
        for product in products
    ]


class TestSearchProductsQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_no_filters_reads_the_catalog_sorted_without_a_fieldset(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_PRODUCTS_URL).mock(return_value=_page(_GLOBAL_US, _GLOBAL_OFFSHORE))

        result = await make_search_products_query(client).run()

        assert _ids(result.products) == ["1", "2"]
        params = recorded_requests(route.calls)[0].url.params
        assert "fields" not in params
        assert params["sort"] == "name"
        assert "filter[name][like]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_full_record_carries_type_onshore_and_inception_date(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_page(_GLOBAL_US))

        item = (await make_search_products_query(client).run()).products[0]

        assert item.product_type == "ONSHORE_BALANCE_DRIVEN_TMV"
        assert item.is_onshore is True
        assert item.inception_date == date(2007, 8, 1)
        assert item.product.short_name == "CGUP"

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_record_carries_the_remaining_product_fields(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_page(_GLOBAL_US, _BARE))

        loaded, bare = (await make_search_products_query(client).run()).products

        assert loaded.currency == "USD"
        assert loaded.master_product_name == "masterName"
        assert loaded.fiscal_year_start_month == 1
        assert loaded.return_calculation_methodology == "TWRR_MV_MR"
        assert loaded.modified_timestamp is not None
        assert loaded.modified_timestamp.year == 2026
        assert (loaded.city, loaded.state_or_province, loaded.country) == (
            "Springfield",
            "XX",
            "Freedonia",
        )
        assert loaded.description is not None
        assert loaded.description.fund_description == "A fund."
        assert loaded.description.thesis == "Because."
        assert loaded.description.manager_bio is None
        assert loaded.risk_free_rate is not None
        assert loaded.risk_free_rate.floating is True
        assert loaded.risk_free_rate.floating_rate_benchmark_symbol == "None"
        assert loaded.service_providers == {"administrator": "Acme Admin"}
        assert bare.currency is None
        assert bare.country is None
        assert bare.description is None
        assert bare.risk_free_rate is None
        assert bare.service_providers == {}

    @pytest.mark.asyncio
    @respx.mock
    async def test_name_is_matched_in_memory_and_modified_since_is_a_server_side_gt(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_PRODUCTS_URL).mock(
            return_value=_page(_GLOBAL_US, _GLOBAL_OFFSHORE, _BARE)
        )

        result = await make_search_products_query(client).run(
            name="  Global ", modified_since=date(2026, 10, 1)
        )

        assert _ids(result.products) == ["1", "2"]
        assert route.call_count == 1
        params = recorded_requests(route.calls)[0].url.params
        assert "filter[name][like]" not in params
        assert params["filter[modifiedTimestamp][gt]"] == "2026-10-01"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_whole_short_name_matches_case_insensitively(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_PRODUCTS_URL).mock(
            return_value=_page(_GLOBAL_US, _GLOBAL_OFFSHORE, _BARE)
        )

        result = await make_search_products_query(client).run(name="cgup")

        assert _ids(result.products) == ["1"]
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_short_name_inside_another_name_ranks_first(
        self, client: BackstopClient
    ) -> None:
        convert_arb = _product("10", name="Convert Arb Fund", short_name="CVAF")
        global_arb = _product("11", name="Global Arbor Fund", short_name="GARB")
        merger = _product("12", name="Merger Opportunities Partners", short_name="ARB")
        respx.get(_PRODUCTS_URL).mock(return_value=_page(convert_arb, global_arb, merger))

        result = await make_search_products_query(client).run(name="arb")

        assert _ids(result.products) == ["12", "10", "11"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_short_name_fragment_finds_nothing(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_page(_GLOBAL_US, _GLOBAL_OFFSHORE))

        result = await make_search_products_query(client).run(name="CGU")

        assert result.products == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_every_page_with_no_scan_ceiling(self, client: BackstopClient) -> None:
        next_url = f"{_PRODUCTS_URL}?page=2"
        respx.get(_PRODUCTS_URL).mock(
            side_effect=[
                httpx.Response(200, json={"data": [_GLOBAL_US], "links": {"next": next_url}}),
                httpx.Response(200, json={"data": [_GLOBAL_OFFSHORE], "links": {"next": None}}),
            ]
        )

        result = await make_search_products_query(client).run(name="Offshore")

        assert _ids(result.products) == ["2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_in_memory_filters_narrow_the_read(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_page(_GLOBAL_US, _GLOBAL_OFFSHORE, _BARE))
        query = make_search_products_query(client)

        by_type = await query.run(product_type="offshore_balance_driven_tmv")
        onshore = await query.run(is_onshore=True)
        offshore = await query.run(is_onshore=False)

        assert _ids(by_type.products) == ["2"]
        assert _ids(onshore.products) == ["1"]
        assert _ids(offshore.products) == ["2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_filters_and_together(self, client: BackstopClient) -> None:
        _by_id_routes(_GLOBAL_US, _GLOBAL_OFFSHORE, _BARE)

        both = await make_search_products_query(client).run(
            product_ids=["1", "2"], is_onshore=False
        )
        none = await make_search_products_query(client).run(product_ids=["1"], is_onshore=False)

        assert _ids(both.products) == ["2"]
        assert none.products == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_field_values_or_within_a_predicate_and_between_predicates(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_page(_GLOBAL_US, _GLOBAL_OFFSHORE, _BARE))
        query = make_search_products_query(client)

        either = await query.run(custom_fields=[CustomFieldMatch(_FLAVOR, ("beta", "Alpha"))])
        both = await query.run(
            custom_fields=[
                CustomFieldMatch(_FLAVOR, ("Beta", "Alpha")),
                CustomFieldMatch(_REGION, ("North",)),
            ]
        )

        assert _ids(either.products) == ["1", "2"]
        assert _ids(both.products) == ["2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_missing_custom_field_value_never_matches(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_page(_BARE))

        result = await make_search_products_query(client).run(
            custom_fields=[CustomFieldMatch(_FLAVOR, ("Beta",))]
        )

        assert result.products == ()


class TestSearchProductsByIds:
    @pytest.mark.asyncio
    @respx.mock
    async def test_reads_each_id_without_a_fieldset_and_never_walks_the_catalog(
        self, client: BackstopClient
    ) -> None:
        catalog = respx.get(_PRODUCTS_URL).mock(return_value=_page(_GLOBAL_US))
        routes = _by_id_routes(_GLOBAL_US, _GLOBAL_OFFSHORE)

        result = await make_search_products_query(client).run(product_ids=["2", " 1 ", "2"])

        assert catalog.call_count == 0
        assert [route.call_count for route in routes] == [1, 1]
        for route in routes:
            assert dict(recorded_requests(route.calls)[0].url.params) == {}
        full = next(item for item in result.products if item.product.id == "1")
        assert full.product_type == "ONSHORE_BALANCE_DRIVEN_TMV"
        assert [value.definition_id for value in full.stored_custom_field_values] == [
            _FLAVOR,
            _REGION,
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_sorts_by_name_like_the_catalog_read(self, client: BackstopClient) -> None:
        _by_id_routes(_GLOBAL_US, _GLOBAL_OFFSHORE, _BARE)

        result = await make_search_products_query(client).run(product_ids=["1", "2", "3"])

        assert _ids(result.products) == ["3", "2", "1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_missing_or_invalid_id_is_absent_not_an_error(
        self, client: BackstopClient
    ) -> None:
        _by_id_routes(_BARE)
        respx.get(f"{_PRODUCTS_URL}/999").mock(
            return_value=httpx.Response(
                404,
                json={
                    "errors": [
                        {
                            "code": "ResourceNotFoundException",
                            "title": "Resource products not found by id 999",
                        }
                    ]
                },
            )
        )
        respx.get(f"{_PRODUCTS_URL}/NGUP").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "code": "InvalidParameterException",
                            "title": "Resource products with id NGUP is invalid",
                        }
                    ]
                },
            )
        )

        result = await make_search_products_query(client).run(product_ids=["3", "999", "NGUP"])

        assert _ids(result.products) == ["3"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_any_other_error_stays_an_error(self, client: BackstopClient) -> None:
        respx.get(f"{_PRODUCTS_URL}/3").mock(
            return_value=httpx.Response(403, json={"errors": [{"title": "Forbidden"}]})
        )

        with pytest.raises(BackstopApiError) as caught:
            await make_search_products_query(client).run(product_ids=["3"])

        assert caught.value.status_code == 403

    @pytest.mark.asyncio
    @respx.mock
    async def test_name_and_modified_since_apply_in_memory(self, client: BackstopClient) -> None:
        _by_id_routes(_GLOBAL_US, _GLOBAL_OFFSHORE, _BARE)
        query = make_search_products_query(client)

        by_name = await query.run(product_ids=["1", "2", "3"], name="bare")
        by_short_name = await query.run(product_ids=["1", "2", "3"], name="cgol")
        modified_after = await query.run(
            product_ids=["1", "2", "3"], modified_since=date(2026, 10, 1)
        )
        same_day = await query.run(product_ids=["1", "2", "3"], modified_since=date(2026, 10, 2))

        assert _ids(by_name.products) == ["3"]
        assert _ids(by_short_name.products) == ["2"]
        assert _ids(modified_after.products) == ["1"]
        assert same_day.products == ()
