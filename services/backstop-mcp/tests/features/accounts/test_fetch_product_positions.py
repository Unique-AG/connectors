from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.accounts import (
    MAX_POSITION_ACCOUNTS,
    AccountListingDto,
    AccountRecordDto,
    ProductPositionsDto,
    ResolvedProductDto,
    fetch_product_positions,
)
from tests.helpers import BASE_URL

_ACCOUNT_A = "27871657"
_ACCOUNT_B = "28124025"
_PRODUCT = ResolvedProductDto(id="1292283", name="CGUP", short_name="CGUP")
_AUM_URL = f"{BASE_URL}/products/1292283/aums"


def _record(account_id: str, *, name: str = "Row") -> AccountRecordDto:
    return AccountRecordDto(id=account_id, name=name, is_open=True)


def _listing(*accounts: AccountRecordDto, closed_omitted: int = 0) -> AccountListingDto:
    return AccountListingDto(accounts=accounts, closed_omitted=closed_omitted)


def _point(point_id: str, **attributes: object) -> dict[str, object]:
    return {"id": point_id, "type": "values", "attributes": attributes}


def _page(*points: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(points)})


def _series_url(account_id: str, series: str) -> str:
    return f"{BASE_URL}/accounts/{account_id}/{series}"


def _empty_invested_and_redemptions(*account_ids: str) -> None:
    for account_id in account_ids:
        respx.get(_series_url(account_id, "totalInvested")).mock(return_value=_page())
        respx.get(_series_url(account_id, "totalRedemptions")).mock(return_value=_page())


async def _positions(
    client: BackstopClient,
    *accounts: AccountRecordDto,
    closed_omitted: int = 0,
) -> ProductPositionsDto:
    return await fetch_product_positions(
        client,
        _listing(*accounts, closed_omitted=closed_omitted),
        product=_PRODUCT,
    )


