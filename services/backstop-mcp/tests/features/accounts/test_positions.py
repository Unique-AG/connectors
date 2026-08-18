from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.accounts.positions import (
    MAX_POSITION_ACCOUNTS,
    fetch_positions,
    fetch_product_aum,
    fetch_product_positions,
    reconcile,
)
from backstop_mcp.features.accounts.types import (
    AccountListing,
    AccountPosition,
    AccountRecord,
    ResolvedProduct,
    SeriesFigure,
    SeriesPoint,
)
from tests.helpers import BASE_URL, FIXED_TODAY

_ACCOUNT_A = "27871657"
_ACCOUNT_B = "28124025"


def _record(account_id: str, *, name: str = "Row") -> AccountRecord:
    return AccountRecord(id=account_id, name=name, is_open=True)


def _point(point_id: str, **attributes: object) -> dict[str, object]:
    return {"id": point_id, "type": "values", "attributes": attributes}


def _page(*points: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(points)})


def _series_url(account_id: str, series: str) -> str:
    return f"{BASE_URL}/accounts/{account_id}/{series}"


class TestFetchPositions:
    @pytest.mark.asyncio
    @respx.mock
    async def test_attaches_the_three_series_per_account(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                _point("1", date="2026-06-30", value=10.0, valueStatus="ACTUAL"),
                _point("2", date="2026-07-31", value=11.0, valueStatus="ESTIMATE"),
            )
        )
        respx.get(_series_url(_ACCOUNT_A, "totalInvested")).mock(
            return_value=_page(_point("3", date="2026-07-31", value=100.0))
        )
        respx.get(_series_url(_ACCOUNT_A, "totalRedemptions")).mock(
            return_value=_page(_point("4", date="2026-07-31", value=5.0))
        )

        (position,) = await fetch_positions(client, (_record(_ACCOUNT_A),), today=FIXED_TODAY)

        assert position.account.id == _ACCOUNT_A
        assert position.balance is not None
        assert position.balance.valued == SeriesPoint(
            date=date(2026, 7, 31), value=11.0, value_status="ESTIMATE"
        )
        assert position.invested is not None
        assert position.invested.valued == SeriesPoint(
            date=date(2026, 7, 31), value=100.0, value_status=None
        )
        assert position.redemptions is not None
        assert position.redemptions.valued is not None
        assert position.redemptions.valued.value == 5.0
        assert position.errors == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_series_omits_the_figure_and_does_not_zero_it(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(return_value=_page())
        respx.get(_series_url(_ACCOUNT_A, "totalInvested")).mock(return_value=_page())
        respx.get(_series_url(_ACCOUNT_A, "totalRedemptions")).mock(return_value=_page())

        (position,) = await fetch_positions(client, (_record(_ACCOUNT_A),), today=FIXED_TODAY)

        assert position.balance is None
        assert position.invested is None
        assert position.redemptions is None
        assert position.errors == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_series_500_stays_on_that_row_and_siblings_succeed(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "values boom"}]})
        )
        respx.get(_series_url(_ACCOUNT_A, "totalInvested")).mock(
            return_value=_page(_point("3", date="2026-07-31", value=100.0))
        )
        respx.get(_series_url(_ACCOUNT_A, "totalRedemptions")).mock(return_value=_page())
        respx.get(_series_url(_ACCOUNT_B, "values")).mock(
            return_value=_page(_point("5", date="2026-07-31", value=20.0, valueStatus="ACTUAL"))
        )
        respx.get(_series_url(_ACCOUNT_B, "totalInvested")).mock(return_value=_page())
        respx.get(_series_url(_ACCOUNT_B, "totalRedemptions")).mock(return_value=_page())

        first, second = await fetch_positions(
            client,
            (_record(_ACCOUNT_A, name="A"), _record(_ACCOUNT_B, name="B")),
            today=FIXED_TODAY,
        )

        assert first.account.id == _ACCOUNT_A
        assert first.balance is None
        assert first.invested is not None
        assert first.invested.valued is not None
        assert first.invested.valued.value == 100.0
        assert len(first.errors) == 1
        assert first.errors[0].series == "values"
        assert "500" in first.errors[0].message
        assert second.account.id == _ACCOUNT_B
        assert second.balance is not None
        assert second.balance.valued is not None
        assert second.balance.valued.value == 20.0
        assert second.errors == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_aborts_the_fan_out(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(return_value=httpx.Response(401))
        respx.get(_series_url(_ACCOUNT_A, "totalInvested")).mock(return_value=_page())
        respx.get(_series_url(_ACCOUNT_A, "totalRedemptions")).mock(return_value=_page())

        with pytest.raises(BackstopAuthError):
            await fetch_positions(client, (_record(_ACCOUNT_A),), today=FIXED_TODAY)

    @pytest.mark.asyncio
    async def test_no_accounts_makes_no_requests(self, client: BackstopClient) -> None:
        assert await fetch_positions(client, (), today=FIXED_TODAY) == ()


_PRODUCT = ResolvedProduct(id="1292283", name="CGUP", short_name="CGUP")
_AUM_URL = f"{BASE_URL}/products/1292283/aums"


def _figure(value: float | None, *, day: int = 31) -> SeriesFigure:
    point = SeriesPoint(date=date(2026, 7, day), value=value)
    return SeriesFigure(latest=point, valued=point if value is not None else None)


def _position(
    account_id: str,
    *,
    balance: SeriesFigure | None = None,
) -> AccountPosition:
    return AccountPosition(account=_record(account_id), balance=balance)


class TestReconcile:
    def test_flags_when_summed_balances_differ_beyond_tolerance(self) -> None:
        result = reconcile(
            (_position("1", balance=_figure(10.0)), _position("2", balance=_figure(20.0))),
            _figure(40.0),
        )

        assert result.balance_total == 30.0
        assert result.difference == -10.0
        assert result.diverges is True

    def test_matches_when_the_sum_equals_aum(self) -> None:
        result = reconcile((_position("1", balance=_figure(30.0)),), _figure(30.0))

        assert result.difference == 0.0
        assert result.diverges is False

    def test_a_gap_inside_the_tolerance_is_not_divergence(self) -> None:
        result = reconcile((_position("1", balance=_figure(1_000_000.0)),), _figure(1_002_000.0))

        assert result.diverges is False
        assert result.difference == -2000.0

    def test_a_gap_past_the_tolerance_is_divergence(self) -> None:
        result = reconcile((_position("1", balance=_figure(1_000_000.0)),), _figure(1_010_000.0))

        assert result.diverges is True

    def test_omitted_balances_are_not_treated_as_zero(self) -> None:
        result = reconcile(
            (_position("1", balance=_figure(10.0)), _position("2")),
            _figure(30.0),
        )

        assert result.balance_total == 10.0
        assert result.diverges is True

    def test_a_balance_still_awaiting_its_value_is_left_out_of_the_sum(self) -> None:
        result = reconcile((_position("1", balance=_figure(None)),), _figure(30.0))

        assert result.balance_total is None
        assert result.diverges is False

    def test_no_aum_cannot_diverge(self) -> None:
        result = reconcile((_position("1", balance=_figure(10.0)),), None)

        assert result.balance_total == 10.0
        assert result.difference is None
        assert result.diverges is False

    def test_no_balances_cannot_diverge(self) -> None:
        result = reconcile((_position("1"),), _figure(30.0))

        assert result.balance_total is None
        assert result.diverges is False


class TestFetchProductAum:
    @pytest.mark.asyncio
    @respx.mock
    async def test_takes_the_latest_aum_without_inventing_value_status(
        self, client: BackstopClient
    ) -> None:
        respx.get(_AUM_URL).mock(return_value=_page(_point("1", date="2026-07-31", value=1000.0)))

        aum = await fetch_product_aum(client, "1292283", today=FIXED_TODAY)

        assert aum is not None
        assert aum.valued == SeriesPoint(date=date(2026, 7, 31), value=1000.0, value_status=None)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_aum_is_omitted_rather_than_failing_the_call(
        self, client: BackstopClient
    ) -> None:
        respx.get(_AUM_URL).mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "aum boom"}]})
        )

        assert await fetch_product_aum(client, "1292283", today=FIXED_TODAY) is None


