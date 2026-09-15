from pydantic import TypeAdapter

from with_intelligence_mcp.features.investments.fetch_investments_for_investor import (
    INVESTMENTS_PATH,
)
from with_intelligence_mcp.features.investments.wi_responses import (
    InvestmentExtendedAttributes,
)
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
)

_INVESTMENT_RESPONSE = TypeAdapter(InvestmentExtendedAttributes)


async def fetch_investment(
    client: WithIntelligenceClient, investment_id: int
) -> InvestmentExtendedAttributes | None:
    try:
        return await client.get_json(f"{INVESTMENTS_PATH}/{investment_id}", _INVESTMENT_RESPONSE)
    except NotFound:
        return None
