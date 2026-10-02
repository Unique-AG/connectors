"""`get_fund`: string status ids, currency minimums, and name resolution."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body
from with_intelligence_mcp.features.funds import (
    FundAmbiguousResponse,
    FundNotEntitledResponse,
    FundNotFoundResponse,
    FundProfileResponse,
)
from with_intelligence_mcp.features.funds.queries import GetFundQuery
from with_intelligence_mcp.features.funds.tools.get_fund import get_fund as call_get_fund
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

FUND: dict[str, object] = {
    "id": 8677,
    "name": "Example Macro Fund",
    "management_company": {"id": 10, "name": "Example Manager"},
    "fund_status": {
        "id": "ACTIVE",
        "name": "Active",
        "sub_status": {"id": "OPEN_TO_INVESTMENT", "name": "Open to investment"},
    },
    "is_liquidated": False,
    "inferred": False,
    "primary_strategies": [{"id": 1, "name": "Global Macro"}],
    "investment_min_size": 10000000,
    "investment_min_currency": "USD",
    "latest_aum": 500,
    "currency": {"id": 840, "short_name": "USD"},
}


async def get_fund(
    *,
    client: WithIntelligenceClient,
    name: str | None = None,
    fund_id: int | None = None,
) -> FundProfileResponse | FundAmbiguousResponse | FundNotEntitledResponse | FundNotFoundResponse:
    return await call_get_fund(
        name=name,
        fund_id=fund_id,
        get_fund_query=GetFundQuery(client=client),
    )


class TestProjection:
    @respx.mock
    async def test_projects_status_names_and_keeps_the_minimum_in_currency(self) -> None:
        respx.get(f"{BASE_URL}/v3/funds/8677").mock(return_value=httpx.Response(200, json=FUND))
        client, _ = build_client()
        result = await get_fund(fund_id=8677, client=client)
        assert isinstance(result, FundProfileResponse)
        assert result.manager == "Example Manager"
        assert result.status == "Active"
        assert result.sub_status == "Open to investment"
        assert result.is_liquidated is False
        assert result.strategies == ["Global Macro"]
        assert result.minimum_investment == 10000000
        assert result.aum_millions == 500
        assert result.currency == "USD"


class TestResolution:
    @respx.mock
    async def test_an_ambiguous_name_does_not_fetch_a_detail(self) -> None:
        respx.get(f"{BASE_URL}/v3/funds").mock(
            return_value=httpx.Response(
                200,
                json=page_body(
                    [{"id": 1, "name": "Alpha One"}, {"id": 2, "name": "Alpha Two"}],
                    total=2,
                ),
            )
        )
        detail = respx.get(url__regex=rf"{BASE_URL}/v3/funds/\d+").mock(
            return_value=httpx.Response(200, json=FUND)
        )
        client, _ = build_client()
        result = await get_fund(name="Alpha", client=client)
        assert isinstance(result, FundAmbiguousResponse)
        assert result.total_matches == 2
        assert [candidate.name for candidate in result.candidates] == ["Alpha One", "Alpha Two"]
        assert detail.call_count == 0

    @respx.mock
    async def test_a_missing_id_is_not_found(self) -> None:
        respx.get(f"{BASE_URL}/v3/funds/9").mock(return_value=httpx.Response(404))
        client, _ = build_client()
        result = await get_fund(fund_id=9, client=client)
        assert isinstance(result, FundNotFoundResponse)

    @respx.mock
    async def test_a_refused_detail_is_not_entitled(self) -> None:
        respx.get(f"{BASE_URL}/v3/funds/9").mock(return_value=httpx.Response(403))
        client, _ = build_client()
        result = await get_fund(fund_id=9, client=client)
        assert isinstance(result, FundNotEntitledResponse)
