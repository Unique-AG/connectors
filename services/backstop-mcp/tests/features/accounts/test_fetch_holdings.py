"""`fetch_holdings`: which path runs, and what the documented one can honestly produce.

The interesting behaviour here is entirely about *when* the fallback fires. An empty table and a
dead credential must not trigger it — the first because it is a real answer, the second because
the documented walk would fail identically but slower. A 401 that re-verified still authenticates
is the opposite: this unsupported endpoint refused us, so use the documented one.
"""

from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopClient,
    BackstopRateLimitError,
)
from backstop_mcp.features.accounts import FALLBACK_OMITTED_FIELDS, fetch_holdings
from tests.helpers import BASE_URL, client_factory, credential

_ORG = "341764767"
_ACCOUNT = "27871657"
_TABLE_URL = f"{BASE_URL}/bsg-account-table-data"
_ACCOUNTS_URL = f"{BASE_URL}/accounts"


def _table_row(account_id: str) -> dict[str, object]:
    def ref(rid: str, rtype: str, **extra: object) -> dict[str, object]:
        return {"resourceType": rtype, "resourceId": rid, **extra}

    return {
        "investor": ref(_ORG, "organizations"),
        "account": ref(account_id, "hedge-fund-accounts"),
        "product": ref("1653647", "hedge-fund-products", shortName="CIO2"),
        "closed": False,
        "balance": {"amount": 42.0, "currency": "USD", "formattedValue": "$42.00"},
    }


def _table(*rows: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": None,
                    "type": "bsg-account-table-data",
                    "attributes": {
                        "accounts": list(rows),
                        "openCount": len(rows),
                        "allCount": len(rows),
                        "closedCount": 0,
                    },
                }
            ]
        },
    )


def _accounts_page(*, closed: bool = False) -> httpx.Response:
    """One `/accounts` page carrying a single account owned by `_ORG`."""
    attributes: dict[str, object] = {
        "name": "Row",
        "currency": "USD",
        "accountStartDate": "2017-01-01",
    }
    if closed:
        attributes["closedDate"] = "2022-02-01"
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": _ACCOUNT,
                    "type": "accounts",
                    "attributes": attributes,
                    "relationships": {"owner": {"data": {"id": _ORG, "type": "contacts"}}},
                }
            ],
            "included": [
                {
                    "id": _ORG,
                    "type": "contacts",
                    "attributes": {
                        "name": "Test Org",
                        "specificResource": {"resourceType": "organizations", "resourceId": _ORG},
                    },
                }
            ],
            "meta": {"totalResourceCount": 1},
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


def _mock_fallback_series(*, balance: float | None = 100.0, share: float | None = 0.25) -> None:
    respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/values").mock(return_value=_series(balance))
    respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/percentageOfFundHistory").mock(
        return_value=_series(share)
    )


class TestPrimaryPath:
    @pytest.mark.asyncio
    @respx.mock
    async def test_uses_the_table_and_never_walks_accounts(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_table_row(_ACCOUNT)))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = await fetch_holdings(client, owner_id=_ORG)

        assert not walk.called
        assert result.source == "table-api"
        assert result.omitted_fields == ()
        assert result.rows[0].balance is not None
        assert result.rows[0].balance.formatted == "$42.00"

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_empty_table_is_an_answer_not_a_fallback_trigger(
        self, client: BackstopClient
    ) -> None:
        """Walking 815 accounts to re-confirm "owns nothing" would be pure cost."""
        respx.get(_TABLE_URL).mock(return_value=_table())
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = await fetch_holdings(client, owner_id=_ORG)

        assert not walk.called
        assert result.rows == ()
        assert result.source == "table-api"


