"""`GetHoldingsQuery`: table path, documented walk, and when the fallback fires.

The interesting behaviour here is entirely about *when* the fallback fires. An empty table and a
dead credential must not trigger it — the first because it is a real answer, the second because
the documented walk would fail identically but slower. A 401 that re-verified still authenticates
is the opposite: this unsupported endpoint refused us, so use the documented one.

Table fixtures below are shaped from recorded responses (`docs/json/023`, `026`, `037`, `046`):
rows under `data[0].attributes.accounts`, a `null` element id, `meta.totalResourceCount` of `0`,
and `included` empty.
"""

from collections.abc import Sequence
from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopClient,
    BackstopRateLimitError,
)
from backstop_mcp.features.accounts import FALLBACK_OMITTED_FIELDS, HoldingListingDto
from tests.features.accounts.conftest import make_get_holdings_query
from tests.helpers import BASE_URL, client_factory, credential, recorded_params, resource

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


def _thin_table(*rows: dict[str, object]) -> httpx.Response:
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
        respx.get(_TABLE_URL).mock(return_value=_thin_table(_table_row(_ACCOUNT)))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

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
        respx.get(_TABLE_URL).mock(return_value=_thin_table())
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

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

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

        assert walk.called
        assert result.source == "accounts-api"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_timeout_falls_back(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(side_effect=httpx.ReadTimeout("too slow"))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series()

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

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

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

        assert walk.called
        assert result.source == "accounts-api"

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_does_not_fall_back(self, client: BackstopClient) -> None:
        """The credential is dead; the walk would fail the same way, slower."""
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(401, json={"errors": []}))
        walk = respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())

        with pytest.raises(BackstopAuthError):
            await make_get_holdings_query(client).run(owner_id=_ORG)

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

            result = await make_get_holdings_query(client).run(owner_id=_ORG)

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
            await make_get_holdings_query(client).run(owner_id=_ORG)

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

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

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

        row = (await make_get_holdings_query(client).run(owner_id=_ORG)).rows[0]

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

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

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

        row = (await make_get_holdings_query(client).run(owner_id=_ORG)).rows[0]

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

        row = (await make_get_holdings_query(client).run(owner_id=_ORG)).rows[0]

        assert row.balance is None
        assert row.percentage_of_product is None
        assert row.figure_errors == ()  # nothing failed; there is simply no number

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_published_zero_is_kept_as_a_real_zero(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page())
        _mock_fallback_series(balance=0.0, share=0.0)

        row = (await make_get_holdings_query(client).run(owner_id=_ORG)).rows[0]

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
            await make_get_holdings_query(client).run(owner_id=_ORG)

    @pytest.mark.asyncio
    @respx.mock
    async def test_closed_accounts_are_counted_even_when_filtered_out(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(500, json={"errors": []}))
        respx.get(_ACCOUNTS_URL).mock(return_value=_accounts_page(closed=True))
        _mock_fallback_series()

        result = await make_get_holdings_query(client).run(owner_id=_ORG)

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

        result = await make_get_holdings_query(client).run(owner_id=_ORG, include_closed=True)

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

        row = (await make_get_holdings_query(client).run(owner_id=_ORG)).rows[0]

        assert row.balance is not None
        assert row.balance.amount == 7.0
        assert row.balance_as_of == date(2026, 2, 28)
        assert row.balance_status == "ACTUAL"

_BROKEN_ENVELOPES: tuple[dict[str, object], ...] = (
    {"data": [], "meta": {}},
    {"accounts": []},
    {"data": [{"attrs": {"accounts": []}}]},
    {"data": [{"attributes": None}]},
)
_BROKEN_ENVELOPE_IDS = ("empty-data", "renamed-data", "renamed-attributes", "null-attributes")


def _ref(resource_id: str, resource_type: str, **extra: object) -> dict[str, object]:
    return {
        "resourceType": resource_type,
        "resourceId": resource_id,
        "resourceLink": f"{BASE_URL}/{resource_type}/{resource_id}",
        "restricted": False,
        **extra,
    }


def _money(amount: float | None, formatted: str) -> dict[str, object]:
    return {
        "amount": amount,
        "currency": "USD",
        "currencySymbol": "$",
        "formattedValue": formatted,
    }


_UNSET: object = object()


