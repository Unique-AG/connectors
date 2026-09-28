from pydantic import TypeAdapter

from with_intelligence_mcp.features.investments.api_responses import (
    InvestmentExtendedAttributes,
)
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    WithIntelligenceClient,
)

INVESTMENTS_PATH = "/v3/investments"
_INVESTMENT_RESPONSE = TypeAdapter(InvestmentExtendedAttributes)


async def fetch_investment(
    client: WithIntelligenceClient, investment_id: int
) -> InvestmentExtendedAttributes | None:
    try:
        return await client.get_json(f"{INVESTMENTS_PATH}/{investment_id}", _INVESTMENT_RESPONSE)
    except NotEntitled, NotFound:
        return None
