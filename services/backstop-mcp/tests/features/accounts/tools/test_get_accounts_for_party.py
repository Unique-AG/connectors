"""`get_accounts_for_party` after it was repointed at the holdings path.

Two things carry most of the weight here. The tool must publish figures with a provenance caveat
that says which endpoint answered, and it must not report "this party owns nothing" for an id
Backstop has never heard of — the holdings endpoint answers `200` with an empty table for a bad
id, so the tool verifies before reporting emptiness.
"""

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
_PRODUCT_ID = "1292283"
_ACCOUNT_ID = "27871657"
_TABLE_URL = f"{BASE_URL}/bsg-account-table-data"
_ACCOUNTS_URL = f"{BASE_URL}/accounts"
_ORG_URL = f"{BASE_URL}/organizations/{_ORG_ID}"


def _ref(resource_id: str, resource_type: str, **extra: object) -> dict[str, object]:
    return {"resourceType": resource_type, "resourceId": resource_id, **extra}


def _table_row(
    account_id: str = _ACCOUNT_ID, *, closed: bool = False, **overrides: object
) -> dict[str, object]:
    row: dict[str, object] = {
        "investor": _ref(_ORG_ID, "organizations"),
        "account": _ref(account_id, "hedge-fund-accounts"),
        "product": _ref(_PRODUCT_ID, "hedge-fund-products", shortName="CGUP"),
        "otherId": "90007828_CGUP",
        "fundedDate": "2017-01-01T00:00:00.000-0500",
        "closed": closed,
        "balance": {
            "amount": 1000.0,
            "currency": "USD",
            "currencySymbol": "$",
            "formattedValue": "$1,000.00",
        },
        "commitment": {"amount": 0.0, "currency": "USD", "formattedValue": "-"},
        "percentageOfProduct": {"value": 0.25, "formattedValue": "25.00%"},
    }
    return row | overrides


def _table(*rows: dict[str, object]) -> httpx.Response:
    closed = sum(1 for row in rows if row.get("closed"))
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": None,
                    "type": "bsg-account-table-data",
                    "attributes": {
                        "accounts": list(rows),
                        "openCount": len(rows) - closed,
                        "allCount": len(rows),
                        "closedCount": closed,
                    },
                }
            ]
        },
    )


def _accounts_page(*, closed: bool = False) -> httpx.Response:
    attributes: dict[str, object] = {"name": "Vehicle A", "currency": "USD"}
    if closed:
        attributes["closedDate"] = "2020-01-15"
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": _ACCOUNT_ID,
                    "type": "accounts",
                    "attributes": attributes,
                    "relationships": {
                        "owner": {"data": {"type": "contacts", "id": _ORG_ID}},
                        "product": {"data": {"type": "products", "id": _PRODUCT_ID}},
                    },
                }
            ],
            "included": [
                resource(
                    _ORG_ID,
                    "contacts",
                    name="PSP Investments",
                    specificResource={
                        "resourceType": "organizations",
                        "resourceId": _ORG_ID,
                    },
                ),
                resource(
                    _PRODUCT_ID,
                    "products",
                    name="Capstone Global Unconstrained Portfolio",
                    configuration={"productShortName": "CGUP"},
                ),
            ],
        },
    )


def _series(value: float | None) -> httpx.Response:
    if value is None:
        return httpx.Response(200, json={"data": []})
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "p1",
                    "type": "time-series",
                    "attributes": {"date": "2026-07-31", "value": value, "valueStatus": "ACTUAL"},
                }
            ]
        },
    )


def _mock_fallback() -> None:
    respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
    respx.get(f"{BASE_URL}/accounts/{_ACCOUNT_ID}/values").mock(return_value=_series(500.0))
    respx.get(f"{BASE_URL}/accounts/{_ACCOUNT_ID}/percentageOfFundHistory").mock(
        return_value=_series(0.25)
    )


def _mock_quick_search_hit() -> None:
    """Resolving by name yields a party whose name is already known, so no verification is due."""
    respx.get(f"{BASE_URL}/quick-search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": _ORG_ID,
                        "type": "quick-search",
                        "attributes": {"name": "PSP Investments", "resourceId": _ORG_ID},
                    }
                ]
            },
        )
    )


async def _call(client: BackstopClient, *, include_closed: bool = False) -> object:
    """The trusted-`party_id` path.

    No name, so an empty result is verified before being reported as "owns nothing".
    """
    return await get_accounts_for_party(
        ctx_never_elicit(),
        search_type="organizations",
        party_id=_ORG_ID,
        include_closed=include_closed,
        client=client,
    )


class TestFigures:
    @pytest.mark.asyncio
    @respx.mock
    async def test_publishes_balances_in_one_request(self, client: BackstopClient) -> None:
        """The whole point of the repoint: figures, without walking 815 accounts."""
        table = respx.get(_TABLE_URL).mock(return_value=_table(_table_row()))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = tool_model(await _call(client), PartyAccountsResolvedResponse)

        assert table.call_count == 1
        assert not walk.called
        row = result.holdings[0]
        assert row.account_id == _ACCOUNT_ID
        assert row.product_short_name == "CGUP"
        assert row.balance is not None
        assert row.balance.amount == 1000.0
        assert row.percentage_of_product is not None
        assert row.percentage_of_product.fraction == 0.25
        assert result.source == "table-api"

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_caveat_names_what_the_fast_path_cannot_say(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_table_row()))

        result = tool_model(await _call(client), PartyAccountsResolvedResponse)

        assert "no as-of date" in result.data_caveat
        assert result.holdings[0].balance_as_of is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_fallback_caveat_names_the_fields_it_cannot_produce(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        _mock_fallback()

        result = tool_model(await _call(client), PartyAccountsResolvedResponse)

        assert result.source == "accounts-api"
        for field in ("commitment", "unfunded_commitment", "percentage_of_master"):
            assert field in result.data_caveat
        row = result.holdings[0]
        assert row.commitment is None
        assert row.balance is not None
        assert row.balance.amount == 500.0
        # The fallback dates its figure; the fast path cannot.
        assert row.balance_as_of is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_zero_figure_keeps_its_rendering_so_it_is_not_read_as_missing(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_table_row()))

        result = tool_model(await _call(client), PartyAccountsResolvedResponse)

        commitment = result.holdings[0].commitment
        assert commitment is not None
        assert commitment.amount == 0.0
        assert commitment.formatted == "-"