class TestFallbackTriggers:
    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize("status", [400, 404, 409, 500, 503])
    async def test_any_http_error_falls_back(self, client: BackstopClient, status: int) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(status, json={"errors": []}))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series()

        result = await fetch_holdings(client, owner_id=_ORG)

        assert walk.called
        assert result.source == "accounts-api"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_timeout_falls_back(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(side_effect=httpx.ReadTimeout("too slow"))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series()

        result = await fetch_holdings(client, owner_id=_ORG)

        assert walk.called
        assert result.source == "accounts-api"

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_unparseable_body_falls_back(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=httpx.Response(200, content=b"<html>not json</html>")
        )
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series()

        result = await fetch_holdings(client, owner_id=_ORG)

        assert walk.called
        assert result.source == "accounts-api"

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_does_not_fall_back(self, client: BackstopClient) -> None:
        """The credential is dead; the walk would fail the same way, slower."""
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(401, json={"errors": []}))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        with pytest.raises(BackstopAuthError):
            await fetch_holdings(client, owner_id=_ORG)

        assert not walk.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_reverified_401_on_the_table_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Credential still works; the undocumented table refused us — same as a 404."""

        async def instant_sleep(_delay: float) -> None:
            return None

        monkeypatch.setattr("backstop_mcp.backstop_client.client.asyncio.sleep", instant_sleep)

        async def must_not_revoke() -> None:
            raise AssertionError("must not revoke when /system-info still authenticates")

        factory = client_factory()
        client = factory.for_credential(credential(), on_auth_failure=must_not_revoke)
        try:
            respx.get(_TABLE_URL).mock(return_value=httpx.Response(401, json={"errors": []}))
            respx.get(f"{BASE_URL}/system-info").mock(return_value=httpx.Response(200, json={}))
            walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
            _mock_fallback_series()

            result = await fetch_holdings(client, owner_id=_ORG)

            assert walk.called
            assert result.source == "accounts-api"
        finally:
            await factory.aclose()

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_rate_limit_does_not_fall_back(self, client: BackstopClient) -> None:
        """Answering "slow down" with ~9 pages plus two requests per account makes it worse."""
        respx.get(_TABLE_URL).mock(
            return_value=httpx.Response(429, json={"errors": []}, headers={"Retry-After": "1"})
        )
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        with pytest.raises(BackstopRateLimitError):
            await fetch_holdings(client, owner_id=_ORG)

        assert not walk.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_counts_contradicting_the_rows_falls_back(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"attributes": {"rowz": [], "allCount": 12, "closedCount": 11}}]},
            )
        )
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series()

        result = await fetch_holdings(client, owner_id=_ORG)

        assert walk.called
        assert result.source == "accounts-api"


class TestFallbackContent:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_figures_from_the_documented_series(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series(balance=100.0, share=0.25)

        row = (await fetch_holdings(client, owner_id=_ORG)).rows[0]

        assert row.account_id == _ACCOUNT
        assert row.balance is not None
        assert row.balance.amount == 100.0
        assert row.balance.currency == "USD"
        assert row.percentage_of_product is not None
        assert row.percentage_of_product.fraction == 0.25
        assert row.investor_id == _ORG
        assert row.investor_resource_type == "organizations"
        assert row.funded_date == date(2017, 1, 1)

    @pytest.mark.asyncio
    @respx.mock
    async def test_names_every_unavailable_field_so_it_is_not_read_as_zero(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series()

        result = await fetch_holdings(client, owner_id=_ORG)

        assert result.source == "accounts-api"
        assert result.omitted_fields == FALLBACK_OMITTED_FIELDS
        row = result.rows[0]
        assert row.commitment is None
        assert row.unfunded_commitment is None
        assert row.percentage_of_master is None
        assert row.account_term_id is None
        assert row.other_id is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_failed_series_omits_that_figure_and_keeps_the_row(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/values").mock(return_value=_series(100.0))
        respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/percentageOfFundHistory").mock(
            return_value=httpx.Response(500, json={"errors": []})
        )

        row = (await fetch_holdings(client, owner_id=_ORG)).rows[0]

        assert row.balance is not None
        assert row.balance.amount == 100.0
        assert row.percentage_of_product is None
        # "the request failed" must not read the same as "Backstop publishes no number".
        assert [error.figure for error in row.figure_errors] == ["percentage_of_product"]
        assert "500" in row.figure_errors[0].message

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_empty_series_omits_the_figure_rather_than_zeroing_it(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series(balance=None, share=None)

        row = (await fetch_holdings(client, owner_id=_ORG)).rows[0]

        assert row.balance is None
        assert row.percentage_of_product is None
        assert row.figure_errors == ()  # nothing failed; there is simply no number

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_published_zero_is_kept_as_a_real_zero(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series(balance=0.0, share=0.0)

        row = (await fetch_holdings(client, owner_id=_ORG)).rows[0]

        assert row.balance is not None
        assert row.balance.amount == 0.0
        assert row.percentage_of_product is not None
        assert row.percentage_of_product.fraction == 0.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_on_a_fallback_series_aborts(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/values").mock(
            return_value=httpx.Response(401, json={"errors": []})
        )
        respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/percentageOfFundHistory").mock(
            return_value=_series(0.25)
        )

        with pytest.raises(BackstopAuthError):
            await fetch_holdings(client, owner_id=_ORG)

    @pytest.mark.asyncio
    @respx.mock
    async def test_closed_accounts_are_counted_even_when_filtered_out(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page(closed=True))
        _mock_fallback_series()

        result = await fetch_holdings(client, owner_id=_ORG)

        assert result.rows == ()
        assert result.closed_omitted == 1
        assert (result.open_count, result.all_count, result.closed_count) == (0, 1, 1)

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_the_row_and_still_counts_it_closed(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page(closed=True))
        _mock_fallback_series()

        result = await fetch_holdings(client, owner_id=_ORG, include_closed=True)

        assert [row.account_id for row in result.rows] == [_ACCOUNT]
        assert result.rows[0].closed is True
        assert (result.open_count, result.all_count, result.closed_count) == (0, 1, 1)

    @pytest.mark.asyncio
    @respx.mock
    async def test_publishes_the_as_of_date_because_the_valued_point_can_be_stale(
        self, client: BackstopClient
    ) -> None:
        """The newest point may carry no number yet, so the balance can be months old.

        On the table endpoint the balance is the newest point and there is no date at all. Here
        it is the newest *valued* point, so only the date distinguishes "current" from "last
        known" — publishing it is what stops the two paths silently meaning different things.
        """
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/values").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "newest",
                            "type": "time-series",
                            "attributes": {"date": "2026-08-31", "value": None},
                        },
                        {
                            "id": "valued",
                            "type": "time-series",
                            "attributes": {
                                "date": "2026-02-28",
                                "value": 7.0,
                                "valueStatus": "ACTUAL",
                            },
                        },
                    ]
                },
            )
        )
        respx.get(f"{BASE_URL}/accounts/{_ACCOUNT}/percentageOfFundHistory").mock(
            return_value=_series(0.25)
        )

        row = (await fetch_holdings(client, owner_id=_ORG)).rows[0]

        assert row.balance is not None
        assert row.balance.amount == 7.0
        assert row.balance_as_of == date(2026, 2, 28)
        assert row.balance_status == "ACTUAL"
