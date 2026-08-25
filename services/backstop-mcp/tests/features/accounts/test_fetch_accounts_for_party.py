from collections.abc import Sequence

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts import fetch_accounts_for_party
from tests.helpers import BASE_URL, recorded_params, resource

_ACCOUNTS_URL = f"{BASE_URL}/accounts"
_OWNER_ID = "341688185"
_OTHER_OWNER_ID = "999"
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
    total_count: int | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {
        "data": list(accounts),
        "included": list(included),
    }
    if next_url is not None:
        payload["links"] = {"next": next_url}
    if total_count is not None:
        payload["meta"] = {"totalResourceCount": total_count}
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


class TestFetchAccountsForParty:
    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_accounts_with_product_include_and_no_owner_filter(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account(
                    "1",
                    owner_id=_OWNER_ID,
                    product_id=_PRODUCT_ID,
                    name="PSP CGUP",
                ),
                included=[
                    _owner(_OWNER_ID, name="PSP Investments"),
                    resource(
                        _PRODUCT_ID,
                        "products",
                        name="Capstone Global Unconstrained Portfolio",
                        configuration={"productShortName": "CGUP"},
                    ),
                ],
            )
        )

        listing = await fetch_accounts_for_party(client, owner_id=_OWNER_ID)

        params = route.calls.last.request.url.params
        assert "filter[owner.id][eq]" not in params
        assert "filter[owner][eq]" not in params
        assert params["include"] == "owner,investorType,product"
        assert set(params["fields"].split(",")) == _EXPECTED_FIELDS
        assert listing.accounts[0].product is not None
        assert listing.accounts[0].product.short_name == "CGUP"

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_rows_whose_owner_id_matches_even_when_account_name_differs(
        self, client: BackstopClient
    ) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account(
                    "1",
                    owner_id=_OWNER_ID,
                    name="Vehicle A",
                ),
                _account(
                    "2",
                    owner_id=_OTHER_OWNER_ID,
                    name="PSP Investments",
                ),
                included=[
                    _owner(_OWNER_ID, name="PSP Investments"),
                    _owner(_OTHER_OWNER_ID, name="Someone Else"),
                ],
            )
        )

        listing = await fetch_accounts_for_party(client, owner_id=_OWNER_ID)

        assert [account.id for account in listing.accounts] == ["1"]
        assert listing.accounts[0].name == "Vehicle A"

    @pytest.mark.asyncio
    @respx.mock
    async def test_closed_owned_rows_are_omitted_by_default(self, client: BackstopClient) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("open", owner_id=_OWNER_ID, name="Live"),
                _account(
                    "closed",
                    owner_id=_OWNER_ID,
                    name="Gone",
                    closedDate="2020-01-15",
                ),
                _account("other-closed", owner_id=_OTHER_OWNER_ID, closedDate="2019-01-01"),
                included=[
                    _owner(_OWNER_ID, name="PSP Investments"),
                    _owner(_OTHER_OWNER_ID, name="Someone Else"),
                ],
            )
        )

        listing = await fetch_accounts_for_party(client, owner_id=_OWNER_ID)

        assert [account.id for account in listing.accounts] == ["open"]
        assert listing.closed_omitted == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_matches_the_projected_owner_id_when_it_differs_from_the_linkage(
        self, client: BackstopClient
    ) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("1", owner_id="contact-1", name="Vehicle A"),
                _account("2", owner_id=_OTHER_OWNER_ID, name="Not Theirs"),
                included=[
                    _owner("contact-1", name="PSP Investments", specific_id=_OWNER_ID),
                    _owner(_OTHER_OWNER_ID, name="Someone Else"),
                ],
            )
        )

        listing = await fetch_accounts_for_party(client, owner_id=_OWNER_ID)

        assert [account.id for account in listing.accounts] == ["1"]
        assert listing.accounts[0].owner is not None
        assert listing.accounts[0].owner.id == _OWNER_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_pages_by_offset_when_backstop_reports_a_total(
        self, client: BackstopClient
    ) -> None:
        """815 accounts is 9 pages; serially that is 97s, by offset 9s."""
        route = respx.get(_ACCOUNTS_URL).mock(
            side_effect=[
                _page(_account("1", owner_id=_OWNER_ID, name="First"), total_count=2),
                _page(_account("2", owner_id=_OWNER_ID, name="Second"), total_count=2),
            ]
        )

        listing = await fetch_accounts_for_party(client, owner_id=_OWNER_ID)

        assert [account.id for account in listing.accounts] == ["1", "2"]
        assert sorted(params["page[offset]"] for params in recorded_params(route)) == ["0", "1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_a_row_when_owner_linkage_matches_without_the_include(
        self, client: BackstopClient
    ) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(_account("1", owner_id=_OWNER_ID, name="Vehicle A"))
        )

        listing = await fetch_accounts_for_party(client, owner_id=_OWNER_ID)

        assert [account.id for account in listing.accounts] == ["1"]
        assert listing.accounts[0].owner is None
