from collections.abc import Callable

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import ToolMeta

from backstop_mcp.features.accounts import (
    ProductAmbiguousResponse,
    ProductPositionsResolvedResponse,
)
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from backstop_mcp.server.tools.get_product_positions import get_product_positions
from tests.features.party_resolver.helpers import ctx_decline, ctx_never_elicit
from tests.helpers import BASE_URL, resource
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

type ConnectUser = Callable[..., object]

_PRODUCT_ID = "1292283"
_ACCOUNT_ID = "27871657"
_PRODUCTS_URL = f"{BASE_URL}/products"
_PRODUCT_URL = f"{BASE_URL}/products/{_PRODUCT_ID}"
_ACCOUNTS_URL = f"{BASE_URL}/accounts"
_AUM_URL = f"{BASE_URL}/products/{_PRODUCT_ID}/aums"


def _product_page(*products: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(products)})


def _product_document(product: dict[str, object]) -> httpx.Response:
    """A trusted `product_id` resolves by id, so it reads a document rather than the catalog."""
    return httpx.Response(200, json={"data": product})


def _cgup() -> dict[str, object]:
    return {
        "id": _PRODUCT_ID,
        "type": "products",
        "attributes": {
            "name": "Capstone Global Unconstrained Portfolio",
            "configuration": {"productShortName": "CGUP"},
        },
    }


def _account(
    account_id: str,
    *,
    owner_id: str | None = "341688185",
    **attributes: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {}
    if owner_id is not None:
        relationships["owner"] = {"data": {"type": "contacts", "id": owner_id}}
    return {
        "id": account_id,
        "type": "accounts",
        "attributes": attributes,
        "relationships": relationships,
    }


def _accounts_page(
    *accounts: dict[str, object],
    included: list[dict[str, object]] | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(accounts), "included": included or []},
    )


def _point(point_id: str, **attributes: object) -> dict[str, object]:
    return {"id": point_id, "type": "values", "attributes": attributes}


def _series_page(*points: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(points)})


def _mock_series(
    account_id: str,
    *,
    values: httpx.Response | None = None,
    invested: httpx.Response | None = None,
    redemptions: httpx.Response | None = None,
) -> None:
    empty = _series_page()
    respx.get(f"{BASE_URL}/accounts/{account_id}/values").mock(return_value=values or empty)
    respx.get(f"{BASE_URL}/accounts/{account_id}/totalInvested").mock(
        return_value=invested or empty
    )
    respx.get(f"{BASE_URL}/accounts/{account_id}/totalRedemptions").mock(
        return_value=redemptions or empty
    )


