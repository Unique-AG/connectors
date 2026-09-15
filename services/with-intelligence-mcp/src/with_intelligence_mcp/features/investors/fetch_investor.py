from pydantic import TypeAdapter

from with_intelligence_mcp.features.investors.wi_responses import InvestorExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
)

INVESTORS_PATH = "/v3/investors"
_INVESTOR_RESPONSE = TypeAdapter(InvestorExtendedAttributes)


async def fetch_investor(
    client: WithIntelligenceClient, investor_id: int
) -> InvestorExtendedAttributes | None:
    """`GET /v3/investors/{id}` — the whole record. `None` when the id does not exist."""
    try:
        return await client.get_json(f"{INVESTORS_PATH}/{investor_id}", _INVESTOR_RESPONSE)
    except NotFound:
        return None