class TestSeriesLatestFigure:
    @pytest.mark.asyncio
    @respx.mock
    async def test_asks_for_the_ten_newest_rows(self, client: BackstopClient) -> None:
        route = respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(_point("1", date="2026-07-31", value=9.0, valueStatus="ESTIMATE"))
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        params = route.calls.last.request.url.params
        assert params["sort"] == "-date"
        assert params["page[limit]"] == "10"
        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.valued is not None
        assert position.balance.valued.date == date(2026, 7, 31)
        assert position.balance.valued.value == 9.0
        assert position.balance.valued.value_status == "ESTIMATE"

    @pytest.mark.asyncio
    @respx.mock
    async def test_picks_the_greatest_date(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                _point("1", date="2026-05-31", value=10.0, valueStatus="ACTUAL"),
                _point("2", date="2026-06-15", value=11.0, valueStatus="ESTIMATE"),
                _point("3", date="2026-06-30", value=12.0, valueStatus="ACTUAL"),
            )
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.valued is not None
        assert position.balance.valued.date == date(2026, 6, 30)
        assert position.balance.valued.value == 12.0
        assert position.balance.valued.value_status == "ACTUAL"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_mid_month_point_after_month_end_wins(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                _point("1", date="2026-06-30", value=100.0, valueStatus="ACTUAL"),
                _point("2", date="2026-07-15", value=101.5, valueStatus="ESTIMATE"),
            )
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.valued is not None
        assert position.balance.valued.date == date(2026, 7, 15)
        assert position.balance.valued.value == 101.5
        assert position.balance.valued.value_status == "ESTIMATE"

    @pytest.mark.asyncio
    @respx.mock
    async def test_omits_value_status_when_backstop_omits_it(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(_point("1", date="2026-06-30", value=50.0))
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.valued is not None
        assert position.balance.valued.date == date(2026, 6, 30)
        assert position.balance.valued.value == 50.0
        assert position.balance.valued.value_status is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_points_without_a_date(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                _point("1", value=1.0),
                _point("2", date="2026-01-31", value=2.0),
            )
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.valued is not None
        assert position.balance.valued.date == date(2026, 1, 31)
        assert position.balance.valued.value == 2.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_series_omits_the_figure(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(return_value=_page())
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        assert result.accounts[0].balance is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_undated_points_omit_the_figure(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(_point("1", value=1.0))
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        assert result.accounts[0].balance is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_dated_point_without_a_value_does_not_shadow_the_last_number(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                _point("1", date="2026-06-30", value=1_000_000.0, valueStatus="ACTUAL"),
                _point("2", date="2026-07-31", valueStatus="ESTIMATE"),
            )
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.latest.date == date(2026, 7, 31)
        assert position.balance.latest.value is None
        assert position.balance.valued is not None
        assert position.balance.valued.date == date(2026, 6, 30)
        assert position.balance.valued.value == 1_000_000.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_series_of_valueless_points_has_no_valued_point(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                _point("1", date="2026-06-30"),
                _point("2", date="2026-07-31"),
            )
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.latest.date == date(2026, 7, 31)
        assert position.balance.valued is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_malformed_point_is_an_error_on_that_row(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                {"type": "values", "attributes": {"date": "2026-07-31", "value": 1.0}}
            )
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is None
        assert len(position.errors) == 1
        assert position.errors[0].series == "values"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_non_numeric_value_is_unvalued_not_a_failed_page(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(_point("1", date="2026-07-31", value="not-a-number"))
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))

        position = result.accounts[0]
        assert position.balance is not None
        assert position.balance.latest.date == date(2026, 7, 31)
        assert position.balance.latest.value is None
        assert position.balance.valued is None


class TestFetchPositions:
    @pytest.mark.asyncio
    @respx.mock
    async def test_attaches_the_three_series_per_account(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(
                _point("2", date="2026-07-31", value=11.0, valueStatus="ESTIMATE"),
                _point("1", date="2026-06-30", value=10.0, valueStatus="ACTUAL"),
            )
        )
        respx.get(_series_url(_ACCOUNT_A, "totalInvested")).mock(
            return_value=_page(_point("3", date="2026-07-31", value=100.0))
        )
        respx.get(_series_url(_ACCOUNT_A, "totalRedemptions")).mock(
            return_value=_page(_point("4", date="2026-07-31", value=5.0))
        )
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))
        (position,) = result.accounts

        assert position.account.id == _ACCOUNT_A
        assert position.balance is not None
        assert position.balance.valued is not None
        assert position.balance.valued.date == date(2026, 7, 31)
        assert position.balance.valued.value == 11.0
        assert position.balance.valued.value_status == "ESTIMATE"
        assert position.invested is not None
        assert position.invested.valued is not None
        assert position.invested.valued.value == 100.0
        assert position.invested.valued.value_status is None
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
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record(_ACCOUNT_A))
        (position,) = result.accounts

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
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(
            client, _record(_ACCOUNT_A, name="A"), _record(_ACCOUNT_B, name="B")
        )
        first, second = result.accounts

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
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page())

        with pytest.raises(BackstopAuthError):
            await _positions(client, _record(_ACCOUNT_A))

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_accounts_makes_no_account_series_requests(
        self, client: BackstopClient
    ) -> None:
        values = respx.get(url__regex=rf"{BASE_URL}/accounts/\d+/values").mock(return_value=_page())
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await fetch_product_positions(client, _listing(), product=_PRODUCT)

        assert result.accounts == ()
        assert values.call_count == 0


class TestFetchProductAum:
    @pytest.mark.asyncio
    @respx.mock
    async def test_takes_the_latest_aum_without_inventing_value_status(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(return_value=_page())
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page(_point("1", date="2026-07-31", value=1000.0)))

        result = await _positions(client, _record(_ACCOUNT_A))

        assert result.aum is not None
        assert result.aum.valued is not None
        assert result.aum.valued.date == date(2026, 7, 31)
        assert result.aum.valued.value == 1000.0
        assert result.aum.valued.value_status is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_aum_is_omitted_rather_than_failing_the_call(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(return_value=_page())
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "aum boom"}]})
        )

        result = await _positions(client, _record(_ACCOUNT_A))

        assert result.aum is None