class TestGetProductPositions:
    @pytest.mark.asyncio
    @respx.mock
    async def test_short_name_returns_open_positions(self, connect_user: ConnectUser) -> None:
        await connect_user("user-pos-1", "pos-bob")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account(_ACCOUNT_ID, name="PSP CGUP", currency="USD"),
                included=[
                    resource(
                        "341688185",
                        "contacts",
                        name="PSP Investments",
                        specificResource={
                            "resourceType": "organizations",
                            "resourceId": "341688185",
                        },
                    )
                ],
            )
        )
        _mock_series(
            _ACCOUNT_ID,
            values=_series_page(
                _point("2", date="2026-07-31", value=11.0, valueStatus="ESTIMATE"),
                _point("1", date="2026-06-30", value=10.0, valueStatus="ACTUAL"),
            ),
            invested=_series_page(_point("3", date="2026-07-31", value=100.0)),
        )
        respx.get(_AUM_URL).mock(
            return_value=_series_page(_point("aum", date="2026-07-31", value=11.0))
        )

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="CGUP"),
            ProductPositionsResolvedResponse,
        )

        assert result.product.id == _PRODUCT_ID
        assert result.product.short_name == "CGUP"
        assert result.closed_omitted == 0
        assert result.aum_diverges is False
        assert result.include_closed_hint is None
        row = result.accounts[0]
        assert row.id == _ACCOUNT_ID
        assert row.owner is not None
        assert row.owner.resource_type == "organizations"
        assert row.balance is not None
        assert row.balance.value == 11.0
        assert row.balance.value_status == "ESTIMATE"
        assert row.invested is not None
        assert row.invested.value_status is None
        first = object_dict(object_list(tool_payload(result)["accounts"])[0])
        assert "redemptions" not in first
        assert "value_status" not in object_dict(first["invested"])
        assert "newer_point_without_value" not in object_dict(first["balance"])

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_product_is_not_found(self, connect_user: ConnectUser) -> None:
        await connect_user("user-pos-2", "pos-carol")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="NOPE"),
            NotFoundResponse,
        )

        assert result.query == "NOPE"
        assert result.scope == "products"

    @pytest.mark.asyncio
    @respx.mock
    async def test_zero_accounts_is_distinct_from_not_found(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-pos-3", "pos-dave")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCT_URL).mock(return_value=_product_document(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        respx.get(_AUM_URL).mock(return_value=_series_page())

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product_id=_PRODUCT_ID),
            ProductPositionsResolvedResponse,
        )

        assert result.accounts == ()
        assert result.closed_omitted == 0
        assert result.include_closed_hint is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_closed_mentions_include_closed(self, connect_user: ConnectUser) -> None:
        await connect_user("user-pos-4", "pos-erin")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("closed", name="Gone", closedDate="2020-01-15"),
            )
        )
        respx.get(_AUM_URL).mock(return_value=_series_page())

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="CGUP"),
            ProductPositionsResolvedResponse,
        )

        assert result.accounts == ()
        assert result.closed_omitted == 1
        assert result.include_closed_hint is not None
        assert "include_closed" in result.include_closed_hint

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_series_500_stays_on_the_row(self, connect_user: ConnectUser) -> None:
        await connect_user("user-pos-5", "pos-frank")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(_account(_ACCOUNT_ID, name="PSP CGUP"))
        )
        _mock_series(
            _ACCOUNT_ID,
            values=httpx.Response(500, json={"errors": [{"detail": "values boom"}]}),
            invested=_series_page(_point("3", date="2026-07-31", value=100.0)),
        )
        respx.get(_AUM_URL).mock(return_value=_series_page())

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="CGUP"),
            ProductPositionsResolvedResponse,
        )

        row = result.accounts[0]
        assert row.balance is None
        assert row.invested is not None
        assert row.errors is not None
        assert row.errors[0].series == "values"

    @pytest.mark.asyncio
    @respx.mock
    async def test_aum_divergence_is_a_flag(self, connect_user: ConnectUser) -> None:
        await connect_user("user-pos-6", "pos-gina")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(_account(_ACCOUNT_ID, name="PSP CGUP"))
        )
        _mock_series(
            _ACCOUNT_ID,
            values=_series_page(_point("1", date="2026-07-31", value=10.0)),
        )
        respx.get(_AUM_URL).mock(
            return_value=_series_page(_point("aum", date="2026-07-31", value=99.0))
        )

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="CGUP"),
            ProductPositionsResolvedResponse,
        )

        assert result.aum_diverges is True
        assert result.aum is not None
        assert result.aum.value == 99.0
        assert result.balance_total == 10.0
        assert result.aum_difference == -89.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_gap_inside_the_tolerance_does_not_flag(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-pos-9", "pos-jack")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(_account(_ACCOUNT_ID, name="PSP CGUP"))
        )
        _mock_series(
            _ACCOUNT_ID,
            values=_series_page(_point("1", date="2026-07-31", value=1_000_000.0)),
        )
        respx.get(_AUM_URL).mock(
            return_value=_series_page(_point("aum", date="2026-07-31", value=1_002_000.0))
        )

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="CGUP"),
            ProductPositionsResolvedResponse,
        )

        assert result.aum_diverges is False
        assert result.aum_difference == -2000.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_newer_valueless_point_does_not_hide_the_last_number(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-pos-10", "pos-kate")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(_account(_ACCOUNT_ID, name="PSP CGUP"))
        )
        _mock_series(
            _ACCOUNT_ID,
            values=_series_page(
                _point("1", date="2026-06-30", value=1_000_000.0, valueStatus="ACTUAL"),
                _point("2", date="2026-07-31", valueStatus="ESTIMATE"),
            ),
        )
        respx.get(_AUM_URL).mock(return_value=_series_page())

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="CGUP"),
            ProductPositionsResolvedResponse,
        )

        balance = result.accounts[0].balance
        assert balance is not None
        assert balance.value == 1_000_000.0
        assert balance.date.isoformat() == "2026-06-30"
        assert balance.newer_point_without_value is not None
        assert balance.newer_point_without_value.date.isoformat() == "2026-07-31"
        assert result.balance_total == 1_000_000.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_a_zero_actual_closed_account(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-pos-7", "pos-hank")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(return_value=_product_page(_cgup()))
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_accounts_page(
                _account("closed", name="Gone", closedDate="2020-01-15"),
            )
        )
        _mock_series(
            "closed",
            values=_series_page(_point("1", date="2026-07-31", value=0.0, valueStatus="ACTUAL")),
        )
        respx.get(_AUM_URL).mock(return_value=_series_page())

        result = tool_model(
            await get_product_positions(ctx_never_elicit(), product="CGUP", include_closed=True),
            ProductPositionsResolvedResponse,
        )

        assert result.closed_omitted == 0
        assert result.accounts[0].is_open is False
        assert result.accounts[0].balance is not None
        assert result.accounts[0].balance.value == 0.0
        assert result.accounts[0].balance.value_status == "ACTUAL"

    @pytest.mark.asyncio
    @respx.mock
    async def test_duplicate_short_name_is_ambiguous(self, connect_user: ConnectUser) -> None:
        await connect_user("user-pos-8", "pos-ivy")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(_PRODUCTS_URL).mock(
            return_value=_product_page(
                {
                    "id": "100",
                    "type": "products",
                    "attributes": {
                        "name": "Blue Capital I",
                        "configuration": {"productShortName": "BLUC"},
                    },
                },
                {
                    "id": "101",
                    "type": "products",
                    "attributes": {
                        "name": "Blue Capital II",
                        "configuration": {"productShortName": "BLUC"},
                    },
                },
            )
        )

        result = tool_model(
            await get_product_positions(ctx_decline(), product="BLUC"),
            ProductAmbiguousResponse,
        )

        assert result.query == "BLUC"
        assert {candidate.id for candidate in result.candidates} == {"100", "101"}

    def test_is_registered_read_only(self) -> None:
        assert get_product_positions in TOOLS
        meta = get_fastmcp_meta(get_product_positions)
        assert isinstance(meta, ToolMeta)
        assert "fund" in (get_product_positions.__doc__ or "")
        assert "values" in (get_product_positions.__doc__ or "")
        assert "totalInvested" in (get_product_positions.__doc__ or "")

    def test_output_schema_describes_figures_and_status_fields(self) -> None:
        meta = get_fastmcp_meta(get_product_positions)
        assert isinstance(meta, ToolMeta)
        schema = meta.output_schema
        assert schema is not None
        dumped = str(schema)
        assert "assets under management" in dumped
        assert "general-partner" in dumped
        assert "anti-money-laundering" in dumped
        assert "accreditation" in dumped
        assert "product_id" in dumped
        assert "ESTIMATE" in dumped
        assert "newer_point_without_value" in dumped
        assert "aum_difference" in dumped
        assert "accounts_omitted" in dumped