def _row(
    account_id: str,
    *,
    product_id: str = "1653647",
    short_name: str = "CIO2",
    closed: bool = False,
    balance: object = _UNSET,
    **overrides: object,
) -> dict[str, object]:
    """A recorded row. `balance=None` means "absent"; omitting it means "the usual $0.00"."""
    row: dict[str, object] = {
        "investor": _ref(_ORG, "organizations"),
        "account": _ref(account_id, "hedge-fund-accounts"),
        "organization": _ref(_ORG, "organizations"),
        "product": _ref(product_id, "hedge-fund-products", shortName=short_name),
        "accountTerm": _ref("497339", "account-terms"),
        "associationType": "0",
        "otherId": "90007828_CIO2_00000",
        "fundedDate": "2017-01-01T00:00:00.000-0500",
        "closedDate": "2022-02-01T00:00:00.000-0500" if closed else None,
        "closed": closed,
        "balance": _money(0.0, "$0.00") if balance is _UNSET else balance,
        "commitment": _money(0.0, "-"),
        "unfundedCommitment": _money(0.0, "-"),
        "percentageOfProduct": {"value": 0.0, "formattedValue": "0.00%"},
        "percentageOfMaster": {"value": 0.0, "formattedValue": "0.00%"},
        "customFieldValues": {},
    }
    return row | overrides


def _table(*rows: dict[str, object], **counts: object) -> httpx.Response:
    closed = sum(1 for row in rows if row.get("closed"))
    attributes: dict[str, object] = {
        "accounts": list(rows),
        "openCount": len(rows) - closed,
        "allCount": len(rows),
        "closedCount": closed,
    } | counts
    return httpx.Response(
        200,
        json={
            "data": [{"id": None, "type": "bsg-account-table-data", "attributes": attributes}],
            "included": [],
            "meta": {"totalResourceCount": 0},
        },
    )


async def _fetch(client: BackstopClient, *, include_closed: bool = False) -> HoldingListingDto:
    return await make_get_holdings_query(client).run(owner_id=_ORG, include_closed=include_closed)


def _empty_walk() -> None:
    respx.get(f"{BASE_URL}/accounts").mock(
        return_value=httpx.Response(200, json={"data": [], "included": []})
    )


class TestRequestShape:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_only_entity_id_because_paging_params_are_ignored(
        self, client: BackstopClient
    ) -> None:
        """Paging is ignored upstream, so sending it would imply a bound that does not exist."""
        route = respx.get(_TABLE_URL).mock(return_value=_table(_row("28435967")))

        await _fetch(client)

        assert dict(route.calls.last.request.url.params) == {"entityId": _ORG}

    @pytest.mark.asyncio
    @respx.mock
    async def test_reads_the_whole_table_in_one_request(self, client: BackstopClient) -> None:
        route = respx.get(_TABLE_URL).mock(
            return_value=_table(*(_row(str(28435967 + n)) for n in range(12)))
        )

        result = await _fetch(client)

        assert route.call_count == 1
        assert len(result.rows) == 12


class TestProjection:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_ids_dates_and_figures(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(
                _row(
                    "29431089",
                    short_name="CIO3",
                    balance=_money(3619868606.0, "$3,619,868,606.00"),
                )
            )
        )

        row = (await _fetch(client)).rows[0]

        assert row.account_id == "29431089"
        assert row.product_id == "1653647"
        assert row.product_short_name == "CIO3"
        assert row.investor_id == _ORG
        assert row.investor_resource_type == "organizations"
        assert row.account_term_id == "497339"
        assert row.other_id == "90007828_CIO2_00000"
        assert row.funded_date == date(2017, 1, 1)
        assert row.balance is not None
        assert row.balance.amount == 3619868606.0
        assert row.balance.currency == "USD"

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_a_real_zero_and_its_rendering(self, client: BackstopClient) -> None:
        """`0.0` with `"-"` is "not recorded"; `0.0` with `"$0.00"` is real. Both are kept."""
        respx.get(_TABLE_URL).mock(return_value=_table(_row("28435967")))

        row = (await _fetch(client)).rows[0]

        assert row.balance is not None
        assert row.balance.amount == 0.0
        assert row.balance.formatted == "$0.00"
        assert row.commitment is not None
        assert row.commitment.amount == 0.0
        assert row.commitment.formatted == "-"

    @pytest.mark.asyncio
    @respx.mock
    async def test_share_figures_are_fractions_not_percentages(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(
                _row(
                    "29431089",
                    percentageOfProduct={"value": 0.796, "formattedValue": "79.60%"},
                )
            )
        )

        row = (await _fetch(client)).rows[0]

        assert row.percentage_of_product is not None
        assert row.percentage_of_product.fraction == 0.796
        assert row.percentage_of_product.formatted == "79.60%"

    @pytest.mark.asyncio
    @respx.mock
    async def test_omits_a_missing_other_id_rather_than_blanking_it(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_row("28435967", otherId=None)))

        assert (await _fetch(client)).rows[0].other_id is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_relays_backstops_own_counts_rather_than_recomputing_them(
        self, client: BackstopClient
    ) -> None:
        """`openCount` is relayed verbatim. Deriving it from the rows would give 1, not 7."""
        respx.get(_TABLE_URL).mock(
            return_value=_table(
                _row("1"),
                _row("2", closed=True),
                _row("3", closed=True),
                openCount=7,
            )
        )

        result = await _fetch(client, include_closed=True)

        assert result.open_count == 7
        assert (result.all_count, result.closed_count) == (3, 2)


