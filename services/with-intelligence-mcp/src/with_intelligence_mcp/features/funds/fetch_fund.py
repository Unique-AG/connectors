from pydantic import TypeAdapter

from with_intelligence_mcp.features.funds.api_responses import FundExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import NotFound, WithIntelligenceClient

_FUND_RESPONSE = TypeAdapter(FundExtendedAttributes)


async def fetch_fund(client: WithIntelligenceClient, fund_id: int) -> FundExtendedAttributes | None:
    """`GET /v3/funds/{id}`. `None` when the id does not exist."""
    try:
        return await client.get_json(f"/v3/funds/{fund_id}", _FUND_RESPONSE)
    except NotFound:
        return None
