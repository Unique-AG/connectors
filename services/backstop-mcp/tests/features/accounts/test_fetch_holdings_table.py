"""`fetch_holdings_table` against the undocumented UI table endpoint.

Every fixture below is shaped from a real recorded response (`docs/json/023`, `026`, `037`, `046`):
rows under `data[0].attributes.accounts`, a `null` element id, `meta.totalResourceCount` of `0`,
and `included` empty.
"""

from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.accounts import HoldingListingDto, fetch_holdings_table
from tests.helpers import BASE_URL

_ORG = "341764767"
_URL = f"{BASE_URL}/bsg-account-table-data"


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


def _row(
    account_id: str,
    *,
    product_id: str = "1653647",
    short_name: str = "CIO2",
    closed: bool = False,
    balance: dict[str, object] | None = None,
    **overrides: object,
) -> dict[str, object]:
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
        "balance": balance if balance is not None else _money(0.0, "$0.00"),
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
    return await fetch_holdings_table(client, entity_id=_ORG, include_closed=include_closed)


class TestRequestShape:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_only_entity_id_because_paging_params_are_ignored(
        self, client: BackstopClient
    ) -> None:
        """Paging is ignored upstream, so sending it would imply a bound that does not exist."""
        route = respx.get(_URL).mock(return_value=_table(_row("28435967")))

        await _fetch(client)

        assert dict(route.calls.last.request.url.params) == {"entityId": _ORG}

    @pytest.mark.asyncio
    @respx.mock
    async def test_reads_the_whole_table_in_one_request(self, client: BackstopClient) -> None:
        route = respx.get(_URL).mock(
            return_value=_table(*(_row(str(28435967 + n)) for n in range(12)))
        )

        result = await _fetch(client)

        assert route.call_count == 1
        assert len(result.rows) == 12


class TestProjection:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_ids_dates_and_figures(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(
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
        respx.get(_URL).mock(return_value=_table(_row("28435967")))

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
        respx.get(_URL).mock(
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
        respx.get(_URL).mock(return_value=_table(_row("28435967", otherId=None)))

        assert (await _fetch(client)).rows[0].other_id is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_publishes_backstops_own_counts(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(
            return_value=_table(_row("1"), _row("2", closed=True), _row("3", closed=True))
        )

        result = await _fetch(client, include_closed=True)

        assert (result.open_count, result.all_count, result.closed_count) == (1, 3, 2)


class TestClosedFiltering:
    @pytest.mark.asyncio
    @respx.mock
    async def test_drops_closed_rows_and_counts_them(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(return_value=_table(_row("1"), _row("2", closed=True)))

        result = await _fetch(client)

        assert [row.account_id for row in result.rows] == ["1"]
        assert result.closed_omitted == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_include_closed_keeps_them(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(return_value=_table(_row("1"), _row("2", closed=True)))

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
        respx.get(_URL).mock(return_value=_table())

        result = await _fetch(client)

        assert result.rows == ()
        assert result.all_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_row_without_an_account_id_is_dropped_and_reported(
        self, client: BackstopClient
    ) -> None:
        """The account id is what every follow-up call needs; a row without one is unusable."""
        respx.get(_URL).mock(return_value=_table(_row("28435967"), _row("ignored", account=None)))

        result = await _fetch(client)

        assert [row.account_id for row in result.rows] == ["28435967"]
        assert result.rows_dropped == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_reference_without_a_resource_id_degrades_to_none(
        self, client: BackstopClient
    ) -> None:
        respx.get(_URL).mock(
            return_value=_table(_row("28435967", product={"resourceType": "hedge-fund-products"}))
        )

        row = (await _fetch(client)).rows[0]

        assert row.product_id is None
        assert row.account_id == "28435967"

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_row_fields_are_ignored(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(return_value=_table(_row("28435967", somethingBrandNew={"nested": 1})))

        assert (await _fetch(client)).rows[0].account_id == "28435967"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_body_with_no_data_element_is_an_empty_table(
        self, client: BackstopClient
    ) -> None:
        respx.get(_URL).mock(return_value=httpx.Response(200, json={"data": [], "meta": {}}))

        result = await _fetch(client)

        assert result.rows == ()
        assert result.all_count is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_figures_are_omitted_never_zeroed(self, client: BackstopClient) -> None:
        # Via a dict update, not the `balance=` kwarg, whose default fills a `None` back in.
        respx.get(_URL).mock(
            return_value=_table(_row("28435967") | {"balance": None, "commitment": None})
        )

        row = (await _fetch(client)).rows[0]

        assert row.balance is None
        assert row.commitment is None


class TestFailuresPropagate:
    """The caller decides whether to fall back, so transport failures are not swallowed here."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_404_raises(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(return_value=httpx.Response(404, json={"errors": []}))

        with pytest.raises(BackstopApiError):
            await _fetch(client)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_timeout_raises(self, client: BackstopClient) -> None:
        respx.get(_URL).mock(side_effect=httpx.ReadTimeout("too slow"))

        with pytest.raises(httpx.ReadTimeout):
            await _fetch(client)