class TestFetchProductPositions:
    @pytest.mark.asyncio
    @respx.mock
    async def test_flags_divergence_against_returned_balances(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(_point("1", date="2026-07-31", value=10.0))
        )
        respx.get(_series_url(_ACCOUNT_A, "totalInvested")).mock(return_value=_page())
        respx.get(_series_url(_ACCOUNT_A, "totalRedemptions")).mock(return_value=_page())
        respx.get(_AUM_URL).mock(return_value=_page(_point("aum", date="2026-07-31", value=99.0)))

        result = await fetch_product_positions(
            client,
            AccountListing(accounts=(_record(_ACCOUNT_A),), closed_omitted=2),
            product=_PRODUCT,
            today=FIXED_TODAY,
        )

        assert result.aum is not None
        assert result.aum.valued is not None
        assert result.aum.valued.value == 99.0
        assert result.reconciliation.diverges is True
        assert result.reconciliation.balance_total == 10.0
        assert result.reconciliation.difference == -89.0
        assert result.closed_omitted == 2
        assert result.accounts_omitted == 0
        assert result.accounts[0].balance is not None
        assert result.accounts[0].balance.valued is not None
        assert result.accounts[0].balance.valued.value == 10.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_caps_the_fan_out_and_publishes_what_it_dropped(
        self, client: BackstopClient
    ) -> None:
        listed = tuple(_record(str(index)) for index in range(MAX_POSITION_ACCOUNTS + 3))
        for series in ("values", "totalInvested", "totalRedemptions"):
            respx.get(url__regex=rf"{BASE_URL}/accounts/\d+/{series}").mock(return_value=_page())
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await fetch_product_positions(
            client,
            AccountListing(accounts=listed),
            product=_PRODUCT,
            today=FIXED_TODAY,
        )

        assert len(result.accounts) == MAX_POSITION_ACCOUNTS
        assert result.accounts_omitted == 3