class TestReconcile:
    @pytest.mark.asyncio
    @respx.mock
    async def test_flags_when_summed_balances_differ_beyond_tolerance(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url("1", "values")).mock(
            return_value=_page(_point("a", date="2026-07-31", value=10.0))
        )
        respx.get(_series_url("2", "values")).mock(
            return_value=_page(_point("b", date="2026-07-31", value=20.0))
        )
        _empty_invested_and_redemptions("1", "2")
        respx.get(_AUM_URL).mock(return_value=_page(_point("aum", date="2026-07-31", value=40.0)))

        result = await _positions(client, _record("1"), _record("2"))

        assert result.reconciliation.balance_total == 30.0
        assert result.reconciliation.difference == -10.0
        assert result.reconciliation.diverges is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_matches_when_the_sum_equals_aum(self, client: BackstopClient) -> None:
        respx.get(_series_url("1", "values")).mock(
            return_value=_page(_point("a", date="2026-07-31", value=30.0))
        )
        _empty_invested_and_redemptions("1")
        respx.get(_AUM_URL).mock(return_value=_page(_point("aum", date="2026-07-31", value=30.0)))

        result = await _positions(client, _record("1"))

        assert result.reconciliation.difference == 0.0
        assert result.reconciliation.diverges is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_gap_inside_the_tolerance_is_not_divergence(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url("1", "values")).mock(
            return_value=_page(_point("a", date="2026-07-31", value=1_000_000.0))
        )
        _empty_invested_and_redemptions("1")
        respx.get(_AUM_URL).mock(
            return_value=_page(_point("aum", date="2026-07-31", value=1_002_000.0))
        )

        result = await _positions(client, _record("1"))

        assert result.reconciliation.diverges is False
        assert result.reconciliation.difference == -2000.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_gap_past_the_tolerance_is_divergence(self, client: BackstopClient) -> None:
        respx.get(_series_url("1", "values")).mock(
            return_value=_page(_point("a", date="2026-07-31", value=1_000_000.0))
        )
        _empty_invested_and_redemptions("1")
        respx.get(_AUM_URL).mock(
            return_value=_page(_point("aum", date="2026-07-31", value=1_010_000.0))
        )

        result = await _positions(client, _record("1"))

        assert result.reconciliation.diverges is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_omitted_balances_are_not_treated_as_zero(self, client: BackstopClient) -> None:
        respx.get(_series_url("1", "values")).mock(
            return_value=_page(_point("a", date="2026-07-31", value=10.0))
        )
        respx.get(_series_url("2", "values")).mock(return_value=_page())
        _empty_invested_and_redemptions("1", "2")
        respx.get(_AUM_URL).mock(return_value=_page(_point("aum", date="2026-07-31", value=30.0)))

        result = await _positions(client, _record("1"), _record("2"))

        assert result.reconciliation.balance_total == 10.0
        assert result.reconciliation.diverges is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_balance_still_awaiting_its_value_is_left_out_of_the_sum(
        self, client: BackstopClient
    ) -> None:
        respx.get(_series_url("1", "values")).mock(
            return_value=_page(_point("a", date="2026-07-31"))
        )
        _empty_invested_and_redemptions("1")
        respx.get(_AUM_URL).mock(return_value=_page(_point("aum", date="2026-07-31", value=30.0)))

        result = await _positions(client, _record("1"))

        assert result.reconciliation.balance_total is None
        assert result.reconciliation.diverges is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_aum_cannot_diverge(self, client: BackstopClient) -> None:
        respx.get(_series_url("1", "values")).mock(
            return_value=_page(_point("a", date="2026-07-31", value=10.0))
        )
        _empty_invested_and_redemptions("1")
        respx.get(_AUM_URL).mock(return_value=_page())

        result = await _positions(client, _record("1"))

        assert result.reconciliation.balance_total == 10.0
        assert result.reconciliation.difference is None
        assert result.reconciliation.diverges is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_balances_cannot_diverge(self, client: BackstopClient) -> None:
        respx.get(_series_url("1", "values")).mock(return_value=_page())
        _empty_invested_and_redemptions("1")
        respx.get(_AUM_URL).mock(return_value=_page(_point("aum", date="2026-07-31", value=30.0)))

        result = await _positions(client, _record("1"))

        assert result.reconciliation.balance_total is None
        assert result.reconciliation.diverges is False


class TestFetchProductPositions:
    @pytest.mark.asyncio
    @respx.mock
    async def test_flags_divergence_against_returned_balances(self, client: BackstopClient) -> None:
        respx.get(_series_url(_ACCOUNT_A, "values")).mock(
            return_value=_page(_point("1", date="2026-07-31", value=10.0))
        )
        _empty_invested_and_redemptions(_ACCOUNT_A)
        respx.get(_AUM_URL).mock(return_value=_page(_point("aum", date="2026-07-31", value=99.0)))

        result = await _positions(client, _record(_ACCOUNT_A), closed_omitted=2)

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
            AccountListingDto(accounts=listed),
            product=_PRODUCT,
        )

        assert len(result.accounts) == MAX_POSITION_ACCOUNTS
        assert result.accounts_omitted == 3
        assert MAX_POSITION_ACCOUNTS == 500
