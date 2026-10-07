from collections.abc import Sequence
from datetime import date
from typing import cast

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import FunctionTool, ToolMeta

from backstop_mcp.backstop_client import BackstopApiError, BackstopAuthError, BackstopClient
from backstop_mcp.config import ProductInvestorsConfig
from backstop_mcp.features.accounts import (
    AccountRowResponse,
    ProductAmbiguousResponse,
    ProductInvestorsResolvedResponse,
)
from backstop_mcp.features.accounts.tools.get_product_investors import get_product_investors
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from tests.features.accounts.conftest import (
    make_get_accounts_for_product_query,
    make_get_latest_account_values_query,
)
from tests.features.party_resolver.helpers import ctx_accept, ctx_decline, ctx_never_elicit
from tests.helpers import BASE_URL, recorded_params, resource
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_CONFIG = ProductInvestorsConfig(max_valued_accounts=50)

_PRODUCT_ID = "1292283"
_OWNER_ID = "341688185"
_ACCOUNT_ID = "27871657"
_PRODUCTS_URL = f"{BASE_URL}/products"
_PRODUCT_URL = f"{BASE_URL}/products/{_PRODUCT_ID}"
_ACCOUNTS_URL = f"{BASE_URL}/accounts"
_EXPECTED_FIELDS = {
    "name",
    "currency",
    "accountStartDate",
    "closedDate",
    "ownershipType",
    "investorQualification",
    "isEmployeeAccount",
    "isGpAccount",
    "amlCheckComplete",
    "newIssueEligible",
    "usDomiciled",
}


def _ngup() -> dict[str, object]:
    return {
        "id": _PRODUCT_ID,
        "type": "products",
        "attributes": {
            "name": "Northwind Global Unconstrained Portfolio",
            "configuration": {"productShortName": "NGUP"},
        },
    }


def _accounts(result: ProductInvestorsResolvedResponse) -> tuple[AccountRowResponse, ...]:
    return tuple(account for listing in result.products for account in listing.accounts)


def _nwon() -> dict[str, object]:
    return {
        "id": "11",
        "type": "products",
        "attributes": {
            "name": "Northwind Dispersion Fund (Onshore)",
            "configuration": {"productShortName": "NWON"},
        },
    }


def _nwof() -> dict[str, object]:
    return {
        "id": "22",
        "type": "products",
        "attributes": {
            "name": "Northwind Dispersion Fund (Offshore)",
            "configuration": {"productShortName": "NWOF"},
        },
    }


def _values(*points: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {"id": str(index), "type": "values", "attributes": point}
                for index, point in enumerate(points)
            ]
        },
    )


def _product_document(product: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": product})


def _product_page(*products: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(products)})


