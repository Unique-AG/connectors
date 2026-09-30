from pydantic import TypeAdapter

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
)

_INVESTOR_RESPONSE = TypeAdapter(InvestorExtendedAttributes)


async def fetch_investor(
    client: WithIntelligenceClient, investor_id: int
) -> InvestorExtendedAttributes | None:
    """`GET /v3/investors/{id}` — the whole record. `None` when the id does not exist."""
    try:
        return await client.get_json(f"/v3/investors/{investor_id}", _INVESTOR_RESPONSE)
    except NotFound:
        return None
