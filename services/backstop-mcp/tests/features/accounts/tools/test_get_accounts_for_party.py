import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import ToolMeta

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts import PartyAccountsResolvedResponse
from backstop_mcp.features.accounts.tools.get_accounts_for_party import get_accounts_for_party
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_never_elicit
from tests.helpers import BASE_URL, resource
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_ORG_ID = "341688185"
_OTHER_ID = "999"
_PRODUCT_ID = "1292283"
_ACCOUNTS_URL = f"{BASE_URL}/accounts"


def _account(
    account_id: str,
    *,
    owner_id: str,
    product_id: str | None = _PRODUCT_ID,
    **attributes: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {
        "owner": {"data": {"type": "contacts", "id": owner_id}},
    }
    if product_id is not None:
        relationships["product"] = {"data": {"type": "products", "id": product_id}}
    return {
        "id": account_id,
        "type": "accounts",
        "attributes": attributes,
        "relationships": relationships,
    }


def _page(
    *accounts: dict[str, object],
    included: list[dict[str, object]] | None = None,
) -> httpx.Response:
    return httpx.Response(200, json={"data": list(accounts), "included": included or []})


def _owner(owner_id: str, *, name: str) -> dict[str, object]:
    return resource(
        owner_id,
        "contacts",
        name=name,
        specificResource={"resourceType": "organizations", "resourceId": owner_id},
    )


def _product() -> dict[str, object]:
    return resource(
        _PRODUCT_ID,
        "products",
        name="Capstone Global Unconstrained Portfolio",
        configuration={"productShortName": "CGUP"},
    )


class TestGetAccountsForParty:
    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_rows_by_owner_id_not_account_name(self, client: BackstopClient) -> None:
        route = respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("1", owner_id=_ORG_ID, name="Vehicle A"),
                _account("2", owner_id=_OTHER_ID, name="PSP Investments"),
                included=[
                    _owner(_ORG_ID, name="PSP Investments"),
                    _owner(_OTHER_ID, name="Someone Else"),
                    _product(),
                ],
            )
        )

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(), search_type="organizations", party_id=_ORG_ID,
                client=client,
            ),
            PartyAccountsResolvedResponse,
        )

        params = route.calls.last.request.url.params
        assert "filter[owner]" not in params
        assert "filter[owner.id]" not in params
        assert [row.id for row in result.accounts] == ["1"]
        assert result.accounts[0].name == "Vehicle A"
        assert result.accounts[0].product is not None
        assert result.accounts[0].product.short_name == "CGUP"
        row = object_dict(object_list(tool_payload(result)["accounts"])[0])
        assert "balance" not in row
        assert "invested" not in row

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_closed_mentions_include_closed(self, client: BackstopClient) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("1", owner_id=_ORG_ID, name="Gone", closedDate="2020-01-15"),
                included=[_owner(_ORG_ID, name="PSP Investments"), _product()],
            )
        )

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(), search_type="organizations", party_id=_ORG_ID,
                client=client,
            ),
            PartyAccountsResolvedResponse,
        )

        assert result.accounts == ()
        assert result.closed_omitted == 1
        assert result.include_closed_hint is not None
        assert "include_closed" in result.include_closed_hint

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_party_is_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(), search_type="organizations", search="No Such Org",
                client=client,
            ),
            NotFoundResponse,
        )

        assert result.scope == "organizations"

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_owned_closed_rows(self, client: BackstopClient) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(
                _account("1", owner_id=_ORG_ID, name="Live"),
                _account("2", owner_id=_ORG_ID, name="Gone", closedDate="2020-01-15"),
                included=[_owner(_ORG_ID, name="PSP Investments"), _product()],
            )
        )

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(),
                search_type="organizations",
                party_id=_ORG_ID,
                include_closed=True,
                client=client,
            ),
            PartyAccountsResolvedResponse,
        )

        assert [row.id for row in result.accounts] == ["1", "2"]
        assert result.closed_omitted == 0
        assert result.accounts[1].is_open is False

    def test_is_registered_and_names_product(self) -> None:
        assert get_accounts_for_party in TOOLS
        meta = get_fastmcp_meta(get_accounts_for_party)
        assert isinstance(meta, ToolMeta)
        doc = get_accounts_for_party.__doc__ or ""
        assert "product" in doc
        assert "fund" in doc
        assert "get_product_positions" in doc

    def test_output_schema_describes_account_status_fields(self) -> None:
        meta = get_fastmcp_meta(get_accounts_for_party)
        assert isinstance(meta, ToolMeta)
        schema = meta.output_schema
        assert schema is not None
        dumped = str(schema)
        assert "general-partner" in dumped
        assert "anti-money-laundering" in dumped
        assert "Investor accreditation" in dumped
        assert "domiciled in the United States" in dumped
