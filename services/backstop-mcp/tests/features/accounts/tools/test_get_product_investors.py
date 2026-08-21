from collections.abc import Sequence

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import ToolMeta

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.accounts import (
    ProductAmbiguousResponse,
    ProductInvestorsResolvedResponse,
)
from backstop_mcp.features.accounts.tools.get_product_investors import get_product_investors
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_decline, ctx_never_elicit
from tests.helpers import BASE_URL, recorded_params, resource
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

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


def _cgup() -> dict[str, object]:
    return {
        "id": _PRODUCT_ID,
        "type": "products",
        "attributes": {
            "name": "Capstone Global Unconstrained Portfolio",
            "configuration": {"productShortName": "CGUP"},
        },
    }


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
        by_id = respx.get(_PRODUCT_URL).mock(return_value=_product_document(_cgup()))
        accounts = respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account(
                    _ACCOUNT_ID,
                    owner_id=_OWNER_ID,
                    investor_type_id="10",
                    name="PSP CGUP",
                ),
                included=[
                    _owner(_OWNER_ID, name="PSP Investments"),
                    resource("10", "investor-types", name="Fund of Funds"),
                ],
            )
        )
        values = respx.get(f"{BASE_URL}/accounts/{_ACCOUNT_ID}/values").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = tool_model(
            await get_product_investors(ctx_never_elicit(), product_id=_PRODUCT_ID, client=client),
            ProductInvestorsResolvedResponse,
        )

        assert by_id.call_count == 1
        assert accounts.call_count == 1
        assert values.call_count == 0
        params = recorded_params(accounts)[0]
        assert params["filter[product.id][eq]"] == _PRODUCT_ID
        assert params["include"] == "owner,investorType"
        assert set(params["fields"].split(",")) == _EXPECTED_FIELDS
        assert result.product.id == _PRODUCT_ID
        assert result.product.short_name == "CGUP"
        assert [row.id for row in result.accounts] == [_ACCOUNT_ID]
        assert result.accounts[0].owner is not None
        assert result.accounts[0].owner.id == _OWNER_ID
        assert result.accounts[0].owner.resource_type == "organizations"
        assert result.accounts[0].investor_type is not None
        assert result.accounts[0].investor_type.name == "Fund of Funds"
        payload = object_dict(object_list(tool_payload(result)["accounts"])[0])
        assert "balance" not in payload
        assert "value" not in payload

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        "kwargs",
        [{"product": "CGUP"}, {"search": "CGUP"}],
    )
    async def test_short_name_resolves_through_the_catalog(
        self, client: BackstopClient, kwargs: dict[str, str]
    ) -> None:
        by_id = respx.get(f"{_PRODUCTS_URL}/CGUP").mock(
            return_value=httpx.Response(400, json={"errors": [{"title": "Bad Request"}]})
        )
        catalog = respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        accounts = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                client=client,
                product=kwargs.get("product"),
                search=kwargs.get("search"),
            ),
            ProductInvestorsResolvedResponse,
        )

        assert by_id.call_count == 0
        assert catalog.call_count == 1
        assert accounts.call_count == 1
        assert result.product.id == _PRODUCT_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_short_name_in_product_id_goes_to_the_catalog(
        self, client: BackstopClient
    ) -> None:
        by_id = respx.get(f"{_PRODUCTS_URL}/CGUP").mock(
            return_value=httpx.Response(400, json={"errors": [{"title": "Bad Request"}]})
        )
        catalog = respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = tool_model(
            await get_product_investors(ctx_never_elicit(), product_id="CGUP", client=client),
            ProductInvestorsResolvedResponse,
        )

        assert by_id.call_count == 0
        assert catalog.call_count == 1
        assert result.product.id == _PRODUCT_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_defaults_to_open_and_hints_when_all_are_closed(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(_account("closed", name="Gone", closedDate="2020-01-15"))
        )

        result = tool_model(
            await get_product_investors(ctx_never_elicit(), product_id=_PRODUCT_ID, client=client),
            ProductInvestorsResolvedResponse,
        )

        assert result.accounts == ()
        assert result.closed_omitted == 1
        assert result.include_closed_hint is not None
        assert "all of them are closed" in result.include_closed_hint

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_closed_rows(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("open", name="Live"),
                _account("closed", name="Gone", closedDate="2020-01-15"),
            )
        )

        result = tool_model(
            await get_product_investors(
                ctx_never_elicit(),
                product_id=_PRODUCT_ID,
                include_closed=True,
                client=client,
            ),
            ProductInvestorsResolvedResponse,
        )

        assert [row.id for row in result.accounts] == ["open", "closed"]
        assert result.closed_omitted == 0
        assert result.include_closed_hint is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_product_is_not_found(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page())

        result = tool_model(
            await get_product_investors(ctx_never_elicit(), product_id=_PRODUCT_ID, client=client),
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
            await get_product_investors(ctx_decline(), product="BLUC", client=client),
            ProductAmbiguousResponse,
        )

        assert [candidate.id for candidate in result.candidates] == ["1", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_accounts_listing_500_propagates(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=httpx.Response(
                500, json={"errors": [{"title": "InternalServerException"}]}
            )
        )

        with pytest.raises(BackstopApiError) as caught:
            await get_product_investors(ctx_never_elicit(), product_id=_PRODUCT_ID, client=client)

        assert caught.value.status_code == 500

    @pytest.mark.asyncio
    @respx.mock
    async def test_both_or_neither_identifier_fails_before_any_request(
        self, client: BackstopClient
    ) -> None:
        products = respx.get(_PRODUCTS_URL)
        accounts = respx.get(_ACCOUNTS_URL)
        with pytest.raises(ValueError, match="Exactly one of product_id or product"):
            await get_product_investors(ctx_never_elicit(), client=client)
        with pytest.raises(ValueError, match="Exactly one of product_id or product"):
            await get_product_investors(
                ctx_never_elicit(),
                product_id=_PRODUCT_ID,
                product="CGUP",
                client=client,
            )
        with pytest.raises(ValueError, match="Pass at most one of product or search"):
            await get_product_investors(
                ctx_never_elicit(),
                product="CGUP",
                search="Keystone",
                client=client,
            )
        assert products.call_count == 0
        assert accounts.call_count == 0

    def test_is_registered_and_names_the_two_step(self) -> None:
        assert get_product_investors in TOOLS
        meta = get_fastmcp_meta(get_product_investors)
        assert isinstance(meta, ToolMeta)
        doc = get_product_investors.__doc__ or ""
        assert "get_time_series" in doc
        assert "aums" in doc
        assert "account-by-account" in doc
        assert "one call per (account, series)" in doc
        assert "not one investor's balance" in doc
        assert "search" in doc
        assert "fan-out" in doc
