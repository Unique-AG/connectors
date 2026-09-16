from pydantic import TypeAdapter

from with_intelligence_mcp.features.mandates.fetch_mandates_for_investor import MANDATES_PATH
from with_intelligence_mcp.features.mandates.wi_responses import MandateExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
)

_MANDATE_RESPONSE = TypeAdapter(MandateExtendedAttributes)


async def fetch_mandate(
    client: WithIntelligenceClient, mandate_id: int
) -> MandateExtendedAttributes | None:
    try:
        return await client.get_json(f"{MANDATES_PATH}/{mandate_id}", _MANDATE_RESPONSE)
    except NotFound:
        return None