class TestOwnsNothingIsVerified:
    """The endpoint answers 200/empty for a bad id, so emptiness must be checked, not relayed."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_unconfirmed_id_with_no_holdings_is_verified_before_reporting_nothing(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table())
        confirm = respx.get(_ORG_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {"id": _ORG_ID, "type": "organizations", "attributes": {"name": "PSP"}}
                },
            )
        )

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(),
                search_type="organizations",
                party_id=_ORG_ID,
                client=client,
            ),
            PartyAccountsResolvedResponse,
        )

        assert confirm.called
        assert result.holdings == ()
        assert result.resolved.name == "PSP"

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_id_backstop_does_not_know_is_not_found_not_owns_nothing(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table())
        respx.get(_ORG_URL).mock(return_value=httpx.Response(404, json={"errors": []}))

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(),
                search_type="organizations",
                party_id=_ORG_ID,
                client=client,
            ),
            NotFoundResponse,
        )

        assert result.scope == "organizations"
        assert _ORG_ID in result.query

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_party_resolved_by_name_is_not_re_verified(
        self, client: BackstopClient
    ) -> None:
        """Quick-search already proved the party exists, so the extra request is not spent."""
        respx.get(_TABLE_URL).mock(return_value=_table())
        _mock_quick_search_hit()
        confirm = respx.get(_ORG_URL).mock(return_value=httpx.Response(200, json={"data": {}}))

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(),
                search_type="organizations",
                search="PSP Investments",
                client=client,
            ),
            PartyAccountsResolvedResponse,
        )

        assert not confirm.called
        assert result.holdings == ()
        assert result.resolved.name == "PSP Investments"

    @pytest.mark.asyncio
    @respx.mock
    async def test_holdings_present_never_costs_a_verification_request(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_table_row()))
        confirm = respx.get(_ORG_URL).mock(return_value=httpx.Response(200, json={"data": {}}))

        await get_accounts_for_party(
            ctx_never_elicit(),
            search_type="organizations",
            party_id=_ORG_ID,
            client=client,
        )

        assert not confirm.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_closed_is_not_owns_nothing_and_is_not_verified(
        self, client: BackstopClient
    ) -> None:
        """`closed_omitted>0` already explains the empty list, so there is nothing to check."""
        respx.get(_TABLE_URL).mock(return_value=_table(_table_row(closed=True)))
        confirm = respx.get(_ORG_URL).mock(return_value=httpx.Response(200, json={"data": {}}))

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(),
                search_type="organizations",
                party_id=_ORG_ID,
                client=client,
            ),
            PartyAccountsResolvedResponse,
        )

        assert not confirm.called
        assert result.holdings == ()
        assert result.closed_omitted == 1
        assert result.include_closed_hint is not None


class TestClosedFiltering:
    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_closed_rows(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(_table_row("1"), _table_row("2", closed=True))
        )

        result = tool_model(await _call(client, include_closed=True), PartyAccountsResolvedResponse)

        assert [row.account_id for row in result.holdings] == ["1", "2"]
        assert result.holdings[1].closed is True
        assert result.closed_omitted == 0


class TestResolution:
    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_search_is_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        respx.get(f"{BASE_URL}/organizations").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = tool_model(
            await get_accounts_for_party(
                ctx_never_elicit(),
                search_type="organizations",
                search="No Such Org",
                client=client,
            ),
            NotFoundResponse,
        )

        assert result.scope == "organizations"


class TestContract:
    def test_is_registered_and_routes_dated_figures_elsewhere(self) -> None:
        assert get_accounts_for_party in TOOLS
        meta = get_fastmcp_meta(get_accounts_for_party)
        assert isinstance(meta, ToolMeta)
        doc = get_accounts_for_party.__doc__ or ""
        assert "product" in doc
        assert "fund" in doc
        # The old contract pointed at get_product_positions for balances; it now has them.
        assert "get_product_positions" not in doc
        assert "get_time_series" in doc
        assert "data_caveat" in doc

    def test_output_schema_explains_provenance_and_the_zero_trap(self) -> None:
        meta = get_fastmcp_meta(get_accounts_for_party)
        assert isinstance(meta, ToolMeta)
        schema = meta.output_schema
        assert schema is not None
        dumped = str(schema)
        assert "0.796 is 79.6%" in dumped
        assert "no figure is recorded" in dumped
        assert "Omitted, never zeroed" in dumped

    @pytest.mark.asyncio
    @respx.mock
    async def test_absent_figures_are_omitted_from_the_payload_not_nulled(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_table_row() | {"percentageOfMaster": None}))

        result = tool_model(await _call(client), PartyAccountsResolvedResponse)
        row = object_dict(object_list(tool_payload(result)["holdings"])[0])

        assert "percentage_of_master" not in row
        assert "balance" in row
