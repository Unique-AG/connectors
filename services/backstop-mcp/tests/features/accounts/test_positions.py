from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.accounts.positions import (
    aum_diverges,
    fetch_positions,
    fetch_product_aum,
    fetch_product_positions,
)
from backstop_mcp.features.accounts.types import (
    AccountListing,
    AccountPosition,
    AccountRecord,
    ResolvedProduct,
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
        assert position.balance == SeriesPoint(
            date=date(2026, 7, 31), value=11.0, value_status="ESTIMATE"
        )
        assert position.invested == SeriesPoint(
            date=date(2026, 7, 31), value=100.0, value_status=None
        )
        assert position.redemptions is not None
        assert position.redemptions.value == 5.0
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
        assert first.invested.value == 100.0
        assert len(first.errors) == 1
        assert first.errors[0].series == "values"
        assert "500" in first.errors[0].message
        assert second.account.id == _ACCOUNT_B
        assert second.balance is not None
        assert second.balance.value == 20.0
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


def _position(
    account_id: str,
    *,
    balance: SeriesPoint | None = None,
) -> AccountPosition:
    return AccountPosition(account=_record(account_id), balance=balance)


class TestAumDiverges:
    def test_flags_when_summed_balances_differ_from_aum(self) -> None:
        assert (
            aum_diverges(
                (
                    _position("1", balance=SeriesPoint(date=date(2026, 7, 31), value=10.0)),
                    _position("2", balance=SeriesPoint(date=date(2026, 7, 31), value=20.0)),
                ),
                SeriesPoint(date=date(2026, 7, 31), value=40.0),
            )
            is True
        )

    def test_matches_when_the_sum_equals_aum(self) -> None:
        assert (
            aum_diverges(
                (_position("1", balance=SeriesPoint(date=date(2026, 7, 31), value=30.0)),),
                SeriesPoint(date=date(2026, 7, 31), value=30.0),
            )
            is False
        )

    def test_omitted_balances_are_not_treated_as_zero(self) -> None:
        assert (
            aum_diverges(
                (
                    _position("1", balance=SeriesPoint(date=date(2026, 7, 31), value=10.0)),
                    _position("2"),
                ),
                SeriesPoint(date=date(2026, 7, 31), value=30.0),
            )
            is True
        )

    def test_no_aum_cannot_diverge(self) -> None:
        assert (
            aum_diverges(
                (_position("1", balance=SeriesPoint(date=date(2026, 7, 31), value=10.0)),),
                None,
            )
            is False
        )


class TestFetchProductAum:
    @pytest.mark.asyncio
    @respx.mock
    async def test_takes_the_latest_aum_without_inventing_value_status(
        self, client: BackstopClient
    ) -> None:
        respx.get(_AUM_URL).mock(return_value=_page(_point("1", date="2026-07-31", value=1000.0)))

        aum = await fetch_product_aum(client, "1292283", today=FIXED_TODAY)

        assert aum == SeriesPoint(date=date(2026, 7, 31), value=1000.0, value_status=None)

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
        assert result.aum.value == 99.0
        assert result.aum_diverges is True
        assert result.closed_omitted == 2
        assert result.accounts[0].balance is not None
        assert result.accounts[0].balance.value == 10.0
