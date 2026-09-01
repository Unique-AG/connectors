"""`get_investments`: the roster, exits, units, and the unidentified-fund case."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body, sent_query
from with_intelligence_mcp.features.investments import InvestorPositionsResponse
from with_intelligence_mcp.features.investments.tools.get_investments import get_investments
from with_intelligence_mcp.features.investors import InvestorAmbiguousResponse

INVESTOR: dict[str, object] = {"id": 2504, "name": "Example Retirement System (ERS)"}

HELD: dict[str, object] = {
    "id": 11,
    "latest_as_of": "2026-06-30",
    "amount": {"amount": 250.0, "date": "2026-06-30", "currency": {"short_name": "USD"}},
    "fund": {"id": 900, "name": "Example Macro Fund", "unknown": False},
    "manager_firm": {"id": 500, "name": "Manager One"},
    "asset_classes": [{"id": 1, "name": "Hedge Funds"}],
    "fund_primary_strategies": [{"id": 7, "name": "Macro"}],
    "fund_secondary_strategies": [{"id": 135, "name": "Global Macro"}],
    "fund_structures": [{"id": 1, "name": "Commingled Fund"}],
}

EXITED: dict[str, object] = {
    "id": 12,
    "deleted_at": "2025-03-31",
    "fund": {"id": 901, "name": "Example Credit Fund", "unknown": False},
    "manager_firm": {"id": 501, "name": "Manager Two"},
}

UNIDENTIFIED: dict[str, object] = {"id": 13, "fund": {"unknown": True}}


def _mock(positions: list[dict[str, object]], *, total: int | None = None) -> None:
    listing = [{"id": p["id"], "updated_at": "2026-08-01"} for p in positions]
    respx.get(f"{BASE_URL}/v3/investments").mock(
        return_value=httpx.Response(
            200, json=page_body(listing, total=total if total is not None else len(positions))
        )
    )
    for position in positions:
        respx.get(f"{BASE_URL}/v3/investments/{position['id']}").mock(
            return_value=httpx.Response(200, json=position)
        )
    respx.get(f"{BASE_URL}/v3/investors/2504").mock(return_value=httpx.Response(200, json=INVESTOR))


class TestTheRoster:
    @respx.mock
    async def test_returns_fund_manager_and_strategies(self) -> None:
        _mock([HELD])
        client, _ = build_client()
        result = await get_investments(investor_id=2504, client=client)
        assert isinstance(result, InvestorPositionsResponse)
        position = result.positions[0]
        assert position.fund == "Example Macro Fund"
        assert position.manager == "Manager One"
        assert position.strategies == ["Macro", "Global Macro"]
        assert position.structures == ["Commingled Fund"]

    @respx.mock
    async def test_keeps_the_manager_id_for_a_follow_up_query(self) -> None:
        """`manager_id` is what turns "who else holds this manager" into one filter."""
        _mock([HELD])
        client, _ = build_client()
        result = await get_investments(investor_id=2504, client=client)
        assert isinstance(result, InvestorPositionsResponse)
        assert result.positions[0].manager_id == 500

    @respx.mock
    async def test_reports_the_total_alongside_what_it_returned(self) -> None:
        _mock([HELD], total=40)
        client, _ = build_client()
        result = await get_investments(investor_id=2504, client=client)
        assert isinstance(result, InvestorPositionsResponse)
        assert (result.total, result.returned) == (40, 1)


class TestAmounts:
    @respx.mock
    async def test_the_amount_is_labelled_as_millions(self) -> None:
        _mock([HELD])
        client, _ = build_client()
        result = await get_investments(investor_id=2504, client=client)
        assert isinstance(result, InvestorPositionsResponse)
        amount = result.positions[0].amount
        assert amount is not None
        assert amount.value_millions == 250.0
        assert amount.currency == "USD"
        assert amount.as_of == "2026-06-30"

    @respx.mock
    async def test_a_position_with_no_amount_omits_it(self) -> None:
        _mock([EXITED])
        client, _ = build_client()
        result = await get_investments(investor_id=2504, client=client)
        assert isinstance(result, InvestorPositionsResponse)
        assert result.positions[0].amount is None


class TestExits:
    @respx.mock
    async def test_an_exited_position_is_flagged_not_dropped(self) -> None:
        """A redemption is the answer to "what changed" — hiding it loses the finding."""
        _mock([HELD, EXITED])
        client, _ = build_client()
        result = await get_investments(investor_id=2504, client=client)
        assert isinstance(result, InvestorPositionsResponse)
        by_id = {p.id: p for p in result.positions}
        assert by_id[11].is_current is True
        assert by_id[12].is_current is False
        assert by_id[12].exited_on == "2025-03-31"


class TestUnidentifiedFund:
    @respx.mock
    async def test_an_unidentified_fund_says_so(self) -> None:
        """Not the same as holding nothing — the position is real, the fund is unknown."""
        _mock([UNIDENTIFIED])
        client, _ = build_client()
        result = await get_investments(investor_id=2504, client=client)
        assert isinstance(result, InvestorPositionsResponse)
        assert result.positions[0].fund_unidentified is True
        assert result.positions[0].fund is None


class TestScoping:
    @respx.mock
    async def test_scopes_by_investor_and_package(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investments").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=INVESTOR)
        )
        client, _ = build_client()
        _ = await get_investments(investor_id=2504, client=client)
        query = sent_query(route)
        assert "investor_id=2504" in query
        assert "asset_class_group=hfm" in query

    @respx.mock
    async def test_updated_since_becomes_a_change_log_window(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investments").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=INVESTOR)
        )
        client, _ = build_client()
        _ = await get_investments(investor_id=2504, updated_since="2025-09-01", client=client)
        assert "updated_at%5Bfrom%5D=2025-09-01" in sent_query(route)

    @respx.mock
    async def test_an_ambiguous_name_asks_before_fetching(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(
                200,
                json=page_body(
                    [{"id": 1, "name": "Virginia A"}, {"id": 2, "name": "Virginia B"}], total=20
                ),
            )
        )
        listing = respx.get(f"{BASE_URL}/v3/investments").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        result = await get_investments(name="Virginia", client=client)
        assert isinstance(result, InvestorAmbiguousResponse)
        assert listing.call_count == 0
