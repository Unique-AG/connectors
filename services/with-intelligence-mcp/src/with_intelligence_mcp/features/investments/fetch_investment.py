from with_intelligence_mcp.features.investments.api_responses import (
    InvestmentExtendedAttributes,
)
from with_intelligence_mcp.features.investments.fetch_investments_for_investor import (
    INVESTMENTS_PATH,
)
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
    narrow_dict,
)


async def fetch_investment(
    client: WithIntelligenceClient, investment_id: int
) -> InvestmentExtendedAttributes | None:
    try:
        body = await client.get_json(f"{INVESTMENTS_PATH}/{investment_id}")
    except NotFound:
        return None
    return InvestmentExtendedAttributes.model_validate(narrow_dict(body))
