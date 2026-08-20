from collections.abc import Sequence

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopResponseSchemaError
from backstop_mcp.features.accounts import fetch_accounts_for_product
from tests.helpers import BASE_URL, resource

_ACCOUNTS_URL = f"{BASE_URL}/accounts"
_NEXT_PAGE = "/accounts?page[offset]=100"
_OWNER_ID = "341688185"
_PRODUCT_ID = "1292283"


def _account(
    account_id: str,
    *,
    owner_id: str | None = None,
    investor_type_id: str | None = None,
    product_id: str | None = None,
    **attributes: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {}
    if owner_id is not None:
        relationships["owner"] = {"data": {"type": "contacts", "id": owner_id}}
    if investor_type_id is not None:
        relationships["investorType"] = {"data": {"type": "investor-types", "id": investor_type_id}}
    if product_id is not None:
        relationships["product"] = {"data": {"type": "products", "id": product_id}}
    return {
        "id": account_id,
        "type": "accounts",
        "attributes": attributes,
        "relationships": relationships,
    }


def _owner(owner_id: str, *, name: str, specific_id: str | None = None) -> dict[str, object]:
    return resource(
        owner_id,
        "contacts",
        name=name,
        specificResource={
            "resourceType": "organizations",
            "resourceId": specific_id or owner_id,
        },
    )


def _page(
    *accounts: dict[str, object],
    included: Sequence[dict[str, object]] = (),
    next_url: str | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {
        "data": list(accounts),
        "included": list(included),
    }
    if next_url is not None:
        payload["links"] = {"next": next_url}
    return httpx.Response(200, json=payload)


# The attributes `AccountAttributes` reads. `fields=` is what keeps a full walk affordable, and
# what would silently blank a column if this set ever fell behind the model.
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


class TestFetchAccountsForProduct:
    @pytest.mark.asyncio
    @respx.mock
    async def test_filters_by_product_id_and_includes_owner_and_investor_type(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account(
                    "1",
                    owner_id=_OWNER_ID,
                    investor_type_id="10",
                    name="Open",
                ),
                included=[
                    _owner(_OWNER_ID, name="PSP Investments"),
                    resource("10", "investor-types", name="Fund of Funds"),
                ],
            )
        )

        listing = await fetch_accounts_for_product(client, product_id=_PRODUCT_ID)

        params = route.calls.last.request.url.params
        assert params["filter[product.id][eq]"] == _PRODUCT_ID
        assert params["include"] == "owner,investorType"
        assert params["page[limit]"] == "100"
        assert set(params["fields"].split(",")) == _EXPECTED_FIELDS
        assert "product" not in params["include"]
        assert len(listing.accounts) == 1
        assert listing.accounts[0].owner is not None
        assert listing.accounts[0].owner.id == _OWNER_ID
        assert listing.accounts[0].investor_type is not None
        assert listing.accounts[0].investor_type.name == "Fund of Funds"
        assert listing.accounts[0].product is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_links_next(self, client: BackstopClient) -> None:
        route = respx.get(_ACCOUNTS_URL).mock(
            side_effect=[
                _page(_account("1", name="First"), next_url=_NEXT_PAGE),
                _page(_account("2", name="Second")),
            ]
        )

        listing = await fetch_accounts_for_product(client, product_id=_PRODUCT_ID)

        assert route.call_count == 2
        assert [account.id for account in listing.accounts] == ["1", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_defaults_to_open_and_counts_omitted_closed(self, client: BackstopClient) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("open", name="Live"),
                _account("closed", name="Gone", closedDate="2020-01-15"),
            )
        )

        listing = await fetch_accounts_for_product(client, product_id=_PRODUCT_ID)

        assert [account.id for account in listing.accounts] == ["open"]
        assert listing.closed_omitted == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_closed_rows(self, client: BackstopClient) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("open", name="Live"),
                _account("closed", name="Gone", closedDate="2020-01-15"),
            )
        )

        listing = await fetch_accounts_for_product(
            client, product_id=_PRODUCT_ID, include_closed=True
        )

        assert [account.id for account in listing.accounts] == ["open", "closed"]
        assert listing.closed_omitted == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_malformed_account_fails_the_page(self, client: BackstopClient) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("ok", name="Keep"),
                {"type": "accounts", "attributes": {"name": "Drop"}},
            )
        )

        with pytest.raises(BackstopResponseSchemaError):
            await fetch_accounts_for_product(client, product_id=_PRODUCT_ID)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_non_bool_flag_is_absence_not_a_failed_page(
        self, client: BackstopClient
    ) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(_account("ok", name="Keep", isEmployeeAccount="not-a-bool"))
        )

        listing = await fetch_accounts_for_product(client, product_id=_PRODUCT_ID)

        assert [account.id for account in listing.accounts] == ["ok"]
        assert listing.accounts[0].is_employee_account is None
