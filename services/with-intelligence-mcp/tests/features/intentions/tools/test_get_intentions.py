"""`get_intentions`: the add-on refusal is distinct from an empty list."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body
from with_intelligence_mcp.features.intentions import InvestorIntentionsResponse
from with_intelligence_mcp.features.intentions.queries import GetIntentionsQuery
from with_intelligence_mcp.features.intentions.tools.get_intentions import (
    GetIntentionsResult,
)
from with_intelligence_mcp.features.intentions.tools.get_intentions import (
    get_intentions as call_get_intentions,
)
from with_intelligence_mcp.features.investors import InvestorNotEntitledResponse
from with_intelligence_mcp.features.investors.queries import ResolveInvestorRecordQuery
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

INVESTOR: dict[str, object] = {"id": 2504, "name": "Example Retirement System (ERS)"}
INTENTION: dict[str, object] = {
    "id": 7,
    "date": "2026-06-01",
    "status": {
        "id": "POTENTIAL",
        "name": "Potential",
        "sub_status": {"id": "EARLY", "name": "Early"},
    },
    "asset_class": {"id": 1, "name": "Hedge Funds"},
    "allocation_amount": {"value_lower_usd": 10000000, "value_upper_usd": 25000000},
    "preference_only": False,
    "note": "<p>Looking at global macro.&nbsp;Ticket is firm.</p>",
    "structures": [{"id": 1, "name": "Commingled"}],
    "classification_segments": {
        "strategies": {
            "primary_strategy": {"id": 3, "name": "Global Macro"},
            "secondary_strategies": [{"id": 4, "name": "Discretionary"}],
        }
    },
}


async def get_intentions(
    *,
    client: WithIntelligenceClient,
    investor_id: int | None = None,
) -> GetIntentionsResult:
    return await call_get_intentions(
        investor_id=investor_id,
        resolve_investor_record_query=ResolveInvestorRecordQuery(client),
        get_intentions_query=GetIntentionsQuery(client=client),
    )


def _mock_investor() -> None:
    respx.get(f"{BASE_URL}/v3/investors/2504").mock(return_value=httpx.Response(200, json=INVESTOR))


class TestEntitlement:
    @respx.mock
    async def test_a_refused_listing_is_the_add_on_not_an_empty_book(self) -> None:
        respx.get(f"{BASE_URL}/v3/intentions").mock(
            return_value=httpx.Response(
                403,
                json={
                    "message": "Access denied. You do not have the required package.",
                    "error": "Forbidden",
                    "statusCode": 403,
                },
            )
        )
        _mock_investor()
        client, _ = build_client()
        result = await get_intentions(investor_id=2504, client=client)
        assert isinstance(result, InvestorNotEntitledResponse)
        assert result.hint is not None
        assert "add-on" in result.hint

    @respx.mock
    async def test_a_refused_detail_is_the_add_on_not_an_empty_row(self) -> None:
        respx.get(f"{BASE_URL}/v3/intentions").mock(
            return_value=httpx.Response(
                200, json=page_body([{"id": 7, "date": "2026-06-01"}], total=1)
            )
        )
        respx.get(f"{BASE_URL}/v3/intentions/7").mock(return_value=httpx.Response(403))
        _mock_investor()
        client, _ = build_client()
        result = await get_intentions(investor_id=2504, client=client)
        assert isinstance(result, InvestorNotEntitledResponse)
        assert result.hint is not None
        assert "add-on" in result.hint

    @respx.mock
    async def test_an_empty_page_stays_an_empty_list(self) -> None:
        respx.get(f"{BASE_URL}/v3/intentions").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        _mock_investor()
        client, _ = build_client()
        result = await get_intentions(investor_id=2504, client=client)
        assert isinstance(result, InvestorIntentionsResponse)
        assert result.intentions == []
        assert result.total == 0


class TestProjection:
    @respx.mock
    async def test_amounts_stay_in_dollars(self) -> None:
        respx.get(f"{BASE_URL}/v3/intentions").mock(
            return_value=httpx.Response(
                200, json=page_body([{"id": 7, "date": "2026-06-01"}], total=1)
            )
        )
        respx.get(f"{BASE_URL}/v3/intentions/7").mock(
            return_value=httpx.Response(200, json=INTENTION)
        )
        _mock_investor()
        client, _ = build_client()
        result = await get_intentions(investor_id=2504, client=client)
        assert isinstance(result, InvestorIntentionsResponse)
        intention = result.intentions[0]
        assert intention.status == "Potential"
        assert intention.sub_status == "Early"
        assert intention.asset_class == "Hedge Funds"
        assert intention.strategies == ["Global Macro", "Discretionary"]
        assert intention.allocation_amount is not None
        assert intention.allocation_amount.lower_usd == 10000000
        assert intention.preference_only is False
        assert intention.structures == ["Commingled"]
        assert intention.note == "Looking at global macro. Ticket is firm."