def _account(
    account_id: str,
    *,
    owner_id: str | None = None,
    investor_type_id: str | None = None,
    **attributes: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {}
    if owner_id is not None:
        relationships["owner"] = {"data": {"type": "contacts", "id": owner_id}}
    if investor_type_id is not None:
        relationships["investorType"] = {"data": {"type": "investor-types", "id": investor_type_id}}
    return {
        "id": account_id,
        "type": "accounts",
        "attributes": attributes,
        "relationships": relationships,
    }


def _owner(owner_id: str, *, name: str) -> dict[str, object]:
    return resource(
        owner_id,
        "contacts",
        name=name,
        specificResource={"resourceType": "organizations", "resourceId": owner_id},
    )


def _accounts_page(
    *accounts: dict[str, object],
    included: Sequence[dict[str, object]] = (),
) -> httpx.Response:
    return httpx.Response(200, json={"data": list(accounts), "included": list(included)})


class TestGetProductInvestors:
    @pytest.mark.asyncio
    @respx.mock
    async def test_lists_owners_with_no_figures_in_two_requests(
        self, client: BackstopClient
    ) -> None:
        by_id = respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        accounts = respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account(
                    _ACCOUNT_ID,
                    owner_id=_OWNER_ID,
                    investor_type_id="10",
                    name="Tailspin NGUP",
                ),
                included=[
                    _owner(_OWNER_ID, name="Tailspin Investments"),
                    resource("10", "investor-types", name="Fund of Funds"),
                ],
            )
        )
        values = respx.get(f"{BASE_URL}/accounts/{_ACCOUNT_ID}/values").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert by_id.call_count == 1
        assert accounts.call_count == 1
        assert values.call_count == 0
        params = recorded_params(accounts)[0]
        assert params["filter[product.id][eq]"] == _PRODUCT_ID
        assert params["include"] == "owner,investorType"
        assert set(params["fields"].split(",")) == _EXPECTED_FIELDS | {"regularCustomFieldValues"}
        assert len(result.products) == 1
        listing = result.products[0]
        assert listing.product.id == _PRODUCT_ID
        assert listing.product.short_name == "NGUP"
        assert [row.id for row in listing.accounts] == [_ACCOUNT_ID]
        assert listing.accounts[0].owner is not None
        assert listing.accounts[0].owner.id == _OWNER_ID
        assert listing.accounts[0].owner.resource_type == "organizations"
        assert listing.accounts[0].investor_type is not None
        assert listing.accounts[0].investor_type.name == "Fund of Funds"
        assert [investor.id for investor in result.investors] == [_OWNER_ID]
        listing_payload = object_dict(object_list(tool_payload(result)["products"])[0])
        payload = object_dict(object_list(listing_payload["accounts"])[0])
        assert "latest_value" not in payload
        assert "product_id" not in payload
        investor_payload = object_dict(object_list(tool_payload(result)["investors"])[0])
        assert "latest_value_totals" not in investor_payload
        assert "custom_field_values" not in payload

    @pytest.mark.asyncio
    @respx.mock
    async def test_exclude_custom_fields_does_not_request_them(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        accounts = respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account(
                    _ACCOUNT_ID,
                    name="North account",
                    regularCustomFieldValues=[
                        {"definitionId": 8689949, "name": "Region", "value": "North"},
                    ],
                ),
            )
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                exclude_custom_fields=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert set(recorded_params(accounts)[0]["fields"].split(",")) == _EXPECTED_FIELDS
        assert _accounts(result)[0].custom_field_values is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_investor_type_publishes_name_and_classification_separately(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account(_ACCOUNT_ID, owner_id=_OWNER_ID, investor_type_id="10", name="Endowment"),
                included=[
                    _owner(_OWNER_ID, name="Tailspin Investments"),
                    resource(
                        "10",
                        "investor-types",
                        name="",
                        classificationType="Endowment/Foundation",
                        investorType="Endowment",
                    ),
                ],
            )
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        investor_type = _accounts(result)[0].investor_type
        assert investor_type is not None
        assert investor_type.name is None
        assert investor_type.classification_type == "Endowment/Foundation"

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_fields_are_published_on_each_account_by_default(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        accounts = respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account(
                    _ACCOUNT_ID,
                    owner_id=_OWNER_ID,
                    name="North account",
                    regularCustomFieldValues=[
                        {"definitionId": 8689949, "name": "Region", "value": "North"},
                    ],
                ),
                _account("2", name="Blank location"),
                included=[_owner(_OWNER_ID, name="Tailspin Investments")],
            )
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        params = recorded_params(accounts)[0]
        assert "regularCustomFieldValues" in params["fields"]
        listing_payload = object_dict(object_list(tool_payload(result)["products"])[0])
        rows = [object_dict(item) for item in object_list(listing_payload["accounts"])]
        assert rows[0]["custom_field_values"] == [
            {"definition_id": "8689949", "name": "Region", "value": "North"}
        ]
        assert "custom_field_values" not in rows[1]

    @pytest.mark.asyncio
    @respx.mock
    async def test_short_name_resolves_through_the_catalog(self, client: BackstopClient) -> None:
        by_id = respx.get(f"{_PRODUCTS_URL}/NGUP").mock(
            return_value=httpx.Response(400, json={"errors": [{"title": "Bad Request"}]})
        )
        catalog = respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_ngup()))
        accounts = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=["NGUP"],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert by_id.call_count == 0
        assert catalog.call_count == 1
        assert accounts.call_count == 1
        assert result.products[0].product.id == _PRODUCT_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_fund_name_covers_every_vehicle_it_matches(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_nwon(), _nwof()))
        accounts = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=["Northwind Dispersion Fund"],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert [listing.product.short_name for listing in result.products] == ["NWON", "NWOF"]
        assert accounts.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_overlapping_entries_list_each_product_once(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_nwon(), _nwof()))
        accounts = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=["NWOF", "Northwind Dispersion Fund"],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert [listing.product.short_name for listing in result.products] == ["NWOF", "NWON"]
        assert accounts.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_defaults_to_open_and_hints_when_all_are_closed(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(_account("closed", name="Gone", closedDate="2020-01-15"))
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        listing = result.products[0]
        assert listing.accounts == ()
        assert listing.closed_omitted == 1
        assert listing.include_closed_hint is not None
        assert "all of them are closed" in listing.include_closed_hint
        assert result.investors == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_closed_rows(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("open", name="Live"),
                _account("closed", name="Gone", closedDate="2020-01-15"),
            )
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_closed=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        listing = result.products[0]
        assert [row.id for row in listing.accounts] == ["open", "closed"]
        assert listing.closed_omitted == 0
        assert listing.include_closed_hint is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_product_is_not_found(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page())

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            NotFoundResponse,
        )

        assert result.query == _PRODUCT_ID
        assert result.scope == "products"

    @pytest.mark.asyncio
    @respx.mock
    async def test_duplicate_short_name_is_ambiguous(self, client: BackstopClient) -> None:
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
            await get_product_investors(
                ctx_decline(),
                products=["BLUC"],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductAmbiguousResponse,
        )

        assert [candidate.id for candidate in result.candidates] == ["1", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_accounts_listing_500_propagates(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=httpx.Response(
                500, json={"errors": [{"title": "InternalServerException"}]}
            )
        )

        with pytest.raises(BackstopApiError) as caught:
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            )

        assert caught.value.status_code == 500

    def test_products_is_the_only_product_argument_and_is_bounded(self) -> None:
        meta = get_fastmcp_meta(get_product_investors)
        assert isinstance(meta, ToolMeta)
        schema = object_dict(
            cast(
                "object",
                FunctionTool.from_function(get_product_investors, metadata=meta).parameters,
            )
        )
        properties = object_dict(schema["properties"])
        assert set(properties) == {
            "products",
            "include_closed",
            "include_latest_value",
            "investor_ids",
            "exclude_custom_fields",
        }
        assert schema["required"] == ["products"]
        products = object_dict(properties["products"])
        assert products["minItems"] == 1
        assert products["maxItems"] == 10
        latest = object_dict(properties["include_latest_value"])
        assert latest["default"] is False
        assert "Pass true when the answer needs balances" in str(latest["description"])
        assert "Ask the user first" not in str(latest["description"])

    def test_the_contacts_envelope_id_is_not_in_the_published_schema(self) -> None:
        meta = get_fastmcp_meta(get_product_investors)
        assert isinstance(meta, ToolMeta)
        schema = meta.output_schema

        assert schema is not None
        assert "OwnerResponse" in str(schema)
        assert "contacts_id" not in str(schema)

    def test_is_registered_and_names_the_two_step(self) -> None:
        assert get_product_investors in TOOLS
        meta = get_fastmcp_meta(get_product_investors)
        assert isinstance(meta, ToolMeta)
        doc = get_product_investors.__doc__ or ""
        assert "get_time_series" in doc
        assert "aums" in doc
        assert "one call per (account, series)" in doc
        assert "not one investor's balance" in doc
        assert "once per account" in doc
        assert "ask whether to pull latest" not in doc
        assert "include_latest_value=true" in doc
        assert "latest_value_totals" in doc
        assert "Investor Location" not in doc
        assert "geographical" not in doc
        assert "us_domiciled" not in doc
        assert "exclude_custom_fields" not in doc

    @pytest.mark.asyncio
    @respx.mock
    async def test_each_product_is_its_own_listing_and_an_investor_appears_once(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_nwon(), _nwof()))

        def accounts(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("filter[product.id][eq]") == "11":
                return _accounts_page(
                    _account("a1", owner_id=_OWNER_ID, name="Onshore"),
                    included=[_owner(_OWNER_ID, name="Contoso Pension")],
                )
            return _accounts_page(
                _account("a2", owner_id=_OWNER_ID, name="Offshore"),
                _account("a3", owner_id=_OWNER_ID, name="Closed", closedDate="2020-01-01"),
                included=[_owner(_OWNER_ID, name="Contoso Pension")],
            )

        accounts_route = respx.get(_ACCOUNTS_URL).mock(side_effect=accounts)
        respx.get(f"{BASE_URL}/accounts/a1/values").mock(
            return_value=_values({"date": "2026-09-30", "value": 30.0})
        )
        respx.get(f"{BASE_URL}/accounts/a2/values").mock(
            return_value=_values({"date": "2026-08-31", "value": 12.0})
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=["NWON", "NWOF"],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert accounts_route.call_count == 2
        assert [
            (
                listing.product.short_name,
                [row.id for row in listing.accounts],
                listing.closed_omitted,
            )
            for listing in result.products
        ] == [("NWON", ["a1"], 0), ("NWOF", ["a2"], 1)]
        assert len(result.investors) == 1
        investor = result.investors[0]
        assert investor.name == "Contoso Pension"
        assert [
            (holding.product_id, holding.product_short_name, holding.account_ids)
            for holding in investor.holdings
        ] == [("11", "NWON", ("a1",)), ("22", "NWOF", ("a2",))]
        holding_totals = [holding.latest_value_totals for holding in investor.holdings]
        assert [[total.amount for total in totals or ()] for totals in holding_totals] == [
            [30.0],
            [12.0],
        ]
        assert investor.latest_value_totals is not None
        assert [(total.amount, total.account_count) for total in investor.latest_value_totals] == [
            (42.0, 2)
        ]
        assert investor.latest_value_totals[0].oldest_as_of == date(2026, 8, 31)

    @pytest.mark.asyncio
    @respx.mock
    async def test_latest_values_fill_rows_and_sum_per_owner_and_currency(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id=_OWNER_ID, name="USD one", currency="USD"),
                _account("a2", owner_id=_OWNER_ID, name="USD two", currency="USD"),
                _account("a3", owner_id=_OWNER_ID, name="EUR", currency="EUR"),
                _account("a4", owner_id="other", name="Unpublished", currency="USD"),
                included=[
                    _owner(_OWNER_ID, name="Fabrikam Retirement"),
                    _owner("other", name="New LP"),
                ],
            )
        )
        respx.get(f"{BASE_URL}/accounts/a1/values").mock(
            return_value=_values(
                {"date": "2026-09-30", "value": 100.0, "valueStatus": "ESTIMATE"},
                {"date": "2026-08-31", "value": 90.0, "valueStatus": "ACTUAL"},
            )
        )
        respx.get(f"{BASE_URL}/accounts/a2/values").mock(
            return_value=_values(
                {"date": "2026-09-30"},
                {"date": "2026-08-31", "value": 50.0, "valueStatus": "ACTUAL"},
            )
        )
        respx.get(f"{BASE_URL}/accounts/a3/values").mock(
            return_value=_values({"date": "2026-09-30", "value": 7.0})
        )
        unpublished = respx.get(f"{BASE_URL}/accounts/a4/values").mock(return_value=_values())

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert recorded_params(unpublished)[0]["sort"] == "-date"
        latest = {row.id: row.latest_value for row in _accounts(result)}
        assert latest["a1"] is not None
        assert (latest["a1"].amount, latest["a1"].status) == (100.0, "ESTIMATE")
        assert latest["a2"] is not None
        assert latest["a2"].amount == 50.0
        assert latest["a2"].as_of == date(2026, 8, 31)
        assert latest["a2"].pending_as_of == date(2026, 9, 30)
        assert latest["a4"] is not None
        assert latest["a4"].available is False
        assert latest["a4"].amount is None
        investors = {investor.id: investor for investor in result.investors}
        owner_totals = investors[_OWNER_ID].latest_value_totals
        assert owner_totals is not None
        assert [(total.currency, total.amount, total.account_count) for total in owner_totals] == [
            ("USD", 150.0, 2),
            ("EUR", 7.0, 1),
        ]
        assert owner_totals[0].oldest_as_of == date(2026, 8, 31)
        assert owner_totals[0].newest_as_of == date(2026, 9, 30)
        assert investors["other"].latest_value_totals == ()
        assert result.latest_value_hint is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_failed_value_costs_that_row_only(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id=_OWNER_ID, currency="USD"),
                _account("a2", owner_id=_OWNER_ID, currency="USD"),
                included=[_owner(_OWNER_ID, name="Fabrikam Retirement")],
            )
        )
        respx.get(f"{BASE_URL}/accounts/a1/values").mock(
            return_value=_values({"date": "2026-09-30", "value": 10.0})
        )
        respx.get(f"{BASE_URL}/accounts/a2/values").mock(
            return_value=httpx.Response(500, json={"errors": [{"title": "Boom"}]})
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        failed = _accounts(result)[1].latest_value
        assert failed is not None
        assert failed.available is False
        assert failed.error is not None
        totals = result.investors[0].latest_value_totals
        assert totals is not None
        assert [(total.amount, total.account_count) for total in totals] == [(10.0, 1)]

    @pytest.mark.asyncio
    @respx.mock
    async def test_over_the_account_cap_fetches_no_values_and_says_why(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                *(_account(f"a{index}", owner_id=_OWNER_ID) for index in range(51)),
                included=[_owner(_OWNER_ID, name="Fabrikam Retirement")],
            )
        )
        values = respx.get(url__regex=rf"{BASE_URL}/accounts/a\d+/values")

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert values.call_count == 0
        assert result.latest_value_hint is not None
        assert "51 accounts" in result.latest_value_hint
        assert "get_accounts_for_party" in result.latest_value_hint
        assert "run_report" in result.latest_value_hint
        assert all(row.latest_value is None for row in _accounts(result))
        assert result.investors[0].latest_value_totals is None

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(("limit", "fetched"), [(3, 0), (4, 4)])
    async def test_the_account_limit_comes_from_config(
        self, client: BackstopClient, limit: int, fetched: int
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                *(_account(f"a{index}", owner_id=_OWNER_ID) for index in range(4)),
                included=[_owner(_OWNER_ID, name="Fabrikam Retirement")],
            )
        )
        values = respx.get(url__regex=rf"{BASE_URL}/accounts/a\d+/values").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=ProductInvestorsConfig(max_valued_accounts=limit),
            ),
            ProductInvestorsResolvedResponse,
        )

        assert values.call_count == fetched
        assert (result.latest_value_hint is not None) == (fetched == 0)

    @pytest.mark.asyncio
    @respx.mock
    async def test_investor_ids_list_and_value_only_those_owners(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id=_OWNER_ID, currency="USD"),
                _account("a2", owner_id=_OWNER_ID, closedDate="2020-01-01"),
                *(_account(f"b{index}", owner_id="other") for index in range(5)),
                _account("b-closed", owner_id="other", closedDate="2020-01-01"),
                included=[
                    _owner(_OWNER_ID, name="Fabrikam Retirement"),
                    _owner("other", name="Contoso Pension"),
                ],
            )
        )
        mine = respx.get(f"{BASE_URL}/accounts/a1/values").mock(
            return_value=_values({"date": "2026-09-30", "value": 10.0})
        )
        others = respx.get(url__regex=rf"{BASE_URL}/accounts/b\d+/values")

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                investor_ids=[_OWNER_ID, "999", _OWNER_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=ProductInvestorsConfig(max_valued_accounts=1),
            ),
            ProductInvestorsResolvedResponse,
        )

        assert mine.call_count == 1
        assert others.call_count == 0
        assert [row.id for row in _accounts(result)] == ["a1"]
        assert result.products[0].closed_omitted == 1
        assert [investor.id for investor in result.investors] == [_OWNER_ID]
        totals = result.investors[0].latest_value_totals
        assert totals is not None
        assert [total.amount for total in totals] == [10.0]
        assert result.investor_ids_not_found == ("999",)
        assert result.latest_value_hint is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_investor_ids_accept_the_contacts_envelope_id(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id="contact-7", currency="USD"),
                _account("b1", owner_id="other"),
                included=[
                    resource(
                        "contact-7",
                        "contacts",
                        name="Fabrikam Retirement",
                        specificResource={"resourceType": "organizations", "resourceId": "org-7"},
                    ),
                    _owner("other", name="Contoso Pension"),
                ],
            )
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                investor_ids=["contact-7", "org-7", "999"],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=ProductInvestorsConfig(max_valued_accounts=1),
            ),
            ProductInvestorsResolvedResponse,
        )

        assert [row.id for row in _accounts(result)] == ["a1"]
        assert [investor.id for investor in result.investors] == ["org-7"]
        assert result.investor_ids_not_found == ("999",)

    @pytest.mark.asyncio
    @respx.mock
    async def test_without_investor_ids_not_found_is_omitted(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id=_OWNER_ID),
                included=[_owner(_OWNER_ID, name="Fabrikam Retirement")],
            )
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert result.investor_ids_not_found is None
        assert "investor_ids_not_found" not in tool_payload(result)

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(("offshore_accounts", "offers_per_vehicle"), [(3, True), (4, False)])
    async def test_over_the_limit_hint_offers_investor_ids_and_per_vehicle_when_each_fits(
        self, client: BackstopClient, offshore_accounts: int, offers_per_vehicle: bool
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_nwon(), _nwof()))

        def accounts(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("filter[product.id][eq]") == "11":
                count, prefix = 3, "on"
            else:
                count, prefix = offshore_accounts, "off"
            return _accounts_page(
                *(_account(f"{prefix}-{index}", owner_id=_OWNER_ID) for index in range(count)),
                included=[_owner(_OWNER_ID, name="Contoso Pension")],
            )

        respx.get(_ACCOUNTS_URL).mock(side_effect=accounts)
        values = respx.get(url__regex=rf"{BASE_URL}/accounts/.+/values")

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=["NWON", "NWOF"],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=ProductInvestorsConfig(max_valued_accounts=3),
            ),
            ProductInvestorsResolvedResponse,
        )

        assert values.call_count == 0
        hint = result.latest_value_hint
        assert hint is not None
        assert f"{3 + offshore_accounts} accounts" in hint
        assert "`investor_ids`" in hint
        assert ("call once per vehicle" in hint) == offers_per_vehicle
        assert "get_accounts_for_party" in hint

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_auth_failure_on_one_value_aborts_the_call(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id=_OWNER_ID, currency="USD"),
                _account("a2", owner_id=_OWNER_ID, currency="USD"),
                included=[_owner(_OWNER_ID, name="Fabrikam Retirement")],
            )
        )
        respx.get(f"{BASE_URL}/accounts/a1/values").mock(
            return_value=_values({"date": "2026-09-30", "value": 10.0})
        )
        respx.get(f"{BASE_URL}/accounts/a2/values").mock(
            return_value=httpx.Response(401, json={"errors": []})
        )

        with pytest.raises(BackstopAuthError):
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_dated_point_with_no_number_yet_is_pending_not_zero(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id=_OWNER_ID, currency="USD"),
                included=[_owner(_OWNER_ID, name="Fabrikam Retirement")],
            )
        )
        respx.get(f"{BASE_URL}/accounts/a1/values").mock(
            return_value=_values({"date": "2026-09-30"})
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        latest = _accounts(result)[0].latest_value
        assert latest is not None
        assert latest.available is False
        assert latest.amount is None
        assert latest.pending_as_of == date(2026, 9, 30)
        assert result.investors[0].latest_value_totals == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_ambiguous_entry_elicits_and_lists_the_chosen_product(
        self, client: BackstopClient
    ) -> None:
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
        accounts = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = tool_model(
            await get_product_investors(
                ctx_accept("Blue Two (BLUC)"),
                products=["BLUC"],
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert [listing.product.id for listing in result.products] == ["2"]
        assert recorded_params(accounts)[0]["filter[product.id][eq]"] == "2"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_total_over_different_as_of_dates_reports_both_ends(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_ngup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("a1", owner_id=_OWNER_ID, currency="USD"),
                _account("a2", owner_id=_OWNER_ID, currency="USD"),
                included=[_owner(_OWNER_ID, name="Fabrikam Retirement")],
            )
        )
        respx.get(f"{BASE_URL}/accounts/a1/values").mock(
            return_value=_values({"date": "2026-09-30", "value": 5.0})
        )
        respx.get(f"{BASE_URL}/accounts/a2/values").mock(
            return_value=_values({"date": "2026-06-30", "value": 7.0})
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                products=[_PRODUCT_ID],
                include_latest_value=True,
                client=client,
                get_accounts_for_product_query=make_get_accounts_for_product_query(client),
                get_latest_account_values_query=make_get_latest_account_values_query(client),
                config=_CONFIG,
            ),
            ProductInvestorsResolvedResponse,
        )

        totals = result.investors[0].latest_value_totals
        assert totals is not None
        assert len(totals) == 1
        assert totals[0].amount == 12.0
        assert totals[0].oldest_as_of == date(2026, 6, 30)
        assert totals[0].newest_as_of == date(2026, 9, 30)