class TestClosedFiltering:
    @pytest.mark.asyncio
    @respx.mock
    async def test_drops_closed_rows_and_counts_them(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_row("1"), _row("2", closed=True)))

        result = await _fetch(client)

        assert [row.account_id for row in result.rows] == ["1"]
        assert result.closed_omitted == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_them(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_row("1"), _row("2", closed=True)))

        result = await _fetch(client, include_closed=True)

        assert [row.account_id for row in result.rows] == ["1", "2"]
        assert result.closed_omitted == 0
        assert result.rows[1].closed_date == date(2022, 2, 1)


class TestDegradation:
    """An undocumented endpoint changing shape must cost a field, not the whole answer."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_empty_table_is_a_successful_owns_nothing(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table())

        result = await _fetch(client)

        assert result.rows == ()
        assert result.all_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_row_without_an_account_id_is_dropped_and_reported(
        self, client: BackstopClient
    ) -> None:
        """The account id is what every follow-up call needs; a row without one is unusable."""
        respx.get(_TABLE_URL).mock(
            return_value=_table(_row("28435967"), _row("ignored", account=None))
        )

        result = await _fetch(client)

        assert [row.account_id for row in result.rows] == ["28435967"]
        assert result.rows_dropped == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_reference_without_a_resource_id_degrades_to_none(
        self, client: BackstopClient
    ) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(_row("28435967", product={"resourceType": "hedge-fund-products"}))
        )

        row = (await _fetch(client)).rows[0]

        assert row.product_id is None
        assert row.account_id == "28435967"

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_row_fields_are_ignored(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(_row("28435967", somethingBrandNew={"nested": 1}))
        )

        assert (await _fetch(client)).rows[0].account_id == "28435967"

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize("body", _BROKEN_ENVELOPES, ids=_BROKEN_ENVELOPE_IDS)
    async def test_a_broken_envelope_raises_rather_than_reporting_owns_nothing(
        self, client: BackstopClient, body: dict[str, object]
    ) -> None:
        """A row losing a field costs the field. The envelope losing a key costs the answer,
        so it must fail into the documented fallback instead of returning zero rows."""
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(200, json=body))
        _empty_walk()

        result = await _fetch(client)

        assert result.source == "accounts-api"
        assert result.rows == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_counts_contradicting_the_rows_is_rejected(self, client: BackstopClient) -> None:
        """A renamed `accounts` key still ships the counts, which is what catches it."""
        respx.get(_TABLE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": None,
                            "type": "bsg-account-table-data",
                            "attributes": {"rowz": [], "allCount": 12, "closedCount": 11},
                        }
                    ]
                },
            )
        )

        _empty_walk()

        result = await _fetch(client)

        assert result.source == "accounts-api"
        assert result.rows == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_lost_closed_flag_is_rejected_rather_than_reported_as_all_open(
        self, client: BackstopClient
    ) -> None:
        """Without this, 9 closed accounts would be published as 12 open holdings."""
        rows = [_row(str(n)) | {"closed": None} for n in range(3)]
        respx.get(_TABLE_URL).mock(return_value=_table(*rows, closedCount=2))
        _empty_walk()

        result = await _fetch(client)

        assert result.source == "accounts-api"
        assert result.rows == ()

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        "balance", ["$1.00", 1.0, [], True], ids=["string", "number", "list", "bool"]
    )
    async def test_an_off_type_figure_costs_that_figure_not_the_table(
        self, client: BackstopClient, balance: object
    ) -> None:
        respx.get(_TABLE_URL).mock(return_value=_table(_row("28435967", balance=balance)))

        row = (await _fetch(client)).rows[0]

        assert row.balance is None
        assert row.account_id == "28435967"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_numeric_id_is_read_as_the_same_id(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(_row("1", otherId=90007828, account={"resourceId": 28435967}))
        )

        row = (await _fetch(client)).rows[0]

        assert row.account_id == "28435967"
        assert row.other_id == "90007828"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_whitespace_reference_id_degrades(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(_row("28435967", product={"resourceId": "   "}))
        )

        assert (await _fetch(client)).rows[0].product_id is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_figures_are_omitted_never_zeroed(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(
            return_value=_table(_row("28435967", balance=None) | {"commitment": None})
        )

        row = (await _fetch(client)).rows[0]

        assert row.balance is None
        assert row.commitment is None


class TestUnusableTableFallsBack:
    """`run` does not publish a broken table as an empty one; it uses the documented walk."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_404_falls_back(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(return_value=httpx.Response(404, json={"errors": []}))
        _empty_walk()

        result = await _fetch(client)

        assert result.source == "accounts-api"
        assert result.rows == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_timeout_falls_back(self, client: BackstopClient) -> None:
        respx.get(_TABLE_URL).mock(side_effect=httpx.ReadTimeout("too slow"))
        _empty_walk()

        result = await _fetch(client)

        assert result.source == "accounts-api"
        assert result.rows == ()

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


