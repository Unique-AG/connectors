from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
    narrow_dict,
)

INVESTORS_PATH = "/v3/investors"


async def fetch_investor(
    client: WithIntelligenceClient, investor_id: int
) -> InvestorExtendedAttributes | None:
    """`GET /v3/investors/{id}` — the whole record. `None` when the id does not exist."""
    try:
        body = await client.get_json(f"{INVESTORS_PATH}/{investor_id}")
    except NotFound:
        return None
    return InvestorExtendedAttributes.model_validate(narrow_dict(body))