def _table_unavailable() -> None:
    respx.get(f"{BASE_URL}/bsg-account-table-data").mock(
        return_value=httpx.Response(404, json={"errors": []})
    )


def _empty_series(*account_ids: str) -> None:
    empty = httpx.Response(200, json={"data": []})
    for account_id in account_ids:
        respx.get(f"{BASE_URL}/accounts/{account_id}/values").mock(return_value=empty)
        respx.get(f"{BASE_URL}/accounts/{account_id}/percentageOfFundHistory").mock(
            return_value=empty
        )


async def _documented_holdings(client: BackstopClient, *, owner_id: str) -> HoldingListingDto:
    _table_unavailable()
    return await make_get_holdings_query(client).run(owner_id=owner_id)


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

        _empty_series("1")
        listing = await _documented_holdings(client, owner_id=_OWNER_ID)

        params = route.calls.last.request.url.params
        assert "filter[owner.id][eq]" not in params
        assert "filter[owner][eq]" not in params
        assert params["include"] == "owner,investorType,product"
        assert set(params["fields"].split(",")) == _EXPECTED_FIELDS
        assert listing.rows[0].product_short_name == "CGUP"

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

        _empty_series("1")
        listing = await _documented_holdings(client, owner_id=_OWNER_ID)

        assert [row.account_id for row in listing.rows] == ["1"]

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

        _empty_series("open")
        listing = await _documented_holdings(client, owner_id=_OWNER_ID)

        assert [row.account_id for row in listing.rows] == ["open"]
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

        _empty_series("1")
        listing = await _documented_holdings(client, owner_id=_OWNER_ID)

        assert [row.account_id for row in listing.rows] == ["1"]
        assert listing.rows[0].investor_id == _OWNER_ID

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

        _empty_series("1", "2")
        listing = await _documented_holdings(client, owner_id=_OWNER_ID)

        assert [row.account_id for row in listing.rows] == ["1", "2"]
        assert sorted(params["page[offset]"] for params in recorded_params(route)) == ["0", "1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_a_row_when_owner_linkage_matches_without_the_include(
        self, client: BackstopClient
    ) -> None:
        respx.get(_ACCOUNTS_URL).mock(
            return_value=_page(_account("1", owner_id=_OWNER_ID, name="Vehicle A"))
        )

        _empty_series("1")
        listing = await _documented_holdings(client, owner_id=_OWNER_ID)

        assert [row.account_id for row in listing.rows] == ["1"]
        assert listing.rows[0].investor_id is None
